"""Behavioral invariants using explicitly synthetic, isolated fixtures."""
import json
from pathlib import Path
import sys
import stat
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline as p


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = p.workspace_temp(Path.cwd(), ".paper-weaver-unit-")
        self.base = self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.paper = self.base / "test.pdf"
        self.paper.write_bytes(b"%PDF-1.4\nSynthetic header fixture, not scientific evidence.\n%%EOF")
        self.chat = self.base / "chat.md"
        self.chat.write_text("## Prompt:\n测试参数？\n## Response:\n参数为 2 个测试对象。", encoding="utf-8")
        self.root = self.base / "article"

    def init(self, **kwargs):
        return p.archive_inputs(self.root, [self.paper], [self.chat], **kwargs)

    def write(self, name, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def yaml(self, name, value):
        self.write(name, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def approve_fixture(self):
        self.yaml("analysis/review.yaml", dict(schema_version=1, verdict="approved",
                  reviewer="Unit-test fixture, NOT a scientific review", reviewed_at=p.now(),
                  profiles=["synthetic-test"], checks={k: "checked" for k in p.CHECKS},
                  limitations=["Synthetic fixture; not research evidence"], fingerprints=p.fingerprints(self.root)))

    def complete_fixture(self):
        self.init()
        article = "测试参数为 2 个对象[1]。\n\n## 参考文献\n\n[1] Synthetic test fixture. Not a research article.\n"
        self.write("article.md", article)
        self.write("refs.md", "[1] Synthetic test fixture. Not a research article.\n")
        for name in ("01-draft", "02-polished", "03-reviewed"):
            self.write(f"drafts/{name}.md", article)
        for name in ("discussion-map", "paper-facts", "story-map", "review"):
            self.write(f"analysis/{name}.md", "Explicitly synthetic unit-test artifact.\n")
        self.yaml("meta.yaml", dict(title="单元测试", summary="虚构测试材料，不构成科研结论", tags=["test"], status="planned"))
        self.yaml("analysis/claim-ledger.yaml", dict(schema_version=1, claims=[dict(
            id="C001", kind="fact", text="测试参数为 2 个对象", verification="verified",
            sources=[dict(source_id="P001", locator="Synthetic fixture only", pdf_page=1)],
            disposition="include", article_anchor="测试参数为 2 个对象")]))
        self.approve_fixture()

    def errors(self):
        return "\n".join(p.check(self.root)[0])

    def test_prompt_response_and_line_provenance(self):
        turns = p.parse_markdown("# Export\n**User:** Anonymous\n\n## Prompt:\n问\n\n## Response:\n答")
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertEqual(turns[0]["line_start"], 4)
        self.assertEqual(turns[1]["line_end"], 8)
        self.assertEqual(turns[1]["id"], "D001-T002")

    def test_you_chatgpt(self):
        self.assertEqual(len(p.parse_markdown("**You:**\n问\n**ChatGPT:**\n答")), 2)

    def test_chinese_roles(self):
        self.assertEqual(len(p.parse_markdown("## 用户：\n问\n## 助手：\n答")), 2)

    def test_code_fence_immunity(self):
        text = "## Prompt\n问\n## Response\n例子：\n````markdown\n## Prompt\n```\n## Response\n````\n结束"
        turns = p.parse_markdown(text)
        self.assertEqual(len(turns), 2)
        self.assertIn("## Prompt", turns[-1]["text"])
        self.assertIn("结束", turns[-1]["text"])

    def test_tilde_fence_and_blockquote(self):
        self.assertEqual(len(p.parse_markdown("## You\n问\n## ChatGPT\n> ## Prompt\n~~~\n## Prompt\n~~~\n答")), 2)

    def test_plain_notes_are_not_dialogue(self):
        with self.assertRaisesRegex(ValueError, "No complete"):
            p.parse_markdown("# 一般笔记\n内容没有角色")

    def test_only_one_role_rejected(self):
        with self.assertRaises(ValueError):
            p.parse_markdown("## Prompt\n仅有问题")

    def test_empty_turn_rejected(self):
        with self.assertRaisesRegex(ValueError, "Empty"):
            p.parse_markdown("## Prompt\n## Response\n答")

    def test_archives_original_without_modifying(self):
        before = p.sha(self.chat)
        result = self.init()
        self.assertEqual(result["turn_count"], 2)
        self.assertEqual(p.sha(self.chat), before)
        self.assertTrue((self.root / "materials/raw/D001-chat.md").is_file())
        self.assertFalse((self.root / "article.md").exists())

    def test_readonly_onedrive_source_can_be_archived(self):
        self.paper.chmod(stat.S_IREAD)
        self.addCleanup(self.paper.chmod, stat.S_IREAD | stat.S_IWRITE)
        before = p.sha(self.paper)
        result = self.init()
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(p.sha(self.paper), before)
        self.assertTrue((self.root / "materials/raw/P001-test.pdf").stat().st_mode & stat.S_IWRITE)

    def test_multi_paper_and_supplement_ids(self):
        p.archive_inputs(self.root, [self.paper, self.paper], [self.chat, self.chat], [f"P002={self.paper}"])
        data = json.loads((self.root / "materials/sources.json").read_text(encoding="utf-8"))["sources"]
        self.assertEqual([s["id"] for s in data], ["P001", "P002", "S001", "D001", "D002"])
        self.assertEqual(data[2]["parent_paper"], "P002")

    def test_unknown_supplement_parent_rejected(self):
        with self.assertRaises(ValueError):
            self.init(supplements=[f"P099={self.paper}"])
        self.assertFalse(self.root.exists())

    def test_refuses_existing_nonempty_destination(self):
        self.root.mkdir()
        self.write("user.txt", "keep")
        with self.assertRaisesRegex(ValueError, "Refusing"):
            self.init()
        self.assertEqual((self.root / "user.txt").read_text(), "keep")

    def test_failed_parser_does_not_leave_partial_output(self):
        self.chat.write_text("Plain notes", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.init()
        self.assertFalse(self.root.exists())

    def test_incomplete_init_cannot_pass(self):
        self.init()
        self.assertIn("Missing/empty article.md", self.errors())

    def test_complete_structural_fixture(self):
        self.complete_fixture()
        self.assertEqual(self.errors(), "")

    def test_changed_article_invalidates_review(self):
        self.complete_fixture()
        for name in ("article.md", "drafts/03-reviewed.md"):
            self.write(name, (self.root / name).read_text(encoding="utf-8") + "\n新增句。")
        self.assertIn("Stale/missing review", self.errors())

    def test_changed_ledger_invalidates_review(self):
        self.complete_fixture()
        ledger = p.read_yaml(self.root / "analysis/claim-ledger.yaml")
        ledger["claims"][0]["conditions"] = "Changed interpretation"
        self.yaml("analysis/claim-ledger.yaml", ledger)
        self.assertIn("Stale/missing review", self.errors())

    def test_changed_title_invalidates_review(self):
        self.complete_fixture()
        meta = p.read_yaml(self.root / "meta.yaml")
        meta["title"] = "Changed conclusion"
        self.yaml("meta.yaml", meta)
        self.assertIn("Stale/missing review", self.errors())

    def test_status_only_does_not_invalidate(self):
        self.complete_fixture()
        meta = p.read_yaml(self.root / "meta.yaml")
        meta["status"] = "rendered"
        self.yaml("meta.yaml", meta)
        self.assertEqual(self.errors(), "")

    def test_source_tamper_rejected_even_with_refreshed_review(self):
        self.complete_fixture()
        (self.root / "materials/raw/P001-test.pdf").write_bytes(b"changed")
        self.approve_fixture()
        self.assertIn("Source missing or changed: P001", self.errors())

    def test_unverified_included_fact_rejected(self):
        self.complete_fixture()
        ledger = p.read_yaml(self.root / "analysis/claim-ledger.yaml")
        ledger["claims"][0]["verification"] = "unverified"
        self.yaml("analysis/claim-ledger.yaml", ledger)
        self.approve_fixture()
        self.assertIn("Unverified fact", self.errors())

    def test_chat_cannot_be_sole_source_of_paper_fact(self):
        self.complete_fixture()
        ledger = p.read_yaml(self.root / "analysis/claim-ledger.yaml")
        ledger["claims"][0]["sources"] = [dict(source_id="D001", locator="D001-T002")]
        self.yaml("analysis/claim-ledger.yaml", ledger)
        self.approve_fixture()
        self.assertIn("Paper fact cannot be sourced only to chat", self.errors())

    def test_source_path_escape_rejected(self):
        self.complete_fixture()
        path = self.root / "materials/sources.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sources"][0]["path"] = "../test.pdf"
        p.write_json(path, data)
        self.approve_fixture()
        self.assertIn("escapes article directory", self.errors())

    def test_citation_order_rejected(self):
        self.complete_fixture()
        for name in ("article.md", "drafts/03-reviewed.md"):
            self.write(name, (self.root / name).read_text(encoding="utf-8").replace("对象[1]", "对象[2]"))
        self.approve_fixture()
        self.assertIn("Citations must resolve", self.errors())

    def test_bad_scientific_subscript_rejected(self):
        self.complete_fixture()
        for name in ("article.md", "drafts/03-reviewed.md"):
            self.write(name, (self.root / name).read_text(encoding="utf-8") + "\n10~11~")
        self.approve_fixture()
        self.assertIn("Scientific powers", self.errors())

    def test_no_cover_adapter_has_no_broken_image(self):
        result = p.no_cover_content(dict(title="测试 <title>", series="研发 & QA"), "<p>Body</p>")
        self.assertNotIn("<img", result)
        self.assertIn("&lt;title&gt;", result)
        self.assertIn("研发 &amp; QA", result)

    def test_asset_change_invalidates_review(self):
        self.complete_fixture()
        self.write("images/figure.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        for name in ("article.md", "drafts/03-reviewed.md"):
            self.write(name, "![fixture](images/figure.svg)\n\n" + (self.root / name).read_text(encoding="utf-8"))
        self.approve_fixture()
        self.write("images/figure.svg", '<svg xmlns="http://www.w3.org/2000/svg"><title>Changed</title></svg>')
        self.assertIn("Stale/missing review", self.errors())

    def test_official_current_branch_and_ambiguous_selection(self):
        try:
            p.dependency("reona", p.roots())
        except FileNotFoundError:
            self.skipTest("Official-format integration needs installed ReoNa")
        def node(parent, role, text):
            return dict(parent=parent, message=dict(author=dict(role=role), content=dict(parts=[text])))
        conv = dict(title="one", current_node="active", mapping={
            "q": node(None, "user", "question"), "abandoned": node("q", "assistant", "wrong branch"),
            "active": node("q", "assistant", "active branch")})
        path = self.base / "conversations.json"
        p.write_json(path, [conv])
        turns = p.official_dialogue(path, "D001", self.base / "official", p.roots())
        self.assertEqual([t["text"] for t in turns], ["question", "active branch"])
        p.write_json(path, [conv, dict(conv, title="two")])
        with self.assertRaisesRegex(ValueError, "Expected one conversation"):
            p.official_dialogue(path, "D001", self.base / "ambiguous", p.roots())


if __name__ == "__main__":
    unittest.main()
