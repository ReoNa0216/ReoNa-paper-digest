"""Dependency discovery in a checkout, explicit overrides and flat installations."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline as p


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = p.workspace_temp(Path.cwd(), ".paper-weaver-bundle-test-")
        self.base = self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)

    def write(self, root, relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic discovery fixture only.\n", encoding="utf-8")

    def checkout(self):
        repo = self.base / "arbitrary-fork-name"
        for relative in ("SKILL.md", "scripts/ingest.py", "scripts/render.py"):
            self.write(repo, relative)
        skill = repo / "skills/paper-weaver-zh"
        self.write(skill, "SKILL.md")
        for name in p.DEPENDENCIES.values():
            if name != "ReoNa-paper-digest":
                self.write(repo, f"skills/{name}/SKILL.md")
        return repo, skill

    def test_checkout_is_self_contained_without_installed_skills(self):
        repo, skill = self.checkout()
        with patch.object(p, "SKILL", skill), patch.dict("os.environ", {"CODEX_HOME": str(self.base / "absent-home")}):
            self.assertEqual(p.bundle_root(), repo)
            for key, name in p.DEPENDENCIES.items():
                expected = repo if key == "reona" else repo / "skills" / name
                self.assertEqual(p.dependency(key, p.roots()), expected)

    def test_explicit_roots_override_the_bundle(self):
        repo, skill = self.checkout()
        override = self.base / "overrides"
        self.write(override, "ReoNa-paper-digest/SKILL.md")
        self.write(override, "humanizer-zh/SKILL.md")
        with patch.object(p, "SKILL", skill):
            search = p.roots([override])
            self.assertEqual(p.dependency("reona", search), override / "ReoNa-paper-digest")
            self.assertEqual(p.dependency("humanizer", search), override / "humanizer-zh")
            self.assertEqual(p.dependency("writing", search), repo / "skills/article-writing")

    def test_flat_installation_remains_compatible(self):
        config = self.base / "isolated-config"
        skill = config / "skills/paper-weaver-zh"
        self.write(skill, "SKILL.md")
        for name in p.DEPENDENCIES.values():
            self.write(config, f"skills/{name}/SKILL.md")
        with patch.object(p, "SKILL", skill), patch.dict("os.environ", {"CODEX_HOME": str(config)}):
            self.assertIsNone(p.bundle_root())
            for key, name in p.DEPENDENCIES.items():
                self.assertEqual(p.dependency(key, p.roots()), config / "skills" / name)

    def test_unrelated_parent_is_not_a_reona_checkout(self):
        skill = self.base / "unrelated/skills/paper-weaver-zh"
        self.write(skill, "SKILL.md")
        self.write(skill.parent.parent, "SKILL.md")
        with patch.object(p, "SKILL", skill), patch.dict("os.environ", {"CODEX_HOME": str(self.base / "absent-home")}):
            self.assertIsNone(p.bundle_root())
            with self.assertRaises(FileNotFoundError):
                p.dependency("reona", p.roots())

    def test_repeated_roots_preserve_first_occurrence(self):
        _, skill = self.checkout()
        with patch.object(p, "SKILL", skill):
            result = p.roots([skill.parent, skill.parent])
            self.assertEqual(result[0], skill.parent)
            self.assertEqual(result.count(skill.parent), 1)


if __name__ == "__main__":
    unittest.main()
