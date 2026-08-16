#!/usr/bin/env python3
"""prepare.py — 一键收料：inbox/子文件夹 → articles/00X-标题 完整骨架

用户约定（2026-08-16）：
  1. 在 inbox/ 下建一个子文件夹（名字随意，最好含标题关键词）
  2. 把材料丢进去：对话导出（.md/.zip/.json）+ 论文 PDF + 补充材料 PDF
  3. 运行：python prepare.py inbox/子文件夹 --title "文章标题" [--series scOmics]
  4. 脚本自动：识别材料 → 建 articles/骨架 → 归档 PDF → 跑 ingest.py → 汇报

识别规则：
  - PDF：文件名含 sup/supplementary/补充 或更小体积 → 补充材料；否则主论文
  - 对话：.md / .zip / .json（交给 ingest.py 处理）
  - 冲突（两个 PDF 都像补充）时停下问用户，不猜测

用法：
  python prepare.py <inbox_subdir> --title "标题"
  python prepare.py <inbox_subdir> --title "标题" --series myColumn --article-number 3
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
INGEST = SCRIPTS / "ingest.py"

SUP_KEYWORDS = ("sup", "supplement", "补充", "supporting", "si_", "s1", "extended")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def ask(question: str, options: list) -> str:
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        try:
            n = int(input("请输入编号：").strip())
            if 1 <= n <= len(options):
                return options[n - 1]
        except (ValueError, EOFError):
            pass
        print("无效输入，请重试。")


def classify_pdfs(pdfs: list) -> dict:
    """按文件名关键词 + 体积分主论文/补充材料。无法区分时让用户决定。"""
    mains, sups = [], []
    for p in pdfs:
        low = p.stem.lower()
        if any(k in low for k in SUP_KEYWORDS):
            sups.append(p)
        else:
            mains.append(p)
    # 无关键词且多于 1 个「主论文」候选：按体积取最大的为主，其余问用户
    while len(mains) > 1:
        big = max(mains, key=lambda x: x.stat().st_size)
        print(f"[ask] 有 {len(mains)} 个 PDF 未识别为补充材料："
              + "、".join(m.name for m in mains))
        choice = ask("哪个是主论文？", [m.name for m in mains] + ["都不是，列为补充材料"])
        if choice == "都不是，列为补充材料":
            for m in mains:
                sups.append(m)
            mains = []
        else:
            picked = next(m for m in mains if m.name == choice)
            mains = [picked]
            sups.extend(m for m in mains if m is not picked)
    return {"main": mains[0] if mains else None, "sup": sups}


def next_article_dir(articles_dir: Path, series_prefix: str, explicit: int | None) -> Path:
    if explicit is not None:
        return articles_dir / f"{explicit:03d}-待定标题"
    nums = []
    for d in articles_dir.glob("*-*") if articles_dir.exists() else []:
        m = re.match(r"(\d+)", d.name)
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return articles_dir / f"{nxt:03d}-待定标题"


def main():
    ap = argparse.ArgumentParser(description="inbox 子文件夹 → articles/骨架（一键收料）")
    ap.add_argument("subdir", help="inbox 下的材料文件夹（相对或绝对路径）")
    ap.add_argument("--title", required=True, help="文章标题（写入目录名与 meta.yaml）")
    ap.add_argument("--series", default="scOmics", help="专栏目录名（默认 scOmics）")
    ap.add_argument("--article-number", type=int, default=None, help="手动指定序号（默认自动取下一篇）")
    args = ap.parse_args()

    src = Path(args.subdir)
    if not src.is_absolute():
        src = WORKSPACE / "inbox" / src
    if not src.exists() or not src.is_dir():
        fail(f"材料文件夹不存在：{src}")

    files = [p for p in src.iterdir() if p.is_file()]
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    chats = [p for p in files if p.suffix.lower() in (".md", ".zip", ".json")]
    others = [p for p in files if p not in pdfs and p not in chats]
    if not pdfs and not chats:
        fail(f"{src} 里没有 PDF 或对话文件，请检查")
    if others:
        print(f"[warn] 忽略无法识别的文件：{'、'.join(p.name for p in others)}")
    if not pdfs:
        print("[warn] 未找到 PDF（主论文/补充材料）")
    if not chats:
        print("[warn] 未找到对话导出（.md/.zip/.json）")

    # 1) 分类 PDF
    pdf_map = classify_pdfs(pdfs) if pdfs else {"main": None, "sup": []}

    # 2) 建文章目录骨架
    column = WORKSPACE / args.series
    articles_dir = column / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    art = next_article_dir(articles_dir, args.series, args.article_number)
    num = int(re.match(r"(\d+)", art.name).group(1))
    slug = re.sub(r'[\\/:*?"<>|]', "", args.title).strip()
    art = art.parent / f"{num:03d}-{slug}"
    if art.exists():
        fail(f"文章目录已存在：{art}")
    (art / "materials" / "chat").mkdir(parents=True)
    (art / "images").mkdir(parents=True)

    # 3) 归档 PDF
    if pdf_map["main"]:
        dst = art / "materials" / pdf_map["main"].name
        shutil.copy2(pdf_map["main"], dst)
        print(f"[ok] 主论文   → {dst.relative_to(WORKSPACE)}")
    for sp in pdf_map["sup"]:
        dst = art / "materials" / sp.name
        shutil.copy2(sp, dst)
        print(f"[ok] 补充材料 → {dst.relative_to(WORKSPACE)}")

    # 4) 跑 ingest.py（对话）
    chat_src = chats[0] if len(chats) == 1 else None
    if len(chats) > 1:
        print(f"[ask] 有 {len(chats)} 个对话文件："
              + "、".join(c.name for c in chats))
        chat_src = Path(ask("用哪个作为正文对话材料？", [c.name for c in chats] + ["全部忽略"]))
        if chat_src.name == "全部忽略":
            chat_src = None
    if chat_src:
        out = art / "materials" / "chat"
        cmd = [sys.executable, str(INGEST), str(chat_src), "--out", str(out)]
        # 官方 zip 多对话时可能需要 --title-filter；先试 --list 提示
        print(f"[ingest] 运行：{' '.join(cmd)}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("[warn] ingest 未成功——若官方 zip 含多个对话，请用 --title-filter 手动指定")
    else:
        print("[warn] 未处理对话，后续可手动：python scripts/ingest.py <文件> --out "
              f"{art.relative_to(WORKSPACE)}/materials/chat")

    # 5) 写骨架文件（article.md 留到写作阶段）
    meta = f"""title: '{args.title}'
