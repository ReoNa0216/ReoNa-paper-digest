#!/usr/bin/env python3
"""publish-check.py — 微信公众号文章发布前检查（PyYAML 版）。

检查项：
  1. 正文字数（1500-8000 为参考区间，超界仅告警）
  2. meta.yaml 完整性（title / summary / tags）与 status 状态机合法性
  3. 封面图存在性
  4. 文中本地图片路径有效性
  5. [n] 引用与 refs.md 条目闭环
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

from wechat_cover import legacy_cover_candidates, resolve_cover

VALID_STATUS = {"planned", "draft", "rendered", "published"}
REQUIRED_META_FIELDS = ["title", "summary", "tags"]

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def load_meta(path: Path):
    """返回 (meta, parse_ok)。meta=None 表示文件缺失。"""
    if not path.exists():
        return None, True
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            data = {}
        if not isinstance(data, dict):
            print(f"[error] meta.yaml 顶层必须是键值映射")
            return {}, False
        return data, True
    except yaml.YAMLError as exc:
        print(f"[error] meta.yaml 解析失败：{exc}")
        return {}, False


def check_article(article_dir: Path) -> int:
    """Run all checks for a single article directory. Returns error count."""
    errors = 0
    article_md = article_dir / "article.md"
    meta_yaml = article_dir / "meta.yaml"

    if not article_md.exists():
        print(f"[error] Missing {article_md}")
        return 1

    text = article_md.read_text(encoding="utf-8")

    # 1. Word count (Chinese characters + English words approx)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    word_count = chinese_chars + english_words
    print(f"[info] Estimated word count: {word_count} (CN chars: {chinese_chars}, EN words: {english_words})")
    if word_count < 1500:
        print(f"[warn] Word count ({word_count}) is quite short for a research article.")
    elif word_count > 8000:
        print(f"[warn] Word count ({word_count}) is very long; consider splitting.")

    # 2. meta.yaml completeness + status state machine
    meta, parse_ok = load_meta(meta_yaml)
    if meta is None:
        print(f"[error] Missing meta.yaml")
        errors += 1
    elif not parse_ok:
        errors += 1
    else:
        missing = [f for f in REQUIRED_META_FIELDS if f not in meta or not meta.get(f)]
        if missing:
            print(f"[error] meta.yaml missing fields: {', '.join(missing)}")
            errors += 1
        else:
            print("[ok] meta.yaml fields look complete")
        status = str(meta.get("status") or "")
        if status and status not in VALID_STATUS:
            print(f"[warn] meta.yaml status '{status}' 不在状态机 {sorted(VALID_STATUS)} 中")
        else:
            print(f"[info] status: {status or '(未设置)'}")

    # 3. Cover image existence（与 publish.py 统一解析：meta.cover_image 优先）
    meta_dict = meta if isinstance(meta, dict) else {}
    cover = resolve_cover(article_dir, meta_dict) if meta_dict else None
    if cover:
        print(f"[ok] Cover image found: {cover}")
    else:
        candidates = list(legacy_cover_candidates(article_dir))
        found = [c for c in candidates if c.exists()]
        if found:
            print(f"[ok] Cover image found (legacy): {found[0]}")
        else:
            print("[warn] No cover image found. Expected one of:")
            for c in candidates:
                print(f"       - {c}")

    # 4. Local image path validation
    img_paths = re.findall(r"!\[.*?\]\((.*?)\)", text)
    broken_images = []
    for img_path in img_paths:
        if img_path.startswith(("http://", "https://", "data:")):
            print(f"[warn] Article references non-local image (should be local): {img_path[:60]}")
            continue
        resolved = (article_dir / img_path).resolve()
        if not resolved.exists():
            broken_images.append(img_path)

    if broken_images:
        print(f"[error] Broken local image paths ({len(broken_images)}):")
        for p in broken_images:
            print(f"       - {p}")
        errors += len(broken_images)
    else:
        print("[ok] All local image paths are valid")

    # 5. Citation integrity
    refs_md = article_dir / "refs.md"
    text_before_refs = text.split("## 参考文献")[0] if "## 参考文献" in text else text
    citations = set(re.findall(r"\[(\d+)\]", text_before_refs))
    if refs_md.exists():
        refs_text = refs_md.read_text(encoding="utf-8")
        ref_entries = set(re.findall(r"(?m)^\[(\d+)\]", refs_text))
        numbered_refs = set(re.findall(r"(?m)^\s*(\d+)\.", refs_text))
        valid_refs = ref_entries | numbered_refs

        missing_refs = [c for c in citations if c not in valid_refs]
        if missing_refs:
            print(f"[error] Citations without refs.md entries: {', '.join(f'[{c}]' for c in missing_refs)}")
            errors += len(missing_refs)
        else:
            print(f"[ok] All {len(citations)} citations have corresponding refs.md entries")
    else:
        if citations:
            print(f"[error] Article has {len(citations)} citations but refs.md is missing")
            errors += 1
        else:
            print("[ok] No citations and no refs.md (acceptable)")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Pre-publish check for wechat article.")
    parser.add_argument("--article-dir", required=True, help="Path to the article directory")
    args = parser.parse_args()

    article_dir = Path(args.article_dir)
    if not article_dir.is_dir():
        print(f"[error] Not a directory: {article_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Publish Check: {article_dir.name} ===\n")
    error_count = check_article(article_dir)
    print()
    if error_count == 0:
        print("=== Result: PASS ===")
        sys.exit(0)
    else:
        print(f"=== Result: FAIL ({error_count} issue(s)) ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
