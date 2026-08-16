#!/usr/bin/env python3
"""render.py — WeMD 方言 markdown → 微信内联样式 HTML + 本地预览页。

管线（与 doocs/md、WeMD 同源机制，均已验证）：
  1. python-markdown + pymdown-extensions 解析方言：==高亮== / $公式$ / H~2~O 下标 /
     E=mc^2^ 上标 / > [!TIP] 警告块 / 表格 / 任务列表 / :emoji:
  2. 无头 Chromium 内：MathJax tex2svg 把公式渲染为内联 SVG、
     Mermaid 渲染流程图，并执行 doocs/md 同款「微信 SVG 消毒」
     （marker 展开 / currentColor 重映射 / 677px 限宽 / 去 defs+id+class）
  3. css-inline（Rust，Thunderbird 同款）把主题 CSS 全部内联进 style 属性
  4. 产出 dist/article.html（可粘贴片段，本地图片已转 base64 内嵌）与
     dist/preview.html（本地预览 + 一键复制富文本）

用法：
  python render.py article.md [--out-dir dist] [--primary-color "#0F4C81"]
                            [--screenshot] [--open]
"""

import argparse
import base64
import html
import json
import re
import sys
import webbrowser
from pathlib import Path

import css_inline
import emoji
import markdown
from playwright.sync_api import sync_playwright

SKILL_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = SKILL_ROOT / "scripts" / "vendor"
THEME_CSS_PATH = SKILL_ROOT / "scripts" / "theme" / "wechat.css"
DEFAULT_PRIMARY = "#0F4C81"

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "pymdownx.mark",
    "pymdownx.tilde",
    "pymdownx.caret",
    "pymdownx.tasklist",
]