subtitle: ''
series: {args.series}
article_number: {num}
estimated_word_count: 3500
tags:
- （写作时填写）
keywords:
- （写作时填写）
status: draft
scheduled_publish_date: ''
last_edited: ''
author_note: ''
cover_image: assets/covers/{num:03d}-cover.png
target_audience: 计算生物学、生物信息学相关专业的研究生与本科生
difficulty: ''
summary: （写作完成后由 summary.py 自动生成）
"""
    (art / "meta.yaml").write_text(meta, encoding="utf-8")
    (art / "refs.md").write_text(
        f"# Article {num:03d}：{args.title} — 参考文献\n\n"
        "> 更新时间：（写作阶段填写）\n> 来源：论文正文/补充材料 + 对话材料\n\n---\n\n"
        "## 核心论文\n\n[1] （写作阶段按引用顺序补全）\n\n"
        "## 相关工具与数据库\n\n## 对比方法 / 背景文献\n",
        encoding="utf-8",
    )
    pdf_names = "、".join(p.name for p in pdfs) if pdfs else "（未提供）"
    (art / "materials.md").write_text(
        f"# {args.title} 阅读材料\n\n"
        f"> 来源：用户与 ChatGPT 的讨论（见 materials/chat/dialogue.md）\n"
        f"> 原文 PDF：{pdf_names}\n\n---\n\n"
        "## 讨论逻辑脉络\n\n（写作阶段按 dialogue.md 追问链整理）\n",
        encoding="utf-8",
    )

    print(f"\n[done] 骨架已建好：{art.relative_to(WORKSPACE)}")
    print("  下一步（Phase 3 写作）由 Agent 完成；准备就绪后可说「开始写作」")


if __name__ == "__main__":
    main()
