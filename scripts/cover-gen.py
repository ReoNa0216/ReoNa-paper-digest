#!/usr/bin/env python3
"""cover-gen.py — 用 ZenMux 的 gpt-image-2 生成公众号封面（900×383 PNG）。

流程（对齐 SKILL「封面」章节）：
  1. 文章定稿后，先审计封面提示词（须忠于文章传达的内容），再调用本工具；
  2. 经 ZenMux OpenAI 兼容端点（/api/v1/images/generations）生成 1280×544
     （边长 16 的倍数、比例 2.35，符合 gpt-image-2 约束）；
  3. 生成 4 张供挑选，选定后用 PIL 缩放至 900×383 写入目标路径。

注：ZenMux 另有 Vertex AI 兼容端点，但实测 generate_images 返回 500；
本工具使用文档主推的 OpenAI 兼容路径。

密钥读取顺序（统一走 secrets_env.py，发布安全）：
  1. 环境变量 ZENMUX_API_KEY；
  2. 工作区根 .env 文件（gitignore 排除）；
  3. （旧场景兜底）$DSH_HOME/.credentials.yaml 的 ZENMUX_API_KEY 字段。

用法：
  python cover-gen.py -f prompts/20260815-cover.md --out-dir assets/covers --slug 001
  python cover-gen.py --final assets/covers/001-cover-2.png -o assets/covers/001-cover.png
"""

import argparse
import base64
import pathlib
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ZENMUX_BASE = "https://zenmux.ai/api/v1"
DEFAULT_MODEL = "gpt-image-2"
GEN_SIZE = "1280x544"      # 边长 16 倍数、比例 ≈ 900/383
FINAL_SIZE = (900, 383)


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def load_key() -> str:
    from secrets_env import require_secret
    return require_secret("ZENMUX_API_KEY", yaml_key="ZENMUX_API_KEY")


def load_prompt(path: pathlib.Path) -> str:
    """提示词文件：第一个独立 `---` 之前是元数据（人类读），之后是发给模型的正文。"""
    text = path.read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    return parts[1].strip() if len(parts) > 1 else text.strip()


def generate(prompt: str, out_dir: pathlib.Path, slug: str, n: int, quality: str):
    from openai import OpenAI

    client = OpenAI(api_key=load_key(), base_url=ZENMUX_BASE)
    print(f"[cover] 调用 {DEFAULT_MODEL}（{GEN_SIZE}，quality={quality}，n={n}）…")
    resp = client.images.generate(
        model=DEFAULT_MODEL,
        prompt=prompt,
        n=n,
        size=GEN_SIZE,
        quality=quality,
        output_format="png",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, item in enumerate(resp.data, 1):
        if not item.b64_json:
            fail(f"第 {i} 张返回为空（可能被内容审核拦截）")
        p = out_dir / f"{slug}-cover-{i}.png"
        p.write_bytes(base64.b64decode(item.b64_json))
        paths.append(p)
        print(f"[ok] {p}")
    print(f"[cover] 共 {len(paths)} 张，请挑选后用 --final 指定并缩放为 900×383")


def finalize(src: pathlib.Path, out: pathlib.Path):
    from PIL import Image

    if not src.exists():
        fail(f"源图不存在：{src}")
    img = Image.open(src).convert("RGB")
    img = img.resize(FINAL_SIZE, Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"[ok] 封面 → {out}（{FINAL_SIZE[0]}×{FINAL_SIZE[1]}）")


def main():
    ap = argparse.ArgumentParser(description="ZenMux gpt-image-2 生成公众号封面")
    ap.add_argument("-f", "--prompt-file", type=pathlib.Path, help="提示词文件（--- 前为元数据）")
    ap.add_argument("--prompt", help="直接给提示词")
    ap.add_argument("--out-dir", type=pathlib.Path, default=pathlib.Path("assets/covers"))
    ap.add_argument("--slug", default="001", help="封面前缀，如 001 → 001-cover-1.png")
    ap.add_argument("-n", type=int, default=4, help="生成张数（默认 4）")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    ap.add_argument("--final", type=pathlib.Path, help="把指定生成图缩放为 900×383 封面")
    ap.add_argument("-o", "--out", type=pathlib.Path, help="--final 时的输出路径")
    args = ap.parse_args()

    if args.final:
        if not args.out:
            fail("--final 需要 -o 输出路径")
        finalize(args.final, args.out)
        return

    prompt = args.prompt
    if args.prompt_file:
        prompt = load_prompt(args.prompt_file)
    if not prompt:
        fail("需要 --prompt 或 -f 提示词文件")
    generate(prompt, args.out_dir, args.slug, args.n, args.quality)


if __name__ == "__main__":
    main()
