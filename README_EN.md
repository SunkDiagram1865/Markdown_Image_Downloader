# Markdown Image Downloader

English | [简体中文](./README.md)

Interactive tool that scans Markdown documents for `![alt](https://...)` image links, downloads them to a local `./assets` directory, and optionally rewrites the links to local paths.

## Features

- Interactive menu: process a single file, a folder (recursive), or rewrite links
- Regex matching for all https image links in Markdown
- Auto-creates `./assets` directory (in the md file's directory) if missing
- Unique filenames via URL md5 hash — no overwrites, no duplicate downloads
- `config.json` support for custom headers and cookies (bypass anti-leech)
- Already-downloaded images are skipped (incremental updates)
- Failed links are logged to `failed_urls.txt` for manual review
- Option 3 rewrites `https://...` to `./assets/xxx` without downloading

## Requirements

- Python 3.6+
- Standard library only — no third-party dependencies

## Usage

```bash
python download_images.py
```

The menu appears on launch:

```
========== Markdown Image Downloader ==========
1. Specify file(s)    (download to ./assets next to the md)
2. Specify folder     (recursive scan)
3. Replace https links with ./assets paths (no download)
0. Exit
==========================================
```

### Option 1: Specify file(s)

Enter one or more md file paths (space-separated; quote paths containing spaces). Images are downloaded to an `assets/` folder created next to each md file.

### Option 2: Specify folder

Enter a folder path. All `.md` files in the folder and its subdirectories are scanned and images downloaded.

### Option 3: Replace https links with ./assets paths

Enter a file or folder path. Markdown `https://...` links are rewritten to `./assets/xxx` local paths **without downloading**. The original file is updated in place. Filename generation matches the download logic, so you can rewrite links first and download later.

## Configuration file: config.json

Located next to the script. Used to customize request headers and cookies for anti-leech image hosts. Structure:

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

- `headers` — common headers applied to all requests
- `cookies` — common cookie string applied to all requests
- `per_host` — per-host overrides (substring match; e.g. a host containing `sinaimg.cn` matches). Overrides common settings.

**Config is re-read before each run of option 1/2**, so editing `config.json` takes effect on the next run without restarting the program.

## Example

Input `note.md`:

```markdown
![image](https://example.com/a.png)
```

After running option 3:

```markdown
![image](./assets/3f8a9b2c1d4e5f6a.png)
```

## Files

- `download_images.py` — main program
- `config.json` — headers and cookies configuration
- `failed_urls.txt` — failed download log (generated at runtime)
- `assets/` — image output directory (auto-created next to each md file)
