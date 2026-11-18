import json
from pathlib import Path
import tempfile
import unittest

from uncutoff.cli import install_hook, run_hook


class TestHooks(unittest.TestCase):
    def test_claude_posttooluse_hook_blocks_and_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="x"\nrequires-python=">=3.12"\ndependencies=["pydantic>=2.9"]\n',
                encoding="utf-8",
            )
            bad_file = root / "svc.py"
            bad_file.write_text(
                "from pydantic import BaseModel\nclass M(BaseModel):\n    x: int = 1\nf = M().dict()\n",
                encoding="utf-8",
            )
            payload = json.dumps({"cwd": str(root), "tool_input": {"file_path": str(bad_file)}})
            code, out, err = run_hook("claude", payload)
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            parsed = json.loads(out)
            self.assertEqual(parsed["decision"], "block")
            self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "PostToolUse")
            self.assertIn("CUT-010", parsed["hookSpecificOutput"]["additionalContext"])

            # Clean edit
            bad_file.write_text(
                "from pydantic import BaseModel\nclass M(BaseModel):\n    x: int = 1\nf = M().model_dump()\n",
                encoding="utf-8",
            )
            code2, out2, _ = run_hook("claude", payload)
            self.assertEqual(code2, 0)
            self.assertEqual(json.loads(out2), {})

    def test_gemini_and_antigravity_before_tool_strict_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps({"devDependencies": {"tailwindcss": "^4.0.0"}}),
                encoding="utf-8",
            )
            css_path = root / "app.css"

            gem_bad = json.dumps(
                {
                    "cwd": str(root),
                    "tool_name": "write_file",
                    "tool_input": {"path": str(css_path), "content": "@tailwind utilities;\n"},
                }
            )
            code, out, err = run_hook("gemini", gem_bad)
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            res = json.loads(out)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("CUT-040", res["reason"])

            agy_good = json.dumps(
                {
                    "cwd": str(root),
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(css_path), "Content": '@import "tailwindcss";\n'},
                    },
                }
            )
            code2, out2, _ = run_hook("antigravity", agy_good)
            self.assertEqual(code2, 0)
            self.assertEqual(json.loads(out2), {"decision": "allow"})

    def test_codex_pretooluse_exits_2_on_violation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="x"\nrequires-python=">=3.12"\n', encoding="utf-8"
            )
            payload = json.dumps(
                {
                    "cwd": str(root),
                    "hook_event_name": "PreToolUse",
                    "tool_input": {
                        "file_path": str(root / "t.py"),
                        "content": "from datetime import datetime\nnow = datetime.utcnow()\n",
                    },
                }
            )
            code, out, err = run_hook("codex", payload)
            self.assertEqual(code, 2)
            self.assertIn("CUT-001", err)
            self.assertEqual(out, "")

    def test_install_hook_preserves_existing_config_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            claude_dir = root / ".claude"
            claude_dir.mkdir()
            (claude_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PostToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [{"type": "command", "command": "echo existing"}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            install_hook("claude", root)
            install_hook("claude", root)
            cfg = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
            post = cfg["hooks"]["PostToolUse"]
            self.assertEqual(len(post), 2)
            self.assertEqual(post[0]["matcher"], "Bash")
            self.assertEqual(post[1]["matcher"], "Write|Edit|MultiEdit")

            # Verify antigravity, gemini, codex hook structures
            install_hook("gemini", root)
            gem = json.loads((root / ".gemini" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(gem["hooks"]["BeforeTool"][0]["hooks"][0]["name"], "uncutoff")

            install_hook("codex", root)
            codex = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("PostToolUse", codex["hooks"])

            install_hook("antigravity", root)
            agy = json.loads((root / ".agents" / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("uncutoff", agy)
            self.assertIn("PreToolUse", agy["uncutoff"])

    def test_malformed_and_empty_hook_payloads_fail_open_with_valid_json(self) -> None:
        for agent, expected in (
            ("claude", {}),
            ("codex", {}),
            ("gemini", {"decision": "allow"}),
            ("antigravity", {"decision": "allow"}),
        ):
            for raw in ("", "{not-json", '{"cwd": "."}'):
                code, out, err = run_hook(agent, raw)
                self.assertEqual(code, 0)
                self.assertEqual(err, "")
                self.assertEqual(json.loads(out), expected)


if __name__ == "__main__":
    unittest.main()
