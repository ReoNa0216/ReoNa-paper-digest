#!/usr/bin/env python3
"""summary.py — 从 article.md 自动生成/刷新 meta.yaml 的 summary（≤120 字，微信摘要上限）。

默认调用 DeepSeek 生成高质量中文摘要（密钥读取顺序：环境变量 DEEPSEEK_API_KEY →
工作区根 .env → $DSH_HOME/.credentials.yaml 兜底，统一走 secrets_env.py）；
无密钥时退回规则抽取（取开头钩子 + 结语）。

用法：
  python summary.py articles/00X-标题          # 生成并写入 meta.yaml summary
  python summary.py articles/00X-标题 --print   # 只打印不写入
"""

import argparse
import os
import pathlib
import re
import sys

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MAX_LEN = 120  # 微信摘要上限（字符）


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def load_key() -> str:
    from secrets_env import get_secret
    return get_secret("DEEPSEEK_API_KEY", yaml_key="DEEPSEEK_API_KEY")


def strip_md(text: str) -> str:
    """去掉 markdown 语法，提取纯文本供摘要。"""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)          # 代码/流程图块
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)            # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # 链接
    text = re.sub(r"<[^>]+>", " ", text)                          # HTML（fig-caption 等）
    text = re.sub(r"\$\$.*?\$\$|\$[^$\n]+?\$", " ", text, flags=re.S)  # 公式
    text = re.sub(r"[#>*|`=\-]{1,}", " ", text)                  # markdown 符号
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def llm_summary(article_text: str, key: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    prompt = (
        "请为下面的公众号文章写一段中文摘要，要求："
        "不超过 110 字（微信摘要上限 120 字，需留余量自然收尾）；"
        "突出文章核心方法、关键数据与结论；客观不浮夸；"
        "不以『本文』开头。只输出摘要本身。\n\n文章内容：\n" + article_text[:6000]
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是严谨的科研公众号编辑。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()


def rule_summary(article_text: str) -> str:
    """无密钥时的规则回退：开头钩子段 + 结语首句。"""
    paras = [p.strip() for p in article_text.split("\n\n") if p.strip()]
    parts = []
    for p in paras:
        if p and not p.startswith(("图 ", "## ", "# ")):
            parts.append(p)
            break  # 第一段正文
    for p in reversed(paras):
        if p.startswith("把技术贡献") or p.startswith("结语"):
            parts.append(p)
            break
    return "".join(parts)[:MAX_LEN]


def clip_sentence(s: str, limit: int) -> str:
    """在 limit 内按句子边界截断，避免停在句中。"""
    if len(s) <= limit:
        return s
    cut = s[:limit]
    last = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
    return cut[: last + 1] if last > 0 else cut


def main():
    ap = argparse.ArgumentParser(description="自动生成文章摘要并写入 meta.yaml")
    ap.add_argument("article_dir", help="文章目录（含 article.md / meta.yaml）")
    ap.add_argument("--print", action="store_true", help="只打印不写入")
    args = ap.parse_args()

    article_dir = pathlib.Path(args.article_dir).resolve()
    md = article_dir / "article.md"
    meta_path = article_dir / "meta.yaml"
    if not md.exists():
        fail(f"缺少 article.md：{md}")
    if not meta_path.exists():
        fail(f"缺少 meta.yaml：{meta_path}")

    text = strip_md(md.read_text(encoding="utf-8"))
    key = load_key()
    if key:
        summary = llm_summary(text, key)
        source = "DeepSeek"
    else:
        summary = rule_summary(text)
        source = "规则回退"
    if not summary:
        fail("摘要生成为空")
    summary = summary.replace("\n", " ").strip()
    summary = clip_sentence(summary, MAX_LEN)

    print(f"[summary] 来源：{source}（{len(summary)} 字）")
    print(f"[summary] {summary}")
    if args.print:
        return

    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    meta["summary"] = summary
    meta_path.write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"[ok] 已写入 {meta_path}")


if __name__ == "__main__":
    main()
