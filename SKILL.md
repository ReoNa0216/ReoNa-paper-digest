---
name: ReoNa-paper-digest
category: Content Creation
tagline: "AI+科研论文精读与公众号长文写作：从对话/论文到可发布的微信文章"
description: >
  以本地文件夹为单一数据源，把「ChatGPT 讨论对话 + 论文 PDF」加工成微信公众号文章：
  ingest 提取对话 → 按追问链写作 → render 渲染微信兼容富文本 → publish 存草稿（群发人工）。
  内置批判性审稿、可读性规范、PDF 插图、封面生成，保证文章辩证、可读、图文完整。
license: MIT
compatibility: >
  Python 3.12 + Playwright + PyMuPDF + PIL + google-genai + PyYAML + css-inline + pymdown-extensions。
  浏览器渲染资源（MathJax/Mermaid）已 vendored，离线可用。
metadata:
  author: ReoN Chen
  version: "0.6.0"
  tags: paper-reading wechat-writer content-creation ai-research figure-extraction
---

# ReoNa-paper-digest — 论文精读公众号文章生成器

把一篇论文变成一篇**辩证、可读、图文完整**的公众号文章。核心设计：自动化只做「搬运」（对话提取、渲染、存草稿），写作与终审留给人机协作；**群发永远人工**。

## When to Use

- 用户要运营 AI+科研方向的公众号、写论文精读系列
- 用户提到「公众号」「专栏」「系列文章」「论文解读」「科研科普」
- 用户已有 ChatGPT 讨论对话和论文 PDF，需要转成文章

## 专栏结构与文件约定

```
<专栏根>/
├── EDITORIAL_CALENDAR.md      # 选题日历（每次写作必加载）
├── ARTICLES_SUMMARY.md        # 已发文章摘要（避免重复，每次写作必加载）
├── BRAND_VOICE.md             # 品牌调性 + 禁用词（每次写作必加载）
├── README.md                  # 专栏说明与进度
├── assets/covers/             # 封面 900×383 PNG
└── articles/00X-标题/
    ├── article.md             # 正文（唯一正文源，WeMD 方言）——只在写作阶段创建
    ├── meta.yaml              # title/summary/author/cover_image/status 等
    ├── refs.md                # 参考文献（与正文 [n] 闭环）
    ├── materials.md           # 材料入口说明
    ├── materials/             # chat/dialogue.md（ingest 产物）+ 论文 PDF
    └── images/                # 文章插图（pdf-figure.py 产物）
```

约定：

- **脚本单一来源**：全部在 `ReoNa-paper-digest/scripts/`，不复制进专栏。
- **Git 在工作区根**（仓库的上一级目录）：专栏内容入库，原始 PDF 与 dist 构建产物不入库（见 .gitignore）。
- **meta.yaml 状态机**：`planned → rendered → draft → published`；只有 publish.py 确认保存成功才写 `draft`（防假成功）。
- **封面路径统一**：`cover_image` 相对专栏根（如 `assets/covers/001-cover.png`），publish-check 与 publish 共用 `wechat_cover.py` 解析（绝对 → 文章目录 → 专栏根）。

## 五阶段工作流（速览）

| 阶段 | 做什么 | 工具 |
|---|---|---|
| Plan | 建专栏骨架、选题日历、品牌调性 | 模板 |
| Research | 归档对话与 PDF → `materials/`，生成 `refs.md` | `ingest.py`、`pdf-figure.py`（配图源） |
| Write | 按追问链写 `article.md`（见「写作规范」） | — |
| Review | 四层质检 + 发布前检查 | `publish-check.py` |
| Publish | 渲染 → 人工预览 → 存草稿 | `render.py`、`publish.py` |

详细分阶段操作见 `references/workflow.md`。

## 写作规范（核心，逐条执行）

### 1. 叙事主线 = 对话追问链

- 写作前加载 `materials/chat/dialogue.md`；**用户的每个问题就是一个小节钩子**，顺着追问链组织，不要重新发明结构。
- 论文数据（数字、结论）以 PDF 为准，对话用于理解机制与批判点。
- **素材来源不写入正文**：正文不得出现「对话里 ChatGPT 说」「材料中提到」等表述；对话内容一律以作者第一人称（我/我们）消化后呈现，观点归属是"我"，不是"AI 助手"。

### 2. 辩证与批判（硬要求）

- 全文区分「**作者声称了什么**」与「**证据支持了什么**」；每篇至少覆盖：数据处理规则的贡献 vs 仪器灵敏度的贡献、定量是否严格、统计的样本量/伪重复风险、方法通用性（仪器门槛）。
- 夸赞与批评并置，避免「实打实/非常扎实」式堆砌；结语用「贡献 + 边界」平衡收尾。
- 批判来源：论文自认的 limitation、对话的批判分析、领域综述/网络讨论（引用为 [n]）。

### 3. 可读性（公众号排版）

