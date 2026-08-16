#!/usr/bin/env python3
"""ingest.py — ChatGPT 对话 → 结构化 dialogue.md（公众号写作材料）

输入（自动识别）：
  1. ChatGPT 官方数据导出 zip（内含 conversations.json），或解包后的 conversations.json
  2. ChatGPT Exporter 用户脚本导出的单篇 markdown

输出（--out，默认 ./chat-extract）：
  dialogue.md   追问链结构（Q/A 分节）——文章叙事主线的原始材料
  source.json   元数据（标题 / 时间 / 模型 / 消息数 / 图片映射）
  images/       对话中的图片（官方导出且包内含图时）

用法：
  python ingest.py <input> --list
  python ingest.py <input> --title-filter "关键词" --out articles/007-xxx/materials/chat
"""

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROLE_NAMES = {"user": "我", "assistant": "ChatGPT"}
HEADER_SOURCE = {
    "official": "ChatGPT 官方数据导出",
    "exporter": "ChatGPT Exporter 插件导出",
}

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def utc_str(ts) -> str:
    if not ts:
        return "未知"
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError):
        return str(ts)


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------- 官方导出（conversations.json） ----------

def load_conversations(path: Path, zf):
    if zf is not None:
        names = [n for n in zf.namelist() if n.endswith("conversations.json")]
        if not names:
            fail("zip 中未找到 conversations.json（仅含 chat.html 的旧导出不支持）")
        return json.loads(zf.read(names[0]))
    return json.loads(path.read_text(encoding="utf-8"))


def linearize(conv: dict) -> list:
    """沿 current_node 的 parent 链还原线性消息序列（分支对话取当前路径）。"""
    mapping = conv.get("mapping", {})
    node_id = conv.get("current_node")
    nodes, seen = [], set()
    while node_id and node_id not in seen:
        seen.add(node_id)
        node = mapping.get(node_id)
        if node is None:
            break
        nodes.append(node)
        node_id = node.get("parent")
    nodes.reverse()
    return [n for n in nodes if n.get("message")]


def find_zip_image(asset_id: str, zf):
    if zf is None:
        return None
    for name in zf.namelist():
        base = name.rsplit("/", 1)[-1]
        if base.startswith(asset_id) or asset_id in name:
            return name
    return None


def render_part(part, images_dir: Path, zf, used: dict) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    ctype = part.get("content_type")
    if ctype == "image_asset_pointer":
        aid = part.get("asset_pointer", "unknown")
        if aid in used:
            return f"![图片]({used[aid]})"
        entry = find_zip_image(aid, zf)
        if entry:
            ext = Path(entry).suffix or ".png"
            target = images_dir / f"{aid}{ext}"
            with zf.open(entry) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            rel = f"images/{target.name}"
            used[aid] = rel
            return f"![图片]({rel})"
        return f"[图片 {aid} 未在导出包中找到]"
    if ctype in ("text", "multimodal_text"):
        return "".join(render_part(p, images_dir, zf, used) for p in (part.get("parts") or []))
    return ""


