#!/usr/bin/env python3
"""new-column.py — 一键新建公众号文章合集（专栏）骨架

用户只需给一个名字，脚本在工作区根（仓库的上一级）下创建：
  合集名/
    EDITORIAL_CALENDAR.md   选题日历（表 + 空条目模板）
    BRAND_VOICE.md          人设/口吻/禁用词（直接复用 SKILL 的 L1 禁用词）
    ARTICLES_SUMMARY.md     每篇一行占位
    README.md               专栏说明 + 管线 + 文章目录表
    assets/covers/          封面目录

用法：
  python new-column.py 合集名                      # 用默认描述
  python new-column.py 合集名 --desc "一句话定位"  # 自定义定位
  python new-column.py 合集名 --audience "目标读者"
"""

import argparse
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = Path(__file__).resolve().parent.parent

L1_FORBIDDEN = (
    "值得注意的是、不难发现、由此可见、综上所述、总而言之、不可否认、毋庸置疑、"
    "不禁让人、令人深思、令人瞩目、深刻揭示、全面展示、具有重要意义、"
    "对……产生深远影响、开创了新的篇章、带来了新的启示、随着……的不断发展、"
    "在……的背景下、近年来……引起了广泛关注、相信在未来……、期待……能够……、"
    "让我们共同期待……"
)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def slugify(name: str) -> str:
    """目录名：去非法字符与空白。"""
    s = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    return re.sub(r"\s+", "-", s)


def main():
    ap = argparse.ArgumentParser(description="一键新建公众号文章合集骨架")
    ap.add_argument("name", help="合集名（将用作目录名）")
    ap.add_argument("--desc", default="", help="合集定位一句话（写入 README/日历）")
    ap.add_argument("--audience", default="相关领域研究生与从业者", help="目标读者")
    args = ap.parse_args()

    col = WORKSPACE / slugify(args.name)
    if col.exists():
        print(f"[error] 合集目录已存在：{col}")
        sys.exit(1)
    desc = args.desc or f"{args.name}：前沿论文精读公众号专栏"
    covers = col / "assets" / "covers"
    covers.mkdir(parents=True)

    (col / "EDITORIAL_CALENDAR.md").write_text(
        f"# {args.name} — 选题日历\n\n"
        f"> 更新时间：\n> 定位：{desc}\n\n"
        "## 写作进度\n\n| 序号 | 标题 | 状态 | 备注 |\n|---|---|---|---|\n\n"
        "## 选题条目\n\n",
        encoding="utf-8",
    )
    (col / "BRAND_VOICE.md").write_text(
        f"# Brand Voice: {args.name}\n\n"
        "## 人设定位\n"
        f"- {desc}\n\n"
        "## 人称与口吻\n"
        "- 主视角：第一人称「我」/「我们」\n"
        "- 语气：冷静、理性、略带好奇；先讲清楚机制，再指出证据边界\n"
        "- 特色：每篇必须区分「作者说了什么」与「证据支持了什么」，对方法学缺陷直言不讳\n"
        f"- 禁用词（L1 硬规则）：{L1_FORBIDDEN}\n\n"
        "## 引用风格\n"
        "- 优先引用顶刊论文与官方技术博客；正文 `[n]` 引用，文末「## 参考文献」与 refs.md 对应；编号必须连续。\n",
        encoding="utf-8",
    )
    (col / "ARTICLES_SUMMARY.md").write_text(
        "# Articles Summary (Auto-maintained — DO NOT edit manually except after article completion)\n\n"
        "## 文章清单\n\n",
        encoding="utf-8",
    )
    (col / "README.md").write_text(
        f"# {args.name} — 专栏说明\n\n"
        f"## 定位\n{desc}\n\n"
        "## 管线\n"
        "- 材料：ChatGPT 讨论对话（`materials/chat/dialogue.md`）+ 论文 PDF（`materials/`）\n"
        "- 收料：`ReoNa-paper-digest/scripts/prepare.py inbox/子文件夹 --title \"标题\" --series 本合集名`\n"
        "- 正文：`articles/00X-标题/article.md`（唯一正文源，WeMD 方言）\n"
        "- 渲染：`ReoNa-paper-digest/scripts/render.py` → dist/（微信可粘贴）\n"
        "- 发布：`ReoNa-paper-digest/scripts/publish.py` 存草稿（群发人工）\n\n"
        "## 文章目录\n\n| 序号 | 标题 | 状态 |\n|---|---|---|\n\n",
        encoding="utf-8",
    )

    print(f"[ok] 合集骨架已建好：{col}")
    print("  下一步：把材料丢进 inbox/子文件夹，运行 prepare.py --series "
          f"{slugify(args.name)} 开始第一篇")


if __name__ == "__main__":
    main()
