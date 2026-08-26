# Markdown 图片下载器

[English](./README_EN.md) | 简体中文

交互式工具，扫描 Markdown 文档中的 `![alt](https://...)` 和 HTML `<img src="https://...">` 图片链接，下载到 `./assets` 目录，可选把链接替换为本地路径。

> 主程序语言：[中文版 download_images_zh.py](./download_images_zh.py) | [英文版 download_images_en.py](./download_images_en.py)

## 功能

- 交互式菜单：选择处理单个文件、文件夹（递归嵌套子目录）、替换链接或重命名本地图片
- 正则匹配所有 https 开头的 Markdown 图片链接（`![alt](url)`）与 HTML `<img src="url">` 标签
  - 支持双引号 `src="..."` 与单引号 `src='...'` 两种写法
  - 支持大小写不敏感（`<IMG SRC=...>`）、自闭合 `<img ... />`、`src` 属性不限制位置
  - 替换链接时仅改 `src` 值，`alt`、`style`、`class`、`width` 等其他属性原样保留
- 自动创建 `./assets` 目录（在 md 文件所在目录下，不存在时）
- 用 URL 的 md5 哈希命名，避免重名覆盖与重复下载
- 百度图床链接自动回退：当 `*.baidu.com` 链接失效时，自动解析 `src=` 参数还原原始图片链接并重试下载
- 支持 `config.json` 配置请求头和 Cookie，应对防盗链
- 已下载的链接会跳过，支持增量更新
- 失败链接自动记录到 `failed_urls.txt`，方便手动处理
- 选项 3 把 md 中的 Markdown 与 HTML 图片链接统一替换为 `./assets/xxx`（不下载）
- 选项 4 将本地图片重命名为程序使用的 md5 哈希命名格式

## 环境要求

- Python 3.6+
- 仅使用标准库，无需安装第三方依赖

## 使用方法

中文版：

```bash
python download_images_zh.py
```

英文版：

```bash
python download_images_en.py
```

启动后显示菜单：

```
========== Markdown 图片下载器 ==========
1. 指定文件       (下载图片到 md 所在目录的 ./assets)
2. 指定文件夹     (递归扫描子目录)
3. 替换 https 链接为 ./assets 路径 (不下载)
4. 图片重命名       (将本地图片重命名为 md5 哈希格式)
0. 退出
==========================================
```

### 选项 1：指定文件

输入一个或多个 md 文件路径（空格分隔，含空格用双引号包裹），扫描其中的 Markdown 图片语法和 HTML `<img>` 标签，下载 https 图片到该 md 所在目录的 `assets/`。

### 选项 2：指定文件夹

输入文件夹路径，递归扫描所有子目录中的 `.md` 文件并下载图片（含 Markdown 和 HTML `<img>` 两种写法）。

### 选项 3：替换 https 链接为 ./assets 路径

输入文件或文件夹路径，把 md 中的 Markdown 图片链接与 HTML `<img src=...>` 标签统一替换为 `./assets/xxx` 本地路径，**不下载图片**，原文件就地更新。HTML 标签替换时仅修改 `src` 的值，`alt`、`style` 等其他属性保持不变。文件名生成规则与下载时一致，方便先替换链接再下载。

### 选项 4：图片重命名

输入本地图片文件路径（可直接拖入终端，多个用空格分隔），程序将文件重命名为 md5 哈希格式（如 `Snipaste_2026-08-21_14-58-41.png` → `3a7b980484bfd3d3.png`）。原文件就地重命名，不移动位置。

## 百度图床自动回退

当下载百度图床链接（`*.baidu.com`）失败时（网络错误或返回的是 HTML 错误页），程序会自动解析 URL 中 `src=` 参数指向的原始图片链接，并切换到该链接重新下载。

支持的 `src=` 位置：
- Path 内嵌形式：`/image_search/src=<编码URL>&refer=...`（最常见）
- Query 参数形式：`?src=<编码URL>&...`（兼容 `srcUrl` / `src_url` 键名）

对编码值执行最多两层 `unquote` 解码，避免二次百分号编码未还原的问题。回退时会按原始链接域名重新匹配 `per_host` 规则，自动带上正确的 `Referer` 和 `Cookie`。

## 配置文件 config.json

位于脚本同目录，用于自定义请求头和 Cookie，应对防盗链图床。结构如下：

```json
{
    "headers": {
        "User-Agent": "...",
        "Accept": "..."
    },
    "cookies": "key1=val1; key2=val2",
    "per_host": {
        "sinaimg.cn": {
            "headers": { "Referer": "https://weibo.com/" },
            "cookies": ""
        }
    }
}
```

- `headers`：对所有请求生效的通用请求头
- `cookies`：对所有请求生效的 Cookie 字符串
- `per_host`：按域名定制（子串匹配，如 host 包含 `sinaimg.cn` 即命中），覆盖通用设置

**每次执行选项 1/2 前会重新读取配置**，修改 `config.json` 后无需重启程序，下次执行即生效。

## 示例

输入 `note.md`：

```markdown
![image](https://example.com/a.png)

<img src="https://example.com/b.png" alt="示意图" style="zoom:75%;" />
```

运行选项 3 后：

```markdown
![image](./assets/3f8a9b2c1d4e5f6a.png)

<img src="./assets/8e5c1d7d0c4a9c0c.png" alt="示意图" style="zoom:75%;" />
```

HTML 标签的 `alt`、`style` 等属性原样保留，仅 `src` 被替换为本地路径。

## 文件说明

- `download_images_zh.py` — 主程序（中文）
- `download_images_en.py` — 主程序（英文）
- `config.json` — 请求头与 Cookie 配置（中英双语说明）
- `failed_urls.txt` — 下载失败的链接日志（运行后生成）
- `assets/` — 图片输出目录（在 md 文件所在目录下自动创建）
