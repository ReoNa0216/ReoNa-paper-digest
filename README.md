# ReoNa-paper-digest

**把「论文 + ChatGPT 讨论」一键变成微信公众号文章草稿的完整管线。**

面向科研写作者的本地工具链：你提供三样材料（论文 PDF、补充材料 PDF、与 ChatGPT 的逐段讨论导出），它自动完成 **收料 → 写作 → 渲染 → 质检 → 存草稿** 全流程，最终产出微信编辑器可直接粘贴的内联样式 HTML，并可自动登录公众号后台存入草稿箱（**群发/发表永远人工点击**）。

> ⚠️ **免责声明**：本工具仅供个人学习与研究使用。自动登录公众号后台、自动保存草稿属于平台自动化操作，请遵守微信平台规则并自行承担使用风险。本项目与微信官方无关。

---

## 特性

- **一键收料**：材料丢进 `inbox/`，`prepare.py` 自动识别 PDF/对话、归档、建文章骨架
- **多合集支持**：`new-column.py` 一个命令建新合集（专栏），互不干扰
- **WeMD 方言**：专门为微信优化的 Markdown 方言（提示块 / 高亮 / 单行公式 / Mermaid 流程图 / 表格）
- **微信友好渲染**：MathJax SVG 自包含、Mermaid 防样式污染、图片 base64、图注与标题居中、手机端表格自适应（均为真实微信编辑器 DOM 实测调优）
- **防呆设计**：20 项渲染检查 + 15 项发布逻辑测试；草稿保存成功才写 `status=draft`（不造假状态）
- **发布安全**：meta.yaml 只存不含登录 token 的草稿链接；API 密钥走环境变量 / `.env`（gitignore 排除）

## 安装

```bash
git clone https://github.com/<your>/ReoNa-paper-digest.git
cd ReoNa-paper-digest
pip install -r requirements.txt
python -m playwright install chromium   # 浏览器自动化（存草稿用）
```

> 💡 Windows 中文系统提示：`requirements.txt` 保持纯 ASCII（注释为英文）。若你自行加中文注释，pip 在 GBK 默认编码下会报 `UnicodeDecodeError`。

可选依赖：
- 封面生成（`cover-gen.py`）需要 ZenMux API Key（环境变量 `ZENMUX_API_KEY`）
- 摘要生成（`summary.py`）需要 DeepSeek API Key（`DEEPSEEK_API_KEY`）；无密钥时自动退回规则抽取

## 快速开始

```
你的工作区/
├── ReoNa-paper-digest/        # 本仓库（脚本单一份，不复制进专栏）
├── Metabolomics/                   # 你的第一个合集（专栏）——new-column.py 创建
├── inbox/                     # 收料暂存区（gitignore）
└── .env                       # API 密钥（KEY=VALUE，gitignore）
```

### 1. 新建合集（每个公众号栏目一个）

```bash
python ReoNa-paper-digest/scripts/new-column.py 我的合集 --desc "一句话定位"
```

### 2. 收料（每篇文章一次）

把材料丢进 `inbox/任意子文件夹/`：

```
inbox/第2篇/
├── 对话导出.md        # ChatGPT Exporter 单篇 md，或官方导出 zip
├── 论文.pdf
└── 补充材料.pdf
```

```bash
python ReoNa-paper-digest/scripts/prepare.py inbox/第2篇 --title "文章标题" --series 我的合集
```

自动产出 `我的合集/articles/002-标题/` 骨架 + 归档材料 + `dialogue.md`。

### 3. 写作 → 渲染 → 存草稿

1. 按 `SKILL.md` 写作规范写 `article.md`（WeMD 方言）
2. `python ReoNa-paper-digest/scripts/render.py article.md --screenshot` → 预览
3. 预览确认后 `python ReoNa-paper-digest/scripts/publish.py 文章目录` → 自动填标题/作者/摘要、粘贴正文、上传图片、保存草稿，返回草稿链接

> **封面**：生成（`cover-gen.py`）后，在草稿编辑器手动设置（微信封面对话框自动化不可靠，已固定为手动步骤）。
> **发表**：永远由你在公众号后台人工点击，脚本绝不自动群发。

## 工具一览

| 工具 | 作用 |
|---|---|
| `new-column.py` | 一键新建合集骨架（日历/品牌调性/README） |
| `prepare.py` | 一键收料：inbox → 文章骨架 + 归档 + ingest |
| `ingest.py` | ChatGPT 对话导出 → 结构化 `dialogue.md` |
| `render.py` | `article.md` → 微信内联样式 HTML（20 项检查） |
| `publish.py` | 存草稿：填标题/摘要、分段粘贴、图片上传、保存确认 |
| `publish-check.py` | 发布前检查（元数据/封面/引用等） |
| `pdf-figure.py` | 从论文 PDF 截取插图（含图注裁剪） |
| `cover-gen.py` | ZenMux qwen-image-2.0 生成封面（900×383，固定 1 张） |
| `summary.py` | DeepSeek 生成摘要（≤120 字），无密钥规则回退 |
| `fetch-image.py` | 下载外部图片到本地 |
| `wechat_cover.py` | 封面路径统一解析 |

## 测试

```bash
python -m unittest ReoNa-paper-digest/tests/test_publish_logic.py   # 15 项发布逻辑
python ReoNa-paper-digest/tests/verify_render.py dist/article.html  # 20 项渲染检查
```

## 目录结构

```
ReoNa-paper-digest/
├── SKILL.md                  # 写作规范（WeMD 方言 / 质检 / 微信坑清单）
├── references/workflow.md    # 分阶段操作清单
├── scripts/                  # 全部工具脚本（单一来源）
│   ├── theme/wechat.css      # 微信主题样式
│   └── vendor/               # MathJax / Mermaid（本地化，防 CDN 失效）
├── tests/                    # 离线测试 + fixtures
└── requirements.txt / LICENSE
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)。vendored 的 MathJax（Apache-2.0）与 Mermaid（MIT）版权归其各自作者。
