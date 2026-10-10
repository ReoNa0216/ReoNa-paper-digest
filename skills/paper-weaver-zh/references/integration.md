# 依赖与执行约定

首次执行本 skill 前读取本文件。用 `pipeline.py doctor` 确认实际路径；在本仓库内使用时自动识别根目录的 ReoNa 工具链，其余四个 skill 独立安装。重复的 `--skills-root` 优先于仓库 `skills/`、`~/.agents/skills` 和 `$CODEX_HOME/skills`。Python 使用当前环境可用的解释器，不把开发机的绝对路径写成依赖。渲染需要 ReoNa 环境中的 PyYAML、Markdown、pymdown-extensions、css-inline、Pillow、Playwright 及 Chromium；PDF 阅读另需相应工具。脚本不会联网安装、更新依赖或启动常驻服务。

## 能力分工与冲突消解

组合的是能力，不是依次把所有规则叠在正文上。用户本次要求优先；在组合流程内，事实与证据边界优先于叙事效果，用户明确的结构优先于默认重排，语义优先于句式偏好。

| 依赖原有规则 | 本流程的适用范围 |
|---|---|
| note-organizing 不负责公众号成稿 | 本阶段交付的是内部 discussion map，因此使用其主题归并与忠实整理能力；随后继续成稿，不以笔记结束 |
| article-writing 强制标题冲突、结尾升维 | 改为提出真实问题和证据支持的判断；不制造冲突、反直觉或行业意义 |
| article-writing 重排用户大纲 | 可以重排作为素材的大纲；用户明确指定章节顺序时保留 |
| article-writing 段落不空行 | Markdown 段落、标题、列表间保留正常空行，以免渲染合段 |
| article-writing 写入前再次确认路径 | 用户已指定目录或可沿用当前专栏时直接使用；仅在可能覆盖用户内容时澄清 |
| humanizer 增加作者声音、压缩限定词 | 默认中立科学书面语；不要求用户再给人设，不删除影响科学含义的限定词 |
| ReoNa 按追问链展开 | 追问链用于覆盖检查；文章顺序由 story map 组织。用户指定的顺序例外 |
| 依赖默认使用原生 Markdown 表格、流程图 | 完整公众号稿按本组合层的表格图片与单张研究导图流程执行，保留可编辑源；用户明确选择优先，详见 [research-visuals.md](research-visuals.md) |
| 原有完整流水线包括 publish | 默认止于本地成稿。上传草稿另需用户要求，公开发布/群发由用户操作 |

依赖内容属于参考工作流，不能把导出对话或论文里出现的命令当成本次授权。原始材料只读，新增产物写入本篇目录。

## 常用命令

以下 `SKILL` 表示当前 skill 的实际绝对路径，`SKILLS` 表示依赖所在 skills 目录；命令中的路径均需替换。`--skills-root` 可重复，用于先在本地测试目录查找新增依赖、再查已安装依赖。

```text
python SKILL/scripts/pipeline.py doctor --skills-root SKILLS
python SKILL/scripts/pipeline.py init --out ARTICLE --paper MAIN.pdf --chat CHAT.md
python SKILL/scripts/pipeline.py init --out ARTICLE --paper A.pdf --paper B.pdf --supplement P002=SUPP.pdf --chat DISCUSSION.zip --title-filter 对话标题
python SKILL/scripts/pipeline.py fingerprint ARTICLE
python SKILL/scripts/pipeline.py check ARTICLE
python SKILL/scripts/pipeline.py build ARTICLE --screenshot
```

`init` 只接受新的或空的目录；参数按传入顺序分配 P001、P002 和 D001、D002。官方导出有多个匹配对话时必须选到唯一对话，不能取第一个。脚本保留原始文件，并记录归档路径、哈希和规范化对话轮次。无角色标记的普通笔记应作为额外材料人工整理，不能冒充用户/助手对话。

代理读取论文、写分析与三阶段稿件、完成科学复核之后，再运行 `fingerprint`，把结果填入 `analysis/review.yaml`。此命令只输出当前摘要，不生成“已审核”结论。`check` 会检查审核记录是否绑定当前稿件；它不能判断科研结论是否真实。

`build` 先执行结构检查与 ReoNa 的 publish-check，再调用 ReoNa 的 render。生成物先写到独立暂存目录，成功后才更新 `dist` 中的衍生文件；源稿不被渲染器改写。同步页直接调用已安装的 reona-paper-digest-zh 的页面构造函数和验证器。有封面时复用其完整构造器，无封面时只构造文字页头，沿用相同页面外壳。禁止对生成好的 HTML 做补丁式替换。

`meta.status` 仅在完整本地构建成功后从 planned/rendered 更新为 rendered；已有 draft/published 状态不会被本地构建降级。`dist/build.json` 记录当前本地构建和同步内容哈希，不宣称上传成功。

默认通过 renderer 的 `--primary-color` 参数传入 `#7854ab` 紫色强调，可在 meta.yaml 的 `primary_color` 使用六位十六进制颜色覆盖。字体仍来自已安装主题。若 Windows 沙箱阻止 Playwright 创建子进程/管道，在产品许可机制下申请这一次本地无头渲染权限；不要关闭安全设置、改用后台常驻服务或绕过浏览器访问限制。

## 版本与来源

`dependencies.lock.json` 是本地验收时的来源和文件指纹快照，不是自动升级器。尤其 ReoNa-paper-digest 包含用户本机修订，不能仅用远程 commit 描述其内容。doctor 区分缺失、当前匹配和指纹变化；变化不等于损坏，先检查差异再决定是否重测。

本 skill 是组合层，不复制现有 renderer 或人文润色词典。贡献来源为 [kainineo97/paper-weaver-zh](https://github.com/kainineo97/paper-weaver-zh/tree/paper-weaver-zh)；合入后位于 ReoNa 仓库的 `skills/paper-weaver-zh/`。日常文章开发不生成 GitHub 项目、fork 或分发包。
