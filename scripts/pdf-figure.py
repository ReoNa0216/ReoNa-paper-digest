#!/usr/bin/env python3
"""pdf-figure.py — 从论文 PDF 按图注关键词提取整图（渲染为 PNG），供文章插图使用。

用法：
  python pdf-figure.py <pdf> <关键词> --out <png> [--page N] [--dpi 150]

策略：
  1. 在 PDF 全文中定位含关键词的页，默认取【最后出现】的页——补充材料的图注列表在
     文档前部，正式图页在后部，取最后一页才是图本身所在的页；主文图可用 --page 直接指定。
  2. 取该页所有面积较大的内嵌位图 bbox 的并集作为图形区域（整图 / 多面板图都能覆盖，
     过滤掉页眉 logo 等小装饰）。
  3. 以指定 DPI 渲染该区域输出 PNG（默认 200 DPI，手机端清晰够用）。

示例：
  python pdf-figure.py IMMS_MetCell_sup.pdf "Supplementary Figure 6." --out images/fig-s6.png
  python pdf-figure.py IMMS_MetCell.pdf "Fig. 4" --page 6 --out images/fig-4.png
"""

import argparse
import pathlib
import sys

import fitz

MIN_AREA = 30_000  # pt²，过滤页眉 logo / 小装饰图


def find_figure_pages(doc, kw: str) -> list:
    return [i for i, page in enumerate(doc) if kw in page.get_text()]


def figure_clip(page) -> fitz.Rect:
    infos = [
        i for i in page.get_image_info()
        if (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) >= MIN_AREA
    ]
    if not infos:
        return page.rect
    x0 = min(i["bbox"][0] for i in infos)
    y0 = min(i["bbox"][1] for i in infos)
    x1 = max(i["bbox"][2] for i in infos)
    y1 = max(i["bbox"][3] for i in infos)
    return fitz.Rect(x0, y0, x1, y1)


def main():
    ap = argparse.ArgumentParser(description="从论文 PDF 提取整图")
    ap.add_argument("pdf", help="PDF 路径")
    ap.add_argument("kw", help="图注关键词，如 'Supplementary Figure 6.'")
    ap.add_argument("--out", required=True, help="输出 PNG 路径")
    ap.add_argument("--dpi", type=int, default=200, help="渲染 DPI（默认 200）")
    ap.add_argument("--page", type=int, default=None, help="直接指定页（1-based），跳过关键词定位")
    ap.add_argument("--caption", action="store_true",
                    help="按图注定位图区：clip 顶部取页眉之下、底部取图注开始处之上（图注裁掉，主文整页图用）")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    if args.page:
        idx = args.page - 1
        if not (0 <= idx < len(doc)):
            print(f"[error] 页码越界：{args.page}", file=sys.stderr)
            sys.exit(1)
    else:
        hits = find_figure_pages(doc, args.kw)
        if not hits:
            print(f"[error] 未找到含 '{args.kw}' 的页", file=sys.stderr)
            sys.exit(1)
        idx = hits[-1]  # 图注列表在前、正式图页在后，取最后出现页
    page = doc[idx]

    if args.caption:
        blocks = [b for b in page.get_text("blocks") if b[4].strip()]
        start = next((b for b in blocks if args.kw in b[4]), None)
        if start is None:
            print(f"[error] 页 {idx + 1} 未找到图注文字 '{args.kw}'", file=sys.stderr)
            sys.exit(1)
        # 顶部 = 页眉（页面上最靠上的文本块）之下，避开页眉
        header = min(blocks, key=lambda b: b[1])
        y0 = (header[3] + 6) if header else 40.0
        # 底部 = 图注开始处之上（图注裁掉，图区到图注顶部为止）
        y1 = start[1] - 2
        clip = fitz.Rect(20, y0, page.rect.width - 20, y1)
    else:
        clip = figure_clip(page)
    zoom = args.dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    print(f"[ok] {out}（页 {idx + 1}，区域 {clip}，{pix.width}x{pix.height}）")


if __name__ == "__main__":
    main()