def message_text(msg: dict, images_dir: Path, zf, used: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""
    ctype = content.get("content_type", "")
    parts = content.get("parts") or []
    if ctype == "code":
        text = "\n".join(p for p in parts if isinstance(p, str))
        if "```" not in text:
            text = f"```text\n{text}\n```"
        return text
    return "".join(render_part(p, images_dir, zf, used) for p in parts)


def extract_official(conv: dict, images_dir: Path, zf) -> dict:
    messages, used = [], {}
    tool_count = 0
    model_counts = {}
    for node in linearize(conv):
        msg = node.get("message", {})
        role = (msg.get("author") or {}).get("role")
        if role in ("system", "tool"):
            tool_count += 1
            continue
        if role not in ROLE_NAMES:
            continue
        text = message_text(msg, images_dir, zf, used)
        if role == "assistant":
            slug = (msg.get("metadata") or {}).get("model_slug")
            if slug:
                model_counts[slug] = model_counts.get(slug, 0) + 1
        messages.append({"role": role, "text": text})
    model = max(model_counts, key=model_counts.get) if model_counts else ""
    return {
        "source": "official",
        "title": conv.get("title", ""),
        "create_time": utc_str(conv.get("create_time")),
        "model": model,
        "message_count": len(messages),
        "tool_message_count": tool_count,
        "images": dict(used),
        "messages": messages,
    }


# ---------- Exporter 插件导出的 markdown ----------

TURN_RE = re.compile(r"^#{2,6}\s+(You|ChatGPT)\s*:?\s*$", re.IGNORECASE)
TURN_ALT_RE = re.compile(r"^\s*\*{0,2}(You|ChatGPT)\*{0,2}\s*:?\s*$", re.IGNORECASE)
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")


def extract_exporter(md_path: Path, images_dir: Path) -> dict:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    title = ""
    messages = []
    current = None
    used = {}
    body = []

    def flush():
        nonlocal body
        if current is not None and body:
            text = "\n".join(body).strip()
            if text:
                messages.append({"role": current, "text": text})
        body = []

    for line in lines:
        m = TURN_RE.match(line) or TURN_ALT_RE.match(line)
        if m:
            flush()
            current = "user" if m.group(1).lower() == "you" else "assistant"
            continue
        if not title:
            tm = TITLE_RE.match(line)
            if tm:
                title = tm.group(1).strip()
                continue
        body.append(line)
    flush()

    def fix_image(match):
        ref = match.group(1)
        if ref.startswith(("http://", "https://", "images/")):
            return match.group(0)
        src = (md_path.parent / ref).resolve()
        if not src.exists():
            return match.group(0)
        target = images_dir / src.name
        if target.exists():
            target = images_dir / f"{src.stem}-{len(used) + 1}{src.suffix}"
        shutil.copyfile(src, target)
        used[src.name] = f"images/{target.name}"
        return f"![图片](images/{target.name})"

    for msg in messages:
        msg["text"] = IMG_RE.sub(fix_image, msg["text"])

    return {
        "source": "exporter",
        "title": title or md_path.stem,
        "create_time": "",
        "model": "",
        "message_count": len(messages),
        "tool_message_count": 0,
        "images": used,
        "messages": messages,
    }


# ---------- 输出 ----------

def write_dialogue(info: dict, out_dir: Path):
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 对话：{info['title']}",
        "",
        f"> 来源：{HEADER_SOURCE[info['source']]}",
        f"> 时间：{info['create_time'] or '未知'}",
        f"> 模型：{info['model'] or '未知'}",
        f"> 消息数：{info['message_count']} 条"
        + (f"（另含 {info['tool_message_count']} 条系统/工具消息，已省略）" if info["tool_message_count"] else ""),
        "",
        "---",
        "",
    ]
    turn = 0
    for msg in info["messages"]:
        if msg["role"] == "user":
            turn += 1
        lines.append(f"## [{turn}] {ROLE_NAMES[msg['role']]}")
        lines.append("")
        lines.append(msg["text"].strip())
        lines.append("")
    (out_dir / "dialogue.md").write_text("\n".join(lines), encoding="utf-8")
    meta = {k: v for k, v in info.items() if k != "messages"}
    (out_dir / "source.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- CLI ----------

def list_conversations(data):
    print(f"共 {len(data)} 个对话：")
    for i, conv in enumerate(data, 1):
        n = sum(1 for node in linearize(conv)
                if (node.get("message", {}).get("author") or {}).get("role") in ROLE_NAMES)
        print(f"  {i}. {conv.get('title', '(无标题)')}  |  {utc_str(conv.get('create_time'))}  |  {n} 条消息")


def pick_conversation(data, title_filter):
    if title_filter is None:
        if len(data) == 1:
            return data[0]
        fail(f"导出包含 {len(data)} 个对话，请用 --title-filter 指定（--list 查看全部）")
    kw = title_filter.lower()
    hits = [c for c in data if kw in (c.get("title") or "").lower()]
    if not hits:
        fail(f"--title-filter '{title_filter}' 未匹配任何对话（--list 查看全部）")
    if len(hits) > 1:
        fail(f"--title-filter '{title_filter}' 匹配 {len(hits)} 个对话："
             + "；".join(c.get("title", "") for c in hits))
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description="ChatGPT 对话导出 → dialogue.md")
    ap.add_argument("input", help="官方导出 zip / conversations.json / Exporter 导出的 .md")
    ap.add_argument("--out", default="chat-extract", help="输出目录（默认 ./chat-extract）")
    ap.add_argument("--title-filter", help="按对话标题关键词筛选（官方导出多对话时必填）")
    ap.add_argument("--list", action="store_true", help="列出导出包内全部对话标题")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        fail(f"文件不存在：{src}")
    out_dir = Path(args.out)
    suffix = src.suffix.lower()

    zf = None
    if suffix == ".zip":
        zf = zipfile.ZipFile(src)
        data = load_conversations(src, zf)
        if args.list:
            list_conversations(data)
            zf.close()
            return
        conv = pick_conversation(data, args.title_filter)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        info = extract_official(conv, out_dir / "images", zf)
        zf.close()
    elif suffix == ".json":
        data = load_conversations(src, None)
        if args.list:
            list_conversations(data)
            return
        conv = pick_conversation(data, args.title_filter)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        info = extract_official(conv, out_dir / "images", None)
    elif suffix == ".md":
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        info = extract_exporter(src, out_dir / "images")
    else:
        fail(f"不支持的文件类型：{suffix}（支持 .zip / .json / .md）")

    write_dialogue(info, out_dir)
    print(f"[ok] dialogue.md → {out_dir / 'dialogue.md'}"
          f"（{info['message_count']} 条消息，图片 {len(info['images'])} 张）")


if __name__ == "__main__":
    main()
