# Markdown 图片下载器

交互式工具，扫描 Markdown 文档中的 `![alt](https://...)` 图片链接，下载到 `./assets` 目录，可选把链接替换为本地路径。

## 功能

- 交互式菜单：选择处理单个文件、文件夹（递归嵌套子目录），或替换链接
- 正则匹配所有 https 开头的 markdown 图片链接
- 自动创建 `./assets` 目录（在 md 文件所在目录下，不存在时）
- 用 URL 的 md5 哈希命名，避免重名覆盖与重复下载
- 支持 `config.json` 配置请求头和 Cookie，应对防盗链
- 已下载的链接会跳过，支持增量更新
- 失败链接自动记录到 `failed_urls.txt`，方便手动处理
- 选项 3 把 markdown 里的 `https://...` 替换为 `./assets/xxx`（不下载）

## 环境要求

- Python 3.6+
- 仅使用标准库，无需安装第三方依赖

## 使用方法

```bash
python download_images.py
```

启动后显示菜单：

```
========== Markdown 图片下载器 ==========
1. 指定文件       (下载图片到 md 所在目录的 ./assets)
2. 指定文件夹     (递归扫描子目录)
3. 替换 https 链接为 ./assets 路径 (不下载)
0. 退出
==========================================
```

### 选项 1：指定文件

输入一个或多个 md 文件路径（空格分隔，含空格用双引号包裹），下载其中的 https 图片到该 md 所在目录的 `assets/`。

### 选项 2：指定文件夹

输入文件夹路径，递归扫描所有子目录中的 `.md` 文件并下载图片。

### 选项 3：替换 https 链接为 ./assets 路径

输入文件或文件夹路径，把 markdown 中的 `https://...` 链接替换为 `./assets/xxx` 本地路径，**不下载图片**，原文件就地更新。文件名生成规则与下载时一致，方便先替换链接再下载。

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
```

运行选项 3 后：

```markdown
![image](./assets/3f8a9b2c1d4e5f6a.png)
```

## 文件说明

- `download_images.py` — 主程序
- `config.json` — 请求头与 Cookie 配置
- `failed_urls.txt` — 下载失败的链接日志（运行后生成）
- `assets/` — 图片输出目录（在 md 文件所在目录下自动创建）
