import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

p = Path("ReoNa-paper-digest/tests/output/render").resolve()
frag = (p / "article.html").read_text(encoding="utf-8")

checks = {
    "无 <style> 标签残留": "<style>" not in frag,
    "无 var( 残留": "var(" not in frag,
    "无 color-mix 残留": "color-mix" not in frag,
    "无 calc( 残留": "calc(" not in frag,
    "base64 图片内嵌": "data:image/png;base64" in frag,
    "片段以占位 <p> 开头": frag.startswith('<p style="font-size: 0;'),
    "样式已内联 (style= > 80)": frag.count("style=") > 80,
    "警告块存在": all(f"markdown-alert-{t}" in frag for t in ("important", "tip", "warning")),
    "mark 高亮存在": "<mark" in frag,
    "表格存在": "<table" in frag and "<th" in frag,
    "无 @@TOKEN@@ 残留": "@@" not in frag,
    "无 <marker> 残留（箭头已展开）": "<marker" not in frag,
    "无 marker-end 残留": "marker-end" not in frag,
    "无 data-processed 残留": "data-processed" not in frag,
}
for k, v in checks.items():
    print(("PASS" if v else "FAIL"), k)

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page()
    page.goto((p / "preview.html").as_uri(), wait_until="domcontentloaded")
    page.wait_for_function("window.__INNER__", timeout=60000)
    dom = {
        "行内公式已渲染": page.evaluate(
            "!!document.querySelector('.katex-inline svg') || !!document.querySelector('.katex-inline mjx-container')"
        ),
        "行间公式已渲染": page.evaluate("document.querySelectorAll('.katex-block svg').length") > 0,
        "mermaid 已渲染为 svg": page.evaluate(
            "document.querySelectorAll('pre.mermaid svg').length + document.querySelectorAll('div.mermaid svg').length"
        ) > 0,
        "mermaid 节点保留 sub 标签": page.evaluate(
            "document.body.innerHTML.indexOf('X<sub>p</sub>') !== -1"
        ),
        "警告块标题 >= 3": page.evaluate("document.querySelectorAll('.markdown-alert-title').length") >= 3,
        "嵌套列表已修正": page.evaluate(
            "document.querySelectorAll('#output li > ul, #output li > ol').length"
        ) == 0,
    }
    for k, v in dom.items():
        print(("PASS" if v else "FAIL"), "DOM:", k)
    if not dom["mermaid 节点保留 sub 标签"]:
        html = page.evaluate("document.querySelector('svg').outerHTML.slice(0, 1500)")
        print("--- mermaid svg 头部 ---")
        print(html)
    b.close()

failed = [k for k, v in list(checks.items()) + list(dom.items()) if not v]
if failed:
    print(f"[gate] {len(failed)} 项失败：{failed}")
    sys.exit(1)
print(f"[gate] 全部 {len(checks) + len(dom)} 项通过")
