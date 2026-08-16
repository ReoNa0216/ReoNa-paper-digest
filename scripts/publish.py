#!/usr/bin/env python3
"""publish.py — 把渲染好的文章自动保存为公众号草稿（群发仍由人工点击）。

流程：
  1. 若 dist/article.html 缺失或过期，自动先跑 render.py
  2. 用你的 Chrome + 独立持久化 profile（登录态跨运行保留）启动浏览器窗口
  3. 未登录时显示登录页，你在窗口里扫码（一次登录，长期有效）
  4. 打开新建图文 → 填入标题/作者/摘要 → 剪贴板粘贴富文本 → 保存草稿
     （封面不自动上传：微信编辑器封面对话框结构不稳定，2026-08 起固定为
       人工在编辑器封面区手动设置，脚本只打印封面文件路径与操作指引）
  5. 回报草稿链接，meta.yaml 写入 status/draft_url

用法：
  python publish.py articles/xxx                # 保存草稿（默认行为）
  python publish.py articles/xxx --check-login  # 只检查登录态，登录后即退出
  python publish.py articles/xxx --no-wait      # 未登录时直接报错退出（不等待扫码）
  python publish.py articles/xxx --dump         # 保存草稿页 DOM 摘要（选择器失效时排障用）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from wechat_cover import resolve_cover

SKILL_ROOT = Path(__file__).resolve().parent.parent
RENDER_PY = SKILL_ROOT / "scripts" / "render.py"
PROFILE_DIR = Path.home() / ".wepost" / "chrome"
MP_HOME = "https://mp.weixin.qq.com/"
EDIT_SAVE_TIMEOUT = 30_000
LOGIN_TIMEOUT = 300

# 微信编辑器选择器（集中于此：H3 第 2 步登录后 DOM 核验只改这一处）
SEL_TITLE = "#title"
SEL_AUTHOR = "#author"
SEL_DIGEST = "#js_description"
SEL_EDITOR = "#ueditor_0"
SEL_COVER_AREA = "#js_cover_area"
SEL_SAVE = 'button:has-text("保存为草稿")'  # 当前编辑器无 #js_save，改版后为无 id 按钮（H3 第 2 步 DOM 核验确认）

# H3 第 2 步只读核验输出位置（工作区 .artifacts/h3-inspect，gitignore 排除）
INSPECT_DIR = Path(__file__).resolve().parent.parent.parent / ".artifacts" / "h3-inspect"

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def find_chrome() -> str | None:
    """优先用用户安装的 Chrome（真实浏览器指纹），找不到则退回 Playwright 自带 Chromium。"""
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if not base:
            continue
        cand = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if cand.exists():
            return str(cand)
    return None


def ensure_rendered(article_dir: Path) -> Path:
    dist = article_dir / "dist"
    md = article_dir / "article.md"
    frag = dist / "article.html"
    stale = not frag.exists() or (md.exists() and md.stat().st_mtime > frag.stat().st_mtime)
    # 本地图片变更也会使产物过期（H4 ① 实测：只比较 md 会漏掉换图）
    if not stale and frag.exists() and md.exists():
        md_text = md.read_text(encoding="utf-8")
        for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", md_text):
            src = m.group(1)
            if src.startswith(("http://", "https://", "data:")):
                continue
            img = (article_dir / src).resolve()
            if img.exists() and img.stat().st_mtime > frag.stat().st_mtime:
                stale = True
                break
    if stale:
        print("[render] dist/article.html 缺失或已过期，先渲染…")
        subprocess.run(
            [sys.executable, str(RENDER_PY), str(md), "--out-dir", str(dist)],
            check=True,
        )
    return frag


def load_meta(article_dir: Path) -> dict:
    meta_path = article_dir / "meta.yaml"
    if not meta_path.exists():
        return {}
    return yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}


def save_meta(article_dir: Path, meta: dict, **updates):
    meta.update(updates)
    (article_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def extract_token(page) -> str | None:
    m = re.search(r"token=(\d+)", page.url)
    if m:
        return m.group(1)
    try:
        return page.evaluate(
            "() => { try { return (window.wx && window.wx.cgiData && window.wx.cgiData.token) "
            "|| window.token || null } catch(e) { return null } }"
        )
    except Exception:
        return None


def draft_edit_url(appmsgid: str | None, token: str | None = None) -> str:
    """构造草稿编辑链接。

    安全约定（2026-08-16）：meta.yaml 只存**不含 token** 的链接（发布到 GitHub 时
    不会泄露登录会话凭证）；token 由每次运行时从登录态实时提取后拼接。
    """
    if not appmsgid:
        return ""
    base = (
        "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit"
        f"&action=edit&type=10&appmsgid={appmsgid}&isMul=1&lang=zh_CN"
    )
    return base + (f"&token={token}" if token else "")


def load_draft_url(meta: dict) -> str:
    """读 meta.yaml 的草稿链接（无 token 版）；有 appmsgid 时返回编辑链接，否则原样。"""
    url = str(meta.get("draft_url") or "")
    if url:
        return url
    return draft_edit_url(meta.get("appmsgid") or None)


def wait_login(page, timeout: int = LOGIN_TIMEOUT):
    print("[login] 请在浏览器窗口内扫码登录公众号（若已登录会自动跳过）…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        token = extract_token(page)
        if token:
            print(f"[login] ✅ 已登录")
            return token
        time.sleep(2)
    fail(f"登录超时（{timeout}s），未检测到登录态")


def goto_mp_home(page) -> str | None:
    page.goto(MP_HOME, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)
    return extract_token(page)


def new_article_url(token: str) -> str:
    return (
        "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit"
        f"&action=edit&type=10&isMul=1&isNew=1&lang=zh_CN&token={token}"
    )


def paste_fragment(page, fragment: str):
    """把内联样式 HTML 写入剪贴板并在编辑器正文区 Ctrl+V（走编辑器原生粘贴处理器）。

    2026-08-15 H3 第 3 步实证：当前编辑器 #ueditor_0 是 div.mock-iframe（contenteditable），
    不再是 iframe；按 tagName 兼容两种结构。
    """
    page.evaluate(
        """async (html) => {
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([html], { type: 'text/html' }),
                'text/plain': new Blob([''], { type: 'text/plain' })
            })]);
        }""",
        fragment,
    )
    editor = page.locator(SEL_EDITOR)
    if editor.count() == 0:
        fail("未找到正文编辑器元素")
    tag = editor.first.evaluate("el => el.tagName")
    if tag == "IFRAME":
        body = page.frame_locator(SEL_EDITOR).locator("body")
    else:
        body = page.locator("#ueditor_0 .ProseMirror")
        if body.count() == 0:
            body = editor.first
    # 聚焦内容区并把光标移到文档末尾再粘贴（避免点击中心选中图片后被后续粘贴替换）
    try:
        body.focus()
        body.press("Control+End")
    except Exception:
        body.click()
    body.press("Control+V")
    print("[editor] 富文本已粘贴")


def dump_page_summary(info: dict) -> str:
    """页面摘要序列化为有效 JSON（替代旧版 Python repr 输出）。"""
    return json.dumps(info, ensure_ascii=False, indent=2)


def dump_page(page, out_dir: Path, name: str):
    shot = out_dir / f"{name}.png"
    page.screenshot(path=str(shot), full_page=True)
    info = page.evaluate(
        """() => ({
            url: location.href,
            title: document.title,
            inputs: Array.from(document.querySelectorAll('input, textarea')).map(e =>
                (e.id || e.className || e.name) + ':' + (e.placeholder || '')).slice(0, 40),
            buttons: Array.from(document.querySelectorAll('button, a.btn')).map(e =>
                (e.id || e.className) + ':' + (e.textContent || '').trim().slice(0, 20)).slice(0, 40)
        })"""
    )
    dump = out_dir / f"{name}.json"
    dump.write_text(dump_page_summary(info), encoding="utf-8")
    print(f"[dump] 页面摘要 → {dump} / 截图 → {shot}")


def fill_via_js(page, selector: str, value: str, tag: str = "textarea") -> str:
    """对隐藏/特殊状态字段用原生 value setter 赋值（绕过 Playwright 可见性要求）。

    2026-08-15 H3 第 3 步实证：当前微信编辑器的 #title 是 visibility:hidden/height:0
    的绝对定位承载元素（视觉标题由编辑器自行渲染），Playwright fill 会超时；
    原生 setter + input/change 事件可正常写入并读回。
    """
    return page.evaluate(
        """([sel, val, tag]) => {
            const el = document.querySelector(sel);
            if (!el) return '__missing__';
            const proto = tag === 'textarea'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return el.value;
        }""",
        [selector, value, tag],
    )


def save_draft(page, article_dir: Path):
    meta = load_meta(article_dir)
    title = str(meta.get("title") or "").strip()
    digest = str(meta.get("summary") or "").strip()
    author = str(meta.get("author") or "").strip()

    if not title:
        fail("meta.yaml 缺少 title，请先补齐（写作阶段应已填写）")

    print(f"[editor] 标题：{title}")
    got = fill_via_js(page, SEL_TITLE, title, "textarea")
    if got != title:
        print(f"[warn] 标题赋值读回不一致：{got!r} != {title!r}（可能未生效，草稿需人工核对）")
    if author:
        page.fill(SEL_AUTHOR, author)
        print(f"[editor] 作者：{author}")
    if digest:
        page.fill(SEL_DIGEST, digest)
        print(f"[editor] 摘要：{digest[:40]}…" if len(digest) > 40 else f"[editor] 摘要：{digest}")

    fragment = (article_dir / "dist" / "article.html").read_text(encoding="utf-8")
    # 去掉首尾占位 <p>（分段粘贴时不再需要）
    fragment = fragment.replace('<p style="font-size: 0; line-height: 0; margin: 0;">&nbsp;</p>', "")
    parts = split_fragment_images(fragment)
    n_img = sum(1 for kind, _ in parts if kind == "image")
    if n_img:
        print(f"[editor] 片段含 {n_img} 张内嵌图：按「文字段 → 上传插图」顺序逐段处理（微信保存时自动转素材）…")
    for kind, content in parts:
        if kind == "image":
            upload_image_to_editor(page, content, article_dir / "dist" / ".imgwork")
        else:
            paste_fragment(page, content)
            page.wait_for_timeout(1200)

    cover_path = resolve_cover(article_dir, meta)
    if cover_path:
        print(f"[cover] 封面文件：{cover_path}")
        print("[cover] 封面不自动上传（微信编辑器封面对话框自动化不可靠，已固定为手动）：")
        print("[cover]   草稿保存后 → 编辑器左侧封面区点「拖拽或选择封面」→ 本地上传 → 选择上面的文件 → 确定 → 再点保存")

    print("[editor] 点击保存…")
    page.click(SEL_SAVE)
    save_confirmed = False
    try:
        page.get_by_text(re.compile("保存成功|已保存")).first.wait_for(timeout=EDIT_SAVE_TIMEOUT)
        print("[editor] ✅ 已检测到保存成功提示")
        save_confirmed = True
    except Exception:
        print("[warn] 未检测到「保存成功」提示（可能按钮位置变化），已截图备查")
        dump_page(page, article_dir / "dist", "save-state")
    time.sleep(2)

    appmsgid = None
    m = re.search(r"appmsgid=(\d+)", page.url)
    if m:
        appmsgid = m.group(1)
    if appmsgid:
        save_confirmed = True

    if not save_confirmed:
        fail("未能确认草稿保存成功，未写入 status=draft（避免假成功记录）；"
             "请查看 dist/save-state.png 与 save-state.json 后排障")

    token = extract_token(page)
    # 安全约定：meta.yaml 存不含 token 的链接（发布安全），token 运行时实时拼接
    draft_url = draft_edit_url(appmsgid, None)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    save_meta(
        article_dir, meta, status="draft", appmsgid=appmsgid,
        draft_url=draft_url, last_edited=now,
    )
    print(f"[done] 草稿链接：{draft_edit_url(appmsgid, token) or '（未取到，请到草稿箱查看）'}")
    print("[done] 请到公众号后台「草稿箱」人工终审，确认无误后点「发表」")


def probe_image_dialog(page, out_dir: Path):
    """H4 ①：只读探针——打开编辑器「图片」对话框，dump 上传入口与素材列表结构。

    不执行上传、不插入图片、不保存草稿；探针结束按 Escape 关闭对话框。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    toolbar = page.evaluate(
        """() => Array.from(document.querySelectorAll('a, span, button, div')).filter(el =>
            el.textContent.trim() === '图片' && el.offsetParent !== null && el.children.length <= 1)
            .map(el => el.tagName + '|' + (el.className || '') + '|' + (el.id || '')).slice(0, 10)"""
    )
    print(f"[probe] 工具栏「图片」候选：{toolbar}")
    clicked = page.evaluate(
        """() => {
            const el = Array.from(document.querySelectorAll('a, span, button, div')).find(el =>
                el.textContent.trim() === '图片' && el.offsetParent !== null && el.children.length <= 1);
            if (!el) return false;
            el.click(); return true;
        }"""
    )
    print(f"[probe] 点击「图片」：{clicked}")
    page.wait_for_timeout(4000)
    dialog = page.evaluate(
        """() => ({
            fileInputs: Array.from(document.querySelectorAll('input[type=file]')).map(e =>
                (e.id || e.className || e.name) + '|accept=' + (e.accept || '')).slice(0, 10),
            visibleDialogs: Array.from(document.querySelectorAll('[class*="dialog"], [class*="media"], [class*="upload"]'))
                .filter(el => el.offsetParent !== null)
                .map(el => (el.className || '').slice(0, 100) + '|' + (el.textContent || '').trim().slice(0, 80)).slice(0, 12),
            mediaImgs: Array.from(document.querySelectorAll('img')).filter(e => e.offsetParent !== null && /mmbiz/.test(e.getAttribute('src') || '')).map(e => e.getAttribute('src')).slice(0, 6),
            buttons: Array.from(document.querySelectorAll('button, a.btn')).map(e =>
                (e.id || e.className) + '|' + (e.textContent || '').trim().slice(0, 20)).filter(s => s.trim() !== '|').slice(0, 40)
        })"""
    )
    page.screenshot(path=str(out_dir / "image-dialog.png"), full_page=True)
    dump = out_dir / "image-dialog.json"
    dump.write_text(
        json.dumps({"toolbar": toolbar, "clicked": clicked, "dialog": dialog}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[probe] 图片对话框结构 → {dump}")
    print(f"[probe] 截图 → {out_dir / 'image-dialog.png'}")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def test_image_upload(page, image_path: Path, out_dir: Path):
    """H4 ①：实验上传——打开图片对话框上传单张测试图，观察插入结果（不保存草稿）。

    注意：会上传一张测试图到账号素材库（可后续删除）；正文/对话框状态仅读取。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    page.evaluate(
        """() => {
            const el = Array.from(document.querySelectorAll('a, span, button, div')).find(el =>
                el.textContent.trim() === '图片' && el.offsetParent !== null && el.children.length <= 1);
            if (el) el.click();
        }"""
    )
    page.wait_for_timeout(3000)
    file_input = page.locator('input[type=file]').first
    n = file_input.count()
    print(f"[upload-test] 文件输入框 count={n}")
    if not n:
        page.screenshot(path=str(out_dir / "image-upload-test.png"), full_page=True)
        print("[upload-test] 未找到文件输入框，已截图")
        return
    file_input.set_input_files(str(image_path))
    page.wait_for_timeout(10_000)
    info = page.evaluate(
        """() => {
            const editor = document.querySelector('#ueditor_0');
            const imgs = editor ? Array.from(editor.querySelectorAll('img')) : [];
            return {
                editorImgCount: imgs.length,
                imgs: imgs.map(i => (i.outerHTML || '').slice(0, 500)),
                figures: editor ? editor.querySelectorAll('figure').length : 0,
                editorHead: editor ? editor.innerHTML.slice(0, 400) : '',
                dialogVisible: !!Array.from(document.querySelectorAll('[class*="media_dialog"], [class*="media-dialog"]'))
                    .find(el => el.offsetParent !== null)
            };
        }"""
    )
    page.screenshot(path=str(out_dir / "image-upload-test.png"), full_page=True)
    dump = out_dir / "image-upload-test.json"
    dump.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[upload-test] 结果：{json.dumps(info, ensure_ascii=False)}")
    print(f"[upload-test] 证据：{out_dir / 'image-upload-test.json'} / {out_dir / 'image-upload-test.png'}")


def probe_paste_image(page, image_path: Path, out_dir: Path):
    """H4 ①：探针——把含 base64 图的片段粘贴进编辑器，观察是否生成 js_insertlocalimg（保存时自动上传素材）。"""
    import base64 as _b64

    out_dir.mkdir(parents=True, exist_ok=True)
    data_uri = "data:image/png;base64," + _b64.b64encode(image_path.read_bytes()).decode()
    frag = f'<p>测试图片粘贴：</p><p><img src="{data_uri}"></p>'
    paste_fragment(page, frag)
    page.wait_for_timeout(5000)
    info = page.evaluate(
        """() => {
            const editor = document.querySelector('#ueditor_0');
            const imgs = editor ? Array.from(editor.querySelectorAll('img')) : [];
            return {
                count: imgs.length,
                imgs: imgs.map(i => (i.outerHTML || '').slice(0, 400)),
                hasInsertlocal: imgs.some(i => (i.className || '').includes('js_insertlocalimg'))
            };
        }"""
    )
    page.screenshot(path=str(out_dir / "paste-image-test.png"), full_page=True)
    dump = out_dir / "paste-image-test.json"
    dump.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 粘贴图片结果：{json.dumps(info, ensure_ascii=False)}")
    print(f"[probe] 证据：{dump}")


def split_fragment_images(fragment: str) -> list:
    """把内联样式片段按 <img src="data:..."> 切分为 [(kind, content)]。

    kind: "html"（文字段，直接粘贴）| "image"（data URI，走对话框上传插入）。
    实测（H4 ①）：粘贴的 base64 图不带 js_insertlocalimg，保存时被微信丢弃；
    只有经「图片」对话框上传的图带 js_insertlocalimg，保存时自动转素材。
    """
    parts: list = []
    pos = 0
    for m in re.finditer(r'<img[^>]*src="(data:image/[^"]+)"[^>]*>', fragment):
        if m.start() > pos:
            parts.append(("html", fragment[pos:m.start()]))
        parts.append(("image", m.group(1)))
        pos = m.end()
    if pos < len(fragment):
        parts.append(("html", fragment[pos:]))

    def clean_html(s: str) -> str:
        # img 切分会在文字段首尾留下半截标签（如尾部 <p style="margin: 0;"> 开标签、
        # 开头 </p> 闭标签），粘贴时微信会解析成空段落 → 图片前多空行（用户实测反馈）。
        # 剥掉首尾孤立的块级开/闭标签；再丢弃剥离后无文本的碎片。
        s = re.sub(r"<(p|div|section|table|blockquote|pre)[^>]*>\s*$", "", s)
        s = re.sub(r"^\s*</(p|div|section|table|blockquote|pre)>", "", s)
        return s

    cleaned = []
    for kind, content in parts:
        if kind != "html":
            cleaned.append((kind, content))
            continue
        content = clean_html(content)
        if re.sub(r"<[^>]+>", "", content).strip():
            cleaned.append((kind, content))
    return cleaned


def upload_image_to_editor(page, data_uri: str, work_dir: Path):
    """把 data URI 图片经「图片」对话框上传，并在素材列表中点选插入编辑器。

    与人工流程一致：对话框上传 → 素材列表出现真实 URL 缩略图 → 点选 → 插入正文。
    """
    import base64 as _b64

    m = re.match(r"data:(image/\w+);base64,(.+)", data_uri)
    if not m:
        print("[warn] 无法识别的内嵌图，跳过")
        return
    ext = ".png" if m.group(1) == "image/png" else ".jpg"
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp = work_dir / ("img-" + _b64.b64encode(data_uri[-24:].encode("utf-8")).decode("ascii")[:12] + ext)
    tmp.write_bytes(_b64.b64decode(m.group(2)))
    page.evaluate(
        """() => {
            const el = Array.from(document.querySelectorAll('a, span, button, div')).find(el =>
                el.textContent.trim() === '图片' && el.offsetParent !== null && el.children.length <= 1);
            if (el) el.click();
        }"""
    )
    page.wait_for_timeout(2000)
    fi = page.locator("input[type=file]").first
    if fi.count() == 0:
        print("[warn] 未找到图片上传输入框，跳过该图")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return
    before = page.evaluate("document.querySelectorAll('#ueditor_0 img.js_insertlocalimg').length")
    fi.set_input_files(str(tmp))
    # 等待自动插入完成（实测：上传后微信自动插入编辑器并附真实素材 URL）
    deadline = time.time() + 30
    while time.time() < deadline:
        if page.evaluate("document.querySelectorAll('#ueditor_0 img.js_insertlocalimg').length") > before:
            print("[editor] ✅ 图片已自动插入编辑器（真实素材 URL）")
            break
        time.sleep(2)
    else:
        print("[warn] 未检测到图片插入，可能上传失败（后续可在草稿中人工补图）")
        page.screenshot(path=str(work_dir / "img-upload-fail.png"), full_page=True)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def probe_draft(page, article_dir: Path, out_dir: Path):
    """H4 ①：探针——打开 meta.yaml draft_url 指向的已存草稿，dump 正文图片状态（只读不保存）。

    draft_url 存的是无 token 链接（发布安全），打开前先到公众号首页取当前登录 token 拼接。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = load_meta(article_dir)
    url = str(meta.get("draft_url") or "")
    if not url:
        fail("meta.yaml 无 draft_url")
    token = goto_mp_home(page)  # 先确认登录态并取 token
    if token:
        url = draft_edit_url(str(meta.get("appmsgid") or ""), token) or url
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    info = page.evaluate(
        """() => {
            const editor = document.querySelector('#ueditor_0');
            const imgs = editor ? Array.from(editor.querySelectorAll('img')) : [];
            return {
                url: location.href.slice(0, 200),
                editorImgCount: imgs.length,
                imgs: imgs.map(i => ({
                    cls: i.className || '',
                    src: (i.getAttribute('src') || '').slice(0, 140),
                    dataSrc: (i.getAttribute('data-src') || '').slice(0, 140)
                })),
                bodyText: editor ? (editor.innerText || '').slice(0, 150) : ''
            };
        }"""
    )
    page.screenshot(path=str(out_dir / "draft-probe.png"), full_page=True)
    dump = out_dir / "draft-probe.json"
    dump.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 草稿图片状态：{json.dumps(info, ensure_ascii=False)}")
    print(f"[probe] 证据：{dump}")


def close_dialogs(page):
    """连续按 Escape 关闭可能遮挡的对话框（最多 3 次）。"""
    for _ in range(3):
        vis = page.evaluate(
            """() => Array.from(document.querySelectorAll('[class*="dialog"]'))
                .some(el => el.offsetParent !== null)"""
        )
        if not vis:
            return
        try:
            page.keyboard.press("Escape")
        except Exception:
            return
        page.wait_for_timeout(500)


def minimal_image_save(page, image_path: Path, out_dir: Path):
    """H4 ① 最小复现：填标题 + 仅上传一张图（无文字粘贴）→ 保存 → dump 草稿图片状态。"""
    import base64 as _b64

    out_dir.mkdir(parents=True, exist_ok=True)
    got = fill_via_js(page, SEL_TITLE, "【可删除测试】最小图片复现", "textarea")
    print(f"[minimal] 标题赋值：{got!r}")
    data_uri = "data:image/png;base64," + _b64.b64encode(image_path.read_bytes()).decode()
    upload_image_to_editor(page, data_uri, out_dir / "imgwork")
    close_dialogs(page)
    print("[minimal] 点击保存…")
    page.click(SEL_SAVE)
    try:
        # 带图文章保存需等待图片处理，放宽到 120s
        page.get_by_text(re.compile("保存成功|已保存")).first.wait_for(timeout=120_000)
        print("[minimal] ✅ 保存成功")
    except Exception:
        print("[minimal] ⚠️ 未检测到保存成功提示")
        dump_page(page, out_dir, "minimal-save-fail")
    deadline = time.time() + 60
    while time.time() < deadline:
        pending = page.evaluate("document.querySelectorAll('#ueditor_0 img.js_insertlocalimg').length")
        if pending == 0:
            print("[minimal] js_insertlocalimg 已清零")
            break
        time.sleep(2)
    page.wait_for_timeout(3000)
    info = page.evaluate(
        """() => {
            const ed = document.querySelector('#ueditor_0');
            const imgs = ed ? Array.from(ed.querySelectorAll('img')).filter(i => !(i.className||'').includes('ProseMirror-separator')) : [];
            return { url: location.href.slice(0, 160),
                     realImgs: imgs.map(i => ({ cls: i.className || '', src: (i.getAttribute('src') || '').slice(0, 120) })),
                     bodyText: ed ? (ed.innerText || '').slice(0, 120) : '' };
        }"""
    )
    page.screenshot(path=str(out_dir / "minimal-image.png"), full_page=True)
    dump = out_dir / "minimal-image.json"
    dump.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[minimal] 保存后编辑器图片状态：{json.dumps(info, ensure_ascii=False)}")
    # 重新打开草稿（全新加载）确认图片是否真的在草稿内容中
    m = re.search(r"appmsgid=(\d+)", page.url)
    if m:
        token = extract_token(page)
        draft_url = draft_edit_url(m.group(1), token)
        page.goto(draft_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        fresh = page.evaluate(
            """() => {
                const ed = document.querySelector('#ueditor_0');
                const imgs = ed ? Array.from(ed.querySelectorAll('img')).filter(i => !(i.className||'').includes('ProseMirror-separator')) : [];
                return { realImgs: imgs.map(i => ({ cls: i.className || '', src: (i.getAttribute('src') || '').slice(0, 120) })),
                         bodyText: ed ? (ed.innerText || '').slice(0, 80) : '' };
            }"""
        )
        page.screenshot(path=str(out_dir / "minimal-image-reopen.png"), full_page=True)
        dump2 = out_dir / "minimal-image-reopen.json"
        dump2.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[minimal] 重新打开草稿后的图片状态：{json.dumps(fresh, ensure_ascii=False)}")
        print(f"[minimal] 重新打开证据：{dump2}")
    print(f"[minimal] 证据：{dump}")


def debug_image_flow(page, article_dir: Path, out_dir: Path):
    """H4 ① 调试：复现 save_draft 粘贴/上传顺序，逐步 dump 编辑器图片状态，定位图片消失步骤。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    fragment = (article_dir / "dist" / "article.html").read_text(encoding="utf-8")
    fragment = fragment.replace('<p style="font-size: 0; line-height: 0; margin: 0;">&nbsp;</p>', "")
    parts = split_fragment_images(fragment)

    def snap(label):
        st = page.evaluate(
            """() => {
                const ed = document.querySelector('#ueditor_0');
                const imgs = ed ? Array.from(ed.querySelectorAll('img')).filter(i => !(i.className||'').includes('ProseMirror-separator')) : [];
                return { imgs: imgs.map(i => ({ cls: i.className || '', src: (i.getAttribute('src') || '').slice(0, 80) })),
                         textLen: ed ? (ed.innerText || '').length : 0 };
            }"""
        )
        print(f"[debug] {label}: {json.dumps(st, ensure_ascii=False)}")
        return st

    for idx, (kind, content) in enumerate(parts):
        if kind == "image":
            upload_image_to_editor(page, content, out_dir / "imgwork")
        else:
            paste_fragment(page, content)
            page.wait_for_timeout(1500)
        snap(f"step{idx}-{kind}")
    print("[debug] 点击保存…")
    page.click(SEL_SAVE)
    try:
        page.get_by_text(re.compile("保存成功|已保存")).first.wait_for(timeout=60_000)
        print("[debug] ✅ 保存成功")
    except Exception:
        print("[debug] ⚠️ 未检测到保存成功")
    snap("after-save")


def run_check_login(page, no_wait: bool):
    token = goto_mp_home(page)
    if token:
        print("[check] ✅ 登录态有效")
        return 0
    print("[check] ⚠️ 未登录（登录页已显示）")
    if no_wait:
        print("[check] --no-wait：请手动运行 python publish.py <文章> --check-login 完成扫码")
        return 1
    wait_login(page)
    return 0


def inspect_editor(page, out_dir: Path):
    """H3 第 2 步：只读核验编辑页 DOM —— 不填写、不保存、不创建草稿。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / "editor-inspect.png"), full_page=True)
    info = page.evaluate(
        """() => ({
            url: location.href,
            title: document.title,
            bodyText: (document.body && document.body.innerText || '').slice(0, 400),
            dialogs: Array.from(document.querySelectorAll('[class*="dialog"], [class*="Dialog"]')).filter(el => el.offsetParent !== null).map(el =>
                (el.className || '') + '|' + (el.textContent || '').trim().slice(0, 80)).slice(0, 10),
            visibleInputs: Array.from(document.querySelectorAll('input, textarea')).filter(e => e.offsetParent !== null).map(e =>
                (e.id || e.className || e.name) + '|' + (e.placeholder || '')).slice(0, 30),
            inputs: Array.from(document.querySelectorAll('input, textarea')).map(e =>
                (e.id || e.className || e.name) + '|' + (e.placeholder || '')).slice(0, 60),
            buttons: Array.from(document.querySelectorAll('button, a.btn')).map(e =>
                (e.id || e.className) + '|' + (e.textContent || '').trim().slice(0, 20)).slice(0, 60),
            iframes: Array.from(document.querySelectorAll('iframe')).map(e =>
                (e.id || e.className || '') + '|' + (e.getAttribute('src') || '')).slice(0, 20)
        })"""
    )
    selectors = {
        "标题 #title": SEL_TITLE,
        "作者 #author": SEL_AUTHOR,
        "摘要 #js_description": SEL_DIGEST,
        "正文编辑器 #ueditor_0": SEL_EDITOR,
        "封面区 #js_cover_area": SEL_COVER_AREA,
        "保存 button:has-text": SEL_SAVE,
    }
    title_probe = page.evaluate(
        """() => {
            const el = document.querySelector('#title');
            if (!el) return { found: false };
            const cs = getComputedStyle(el);
            const style = { display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
                            width: cs.width, height: cs.height, position: cs.position };
            let setValueAfter = null;
            try {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(el, 'T');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                setValueAfter = el.value;
                setter.call(el, '');
                el.dispatchEvent(new Event('input', { bubbles: true }));
            } catch (e) { return { found: true, style, setterError: String(e) }; }
            const r = el.getBoundingClientRect();
            return { found: true, style, setValueAfter,
                     rect: { x: r.x, y: r.y, width: r.width, height: r.height } };
        }"""
    )
    rows = []
    for name, sel in selectors.items():
        try:
            loc = page.locator(sel)
            n = loc.count()
            vis = None
            if n:
                try:
                    vis = loc.first.is_visible()
                except Exception as exc:
                    vis = f"err:{exc}"
        except Exception as exc:
            n, vis = f"err:{exc}", None
        rows.append({"check": name, "selector": sel, "count": n, "visible": vis})
        mark = "✅" if n and vis is True else ("⚠️" if n else "❌")
        print(f"[inspect] {mark} {name}：{sel} → count={n}, visible={vis}")
    dump = out_dir / "editor-inspect.json"
    dump.write_text(
        json.dumps(
            {
                "url": info["url"],
                "title": info["title"],
                "bodyText": info["bodyText"],
                "dialogs": info["dialogs"],
                "visibleInputs": info["visibleInputs"],
                "selectors": rows,
                "titleProbe": title_probe,
                "inputs": info["inputs"],
                "buttons": info["buttons"],
                "iframes": info["iframes"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[inspect] #title 深度探针：{title_probe}")
    print(f"[inspect] 编辑器 DOM 摘要 → {dump}")
    print(f"[inspect] 截图 → {out_dir / 'editor-inspect.png'}")


def main():
    ap = argparse.ArgumentParser(description="文章 → 公众号草稿箱（群发人工）")
    ap.add_argument("article_dir", help="文章目录（含 article.md / meta.yaml）")
    ap.add_argument("--check-login", action="store_true", help="只检查登录态")
    ap.add_argument("--no-wait", action="store_true", help="未登录直接退出，不等待扫码")
    ap.add_argument("--dump", action="store_true", help="编辑页保存失败时输出 DOM 摘要")
    ap.add_argument("--inspect-editor", action="store_true", help="只读核验编辑页 DOM（不填写不保存）")
    ap.add_argument("--probe-images", action="store_true", help="只读探针：打开图片对话框并 dump 结构（不上传不保存）")
    ap.add_argument("--test-image-upload", action="store_true", help="实验：上传单张测试图到素材库并观察插入（不保存草稿）")
    ap.add_argument("--probe-paste-image", action="store_true", help="探针：粘贴含 base64 图的片段，观察是否生成 js_insertlocalimg（不保存）")
    ap.add_argument("--probe-draft", action="store_true", help="探针：打开 meta.yaml draft_url 的草稿，dump 图片状态（只读）")
    ap.add_argument("--minimal-image-save", action="store_true", help="最小复现：仅上传一张图并保存草稿，dump 图片是否存活")
    ap.add_argument("--debug-image-flow", action="store_true", help="调试：逐步复现混排流程并 dump 图片状态")
    ap.add_argument("--profile-dir", default=str(PROFILE_DIR), help="Chrome 持久化 profile 目录")
    args = ap.parse_args()

    article_dir = Path(args.article_dir).resolve()
    if not (args.minimal_image_save and article_dir.is_file()) and not article_dir.is_dir():
        fail(f"目录不存在：{article_dir}")

    chrome = find_chrome()
    launch_args = ["--disable-blink-features=AutomationControlled"]
    if chrome:
        print(f"[browser] 使用本机 Chrome：{chrome}")
    else:
        print("[browser] 未找到本机 Chrome，使用 Playwright 自带 Chromium")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            args.profile_dir,
            headless=False,
            executable_path=chrome,
            args=launch_args,
            viewport={"width": 1440, "height": 900},
        )
        context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin="https://mp.weixin.qq.com"
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30_000)

        if args.check_login:
            code = run_check_login(page, args.no_wait)
            context.close()
            sys.exit(code)

        if args.inspect_editor:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（只读核验，不填写不保存）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            inspect_editor(page, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.probe_images:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（图片对话框探针，不保存）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            probe_image_dialog(page, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.test_image_upload:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（图片上传实验，不保存）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            test_img = Path(args.article_dir).resolve()
            if test_img.is_file():
                img_path = test_img
            else:
                img_path = SKILL_ROOT / "tests" / "fixtures" / "assets" / "plot.png"
            test_image_upload(page, img_path, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.probe_paste_image:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（粘贴图片探针，不保存）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            img_path = SKILL_ROOT / "tests" / "fixtures" / "assets" / "plot.png"
            probe_paste_image(page, img_path, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.probe_draft:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            probe_draft(page, article_dir, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.minimal_image_save:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（最小图片保存复现）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            img_path = Path(args.article_dir).resolve()
            if not img_path.is_file():
                img_path = SKILL_ROOT / "tests" / "fixtures" / "assets" / "plot.png"
            minimal_image_save(page, img_path, INSPECT_DIR)
            context.close()
            sys.exit(0)

        if args.debug_image_flow:
            token = goto_mp_home(page)
            if not token:
                if args.no_wait:
                    context.close()
                    fail("未登录且 --no-wait：请先运行 --check-login 扫码")
                token = wait_login(page)
            print("[editor] 打开新建图文（混排调试，会保存一张测试草稿）…")
            page.goto(new_article_url(token), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            debug_image_flow(page, article_dir, INSPECT_DIR)
            context.close()
            sys.exit(0)

        ensure_rendered(article_dir)
        token = goto_mp_home(page)
        if not token:
            if args.no_wait:
                context.close()
                fail("未登录且 --no-wait：请先运行 --check-login 扫码")
            token = wait_login(page)

        print(f"[editor] 打开新建图文…")
        page.goto(new_article_url(token), wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        if page.locator(SEL_SAVE).count() == 0:
            dump_page(page, article_dir / "dist", "editor-state")
            fail("未找到编辑页关键元素 #js_save（页面结构可能已改版），已输出 DOM 摘要供排障")

        save_draft(page, article_dir)
        context.close()


if __name__ == "__main__":
    main()
