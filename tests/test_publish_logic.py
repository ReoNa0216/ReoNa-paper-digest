#!/usr/bin/env python3
"""publish.py / publish-check.py 修复项的离线最小测试（H3 第 1 步）。

覆盖 HANDOFF M2 问题清单中可离线验证的修复：
  问题 #3 封面路径统一解析（resolve_cover）
  问题 #1 编辑页 URL token（new_article_url）
  问题 #4 dump_page 输出为有效 JSON（dump_page_summary）

运行：python tests/test_publish_logic.py   （失败返回非零退出码）
"""

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from wechat_cover import legacy_cover_candidates, resolve_cover  # noqa: E402
from publish import (  # noqa: E402
    dump_page_summary,
    new_article_url,
    split_fragment_images,
)

CHECKS = []


def check(name: str, cond: bool):
    CHECKS.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), name)


# ---------- 问题 #3：封面统一解析 ----------
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "article-sample" / "001-检查器测试"
META = {"cover_image": "assets/covers/001-cover.png"}

cover = resolve_cover(FIXTURE, META)
check(
    "resolve_cover: 夹具回归（专栏根相对路径 assets/covers/001-cover.png）",
    cover is not None and cover.exists() and cover.name == "001-cover.png",
)
check("resolve_cover: 不存在的路径 → None", resolve_cover(FIXTURE, {"cover_image": "no-such.png"}) is None)
check("resolve_cover: 空 cover_image → None", resolve_cover(FIXTURE, {}) is None)
if cover is not None:
    check("resolve_cover: 绝对路径", resolve_cover(FIXTURE, {"cover_image": str(cover)}) is not None)
else:
    check("resolve_cover: 绝对路径", False)

legacy = legacy_cover_candidates(FIXTURE)
check("legacy_cover_candidates: 6 个候选", len(legacy) == 6)
check("legacy_cover_candidates: 夹具旧候选命中 001-cover.png", any(c.exists() for c in legacy))

# ---------- 问题 #1：编辑页 URL token ----------
url = new_article_url("12345")
check("new_article_url: 含 token=12345", "token=12345" in url)
check("new_article_url: 不含 token=None", "token=None" not in url)

# ---------- 问题 #4：dump_page 输出有效 JSON ----------
info = {
    "url": "https://mp.weixin.qq.com/",
    "title": "草稿",
    "inputs": ["#title:请在这里输入标题", "#js_description:请输入摘要"],
    "buttons": ["#js_save:保存"],
}
s = dump_page_summary(info)
parsed = json.loads(s)
check("dump_page_summary: 可被 json.loads 解析", parsed["title"] == "草稿")
check("dump_page_summary: 不是 Python repr（无单引号字符串）", "'草稿'" not in s and "'#title" not in s)

# ---------- H4 ①：图片分段（split_fragment_images） ----------
frag_with_img = (
    '<p style="x">前段文字</p>'
    '<p><img src="data:image/png;base64,AAAA" alt=""></p>'
    '<p style="y">后段文字</p>'
)
parts = split_fragment_images(frag_with_img)
check("split_fragment_images: 3 段（文字-图-文字）", len(parts) == 3)
check("split_fragment_images: 段类型正确", [k for k, _ in parts] == ["html", "image", "html"])
check("split_fragment_images: 图片段为 data URI", parts[1][1].startswith("data:image/"))
check("split_fragment_images: 无图片段 → 单段 html", len(split_fragment_images("<p>纯文字</p>")) == 1)
check(
    "split_fragment_images: 保留文字段内容",
    '<p style="x">前段文字</p>' in parts[0][1],
)

# ---------- 汇总 ----------
failed = [name for name, ok in CHECKS if not ok]
print()
if failed:
    print(f"[gate] {len(failed)} 项失败：{failed}")
    sys.exit(1)
print(f"[gate] 全部 {len(CHECKS)} 项通过")
