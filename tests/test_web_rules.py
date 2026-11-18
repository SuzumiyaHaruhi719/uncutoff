import json
from pathlib import Path
import tempfile
import unittest

from uncutoff.cli import scan_paths


class TestWebRules(unittest.TestCase):
    def test_catches_tailwind_v4_next15_react19_svelte5_zod4_eslint9(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {
                            "next": "^15.1.0",
                            "react": "^19.0.0",
                            "svelte": "^5.2.0",
                            "zod": "^4.0.0",
                        },
                        "devDependencies": {
                            "tailwindcss": "^4.0.0",
                            "eslint": "^9.15.0",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "globals.css").write_text(
                "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n",
                encoding="utf-8",
            )
            (root / "tailwind.config.ts").write_text("export default {};\n", encoding="utf-8")
            (root / ".eslintrc.json").write_text("{}\n", encoding="utf-8")
            (root / "page.tsx").write_text(
                'import { cookies } from "next/headers";\n'
                'import { useFormState } from "react-dom";\n'
                'import { z } from "zod";\n'
                'const S = z.nativeEnum({ A: "a" });\n'
                'export function Page() {\n'
                '  const [s, act] = useFormState(() => 0, 0);\n'
                '  return cookies().get("a");\n'
                '}\n',
                encoding="utf-8",
            )
            (root / "Card.svelte").write_text(
                "<script>\n  export let title;\n  $: upper = title.toUpperCase();\n</script>\n<p>{upper}</p>\n",
                encoding="utf-8",
            )
            findings, _ = scan_paths([root])
            rule_ids = {f.rule_id for f in findings}
            self.assertEqual(
                rule_ids,
                {"CUT-040", "CUT-041", "CUT-050", "CUT-060", "CUT-070", "CUT-080", "CUT-090"},
            )

    def test_clean_modern_web_and_at_config_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {
                            "next": "^15.1.0",
                            "react": "^19.0.0",
                            "svelte": "^5.2.0",
                            "zod": "^4.0.0",
                        },
                        "devDependencies": {"tailwindcss": "^4.0.0", "eslint": "^9.15.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "globals.css").write_text(
                '@import "tailwindcss";\n@config "./tailwind.config.ts";\n/* @tailwind base; */\n',
                encoding="utf-8",
            )
            (root / "tailwind.config.ts").write_text("export default {};\n", encoding="utf-8")
            (root / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
            (root / "page.tsx").write_text(
                'import { cookies } from "next/headers";\n'
                'import { useActionState } from "react";\n'
                'import { z } from "zod";\n'
                'const S = z.enum(["a", "b"]);\n'
                'export async function Page() {\n'
                '  // cookies().get("ignored-comment")\n'
                '  const store = await cookies();\n'
                '  return store.get("a");\n'
                '}\n',
                encoding="utf-8",
            )
            (root / "Card.svelte").write_text(
                "<script>\n  let { title } = $props();\n  let upper = $derived(title.toUpperCase());\n</script>\n<p>{upper}</p>\n",
                encoding="utf-8",
            )
            findings, _ = scan_paths([root])
            self.assertEqual(findings, [])

    def test_zod_error_option_and_generative_ai_js(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"zod": "^4.0.0", "@google/generative-ai": "^0.21.0"}}),
                encoding="utf-8",
            )
            (root / "schema.ts").write_text(
                'import { z } from "zod";\n'
                'import { GoogleGenerativeAI } from "@google/generative-ai";\n'
                'export const S = z.string({ invalid_type_error: "bad" });\n',
                encoding="utf-8",
            )
            findings, _ = scan_paths([root])
            rule_ids = {f.rule_id for f in findings}
            self.assertEqual(rule_ids, {"CUT-030", "CUT-080"})


if __name__ == "__main__":
    unittest.main()
