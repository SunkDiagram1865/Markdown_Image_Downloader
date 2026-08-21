import os
import re
import json
import hashlib
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen

# Match markdown image syntax ![alt](https://...)
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\((https://[^)]+)\)')

# Directory of this Python script (used for failed_urls.txt, config.json)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to the configuration file
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

# Parse quoted paths: supports "path with space.md" or path.md, multiple separated by spaces
PATH_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')

# Default User-Agent (used when not set in config.json)
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


def load_config():
    """Load config.json; return an empty config if missing or invalid."""
    if not os.path.isfile(CONFIG_PATH):
        return {'headers': {}, 'cookies': '', 'per_host': {}}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # Drop fields starting with '_' (documentation only)
        cfg = {k: v for k, v in cfg.items() if not k.startswith('_')}
        cfg.setdefault('headers', {})
        cfg.setdefault('cookies', '')
        cfg.setdefault('per_host', {})
        return cfg
    except Exception as e:
        print(f'Failed to read config.json, using defaults: {e}')
        return {'headers': {}, 'cookies': '', 'per_host': {}}


def build_headers_for(url, cfg):
    """Build request headers for a URL: common headers + common cookie + per_host overrides."""
    headers = {}

    # Common headers
    for k, v in (cfg.get('headers') or {}).items():
        headers[k] = v

    # Common Cookie
    general_cookie = (cfg.get('cookies') or '').strip()
    if general_cookie:
        headers['Cookie'] = general_cookie

    # Match per_host rules by substring (e.g. sinaimg.cn matches the host)
    host = (urlparse(url).hostname or '').lower()
    for key, rule in (cfg.get('per_host') or {}).items():
        if key.lower() in host:
            for k, v in (rule.get('headers') or {}).items():
                headers[k] = v
            host_cookie = (rule.get('cookies') or '').strip()
            if host_cookie:
                # Merge with existing cookie if any, otherwise use host cookie
                if 'Cookie' in headers:
                    headers['Cookie'] = headers['Cookie'].rstrip(';') + '; ' + host_cookie
                else:
                    headers['Cookie'] = host_cookie

    # Fallback: default User-Agent if not configured
    if 'User-Agent' not in headers:
        headers['User-Agent'] = DEFAULT_USER_AGENT

    return headers


def parse_paths(raw):
    """Parse a list of paths from user input, supporting quoted paths."""
    paths = []
    for m in PATH_TOKEN_RE.finditer(raw):
        token = m.group(1) if m.group(1) is not None else m.group(2)
        paths.append(os.path.abspath(token.strip()))
    return paths


def assets_dir_for(md_path):
    """The assets directory sits next to the md file (./assets)."""
    return os.path.join(os.path.dirname(os.path.abspath(md_path)), 'assets')


def ensure_assets_dir(assets_dir):
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
        print(f'Created directory: {assets_dir}')


def ext_from_url(url):
    """Guess the file extension from the URL; default to .png."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'):
        return ext
    return '.png'


def unique_filename(url):
    """Generate a unique filename from the URL's md5 to avoid overwrites and duplicate downloads."""
    name = hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
    return name + ext_from_url(url)


def is_image_data(data):
    """Check magic bytes to verify the data is an image (avoid saving HTML error pages as images)."""
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
    # SVG (text): starts with <svg or <?xml containing <svg
    head = data[:512].lstrip()
    if head.startswith(b'<svg') or head.startswith(b'<?xml') and b'<svg' in data[:1024]:
        return True
    return False


def extract_baidu_original_url(url):
    """Extract the original image URL from the src= param of a Baidu image-bed link.

    Returns None if the URL is not a Baidu image link or no src value can be decoded.

    Supported patterns:
      https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fxxx.png%3F...&refer=...
      https://...baidu.com/...?src=http%3A%2F%2Fxxx.png&...
    """
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if 'baidu.com' not in host:
        return None

    # Form 1: src= lives in the query string
    qs_src = None
    if parsed.query:
        try:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs_src_list = qs.get('src') or qs.get('srcUrl') or qs.get('src_url')
            if qs_src_list:
                qs_src = qs_src_list[0]
        except Exception:
            qs_src = None

    # Form 2: src= is embedded inside the path, e.g. /image_search/src=<encoded>&refer=...
    path_src = None
    path = parsed.path or ''
    idx = path.find('src=')
    if idx >= 0:
        rest = path[idx + 4:]
        end = len(rest)
        for sep in ('&', '?', '#'):
            pos = rest.find(sep)
            if 0 <= pos < end:
                end = pos
        path_src = rest[:end] if end > 0 else None

    encoded = path_src if path_src else qs_src
    if not encoded:
        return None
    try:
        decoded = unquote(encoded)
    except Exception:
        decoded = encoded
    # If it still looks percent-encoded, decode one more time
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
    """Download a single image to assets_dir; return the local filename (without directory).

    If url is a Baidu image-bed link and the download fails (or the response isn't image data),
    the function automatically parses the src= fallback URL and retries with the original source.
    Success on either attempt counts as a successful download.
    """
    filename = unique_filename(url)
    filepath = os.path.join(assets_dir, filename)
    if os.path.exists(filepath):
        print(f'Already exists, skipped: {filename}')
        return filename

    # If this looks like a Baidu image-bed link, pre-extract the original src for fallback
    fallback_url = extract_baidu_original_url(url)

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
            # Verify the response is actually an image (avoid saving HTML error pages like Baidu 404)
            if not is_image_data(data):
                msg = 'response is not an image (likely a dead link or error page)'
                print(f'Failed: {attempt_url}  error: {msg}')
                last_error = msg
                continue  # try the next fallback
            with open(filepath, 'wb') as f:
                f.write(data)
            if idx == 0:
                print(f'Downloaded: {attempt_url} -> {filepath} ({len(data)} bytes)')
            else:
                print(f'Baidu image-bed link unreachable, fell back to original: {attempt_url} -> {filepath} ({len(data)} bytes)')
            return filename
        except Exception as e:
            last_error = str(e)
            print(f'Failed: {attempt_url}  error: {e}')
            continue

    # All attempts exhausted
    if fallback_url:
        print(f'Both Baidu image-bed link and its original URL failed: {url} (original: {fallback_url})')
    else:
        print(f'Failed: {url}  error: {last_error}')
    return None


def collect_md_files_in_dir(directory):
    """Recursively collect all .md files under a directory."""
    md_files = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name.lower().endswith('.md'):
                md_files.append(os.path.join(root, name))
    return md_files


def process_markdown(md_path, cfg):
    """Download https images from a single md file; assets dir is next to the md."""
    if not os.path.isfile(md_path):
        print(f'File not found: {md_path}')
        return

    print(f'\nProcessing: {md_path}')
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    urls = [m.group(2) for m in IMAGE_PATTERN.finditer(content)]
    if not urls:
        print('No https:// image links found')
        return

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    assets_dir = assets_dir_for(md_path)
    ensure_assets_dir(assets_dir)

    print(f'Found {len(urls)} image links, {len(unique_urls)} unique')
    success = 0
    failed = []
    for url in unique_urls:
        if download_image(url, assets_dir, cfg):
            success += 1
        else:
            failed.append(url)
    print(f'Done: {success}/{len(unique_urls)} succeeded, assets dir: {assets_dir}')

    # Log failed URLs (in the script directory) for manual review
    if failed:
        log_path = os.path.join(SCRIPT_DIR, 'failed_urls.txt')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'# Failed at: {datetime.now()}\n')
            f.write(f'# Source file: {md_path}\n')
            for u in failed:
                f.write(u + '\n')
            f.write('\n')
        print(f'Failed links logged: {log_path} ({len(failed)} total)')


def replace_urls_in_markdown(md_path, url_to_local):
    """Rewrite https image links in a md file to ./assets/xxx local paths."""
    if not url_to_local:
        print(f'No links to replace: {md_path}')
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
        print(f'No changes: {md_path}')
        return

    # Back up the original file as .md.bak before rewriting, so a failed rewrite can be reverted
    bak_path = md_path + '.bak'
    with open(bak_path, 'w', encoding='utf-8') as f:
        f.write(content)

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'Replaced {len(url_to_local)} links: {md_path}')
    print(f'Backed up original: {bak_path}')


