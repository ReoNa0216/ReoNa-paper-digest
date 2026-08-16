#!/usr/bin/env python3
"""封面路径统一解析 —— publish.py 与 publish-check.py 共用。

背景（HANDOFF M2 问题 #3）：publish-check.py 按固定候选位置找封面，publish.py
却只按 `article_dir / cover_image` 解析，导致「检查通过、上传时找不到封面」。

约定：meta.yaml 的 cover_image 按 SKILL 写入（如 `assets/covers/001-cover.png`），
该路径相对**专栏根目录**（articles/xxx 的上一级再上一级）。本模块统一按
「绝对路径 → 文章目录 → 专栏根目录」顺序解析，两脚本行为一致。
"""

from pathlib import Path


def resolve_cover(article_dir: Path, meta: dict) -> Path | None:
    """解析封面路径，返回存在的路径，否则 None。

    优先级：
      1. cover_image 为绝对路径且存在；
      2. article_dir / cover_image（相对文章目录）；
      3. 专栏根（article_dir.parent.parent）/ cover_image（SKILL 约定）。
    """
    cover = str(meta.get("cover_image") or "").strip()
    if not cover:
        return None
    p = Path(cover)
    if p.is_absolute():
        return p if p.exists() else None
    for base in (article_dir, article_dir.parent.parent):
        cand = (base / p).resolve()
        if cand.exists():
            return cand
    return None


def legacy_cover_candidates(article_dir: Path) -> list[Path]:
    """旧候选名（无 cover_image 字段时的回退提示列表，publish-check 告警用）。"""
    article_num = article_dir.name.split("-")[0]
    covers_dir = article_dir.parent.parent / "assets" / "covers"
    cands = [article_dir / f"cover.{ext}" for ext in ("jpg", "png", "webp")]
    cands += [covers_dir / f"{article_num}-cover.{ext}" for ext in ("jpg", "png", "webp")]
    return cands
