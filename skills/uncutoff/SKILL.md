---
name: uncutoff
description: >-
  Manifest-aware guard against pre-cutoff legacy APIs across Python, Pydantic v2,
  FastAPI, SQLAlchemy 2, AI SDKs, Tailwind CSS v4, Next.js 15, React 19, Svelte 5,
  Zod v4, and ESLint v9. Use when creating, editing, reviewing, or migrating code
  so deprecated patterns are caught against the project's actual dependency versions.
---

# uncutoff

Prevent pre-cutoff API drift in coding sessions by checking edits against the project's declared dependency versions in `pyproject.toml`, `uv.lock`, `requirements*.txt`, `package.json`, and lockfiles.

## Workflow

1. **Detect the project's real dependency versions first** (never guess):
   ```bash
   python3 scripts/uncutoff_cli.py detect .
   ```
   (Or run `uncutoff detect .` if installed on `PATH`.)

2. **Scan edited or staged files before finalizing changes**:
   ```bash
   python3 scripts/uncutoff_cli.py scan --diff
   ```
   To scan the entire workspace or override version gates:
   ```bash
   python3 scripts/uncutoff_cli.py scan .
   python3 scripts/uncutoff_cli.py scan --all-packs path/to/file.py
   ```

3. **Apply the exact modern replacement** reported by `uncutoff`, or inspect the language reference files only when needed:
   - Python 3.10+/3.12+ idioms and packaging: [references/python-modern.md](references/python-modern.md)
   - Pydantic v2, FastAPI, SQLAlchemy 2, and AI SDKs (`google-genai`, OpenAI v1+, current model IDs): [references/python-backend-ai.md](references/python-backend-ai.md)
   - Tailwind CSS v4, Next.js 15+, React 19, Svelte 5, Zod v4, and ESLint v9: [references/web-frameworks.md](references/web-frameworks.md)

4. **Re-run the scan to verify zero issues remain** (exit code `0`):
   ```bash
   python3 scripts/uncutoff_cli.py scan .
   ```

## Installing Automatic Self-Correction Hooks

Wire native hooks so edits are verified automatically after file writes:

```bash
python3 scripts/uncutoff_cli.py hook install --agent claude
python3 scripts/uncutoff_cli.py hook install --agent codex
python3 scripts/uncutoff_cli.py hook install --agent gemini
python3 scripts/uncutoff_cli.py hook install --agent antigravity
```