def option_download_files(cfg):
    """Option 1: specify file(s)."""
    raw = input('Enter markdown file path(s) (space-separated; quote paths with spaces): ').strip()
    if not raw:
        print('No path entered')
        return
    paths = parse_paths(raw)
    if not paths:
        print('No valid paths parsed')
        return
    for md in paths:
        process_markdown(md, cfg)


def option_download_folder(cfg):
    """Option 2: specify a folder (recursive)."""
    raw = input('Enter folder path: ').strip()
    if not raw:
        print('No path entered')
        return
    folder = os.path.abspath(raw.strip('"').strip("'"))
    if not os.path.isdir(folder):
        print(f'Not a valid directory: {folder}')
        return
    md_files = collect_md_files_in_dir(folder)
    if not md_files:
        print('No .md files found in this directory')
        return
    print(f'Found {len(md_files)} .md file(s)')
    for md in md_files:
        process_markdown(md, cfg)


def option_replace_urls():
    """Option 3: rewrite https to ./assets/xxx (no download, link rewrite only)."""
    raw = input('Enter the markdown file or folder path to rewrite: ').strip()
    if not raw:
        print('No path entered')
        return
    path = os.path.abspath(raw.strip('"').strip("'"))

    if os.path.isfile(path):
        md_files = [path] if path.lower().endswith('.md') else []
    elif os.path.isdir(path):
        md_files = collect_md_files_in_dir(path)
    else:
        print(f'Invalid path: {path}')
        return

    if not md_files:
        print('No .md files found')
        return

    # Process each md file separately: rewrite links only, no download.
    # Filename is generated from the URL's md5 hash, matching option 1/2 so links match later downloads.
    for md in md_files:
        md_path = os.path.abspath(md)
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        urls = [m.group(2) for m in IMAGE_PATTERN.finditer(content)]
        if not urls:
            print(f'\nNo https image links: {md_path}')
            continue

        # Deduplicate
        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        # Build url -> ./assets/xxx mapping (no download, path only)
        url_to_local = {url: './assets/' + unique_filename(url) for url in unique_urls}

        print(f'\nProcessing: {md_path}')
        print(f'Found {len(unique_urls)} unique link(s), rewriting (no download)...')
        replace_urls_in_markdown(md_path, url_to_local)

    print('\nAll done')


def show_menu():
    print('\n========== Markdown Image Downloader ==========')
    print('1. Specify file(s)    (download to ./assets next to the md)')
    print('2. Specify folder     (recursive scan)')
    print('3. Replace https links with ./assets paths (no download)')
    print('0. Exit')
    print('==============================================')


def main():
    # Load config once on startup
    cfg = load_config()
    print(f'Config loaded: {CONFIG_PATH}' if os.path.isfile(CONFIG_PATH) else 'config.json not found, using defaults')

    while True:
        show_menu()
        choice = input('Choose [0-3]: ').strip()

        if choice == '1':
            # Re-read before each run so config.json edits take effect without restarting
            cfg = load_config()
            option_download_files(cfg)
        elif choice == '2':
            cfg = load_config()
            option_download_folder(cfg)
        elif choice == '3':
            option_replace_urls()
        elif choice == '0':
            print('Bye')
            break
        else:
            print('Invalid choice, please try again')


if __name__ == '__main__':
    main()
