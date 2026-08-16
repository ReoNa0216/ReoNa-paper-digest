# ReoNa-paper-digest — 分阶段操作清单

> 规范与约束以 `SKILL.md` 为准；本文件是每阶段的具体操作步骤。每个阶段通常是独立会话。

---

## Phase 1 · Plan（建专栏骨架，仅首次/新专栏）

1. 用自然语言向用户收集：专栏名称与定位、目标读者、核心主题范围、更新频率。
2. **一键建合集（推荐）**：`python ReoNa-paper-digest/scripts/new-column.py 合集名 --desc "定位"`——自动建 `合集名/`（EDITORIAL_CALENDAR / BRAND_VOICE / ARTICLES_SUMMARY / README / assets/covers）。
3. 手动建时在工作区根（仓库的上一级）下创建专栏根目录（如 `scOmics/`），写入：
   - `EDITORIAL_CALENDAR.md`（选题日历：每篇序号/标题/摘要/依赖/状态）
   - `BRAND_VOICE.md`（人设、口吻、禁用词清单——直接复用 SKILL 的 L1 禁用词）
   - `ARTICLES_SUMMARY.md`（每篇一行占位）
   - `README.md`（专栏说明 + 文章目录表）
   - `assets/covers/`、`assets/images/`
4. 为每篇文章创建 `articles/00X-标题/`，预置 `meta.yaml`（完整字段模板，`title`/`summary` 留空）、`refs.md`、`materials.md`、`materials/`、`images/`。**`article.md` 只在写作阶段创建**。
5. 确认工作区根 Git 基线存在；没有就先 `git init` + 首次提交。

## Phase 2 · Research（归档材料 + 参考文献）

**收料（一键，推荐）**：用户把材料丢进 `inbox/<子文件夹>/`（对话导出 + 论文 PDF + 补充 PDF），Agent 运行：

```bash
python ReoNa-paper-digest/scripts/prepare.py inbox/子文件夹 --title "文章标题"
```

脚本自动：识别 PDF（文件名含 sup/补充 或更小体积 → 补充材料，歧义时询问）→ 建 `articles/00X-标题/` 骨架（meta.yaml 模板/refs.md/materials.md/materials/chat/images/）→ 归档 PDF → 跑 `ingest.py` 生成 dialogue.md。产出即 Phase 3 写作入口。

1. （如未用 prepare.py）询问用户是否有主动提供的材料（论文 PDF、讨论对话、笔记）。
2. 用户提供的材料归档到 `articles/00X/materials/`：
   - **ChatGPT 对话**：`ingest.py <导出文件> --out materials/chat`（官方 zip 用 `--list` + `--title-filter`；Exporter 单篇 md 直接给路径）。产出 `dialogue.md`（追问链）+ `source.json`。
   - **论文 PDF/补充材料**：直接放 `materials/`。
3. 通读 `dialogue.md` 与 PDF 文本（可用 PyMuPDF 提取文本到 `.artifacts/paper-text/` 暂读）。
4. 生成 `refs.md`：核心论文 + 文中将引用的对比方法/综述/工具；条目与正文 `[n]` 计划对应。
5. （可选）`web_search` 补领域讨论/批判视角，作为 refs 与正文批判来源。

## Phase 3 · Write（按追问链写作）

1. 加载：`EDITORIAL_CALENDAR`、`ARTICLES_SUMMARY`、`BRAND_VOICE`、当前 `refs.md`、`materials.md`、`dialogue.md`。**不加载其他文章全文**。
2. 大纲 = 对话追问链展开（用户问题即小节钩子）。
3. 逐节写 `article.md`，严格遵循 SKILL「写作规范」：
   - 辩证批判、短段落、无说教、术语首次中文注释
   - WeMD 方言（**公式单行**、Mermaid 用 `flowchart TB`、高亮 ≤5、表格 ≤4 列）
   - **正文不写 `#` 大标题**（文章标题在微信文章头显示，正文重复会残留空行删不掉）
   - 引用按首次出现顺序编号；文末「## 参考文献」条目间空行
   - 正文引用 Figure 处保留引用文字，并规划插图（见 Phase 4）
4. 写完更新 `meta.yaml`（title/summary/author）。

## Phase 4 · Review（质检 + 插图）

1. 四层文字质检（L1 禁用词 / L2 风格 / L3 内容 / L4 真人感）。
2. 自动化检查：`publish-check.py --article-dir articles/00X-标题`（PASS 才继续）。
3. **插图**：对正文引用的每个 Figure：
   ```bash
   python ReoNa-paper-digest/scripts/pdf-figure.py materials/IMMS_MetCell_sup.pdf "Supplementary Figure 6." --out images/fig-s6.png
   python ReoNa-paper-digest/scripts/pdf-figure.py materials/IMMS_MetCell.pdf "Fig. 5 |" --page 7 --caption --out images/fig-5.png
   ```
   在 `article.md` 对应位置插入 `![](images/fig-xxx.png)` + `<div class="fig-caption">…</div>`（论文图「图 S1｜描述」，原创图描述性标题）。
4. 重跑 `publish-check.py` 与 `render.py` 验证。

## Phase 5 · Publish（渲染 → 预览 → 草稿）

1. 摘要：`python ReoNa-paper-digest/scripts/summary.py articles/00X-标题`（自动生成并写入 meta.yaml summary，无需手写）。
2. 渲染：`render.py articles/00X-标题/article.md --screenshot` → `dist/preview.html`。
3. 用户打开 preview.html 做视觉终审（公式/流程图/表格/图片/提示块/字体）。
4. 通过后：`publish.py articles/00X-标题`（自动填标题/作者/摘要 → 分段粘贴正文 + 图片上传 → 保存草稿 → 回报链接）。**群发仍由用户在后台人工点击。**
5. **封面（手动）**：草稿保存后，人工在编辑器封面区「拖拽或选择封面 → 本地上传 → 选择 `publish.py` 打印的封面文件 → 确定 → 再保存」；**不做自动上传**（微信编辑器封面对话框自动化不可靠，已固定为手动）。
6. 更新 `EDITORIAL_CALENDAR` / `ARTICLES_SUMMARY` / `README` 状态，Git 提交。
7. **封面生成**：文章定稿后审计提示词 → `cover-gen.py` 生成（选 N → `--final` 缩放 900×383）→ 确认 `meta.yaml.cover_image` 解析正确。

## 已知边界速查

- 跨行 `$...$` 不渲染 → 写作时单行化。
- 微信粘贴必剥 base64 图 → 用 `publish.py`（分段上传），不要手工粘贴含图片段。
- 编辑器改版只改 `publish.py` 顶部 `SEL_*` 常量。
- 封面路径解析统一走 `wechat_cover.py`。
- 封面**上传草稿不做自动化**（编辑器封面对话框不稳定）：`publish.py` 只打印路径，人工在编辑器设置。
- **密钥**：环境变量 / 工作区根 `.env`（gitignore 排除），一律走 `secrets_env.py`；不要写死路径。
- **meta.yaml 的 draft_url 不带 token**（发布安全）；打开草稿时脚本实时取 token 拼接。
