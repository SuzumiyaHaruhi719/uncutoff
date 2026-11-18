import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from uncutoff.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestCliAndSkill(unittest.TestCase):
    def test_src_cli_and_standalone_skill_script_are_identical(self) -> None:
        src_cli = (REPO_ROOT / "src" / "uncutoff" / "cli.py").read_bytes()
        skill_cli = (REPO_ROOT / "skills" / "uncutoff" / "scripts" / "uncutoff_cli.py").read_bytes()
        self.assertEqual(src_cli, skill_cli)

    def test_skill_frontmatter_and_plugin_manifests_valid(self) -> None:
        skill_md = (REPO_ROOT / "skills" / "uncutoff" / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", skill_md, re.DOTALL)
        self.assertIsNotNone(m)
        fm_text = m.group(1)
        top_keys = re.findall(r"^([a-zA-Z0-9_\-]+):", fm_text, re.MULTILINE)
        self.assertEqual(top_keys, ["name", "description"])

        for rel in (
            ".claude-plugin/marketplace.json",
            ".claude-plugin/plugin.json",
            ".codex-plugin/plugin.json",
            ".cursor-plugin/plugin.json",
            "gemini-extension.json",
        ):
            data = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
            self.assertIn("name", data)

    def test_examples_before_after_and_legacy_pin(self) -> None:
        ex = REPO_ROOT / "examples" / "before-after"
        with redirect_stdout(io.StringIO()):
            # Python service before fails, after passes
            self.assertEqual(main(["scan", str(ex / "python-service" / "before")]), 1)
            self.assertEqual(main(["scan", str(ex / "python-service" / "after")]), 0)
            # Web app before fails, after passes
            self.assertEqual(main(["scan", str(ex / "web-app" / "before")]), 1)
            self.assertEqual(main(["scan", str(ex / "web-app" / "after")]), 0)
            # Legacy pin passes with 0 false positives
            self.assertEqual(main(["scan", str(ex / "legacy-pin")]), 0)

    def test_all_packs_ignore_and_git_diff_modes(self) -> None:
        ex_legacy = REPO_ROOT / "examples" / "before-after" / "legacy-pin"
        with redirect_stdout(io.StringIO()):
            # --all-packs overrides version gates on legacy-pin
            self.assertEqual(main(["scan", "--all-packs", str(ex_legacy)]), 1)
            # --ignore filters out CUT-001 from python-service/before
            buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(
                [
                    "scan",
                    "--format",
                    "json",
                    "--ignore",
                    "CUT-001",
                    str(REPO_ROOT / "examples" / "before-after" / "python-service" / "before"),
                ]
            )
        self.assertEqual(rc, 1)
        items = json.loads(buf.getvalue())
        self.assertFalse(any(x["rule_id"] == "CUT-001" for x in items))

        # Test --diff and --staged in a temporary git repo when git is available
        if shutil.which("git"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                subprocess.run(["git", "init", "-q"], cwd=root, check=True)
                subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
                subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
                (root / "requirements.txt").write_text("google-generativeai>=0.8\n", encoding="utf-8")
                (root / "clean.py").write_text("x = 1\n", encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)

                (root / "bad.py").write_text("import google.generativeai as genai\n", encoding="utf-8")
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["scan", "--diff", str(root)]), 1)
                subprocess.run(["git", "add", "bad.py"], cwd=root, check=True)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["scan", "--staged", str(root)]), 1)

    def test_sarif_and_json_outputs(self) -> None:
        ex_before = REPO_ROOT / "examples" / "before-after" / "python-service" / "before"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["scan", "--format", "sarif", str(ex_before)])
        self.assertEqual(rc, 1)
        sarif = json.loads(buf.getvalue())
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertGreaterEqual(len(sarif["runs"][0]["results"]), 5)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = main(["scan", "--format", "json", "--select", "CUT-001", str(ex_before)])
        self.assertEqual(rc2, 1)
        items = json.loads(buf2.getvalue())
        self.assertTrue(all(x["rule_id"] == "CUT-001" for x in items))

    def test_standalone_skill_script_runs_without_src_on_pythonpath(self) -> None:
        script = REPO_ROOT / "skills" / "uncutoff" / "scripts" / "uncutoff_cli.py"
        with tempfile.TemporaryDirectory() as td:
            res = subprocess.run(
                [sys.executable, str(script), "rules", "--format", "json"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            rules = json.loads(res.stdout)
            self.assertEqual(len(rules), 21)

    def test_self_scan_clean(self) -> None:
        rc = main(["scan", str(REPO_ROOT / "src"), str(REPO_ROOT / "skills")])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