- 短段落为主（最长约 300–400 字），手机一屏 ≤3 段。
- **正文不写大标题（`#` 标题）**：文章标题由 `meta.yaml.title` 提供并在微信文章头显示，正文再放 h1 会与标题重复、且手动删除后残留空行删不掉（2026-08-16 实测）。正文从提示块/首段直接开始。
- **禁止说教句式**：「必须记住/需要强调/务必/请你」等一律不用，改用陈述句。
- **引号一律全角中文**（“…” U+201C/U+201D）：正文与 HTML 属性里的 ASCII 双引号 `"` 都算错误；`<div class="fig-caption">` 等代码/HTML 属性除外（保持 ASCII）。
- 英文术语**首次出现加中文注释**（如 缺失率（dropout）、信噪比（SNR）、质荷比（m/z）、伪时间排序（pseudotime））。
- 数字与中文间留空格（「600 个细胞」「0.1 秒」）。
- 开头用真问题做钩子；结尾留互动提问。

### 4. WeMD 方言与渲染约束（违反会渲染失败）

| 特性 | 语法 | 注意 |
|---|---|---|
| 提示块 | `> [!TIP/NOTE/IMPORTANT/WARNING/CAUTION]` | 5 种；正文适度使用 |
| 高亮 | `==关键词==` | **每篇 ≤5 处** |
| 公式 | `$...$`、`$$...$$` | **必须单行书写**（跨行 `$...$` 不渲染！）；对话中讲解关键数学原理的公式（z-score、相似度、倍数变化等）应单行化后保留进正文，帮助读者理解，不要省略 |
| 上下标 | `H~2~O`、`E=mc^2^` | — |
| Emoji | `:smile:` | — |
| 表格 | Markdown 表格 | 列数 ≤4 |
| 流程图 | ```` ```mermaid ```` | 用 `flowchart TB` 竖向；节点文字简短 |
| 图片 | `![](images/xxx.png)` | 本地相对路径，render 自动 base64 |

### 5. 引用规范

- 编号**按正文首次出现顺序**递增（[1]→[2]→…），refs.md 与文末「## 参考文献」对应。
- 文末参考文献条目**之间留空行**（否则渲染成一段）；格式 `[n] 作者, 标题. 期刊, 年, 卷: 页.`。
- 正文保留 Figure 引用文字（如「（补充图 S6）」「（扩展数据图 2d）」），与插图对应。
- **Figure 引用闭环（硬要求）**：正文引用到的每个图号必须有对应截图——主图整页截取，扩展数据图/补充图可裁取被引用的单个面板；发布前逐一核对「正文引用了哪些图号 ↔ images/ 里有哪些文件」。

### 6. 图片插空（PDF 插图）

- 规则：**正文引用到的 Figure 必须插图**（含扩展数据图/补充图，面板级引用可裁面板）；引用文字保留在正文。
- 截图：`pdf-figure.py <pdf> "<图注关键词>" --out images/fig-xxx.png`（补充图自动定位末页，主文整页图加 `--page N --caption`）。
- **矢量图/图注错页的兜底**：部分期刊（如 Nature 系）主图为矢量绘制且图注页与图表页错位（图注在前一页底部、图在后一页），`--caption` 会截到文字栏——用 PyMuPDF 文本块坐标定位图区后按 `clip` 裁剪，并视觉核验。
- **面板级引用优先截整图**：矢量图的面板边界无法靠文本坐标精确定位，单面板裁剪易混入相邻面板或截断（2026-08-27 实测）；扩展数据图/补充图直接截整页图区（含全部面板、裁掉页眉页脚与 "See next page for caption" 占位行），图注注明所引用面板，如「扩展数据图 1｜高通量扰动谱系（含主成分分析面板 h）」。
- 图注：每图下方一行 `.fig-caption`（居中灰色小字）——论文图用「图 S1｜描述」「扩展数据图 1h｜描述」，**原创图（如 Mermaid）用描述性标题**（如「IMMS-MetCell 技术流程示意图」）。
- 不用英文原图注（已在截图时裁掉）。

### 7. 封面（文章定稿后）

- **顺序：先定稿文章 → 再审计封面提示词（必须忠于文章传达的内容）→ 才调用付费 API 生成。**
- 工具：`cover-gen.py`（ZenMux `qwen/qwen-image-3.0-pro`，Vertex AI 协议，16:9 → 900×383）；密钥走 `secrets_env.py`（环境变量 `ZENMUX_API_KEY` 或工作区根 `.env`）。
- **模型选择（2026-08-17 用户决策）**：统一 qwen-image-3.0-pro，$0.04/张（约 gpt-image-2 的 1/4），画质最佳；gpt-image-2 按 token 计费偏贵弃用。
- **固定生成 1 张**：不再出 4 张候选让挑选；`--out` 直接写最终 900×383 封面到 `assets/covers/NNN-cover.png`，covers 下只保留最终版（无 `-1/-2/...` 候选文件）。
- 提示词要点：科学主题意象 + 3D 渲染 + 明确配色 + 左侧留白给标题 + 无文字。
- **上传到微信草稿是手动步骤**：微信编辑器封面对话框自动化不可靠（2026-08 实测，已固定），`publish.py` 只打印封面文件路径；保存草稿后人工在编辑器封面区「拖拽或选择封面 → 本地上传 → 选择该文件 → 确定 → 保存」。
- 发布前摘要：`summary.py <文章目录>` 自动生成并写入 meta.yaml 的 summary（≤120 字，DeepSeek）。

## 四层文字质检（发布前必过）

- **L1 禁用词**：值得注意的是 / 不难发现 / 由此可见 / 综上所述 / 毋庸置疑 / 深刻揭示 / 具有重要意义 / 深远影响 / 随着……的发展 / 近年来……引起广泛关注 / 相信在未来 / 让我们共同期待 等 AI 腔调词——零容忍。
- **L2 风格**：无超 60 字长句；无「先…再…然后…」流水账；连续段首句式不重复；口吻统一。
- **L3 内容**：每节前两句讲清核心；案例具体（有名有数）；无「读后无所得」段落。
- **L4 真人感**：关键段落大声读一遍，不像日常说话就改。

## 工具链

| 工具 | 作用 | 关键点 |
|---|---|---|
| `new-column.py` | 一键新建合集骨架 | 用户只给名字；产出日历/品牌调性/README/covers |
| `prepare.py` | 一键收料：inbox/子文件夹 → 文章骨架 | 自动识别 PDF/对话、归档、跑 ingest；用户只丢材料 |
| `ingest.py` | 对话 → `dialogue.md`+`source.json` | 官方 zip / Exporter md 双路；按标题筛选 |
| `render.py` | `article.md` → 微信内联样式 HTML | MathJax 自包含 SVG、Mermaid、提示块、图片 base64；20 项离线检查 |
| `publish.py` | 存草稿（群发人工） | 分段粘贴 + 图片对话框上传；保存成功双重确认才写 `draft`；选择器集中在文件顶部 `SEL_*`；draft_url 存无 token 链接（发布安全） |
| `publish-check.py` | 发布前检查 | PyYAML；封面路径与 publish 统一 |
| `pdf-figure.py` | 从论文 PDF 截整图 | 补充图取末页最大图区；主文图按图注裁剪 |
| `cover-gen.py` | ZenMux 生成封面 | qwen-image-3.0-pro，16:9 → 900×383；固定 1 张直接出最终版 |
| `summary.py` | 自动生成摘要 | DeepSeek 生成 ≤120 字；无密钥时规则回退；写入 meta.yaml |
| `fetch-image.py` | 下载外部图片 | 独立小工具，urllib 实现 |
| `wechat_cover.py` | 封面路径统一解析 | 两脚本共用 |
| `secrets_env.py` | API 密钥统一加载 | 环境变量 → `.env` → DSH credentials 兜底；无硬编码路径 |

## 密钥与安全约定

- **API 密钥一律走 `secrets_env.py`**：环境变量 → 工作区根 `.env`（gitignore 排除）→ `$DSH_HOME/.credentials.yaml` 兜底。**禁止在脚本/文档里写死密钥路径**。
- **meta.yaml 的 draft_url 存无 token 链接**（发布到 GitHub 安全）；脚本运行时从登录态实时取 token 拼接。**禁止把带 token 的完整链接写进 meta.yaml**。
- **微信登录会话、登录页截图不入 git**（`.gitignore` 已排除）。

## Pitfalls（已知边界，遇到先查这里）

- **跨行 `$...$` 公式不渲染**：写作必须单行；对话材料里的跨行公式要规范成单行。
- **微信粘贴剥 base64 图**：`publish.py` 按「文字段 → 图片对话框上传」分段处理（自动转素材）；不可直接粘贴。
- **`#title` 隐藏、编辑器已改版**：`publish.py` 用 JS setter 填标题、文本选择器点保存；编辑器结构变了只改 `SEL_*`。
- **Mermaid 标签被正文样式污染**：`.mermaid p` 已加 `!important` 覆盖；新增正文样式时留意不要影响 `foreignObject p`。
- **fig-caption 的 `&gt;`**：`render.py` 的 `IMG_RE` 已吞掉自闭合，新增图片处理不要破坏。
- **图片是矢量图时无内嵌位图**：主文整页图用 `--caption` 按图注定位，而不是依赖图像区域。
- **封面路径不一致**：publish-check 与 publish 必须都走 `wechat_cover.resolve_cover`。
- **大范围改代码前先确认 Git 基线存在**（工作区根 `git init` + 首次提交）。

## 上下文窗口策略

- 每次写作只加载：`EDITORIAL_CALENDAR`、`ARTICLES_SUMMARY`、`BRAND_VOICE`、当前文章 `refs.md`/`materials.md`/`dialogue.md`——**不加载其他文章全文**。
- 一次会话只写一篇文章；跨会话续写必须获用户当前确认。
