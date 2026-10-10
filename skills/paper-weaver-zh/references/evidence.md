# 材料与证据账本

在整理讨论与核查论文前读取。账本的用途是让重要判断可回到来源，不是给每句话机械贴标签。

## 来源身份

`materials/sources.json` 由 init 写入，包含 `schema_version: 1`、`sources` 数组。每个来源有 `id`、`kind`（paper/supplement/chat）、`path`（相对本篇）、`original_name`、`sha256`；补充材料还要有 `parent_paper`。原始导出可能包含其他对话和个人信息，只保存在本地材料区，不复制进交付页或上传。

`materials/chat/turns.json` 保留每轮的来源 ID、轮次 ID、role、text。Markdown 轮次还保存起止行；官方导出保存当前分支的消息编号。`dialogue.md` 便于阅读，不替代原文。保留有效追问，不把助手推测当作用户立场；“用户询问是否成立”也不表示用户已经相信。

## 分析产物

discussion map 按主题归并，并逐项记录：

- 问题 ID、来源轮次、用户到底想弄清什么；区分明确观点、疑问与要求。
- 助手曾给出的解释、需要回原文核验的说法及尚无证据的推测。
- 去向：正文哪节、合并至哪个问题、延伸讨论或暂不纳入；对未纳入的核心问题说明理由。

paper facts 按论文 ID 记录研究问题、设计、实验/观察单位、关键结果、作者解释、明确局限。PDF 页码使用从 1 开始的文件页序号；需要时同时给印刷页码。图内信息必须查看图和图注，不能仅依赖 OCR 或对话转述。补充材料缺失会影响核心结论时暂停核验该结论。

story map 至少交代中心问题、可支持的判断、各节功能、证据 ID、问题去向及相邻章节的承接。多论文不能把不同人群、剂量、统计分母或实验端点拼成一条虚构的连续证据链。

## claim-ledger.yaml

顶层使用 `schema_version: 1` 和 `claims` 列表。以下是字段示例，不是可直接标记通过的真实证据：

```yaml
schema_version: 1
claims:
  - id: C001
    kind: fact
    text: "用自己的话记录已核查的关键事实"
    verification: verified
    sources:
      - source_id: P001
        locator: "Results，Fig. 2b；同时核对图注"
        pdf_page: 5
    conditions: "物种、对象、处理、比较对象、时点和适用范围"
    numbers:
      - value: "原文数字"
        unit: "原文单位"
        denominator: "细胞、动物、受试者或实验次数等；不可混用"
    disposition: include
    article_anchor: "最终正文中能精确找到的对应短语"
```

`kind`：fact / interpretation / hypothesis / user_view。`verification`：verified / qualified / unverified；qualified 表示在明确限制下可引用，不表示已经证明。`disposition`：include / extension / omit。include 与 extension 均需正文锚点。

事实必须有论文/补充材料来源及可定位依据，写入正文的事实不能是 unverified。解释与假设应链接其依据，解释记录推理步骤，假设标明未被当前研究直接检验。用户观点链接讨论轮次，不要求把观点“证明”为事实。未核实事实可留账本并标 omit，不带入正文。

数字条目依实际需要填写；没有数字的判断不编造 numbers。脚本只能检查字段、ID、页码格式与来源类型，无法自动发现所有遗漏的数字，也不能确认图号或分母的内容是否正确。主张覆盖度必须由科学复核确认。

## 参考文献与正文

正文使用 `[1]`、`[2]` 等编号，首次出现顺序递增；不要用内部 C001 替代公开引用。`refs.md` 使用同样编号，含足够识别论文的作者、题名、期刊/年份、DOI 或来源链接。编号引用对应内容应在正文末尾可见的“参考文献”中列出，因为 renderer 不会自动把 refs.md 合入正文。正文条目和 refs.md 保持一致。

数值与范围不可只写“显著改善”“提升数倍”，需要对照对象和适用范围。不能把未报告当作零、未检测到当作不存在、分析未显著当作等效。讨论材料与文章措辞冲突时回原论文核对，并在 review 中记录取舍。
