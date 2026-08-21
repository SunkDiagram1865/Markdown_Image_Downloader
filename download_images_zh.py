import os
import re
import json
import hashlib
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen

# 匹配 markdown 图片语法 ![alt](https://...)
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\((https://[^)]+)\)')

# Python 脚本所在目录（用于存放 failed_urls.txt、config.json）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 配置文件路径
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

# 解析带引号的路径：支持 "path with space.md" 或 path.md，多个用空格分隔
PATH_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')

# 默认 User-Agent（config.json 中未配置时使用）
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


def load_config():
    """读取 config.json，返回配置字典；不存在或解析失败时返回空配置"""
    if not os.path.isfile(CONFIG_PATH):
        return {'headers': {}, 'cookies': '', 'per_host': {}}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # 过滤掉以 _ 开头的说明字段
        cfg = {k: v for k, v in cfg.items() if not k.startswith('_')}
        cfg.setdefault('headers', {})
        cfg.setdefault('cookies', '')
        cfg.setdefault('per_host', {})
        return cfg
    except Exception as e:
        print(f'读取 config.json 失败，使用默认配置: {e}')
        return {'headers': {}, 'cookies': '', 'per_host': {}}


def build_headers_for(url, cfg):
    """根据 url 域名和配置构建请求头：通用 headers + 通用 cookie + per_host 覆盖"""
    headers = {}

    # 通用 headers
    for k, v in (cfg.get('headers') or {}).items():
        headers[k] = v

    # 通用 Cookie
    general_cookie = (cfg.get('cookies') or '').strip()
    if general_cookie:
        headers['Cookie'] = general_cookie

    # 按 host 匹配 per_host 规则（子串匹配，如 sinaimg.cn 命中 host）
    host = (urlparse(url).hostname or '').lower()
    for key, rule in (cfg.get('per_host') or {}).items():
        if key.lower() in host:
            for k, v in (rule.get('headers') or {}).items():
                headers[k] = v
            host_cookie = (rule.get('cookies') or '').strip()
            if host_cookie:
                # 如果已有通用 cookie 则合并，否则直接用 host cookie
                if 'Cookie' in headers:
                    headers['Cookie'] = headers['Cookie'].rstrip(';') + '; ' + host_cookie
                else:
                    headers['Cookie'] = host_cookie

    # 兜底：未配置 User-Agent 时使用默认
    if 'User-Agent' not in headers:
        headers['User-Agent'] = DEFAULT_USER_AGENT

    return headers


def parse_paths(raw):
    """从用户输入解析路径列表，支持带引号的路径"""
    paths = []
    for m in PATH_TOKEN_RE.finditer(raw):
        token = m.group(1) if m.group(1) is not None else m.group(2)
        paths.append(os.path.abspath(token.strip()))
    return paths


def assets_dir_for(md_path):
    """assets 目录位于 md 文件所在目录下的 assets 子目录"""
    return os.path.join(os.path.dirname(os.path.abspath(md_path)), 'assets')


def ensure_assets_dir(assets_dir):
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
        print(f'已创建目录: {assets_dir}')


def ext_from_url(url):
    """从 URL 中推测扩展名，默认 .png"""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'):
        return ext
    return '.png'


def unique_filename(url):
    """用 URL 的 md5 生成唯一文件名，避免重名覆盖与重复下载"""
    name = hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
    return name + ext_from_url(url)


def is_image_data(data):
    """通过文件头 magic bytes 判断数据是否为图片，避免把 HTML 错误页当图片存"""
    if not data or len(data) < 12:
        return False
    # PNG: 89 50 4E 47
    if data[:4] == b'\x89PNG':
        return True
    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return True
    # GIF: GIF87a / GIF89a
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return True
    # WebP / RIFF container: RIFF....WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    # BMP: BM
    if data[:2] == b'BM':
        return True
    # ICO: 00 00 01 00
    if data[:4] == b'\x00\x00\x01\x00':
        return True
    # SVG (文本): 以 <svg 或 <?xml 开头（宽进，可能误判，但通常可接受）
    head = data[:512].lstrip()
    if head.startswith(b'<svg') or head.startswith(b'<?xml') and b'<svg' in data[:1024]:
        return True
    return False


def extract_baidu_original_url(url):
    """从百度图床链接中提取 src 参数指向的原始图片链接，失败返回 None

    支持的格式示例：
      https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fxxx.png%3F...&refer=...
      https://...baidu.com/...?src=http%3A%2F%2Fxxx.png&...
    """
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if 'baidu.com' not in host:
        return None

    # 形式1：src= 在 URL 的 query string 中
    qs_src = None
    if parsed.query:
        try:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs_src_list = qs.get('src') or qs.get('srcUrl') or qs.get('src_url')
            if qs_src_list:
                qs_src = qs_src_list[0]
        except Exception:
            qs_src = None

    # 形式2：src= 嵌在 path 中，如 /image_search/src=<encoded>&refer=...
    path_src = None
    path = parsed.path or ''
    # 找到 'src=' 的起始位置（在 path 中）
    idx = path.find('src=')
    if idx >= 0:
        rest = path[idx + 4:]           # 去掉 "src=" 前缀
        # 截到下一个 '&' 或 '?' 或 '#' 或结尾
        end = len(rest)
        for sep in ('&', '?', '#'):
            pos = rest.find(sep)
            if 0 <= pos < end:
                end = pos
        path_src = rest[:end] if end > 0 else None

    # 优先使用 path 中的 src（因为百度图床常用这种形式），其次用 query 中的
    encoded = path_src if path_src else qs_src
    if not encoded:
        return None
    try:
        decoded = unquote(encoded)
    except Exception:
        decoded = encoded
    # 如果解码后仍然看起来像带 % 的未完全解码的 url，再解一次
    try:
        if '%' in decoded:
            decoded2 = unquote(decoded)
            if decoded2 and decoded2 != decoded:
                decoded = decoded2
    except Exception:
        pass
    if decoded and (decoded.startswith('http://') or decoded.startswith('https://')):
        return decoded
    return None


def download_image(url, assets_dir, cfg):
    """下载单个图片到指定 assets_dir，返回本地文件名（不含目录）

    若 url 为百度图床链接且下载失败（或返回的不是图片数据），则自动解析 src= 指向的
    原始图片链接并再次尝试下载（两者之一成功即视为成功）。
    """
    filename = unique_filename(url)
    filepath = os.path.join(assets_dir, filename)
    if os.path.exists(filepath):
        print(f'已存在，跳过: {filename}')
        return filename

    # 若为百度图床链接，提前提取原始链接以便失败回退
    fallback_url = extract_baidu_original_url(url)

    # 尝试下载：先原始 url（百度图床链接），失败则尝试 fallback（src 解码后的真实链接）
    attempts = [url]
    if fallback_url and fallback_url != url:
        attempts.append(fallback_url)

    last_error = None
    for idx, attempt_url in enumerate(attempts):
        headers = build_headers_for(attempt_url, cfg)
        try:
            req = Request(attempt_url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
            # 校验响应数据是否真的是图片，防止把 HTML 错误页（如百度 404 页）当图片保存
            if not is_image_data(data):
                msg = '响应内容不是图片（可能是失效链接或错误页）'
                print(f'下载失败: {attempt_url}  错误: {msg}')
                last_error = msg
                continue  # 尝试下一个 fallback
            with open(filepath, 'wb') as f:
                f.write(data)
            if idx == 0:
                print(f'下载成功: {attempt_url} -> {filepath} ({len(data)} bytes)')
            else:
                print(f'百度图床链接失效，已回退并下载原始链接: {attempt_url} -> {filepath} ({len(data)} bytes)')
            return filename
        except Exception as e:
            last_error = str(e)
            print(f'下载失败: {attempt_url}  错误: {e}')
            # 继续尝试 fallback（如有）
            continue

    # 所有尝试均失败
    if fallback_url:
        print(f'百度图床链接及其原始链接均下载失败: {url} (原始: {fallback_url})')
    else:
        print(f'下载失败: {url}  错误: {last_error}')
    return None


def collect_md_files_in_dir(directory):
    """递归收集目录下所有 .md 文件"""
    md_files = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name.lower().endswith('.md'):
                md_files.append(os.path.join(root, name))
    return md_files


def process_markdown(md_path, cfg):
    """下载单个 md 文件中的 https 图片，assets 目录位于该 md 所在目录"""
    if not os.path.isfile(md_path):
        print(f'文件不存在: {md_path}')
        return

    print(f'\n处理文件: {md_path}')
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    urls = [m.group(2) for m in IMAGE_PATTERN.finditer(content)]
    if not urls:
        print('未找到 https:// 开头的图片链接')
        return

    # 去重但保持顺序
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    assets_dir = assets_dir_for(md_path)
    ensure_assets_dir(assets_dir)

    print(f'共发现 {len(urls)} 个图片链接，{len(unique_urls)} 个唯一')
    success = 0
    failed = []
    for url in unique_urls:
        if download_image(url, assets_dir, cfg):
            success += 1
        else:
            failed.append(url)
    print(f'完成: 成功 {success}/{len(unique_urls)}，图片目录: {assets_dir}')

    # 把失败的 URL 写入日志（放在 Python 脚本所在目录），方便后续手动处理
    if failed:
        log_path = os.path.join(SCRIPT_DIR, 'failed_urls.txt')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'# 失败时间: {datetime.now()}\n')
            f.write(f'# 来源文件: {md_path}\n')
            for u in failed:
                f.write(u + '\n')
            f.write('\n')
        print(f'失败链接已记录: {log_path}（共 {len(failed)} 个）')


def replace_urls_in_markdown(md_path, url_to_local):
    """将 md 文件中的 https 图片链接替换为 ./assets/xxx 本地路径"""
    if not url_to_local:
        print(f'无需要替换的链接: {md_path}')
        return

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def repl(m):
        alt = m.group(1)
        url = m.group(2)
        local = url_to_local.get(url)
        if local:
            return f'![{alt}]({local})'
        return m.group(0)

    new_content = IMAGE_PATTERN.sub(repl, content)
    if new_content == content:
        print(f'无变更: {md_path}')
        return

    # 替换前先备份原文件为 .md.bak，避免替换出错无法恢复
    bak_path = md_path + '.bak'
    with open(bak_path, 'w', encoding='utf-8') as f:
        f.write(content)

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'已替换 {len(url_to_local)} 个链接: {md_path}')
    print(f'已备份原文件: {bak_path}')


def option_download_files(cfg):
    """选项 1：指定文件"""
    raw = input('请输入 markdown 文件路径（多个用空格分隔，路径含空格可用双引号）: ').strip()
    if not raw:
        print('未输入路径')
        return
    paths = parse_paths(raw)
    if not paths:
        print('未解析到有效路径')
        return
    for md in paths:
        process_markdown(md, cfg)


def option_download_folder(cfg):
    """选项 2：指定文件夹（含嵌套）"""
    raw = input('请输入文件夹路径: ').strip()
    if not raw:
        print('未输入路径')
        return
    folder = os.path.abspath(raw.strip('"').strip("'"))
    if not os.path.isdir(folder):
        print(f'不是有效目录: {folder}')
        return
    md_files = collect_md_files_in_dir(folder)
    if not md_files:
        print('该目录下未找到 .md 文件')
        return
    print(f'找到 {len(md_files)} 个 .md 文件')
    for md in md_files:
        process_markdown(md, cfg)


def option_replace_urls():
    """选项 3：将 https 替换为 ./assets/xxx（不下载，仅替换链接）"""
    raw = input('请输入要替换的 markdown 文件或文件夹路径: ').strip()
    if not raw:
        print('未输入路径')
        return
    path = os.path.abspath(raw.strip('"').strip("'"))

    if os.path.isfile(path):
        md_files = [path] if path.lower().endswith('.md') else []
    elif os.path.isdir(path):
        md_files = collect_md_files_in_dir(path)
    else:
        print(f'路径无效: {path}')
        return

    if not md_files:
        print('未找到 .md 文件')
        return

    # 每个 md 文件单独处理：仅替换链接，不下载
    # 文件名用 URL 的 md5 哈希生成，与选项 1/2 下载时的命名一致，方便后续下载能匹配
    for md in md_files:
        md_path = os.path.abspath(md)
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        urls = [m.group(2) for m in IMAGE_PATTERN.finditer(content)]
        if not urls:
            print(f'\n无 https 图片链接: {md_path}')
            continue

        # 去重
        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        # 构建 url -> ./assets/xxx 映射（不下载，仅生成路径）
        url_to_local = {url: './assets/' + unique_filename(url) for url in unique_urls}

        print(f'\n处理文件: {md_path}')
        print(f'发现 {len(unique_urls)} 个唯一链接，开始替换（不下载）...')
        replace_urls_in_markdown(md_path, url_to_local)

    print('\n全部完成')


def option_rename_images():
    """选项 4：将本地图片重命名为程序命名格式（md5 哈希）

    用途：把用户自己的截图文件（如 Snipaste_2026-08-21_14-58-41.png）
    重命名为程序下载时使用的 md5 命名格式（如 324588ab6340f52c.png）。
    """
    raw = input('请输入图片文件路径（多个用空格分隔，可直接拖入）: ').strip()
    if not raw:
        print('未输入路径')
        return
    paths = parse_paths(raw)
    if not paths:
        print('未解析到有效路径')
        return

    renamed = 0
    for old_path in paths:
        if not os.path.isfile(old_path):
            print(f'文件不存在: {old_path}')
            continue

        old_name = os.path.basename(old_path)
        ext = os.path.splitext(old_name)[1].lower()

        # 用文件名计算 md5，和程序用 URL 计算的逻辑一致
        hash_name = hashlib.md5(old_name.encode('utf-8')).hexdigest()[:16]
        new_name = hash_name + ext
        new_path = os.path.join(os.path.dirname(old_path), new_name)

        # 已经是目标格式则跳过
        if old_name == new_name:
            print(f'已经是目标格式，跳过: {old_name}')
            continue

        # 同目录下已有同名文件，追加序号
        if os.path.exists(new_path):
            i = 2
            while os.path.exists(os.path.join(os.path.dirname(old_path), f'{hash_name}_{i}{ext}')):
                i += 1
            new_name = f'{hash_name}_{i}{ext}'
            new_path = os.path.join(os.path.dirname(old_path), new_name)

        os.rename(old_path, new_path)
        print(f'已重命名: {old_name} -> {new_name}')
        renamed += 1

    print(f'\n完成: 共重命名 {renamed} 个文件')


def show_menu():
    print('\n========== Markdown 图片下载器 ==========')
    print('1. 指定文件       (下载图片到 md 所在目录的 ./assets)')
    print('2. 指定文件夹     (递归扫描子目录)')
    print('3. 替换 https 链接为 ./assets 路径 (不下载)')
    print('4. 图片重命名       (将本地图片重命名为 md5 哈希格式)')
    print('0. 退出')
    print('==========================================')


def main():
    # 启动时加载一次配置
    cfg = load_config()
    print(f'已加载配置: {CONFIG_PATH}' if os.path.isfile(CONFIG_PATH) else '未找到 config.json，使用默认配置')

    while True:
        show_menu()
        choice = input('请选择 [0-4]: ').strip()

        if choice == '1':
            # 每次执行前重新读取，方便运行中修改 config.json
            cfg = load_config()
            option_download_files(cfg)
        elif choice == '2':
            cfg = load_config()
            option_download_folder(cfg)
        elif choice == '3':
            option_replace_urls()
        elif choice == '4':
            option_rename_images()
        elif choice == '0':
            print('再见')
            break
        else:
            print('无效选择，请重新输入')


if __name__ == '__main__':
    main()
