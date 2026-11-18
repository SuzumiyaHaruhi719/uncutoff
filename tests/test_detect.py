import json
from pathlib import Path
import tempfile
import unittest

from uncutoff.cli import _fallback_parse_pyproject, detect_manifest_context, parse_version_tuple


class TestDetectManifests(unittest.TestCase):
    def test_parse_version_tuple_respects_lower_bound(self) -> None:
        self.assertEqual(parse_version_tuple("^4.0.0"), (4, 0, 0))
        self.assertEqual(parse_version_tuple("~15.1.2"), (15, 1, 2))
        self.assertEqual(parse_version_tuple(">=1.10,<3.0"), (1, 10, 0))
        self.assertEqual(parse_version_tuple(">=2.0,<3.0"), (2, 0, 0))
        self.assertIsNone(parse_version_tuple("workspace:*"))
        self.assertIsNone(parse_version_tuple("latest"))

    def test_pyproject_and_uv_lock_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="x"\nrequires-python=">=3.12"\ndependencies=["pydantic>=1.10,<3", "fastapi>=0.115"]\n',
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                '[[package]]\nname = "pydantic"\nversion = "2.9.2"\n\n[[package]]\nname = "sqlalchemy"\nversion = "2.0.35"\n',
                encoding="utf-8",
            )
            sub = root / "src" / "pkg"
            sub.mkdir(parents=True)
            target = sub / "app.py"
            target.write_text("", encoding="utf-8")

            ctx = detect_manifest_context(target)
            self.assertEqual(ctx.root, root.resolve())
            self.assertEqual(ctx.versions["python"], (3, 12, 0))
            self.assertEqual(ctx.versions["pydantic"], (2, 9, 2))
            self.assertEqual(ctx.versions["sqlalchemy"], (2, 0, 35))
            self.assertIn("python-modern", ctx.active_packs)
            self.assertIn("pydantic-v2", ctx.active_packs)
            self.assertIn("fastapi-sqlalchemy", ctx.active_packs)

    def test_package_json_and_pnpm_lock_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {"next": "^15.1.0", "react": "^19.0.0", "zod": "^4.0.0"},
                        "devDependencies": {"@tailwindcss/vite": "^4.0.0", "eslint": "^9.12.0"},
                    }
                ),
                encoding="utf-8",
            )
            ctx = detect_manifest_context(root)
            for pack in ("tailwind-v4", "nextjs-15", "react-19", "zod-v4", "eslint-v9"):
                self.assertIn(pack, ctx.active_packs)

    def test_legacy_pins_do_not_activate_modern_packs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="old"\nrequires-python=">=3.9"\ndependencies=["pydantic==1.10.18", "sqlalchemy==1.4.52"]\n',
                encoding="utf-8",
            )
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {"next": "^14.2.0", "react": "^18.3.0", "svelte": "^4.2.0", "zod": "^3.23.0"},
                        "devDependencies": {"tailwindcss": "^3.4.0", "eslint": "^8.57.0"},
                    }
                ),
                encoding="utf-8",
            )
            ctx = detect_manifest_context(root)
            self.assertEqual(ctx.active_packs, ["ai-sdks"])

    def test_lockfiles_requirements_and_py310_toml_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "requirements.txt").write_text("pydantic[email]==2.10.1\n", encoding="utf-8")
            (root / "package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "node_modules/tailwindcss": {"version": "4.0.3"},
                            "node_modules/@tailwindcss/vite": {"version": "4.0.3"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "pnpm-lock.yaml").write_text(
                "packages:\n  next@15.2.0:\n    resolution: {}\n", encoding="utf-8"
            )
            ctx = detect_manifest_context(root)
            self.assertEqual(ctx.versions["pydantic"], (2, 10, 1))
            self.assertEqual(ctx.versions["tailwindcss"], (4, 0, 3))
            self.assertEqual(ctx.versions["next"], (15, 2, 0))
            self.assertIn("tailwind-v4", ctx.active_packs)
            self.assertIn("nextjs-15", ctx.active_packs)

        parsed = _fallback_parse_pyproject(
            '[project]\nname="x"\nrequires-python=">=3.11"\nlicense = {text = "MIT"}\ndependencies=["zod>=4"]\n'
        )
        self.assertEqual(parsed["project"]["requires-python"], ">=3.11")
        self.assertIsInstance(parsed["project"]["license"], dict)
        self.assertEqual(parsed["project"]["dependencies"], ["zod>=4"])


if __name__ == "__main__":
    unittest.main()
