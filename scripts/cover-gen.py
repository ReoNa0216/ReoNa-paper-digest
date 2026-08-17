#!/usr/bin/env python3
"""cover-gen.py — 生成公众号封面（900×383 PNG）

流程（对齐 SKILL「封面」章节）：
  1. 文章定稿后，先审计封面提示词（须忠于文章传达的内容），再调用本工具；
  2. 经 ZenMux Vertex AI 协议调用 qwen/qwen-image-3.0-pro（2026-08-17 用户决策：
     gpt-image-2 按 token 计费过贵弃用；对比 qwen 2.0/3.0/3.0-pro 后统一用
     3.0-pro，$0.04/张，画质最佳）；
  3. 固定生成 1 张（用户决策：不再出 4 张候选让挑选），直接缩放为 900×383
     写入目标路径（covers 下只保留最终版，不留 -1/-2/... 候选文件）。

密钥读取：环境变量 ZENMUX_API_KEY → 工作区根 .env → $DSH_HOME/.credentials.yaml
兜底（统一走 secrets_env.py，发布安全）。

用法：
  python cover-gen.py -f prompts/20260815-cover.md --out assets/covers/001-cover.png --slug 001
  python cover-gen.py --prompt "..." --out assets/covers/001-cover.png
"""

import argparse
import base64
import pathlib
import sys

from google import genai
from google.genai import types

from secrets_env import require_secret

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ZENMUX_VERTEX_BASE = "https://zenmux.ai/api/vertex-ai"
# 2026-08-17 用户决策：统一用 qwen-image-3.0-pro（$0.04/张，画质最佳）
DEFAULT_MODEL = "qwen/qwen-image-3.0-pro"
# 封面比例 ≈ 900/383 ≈ 2.35:1，取 16:9 横版（qwen 支持 aspect_ratio）
ASPECT_RATIO = "16:9"
FINAL_SIZE = (900, 383)


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def load_prompt(path: pathlib.Path) -> str:
    """提示词文件：第一个独立 `---` 之前是元数据（人类读），之后是发给模型的正文。"""
    text = path.read_text(encoding="utf-8")
    parts = text.split("\n---\n", 1)
    return parts[1].strip() if len(parts) > 1 else text.strip()


def generate(prompt: str, out_path: pathlib.Path, slug: str, model: str = DEFAULT_MODEL):
    """生成 1 张封面并直接缩放为 900×383 写入 out_path。"""
    from PIL import Image

    client = genai.Client(
        api_key=require_secret("ZENMUX_API_KEY", yaml_key="ZENMUX_API_KEY"),
        vertexai=True,
        http_options=types.HttpOptions(api_version="v1", base_url=ZENMUX_VERTEX_BASE),
    )
    print(f"[cover] 调用 {model}（{ASPECT_RATIO}，生成 1 张）…")
    resp = client.models.generate_images(
        model=model,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=ASPECT_RATIO,
            output_mime_type="image/png",
        ),
    )
    if not resp.generated_images:
        fail("生成结果为空（可能被内容审核拦截），请调整提示词后重试")
    raw = _fetch_image_bytes(resp.generated_images[0].image)
    img = Image.open(__import__("io").BytesIO(raw)).convert("RGB")
    img = img.resize(FINAL_SIZE, Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_encode_png(img))
    print(f"[ok] 封面 → {out_path}（{FINAL_SIZE[0]}×{FINAL_SIZE[1]}）")


def _fetch_image_bytes(img) -> bytes:
    """qwen-image 走 Vertex 协议返回 gcs_uri（OSS 临时 URL）；gpt-image 返回 image_bytes。"""
    if getattr(img, "image_bytes", None):
        return img.image_bytes
    uri = getattr(img, "gcs_uri", None)
    if uri:
        import urllib.request
        return urllib.request.urlopen(uri, timeout=60).read()
    fail("响应中既无 image_bytes 也无 gcs_uri，无法取图")


def _encode_png(img) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def finalize(src: pathlib.Path, out: pathlib.Path):
    """兼容旧用法：把已有图缩放为 900×383。"""
    from PIL import Image

    if not src.exists():
        fail(f"源图不存在：{src}")
    img = Image.open(src).convert("RGB")
    img = img.resize(FINAL_SIZE, Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.save(out, "PNG")
    print(f"[ok] 封面 → {out}（{FINAL_SIZE[0]}×{FINAL_SIZE[1]}）")


def main():
    ap = argparse.ArgumentParser(description="ZenMux 生成公众号封面（900×383）")
    ap.add_argument("-f", "--prompt-file", type=pathlib.Path, help="提示词文件（--- 前为元数据）")
    ap.add_argument("--prompt", help="直接给提示词")
    ap.add_argument("-o", "--out", type=pathlib.Path, default=pathlib.Path("assets/covers/cover.png"),
                    help="最终封面输出路径（默认 assets/covers/cover.png）")
    ap.add_argument("--slug", default="001", help="日志用文章序号前缀")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"生成模型（默认 {DEFAULT_MODEL}）")
    ap.add_argument("--final", type=pathlib.Path, help="（兼容）把指定已有图缩放为 900×383，不调用 API")
    ap.add_argument("--final-out", type=pathlib.Path, help="--final 时的输出路径")
    args = ap.parse_args()

    if args.final:
        if not args.final_out:
            fail("--final 需要 --final-out 输出路径")
        finalize(args.final, args.final_out)
        return

    prompt = args.prompt
    if args.prompt_file:
        prompt = load_prompt(args.prompt_file)
    if not prompt:
        fail("需要 --prompt 或 -f 提示词文件")
    generate(prompt, args.out, args.slug, args.model)


if __name__ == "__main__":
    main()
