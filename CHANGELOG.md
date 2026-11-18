# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-18

### Added
- Manifest-aware version detector (`uncutoff detect`) supporting `pyproject.toml`, `uv.lock`, `requirements*.txt`, `package.json`, `pnpm-lock.yaml`, and `package-lock.json`.
- Zero-dependency Python AST and structural scanner (`uncutoff scan`) with 21 version-gated rules (`CUT-001` through `CUT-090`) across `python-modern`, `pydantic-v2`, `fastapi-sqlalchemy`, `ai-sdks`, `tailwind-v4`, `nextjs-15`, `react-19`, `svelte-5`, `zod-v4`, and `eslint-v9`.
- Text, JSON, and SARIF 2.1.0 output formatters plus `--diff` and `--staged` git scopes and `--all-packs` / `--select` / `--ignore` filters.
- Native lifecycle hook runners and non-destructive installers (`uncutoff hook run` and `uncutoff hook install`) for Claude Code (`PostToolUse`), OpenAI Codex CLI (`PreToolUse`/`PostToolUse`), Google Gemini CLI (`BeforeTool`), and Google Antigravity (`PreToolUse`).
- Open Agent Skill (`skills/uncutoff/SKILL.md`), reference guides, and plugin manifests for Claude Code, Codex, Cursor, and Gemini CLI.