FENCE_RE = re.compile(r"^```(\w*)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
MATHB_RE = re.compile(r"(?<!\\)\$\$(.+?)\$\$", re.S)
MATHI_RE = re.compile(r"(?<!\\)\$([^$\n]+?)\$")
ALERT_RE = re.compile(
    r"(?m)^> \[!(TIP|NOTE|IMPORTANT|WARNING|CAUTION)\][^\n]*\n(?:^> ?.*\n?)*"
)
IMG_RE = re.compile(r'<img([^>]*?)\s+src="([^"]+)"\s*/?>')

ALERT_ICONS = {"TIP": "💡", "NOTE": "📌", "IMPORTANT": "❗", "WARNING": "⚠️", "CAUTION": "🚨"}
MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


def fail(msg: str):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------- 阶段 1：markdown 预处理与转换 ----------

def tokenize(src: str):
    """抽出围栏代码 / 数学公式 / [!TYPE] 警告块，返回 (文本, 各列表)。"""
    fences, maths_b, maths_i, alerts = [], [], [], []

    def sub_fence(m):
        idx = len(fences)
        fences.append((m.group(1).lower(), m.group(2)))
        return f"\n@@FENCE{idx}@@\n"

    src = FENCE_RE.sub(sub_fence, src)

    def sub_mathb(m):
        idx = len(maths_b)
        maths_b.append(m.group(1))
        return f"\n@@MATHB{idx}@@\n"

    src = MATHB_RE.sub(sub_mathb, src)

    def sub_mathi(m):
        idx = len(maths_i)
        maths_i.append(m.group(1))
        return f"@@MATHI{idx}@@"

    src = MATHI_RE.sub(sub_mathi, src)

    def sub_alert(m):
        idx = len(alerts)
        lines = m.group(0).splitlines()[1:]
        body = "\n".join(
            line[2:] if line.startswith("> ") else line[1:].lstrip() for line in lines
        )
        alerts.append((m.group(1).upper(), body))
        return f"\n@@ALERT{idx}@@\n"

    src = ALERT_RE.sub(sub_alert, src)
    return src, fences, maths_b, maths_i, alerts


def build_alert(atype: str, body_md: str, converter) -> str:
    t = atype.lower()
    inner = converter.reset().convert(emoji.emojize(body_md, language="alias"))
    title = (
        f'<p class="markdown-alert-title alert-title-{t}">'
        f'<span>{ALERT_ICONS.get(atype, "📌")}</span><strong>{atype}</strong></p>'
    )
    return f'<section class="markdown-alert-{t}">{title}{inner}</section>'


def convert(src: str, converter) -> str:
    src, fences, maths_b, maths_i, alerts = tokenize(src)
    body = converter.reset().convert(emoji.emojize(src, language="alias"))

    def block_replace(html_text: str, token: str, repl: str) -> str:
        html_text = re.sub(rf"<p>\s*{token}\s*</p>", lambda _m: repl, html_text)
        return html_text.replace(token, repl)

    for idx, (atype, body_md) in enumerate(alerts):
        body = block_replace(body, f"@@ALERT{idx}@@", build_alert(atype, body_md, converter))
    for idx, (lang, code) in enumerate(fences):
        esc = html.escape(code)
        if lang == "mermaid":
            repl = f'<pre class="mermaid">{esc}</pre>'
        else:
            cls = f' class="language-{lang}"' if lang else ""
            repl = f"<pre><code{cls}>{esc}</code></pre>"
        body = block_replace(body, f"@@FENCE{idx}@@", repl)
    for idx, tex in enumerate(maths_b):
        raw = html.escape(tex, quote=True)
        repl = (f'<section class="katex-block" data-math-raw="{raw}">'
                f"{html.escape(tex)}</section>")
        body = block_replace(body, f"@@MATHB{idx}@@", repl)
    for idx, tex in enumerate(maths_i):
        raw = html.escape(tex, quote=True)
        repl = (f'<span class="katex-inline" data-math-raw="{raw}">'
                f"{html.escape(tex)}</span>")
        body = body.replace(f"@@MATHI{idx}@@", repl)
    return body


# ---------- 阶段 2：主题与图片 ----------

def load_theme_css(primary: str) -> str:
    h = primary.lstrip("#")
    if len(h) != 6:
        fail(f"非法颜色值：{primary}（应为 #RRGGBB）")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    css = THEME_CSS_PATH.read_text(encoding="utf-8")
    return css.replace("__PRIMARY__", primary).replace("__PRIMARY_RGB__", f"{r}, {g}, {b}")


def collect_images(body: str, article_dir: Path):
    """把本地图片 src 换成 file:// URI（预览用），记录 data URI（复制片段用）。"""
    mapping = {}

    def sub(m):
        src = html.unescape(m.group(2))
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        path = (article_dir / src).resolve()
        if not path.exists():
            print(f"[warn] 图片不存在：{src}")
            return m.group(0)
        ext = path.suffix.lower()
        mime = MIME_BY_EXT.get(ext, "application/octet-stream")
        data_uri = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        mapping[path.as_uri()] = data_uri
        return f'<img{m.group(1)} src="{path.as_uri()}">'

    return IMG_RE.sub(sub, body), mapping


def embed_images(inner: str, mapping: dict) -> str:
    for file_uri, data_uri in mapping.items():
        inner = inner.replace(file_uri, data_uri)
    return inner


# ---------- 阶段 3：浏览器渲染（模板内嵌 JS，移植自 doocs/md，WTFPL） ----------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>预览 · @TITLE@</title>
<style>@CSS@</style>
<style>
body { margin: 0; background: #eee; }
#copy-bar { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #ddd; padding: 10px 16px; display: flex; gap: 12px; align-items: center; font-family: sans-serif; }
#copy-btn { font-size: 15px; padding: 8px 16px; border: none; border-radius: 6px; background: @PRIMARY@; color: #fff; cursor: pointer; }
#copy-msg { color: #666; font-size: 14px; }
#page { max-width: 720px; margin: 24px auto; background: #fff; padding: 24px 0; border-radius: 8px; }
#output { max-width: 677px; margin: 0 auto; }
</style>
</head>
<body>
<div id="copy-bar">
  <button id="copy-btn">📋 复制微信富文本</button>
  <span id="copy-msg"></span>
</div>
<div id="page"><div id="output"><section class="container">@CONTENT@</section></div></div>
<script>window.MathJax = { svg: { fontCache: 'none' } };</script>
<script src="@MATHJAX@"></script>
<script src="@MERMAID@"></script>
<script>
const WECHAT_MAX_WIDTH_PX = 677;

function isMathSvg(svg) { return !!svg.closest('.katex-inline, .katex-block, mjx-container'); }

function parseCssColor(v) {
  if (!v) return null;
  v = v.trim().toLowerCase();
  if (v === 'none' || v === 'currentcolor' || v === 'transparent' || v.startsWith('url(')) return null;
  if (v === 'black') return [0, 0, 0];
  if (v === 'white') return [255, 255, 255];
  var h = v.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (h) {
    if (h[1].length === 3) return [parseInt(h[1][0] + h[1][0], 16), parseInt(h[1][1] + h[1][1], 16), parseInt(h[1][2] + h[1][2], 16)];
    return [parseInt(h[1].slice(0, 2), 16), parseInt(h[1].slice(2, 4), 16), parseInt(h[1].slice(4, 6), 16)];
  }
  var rgb = v.match(/^rgba?\\(\\s*([\\d.]+)\\s*,\\s*([\\d.]+)\\s*,\\s*([\\d.]+)/);
  if (rgb) return [Math.min(255, parseFloat(rgb[1])), Math.min(255, parseFloat(rgb[2])), Math.min(255, parseFloat(rgb[3]))];
  return null;
}

function relLum(c) {
  var f = function (x) { x = x / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}

function isDarkInk(v) {
  var c = parseCssColor(v);
  if (!c) return false;
  if (Math.max(c[0], c[1], c[2]) - Math.min(c[0], c[1], c[2]) > 24) return false;
  return relLum(c) < 0.35;
}

function remapColor(v) {
  if (!v) return null;
  if (v.trim().toLowerCase() === 'currentcolor' || isDarkInk(v)) return 'currentColor';
  return null;
}

function remapInk(node) {
  ['fill', 'stroke'].forEach(function (a) {
    var r = remapColor(node.getAttribute(a));
    if (r) node.setAttribute(a, r);
  });
  var st = node.getAttribute('style');
  if (!st) return;
  var changed = false;
  var next = st.split(';').map(function (p) { return p.trim(); }).filter(Boolean).map(function (p) {
    var i = p.indexOf(':');
    if (i === -1) return p;
    var k = p.slice(0, i).trim().toLowerCase();
    if (k !== 'fill' && k !== 'stroke') return p;
    var v = p.slice(i + 1).trim();
    var r = remapColor(v);
    if (!r) return p;
    changed = true;
    return k + ': ' + r;
  }).join('; ');
  if (changed) node.setAttribute('style', next + ';');
}

function parseMarkerRef(value) {
  if (!value) return null;
  var m = value.match(/#([^)'"]+)/);
  return m ? m[1] : null;
}

function expandMarkers(svg) {
  var markers = new Map();
  svg.querySelectorAll('marker').forEach(function (el) {
    var id = el.getAttribute('id');
    if (!id) return;
    var paths = Array.from(el.querySelectorAll('*')).filter(function (n) {
      return ['path', 'polygon', 'polyline', 'line'].indexOf(n.localName) !== -1;
    });
    if (!paths.length) return;
    markers.set(id, {
      paths: paths,
      refX: parseFloat(el.getAttribute('refX') || '0'),
      refY: parseFloat(el.getAttribute('refY') || '0'),
      orient: el.getAttribute('orient') || 'auto',
      markerUnits: el.getAttribute('markerUnits') || 'strokeWidth',
      markerWidth: parseFloat(el.getAttribute('markerWidth') || '3'),
      markerHeight: parseFloat(el.getAttribute('markerHeight') || '3')
    });
  });
  function strokeWidth(el) {
    var a = el.getAttribute('stroke-width');
    if (a) return parseFloat(a) || 1.5;
    var m = (el.getAttribute('style') || '').match(/stroke-width:\\s*([\\d.]+)/);
    return m ? parseFloat(m[1]) : 1.5;
  }
  function strokeColor(el) { return el.getAttribute('stroke') || el.getAttribute('fill') || 'currentColor'; }
  function geom(el, atStart) {
    var point = null, angle = null;
    if (el.localName === 'path' && typeof el.getTotalLength === 'function') {
      var len = el.getTotalLength();
      if (len > 0) {
        var eps = Math.min(5, len / 2);
        var raw = atStart ? el.getPointAtLength(0) : el.getPointAtLength(len);
        var nb = atStart ? el.getPointAtLength(Math.min(len, eps)) : el.getPointAtLength(Math.max(0, len - eps));
        point = { x: raw.x, y: raw.y };
        angle = Math.atan2(point.y - nb.y, point.x - nb.x);
        if (atStart) angle += Math.PI;
      }
    } else if (el.localName === 'line') {
      var x1 = el.getAttribute('x1'), y1 = el.getAttribute('y1'), x2 = el.getAttribute('x2'), y2 = el.getAttribute('y2');
      if (x1 != null && y1 != null && x2 != null && y2 != null) {
        var sx = parseFloat(x1), sy = parseFloat(y1), ex = parseFloat(x2), ey = parseFloat(y2);
        point = { x: atStart ? sx : ex, y: atStart ? sy : ey };
        angle = Math.atan2(ey - sy, ex - sx);
        if (atStart) angle += Math.PI;
      }
    }
    return { point: point, angle: angle };
  }
  function applyMarker(svg, el, markerId, atStart) {
    if (!markerId) return;
    var g = geom(el, atStart);
    if (!g.point) return;
    var spec = markers.get(markerId);
    var sw = strokeWidth(el), st = strokeColor(el);
    var size = Math.max(6, sw * 4);
    var polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    var tipX = g.point.x, tipY = g.point.y;
    var angle = spec ? (spec.orient === 'auto-start-reverse' ? g.angle + Math.PI : g.angle) : g.angle;
    var leftX = tipX - size * Math.cos(angle - Math.PI / 6);
    var leftY = tipY - size * Math.sin(angle - Math.PI / 6);
    var rightX = tipX - size * Math.cos(angle + Math.PI / 6);
    var rightY = tipY - size * Math.sin(angle + Math.PI / 6);
    polygon.setAttribute('points', tipX + ',' + tipY + ' ' + leftX + ',' + leftY + ' ' + rightX + ',' + rightY);
    polygon.setAttribute('fill', st);
    polygon.setAttribute('stroke', 'none');
    el.parentElement.insertBefore(polygon, el.nextSibling);
  }
  svg.querySelectorAll('path, line, polyline').forEach(function (el) {
    applyMarker(svg, el, parseMarkerRef(el.getAttribute('marker-end') || el.getAttribute('markerEnd')), false);
    applyMarker(svg, el, parseMarkerRef(el.getAttribute('marker-start') || el.getAttribute('markerStart')), true);
    el.removeAttribute('marker-end'); el.removeAttribute('marker-start');
    el.removeAttribute('markerEnd'); el.removeAttribute('markerStart');
    el.removeAttribute('marker-mid'); el.removeAttribute('markerMid');
  });
  svg.querySelectorAll('marker').forEach(function (el) { el.remove(); });
}

function inlinePresentationAttributes(svg) {
  svg.querySelectorAll('*[class], path, line, polyline, polygon, rect, circle, ellipse, text').forEach(function (node) {
    if (!(node instanceof SVGElement)) return;
    var computed = window.getComputedStyle(node);
    if (computed.fill && computed.fill !== 'none' && !node.hasAttribute('fill')) node.setAttribute('fill', computed.fill);
    if (computed.stroke && computed.stroke !== 'none' && !node.hasAttribute('stroke')) node.setAttribute('stroke', computed.stroke);
    if (computed.strokeWidth && !node.hasAttribute('stroke-width')) node.setAttribute('stroke-width', computed.strokeWidth);
    if (computed.opacity && computed.opacity !== '1' && !node.hasAttribute('opacity')) node.setAttribute('opacity', computed.opacity);
  });
}

function fixSvgDimensions(svg) {
  var rect = svg.getBoundingClientRect();
  var vb = svg.getAttribute('viewBox');
  var vp = vb ? vb.trim().split(/[\\s,]+/).map(Number) : null;
  var attrW = parseFloat(svg.getAttribute('width'));
  var attrH = parseFloat(svg.getAttribute('height'));
  var width = rect.width > 0 ? rect.width : (isFinite(attrW) && attrW > 0 ? attrW : (vp && vp[2] ? vp[2] : WECHAT_MAX_WIDTH_PX));
  var height = rect.height > 0 ? rect.height : (isFinite(attrH) && attrH > 0 ? attrH : (vp && vp[3] ? vp[3] : width * 0.75));
  if (vp && vp[2] > 0 && vp[3] > 0) {
    var aspect = vp[3] / vp[2];
    if (rect.width <= 0 && !attrW) { width = vp[2]; height = vp[3]; }
    else if (Math.abs(height / width - aspect) > 0.01) height = width * aspect;
  }
  if (width > WECHAT_MAX_WIDTH_PX) { height = height * (WECHAT_MAX_WIDTH_PX / width); width = WECHAT_MAX_WIDTH_PX; }
  if (!svg.hasAttribute('xmlns')) svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  svg.setAttribute('width', String(Math.max(1, Math.round(width))));
  svg.setAttribute('height', String(Math.max(1, Math.round(height))));
}

function stripUnsupported(svg) {
  svg.querySelectorAll('[clip-path], [clipPath]').forEach(function (el) {
    el.removeAttribute('clip-path'); el.removeAttribute('clipPath');
  });
  svg.querySelectorAll('style').forEach(function (el) { el.remove(); });
  svg.querySelectorAll('defs').forEach(function (el) { el.remove(); });
  svg.querySelectorAll('*').forEach(function (el) {
    el.removeAttribute('id'); el.removeAttribute('class');
    Array.from(el.attributes).forEach(function (a) {
      if (a.name.indexOf('data-') === 0 || a.name.indexOf('aria-') === 0) el.removeAttribute(a.name);
    });
  });
  svg.removeAttribute('id'); svg.removeAttribute('class');
}

function sanitizeSvgsForWeChat(root) {
  var svgs = Array.from(root.querySelectorAll('svg'));
  if (!svgs.length) return;
  var host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-99999px;top:0;visibility:hidden;pointer-events:none;width:677px;';
  document.body.appendChild(host);
  try {
    svgs.forEach(function (svg) {
      var parent = svg.parentElement, next = svg.nextSibling;
      host.appendChild(svg);
      expandMarkers(svg);
      inlinePresentationAttributes(svg);
      remapInk(svg);
      svg.querySelectorAll('*').forEach(remapInk);
      fixSvgDimensions(svg);
      stripUnsupported(svg);
      if (parent) parent.insertBefore(svg, next);
    });
  } finally { host.remove(); }
}

function prepareMath(root) {
  root.querySelectorAll('.katex-inline, .katex-block').forEach(function (w) { w.style.removeProperty('color'); });
  root.querySelectorAll('.katex-inline svg, .katex-block svg, mjx-container svg').forEach(function (svg) {
    svg.style.removeProperty('color');
    var fill = svg.getAttribute('fill');
    if (!fill || fill === 'currentColor' || isDarkInk(fill)) svg.setAttribute('fill', 'currentColor');
    svg.querySelectorAll('path, rect, use, g').forEach(remapInk);
  });
}

function unwrapMathSvgs(root) {
  root.querySelectorAll('mjx-container').forEach(function (el) {
    var svg = el.querySelector('svg');
    if (svg) el.replaceWith(svg);
    else el.replaceWith(document.createTextNode(el.textContent));
  });
}

function solveImages(root) {
  Array.from(root.getElementsByTagName('img')).forEach(function (img) {
    var w = img.getAttribute('width'), h = img.getAttribute('height');
    if (w) { img.removeAttribute('width'); img.style.width = /^\\d+$/.test(w) ? w + 'px' : w; }
    if (h) { img.removeAttribute('height'); img.style.height = /^\\d+$/.test(h) ? h + 'px' : h; }
  });
}

function fixNestedLists(root) {
  root.querySelectorAll('li > ul, li > ol').forEach(function (l) { l.parentElement.insertAdjacentElement('afterend', l); });
}

function fixMermaidLabels(out) {
  // css_inline 会把主题 p 规则（16px 边距/字号）内联进 Mermaid 节点标签的 <p>，
  // 导致框内出现额外空行与放大文字；这里清零并还原为紧凑标签样式。
  out.querySelectorAll('foreignObject p').forEach(function (p) {
    p.style.margin = '0';
    p.style.textAlign = 'center';
    p.style.lineHeight = '1.2';
    p.style.fontSize = '14px';
    p.style.color = 'inherit';
    p.style.letterSpacing = 'normal';
  });
}

function nodeLabelSections(root) {
  root.querySelectorAll('.nodeLabel').forEach(function (node) {
    var parent = node.parentElement;
    if (!parent) return;
    var xmlns = parent.getAttribute('xmlns');
    var style = parent.getAttribute('style');
    if (!xmlns || !style) return;
    var section = document.createElement('section');
    section.setAttribute('xmlns', xmlns);
    section.setAttribute('style', style);
    section.innerHTML = parent.innerHTML;
    var grand = parent.parentElement;
    if (!grand) return;
    grand.innerHTML = '';
    grand.appendChild(section);
  });
}

async function pipeline() {
  document.querySelectorAll('.katex-inline, .katex-block').forEach(function (el) {
    var tex = el.getAttribute('data-math-raw') || el.textContent;
    try {
      var display = el.classList.contains('katex-block');
      var node = window.MathJax.tex2svg(tex, { display: display, fontCache: 'none' });
      var svg = node.firstElementChild || node;
      svg.removeAttribute('width');
      svg.style.display = 'initial';
      svg.style.maxWidth = '300vw';
      svg.style.flexShrink = '0';
      var g = svg.querySelector('g');
      if (g) {
        g.style.fill = 'currentColor'; g.style.stroke = 'currentColor';
        g.setAttribute('fill', 'currentColor'); g.setAttribute('stroke', 'currentColor');
      }
      el.innerHTML = '';
      el.appendChild(node);
    } catch (e) { console.error('math:', e); }
  });
  try {
    window.mermaid.initialize({
      startOnLoad: false,
      theme: 'neutral',
      securityLevel: 'loose',
      fontFamily: '"Times New Roman", "Songti SC", SimSun, serif',
      themeVariables: { fontFamily: '"Times New Roman", "Songti SC", SimSun, serif' }
    });
    await window.mermaid.run({ querySelector: '.mermaid' });
  } catch (e) { console.error('mermaid:', e); }
  var out = document.getElementById('output');
  out.innerHTML = out.innerHTML
    .replace(/<span class="nodeLabel"([^>]*)><p[^>]*>(.*?)<\\/p><\\/span>/g, '<span class="nodeLabel"$1>$2</span>')
    .replace(/<span class="edgeLabel"([^>]*)><p[^>]*>(.*?)<\\/p><\\/span>/g, '<span class="edgeLabel"$1>$2</span>');
  nodeLabelSections(out);
  sanitizeSvgsForWeChat(out);
  prepareMath(out);
  unwrapMathSvgs(out);
  solveImages(out);
  fixNestedLists(out);
  fixMermaidLabels(out);
  out.querySelectorAll('*').forEach(function (el) {
    Array.from(el.attributes).forEach(function (a) {
      if (a.name.indexOf('data-') === 0 || a.name.indexOf('aria-') === 0 || a.name === 'role') el.removeAttribute(a.name);
    });
  });
  out.innerHTML = out.innerHTML
    .replace(/<tspan([^>]*?) style="[^"]*"/g, '<tspan$1')
    .replace(/<tspan([^>]*)>/g, '<tspan$1 style="fill: currentColor !important; color: currentColor !important; stroke: none !important;">');
  return out.innerHTML;
}

window.__INNER__ = null;
pipeline().then(function (inner) { window.__INNER__ = inner; });

document.getElementById('copy-btn').addEventListener('click', async function () {
  var msg = document.getElementById('copy-msg');
  try {
    var htmlText = JSON.parse(document.getElementById('wechat-fragment').textContent);
    var plainText = document.getElementById('output').innerText;
    await navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([htmlText], { type: 'text/html' }),
      'text/plain': new Blob([plainText], { type: 'text/plain' })
    })]);
    msg.textContent = '✅ 已复制，去公众号编辑器 Ctrl+V 粘贴';
    msg.style.color = '#2e7d32';
  } catch (e) {
    msg.textContent = '❌ 复制失败（请用 Chrome 打开此文件）：' + e;
    msg.style.color = '#c62828';
  }
});
</script>
<script type="text/plain" id="wechat-fragment">@FRAGMENT@</script>
</body>
</html>
"""


# ---------- 阶段 4：后处理与输出 ----------

# 纯图片段落：markdown 会把 ![](x) 包成 <p><img></p>，段落 16px 边距与
# img 自身 30px 边距叠加，微信里图片前后空隙过大（用户实测反馈）。
# 这里把「p 内只有 img」的段落边距清零，间距交给 img 自身样式控制。
IMG_ONLY_P_RE = re.compile(r'<p style="[^"]*">(\s*<img [^>]+>\s*)</p>')

# 图注必须用 <p> 携带内联样式：微信粘贴时 div 会被剥成无样式的裸 <p>
# （class + style 全丢，回退成 mp-quote 字体/17px/justify/黑色），
# 而 <p> 的内联样式完整保留（2026-08-16 草稿 DOM 实测）。
# 渲染时先把源里的 <div class="fig-caption">…</div> 转成 <p>，css_inline
# 内联完整样式后，微信端即可保留居中/灰色/13px 图注样式。
# 注意：css_inline 之后 div 已带 style 属性，替换时需一并保留。
CAPTION_DIV_RE = re.compile(
    r'<div class="fig-caption"([^>]*)>(.*?)</div>', re.S
)


def post_process(inlined: str) -> str:
    spacer = '<p style="font-size: 0; line-height: 0; margin: 0;">&nbsp;</p>'
    inlined = IMG_ONLY_P_RE.sub(r'<p style="margin: 0;">\1</p>', inlined)
    inlined = CAPTION_DIV_RE.sub(r'<p class="fig-caption"\1>\2</p>', inlined)
    return spacer + inlined + spacer


def main():
    ap = argparse.ArgumentParser(description="WeMD 方言 markdown → 微信内联样式 HTML")
    ap.add_argument("input", help="article.md 路径")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认：文章目录下的 dist/）")
    ap.add_argument("--primary-color", default=DEFAULT_PRIMARY, help="主题色（默认 #0F4C81 经典蓝）")
    ap.add_argument("--screenshot", action="store_true", help="生成 dist/preview.png 整页截图")
    ap.add_argument("--open", action="store_true", help="渲染后在默认浏览器打开预览页")
    args = ap.parse_args()

    article = Path(args.input).resolve()
    if not article.exists():
        fail(f"文件不存在：{article}")
    out_dir = (Path(args.out_dir) if args.out_dir else article.parent / "dist").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    theme_css = load_theme_css(args.primary_color)
    converter = markdown.Markdown(extensions=MD_EXTENSIONS, output_format="html")
    body = convert(article.read_text(encoding="utf-8"), converter)
    body, image_map = collect_images(body, article.parent)

    title = article.stem
    html_doc = (
        PAGE_TEMPLATE
        .replace("@TITLE@", html.escape(title))
        .replace("@CSS@", theme_css)
        .replace("@PRIMARY@", args.primary_color)
        .replace("@CONTENT@", body)
        .replace("@MATHJAX@", (VENDOR_DIR / "mathjax" / "tex-svg.js").as_uri())
        .replace("@MERMAID@", (VENDOR_DIR / "mermaid" / "mermaid.min.js").as_uri())
    )

    print(f"[1/4] markdown 转换完成（{len(body)} 字符 HTML）")
    print("[2/4] 无头 Chromium 渲染公式与流程图…")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 720, "height": 1000})
        page.set_default_timeout(60000)
        (out_dir / "_stage.html").write_text(html_doc, encoding="utf-8")
        page.goto((out_dir / "_stage.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_function("window.__INNER__", timeout=60000)
        inner = page.evaluate("window.__INNER__")

        print("[3/4] 内联样式 + 微信后处理…")
        fragment_inner = embed_images(inner, image_map)
        inlined = css_inline.inline_fragment(fragment_inner, css=theme_css)
        fragment = post_process(inlined)
        (out_dir / "article.html").write_text(fragment, encoding="utf-8")

        final_doc = html_doc.replace("@FRAGMENT@", json.dumps(fragment, ensure_ascii=False))
        (out_dir / "preview.html").write_text(final_doc, encoding="utf-8")

        if args.screenshot:
            page.goto((out_dir / "preview.html").as_uri(), wait_until="domcontentloaded")
            page.wait_for_function("window.__INNER__", timeout=60000)
            page.screenshot(path=str(out_dir / "preview.png"), full_page=True)
            print(f"[ok] 截图 → {out_dir / 'preview.png'}")
        browser.close()

    (out_dir / "_stage.html").unlink(missing_ok=True)
    print(f"[ok] 可粘贴片段 → {out_dir / 'article.html'}（{len(fragment)} 字符）")
    print(f"[ok] 预览页   → {out_dir / 'preview.html'}")
    if args.open:
        webbrowser.open((out_dir / "preview.html").as_uri())


if __name__ == "__main__":
    main()
