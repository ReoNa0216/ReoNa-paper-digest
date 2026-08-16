#!/usr/bin/env python3
"""
fetch-image.py — 下载外部图片到本地，用于微信公众号文章配图。
支持 HTTP/HTTPS 下载，自动处理 User-Agent，基础错误重试。
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path


def download_image(url: str, output_path: str, max_retries: int = 3) -> Path:
    """Download image from url to output_path with retries."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
                out.write_bytes(data)

            # Basic sanity check: file should not be HTML error page
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type and len(data) < 10_000:
                # Might be an error page; warn but keep file
                print(f"[warn] Downloaded content looks like HTML (attempt {attempt})", file=sys.stderr)

            print(f"[ok] Saved to {out.resolve()} ({len(data)} bytes)")
            return out

        except Exception as exc:
            last_error = exc
            print(f"[retry {attempt}/{max_retries}] {exc}", file=sys.stderr)
            time.sleep(1)

    print(f"[error] Failed to download image after {max_retries} attempts: {last_error}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Download an external image for wechat article assets."
    )
    parser.add_argument("--url", required=True, help="Image URL to download")
    parser.add_argument("--output", required=True, help="Local output path")
    parser.add_argument("--retries", type=int, default=3, help="Max retry attempts")
    args = parser.parse_args()

    download_image(args.url, args.output, args.retries)


if __name__ == "__main__":
    main()
