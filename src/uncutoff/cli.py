#!/usr/bin/env python3
"""uncutoff: Manifest-aware scanner and agent hook for preventing pre-cutoff legacy APIs."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

__version__ = "0.1.0"

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".svelte-kit",
        ".nuxt",
        ".output",
        "coverage",
    }
)

PYTHON_EXTS = frozenset({".py", ".pyi"})
JS_TS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
CSS_EXTS = frozenset({".css", ".scss", ".pcss"})
SVELTE_EXTS = frozenset({".svelte"})

LEGACY_TYPING_NAMES = frozenset(
    {"List", "Dict", "Set", "Tuple", "FrozenSet", "Type", "Optional", "Union"}
)

PYDANTIC_V1_METHODS = {
    "dict": ".model_dump()",
    "parse_obj": ".model_validate(...)",
    "parse_raw": ".model_validate_json(...)",
    "from_orm": ".model_validate(..., from_attributes=True)",
    "schema": ".model_json_schema()",
    "schema_json": "json.dumps(Model.model_json_schema())",
}

PYDANTIC_V1_CONFIG_ATTRS = frozenset(
    {
        "orm_mode",
        "allow_population_by_field_name",
        "schema_extra",
        "anystr_strip_whitespace",
        "arbitrary_types_allowed",
        "extra",
        "frozen",
        "env_prefix",
        "validate_assignment",
        "use_enum_values",
        "alias_generator",
        "keep_untouched",
        "copy_on_model_validation",
    }
)

RETIRED_MODEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^claude-3-(?:opus|sonnet|haiku)(?:-\d{8})?$"),
        "Retired Claude 3 model ID; choose an active Claude release or read from config/env.",
    ),
    (
        re.compile(r"^claude-3-5-(?:sonnet|haiku)(?:-\d{8}|-latest)?$"),
        "Retired Claude 3.5 model ID; choose an active Claude release or read from config/env.",
    ),
    (
        re.compile(r"^claude-sonnet-4-20250514$"),
        "Retired Claude Sonnet 4 snapshot ID; update to a current supported Claude model ID.",
    ),
    (
        re.compile(r"^gpt-3\.5-turbo(?:-\d{4}|-instruct|-16k)?$"),
        "Legacy GPT-3.5 model ID; replace with a current GPT model family or env config.",
    ),
    (
        re.compile(r"^gpt-4-(?:0613|0314|32k(?:-0613|-0314)?)$"),
        "Retired GPT-4 snapshot ID; replace with a current model family or env config.",
    ),
    (
        re.compile(r"^text-davinci-\d{3}$"),
        "Retired OpenAI completions model ID; migrate to the Responses API with a current model.",
    ),
    (
        re.compile(r"^gemini-1\.[05]-(?:pro|flash)(?:-\d{3}|-latest|-00[12])?$"),
        "Retired Gemini 1.0/1.5 model ID; use an active Gemini model release via google-genai.",
    ),
)

ESLINT_LEGACY_NAMES = frozenset(
    {
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.mjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        ".eslintignore",
    }
)

TAILWIND_CONFIG_NAMES = frozenset(
    {
        "tailwind.config.js",
        "tailwind.config.ts",
        "tailwind.config.cjs",
        "tailwind.config.mjs",
    }
)


@dataclass(frozen=True)
class RuleMeta:
    id: str
    pack: str
    gate: str
    severity: str
    title: str
    replacement: str


RULES: tuple[RuleMeta, ...] = (
    RuleMeta(
        "CUT-001",
        "python-modern",
        "python >= 3.12",
        "error",
        "Deprecated naive UTC datetime call",
        "Use datetime.now(datetime.UTC) or datetime.fromtimestamp(ts, tz=datetime.UTC).",
    ),
    RuleMeta(
        "CUT-002",
        "python-modern",
        "python >= 3.12",
        "warning",
        "Deprecated asyncio.get_event_loop()",
        "Use asyncio.get_running_loop() inside coroutines or asyncio.run() at entry points.",
    ),
    RuleMeta(
        "CUT-003",
        "python-modern",
        "python >= 3.10",
        "warning",
        "Legacy typing module generic/union alias",
        "Use built-in generics list[T], dict[K, V], set[T], tuple[T, ...], type[T] and T | None.",
    ),
    RuleMeta(
        "CUT-004",
        "python-modern",
        "python >= 3.12",
        "error",
        "Legacy pkg_resources import",
        "Use importlib.metadata and importlib.resources from the standard library.",
    ),
    RuleMeta(
        "CUT-005",
        "python-modern",
        "python >= 3.10",
        "warning",
        "Deprecated pyproject.toml license table or License classifier",
        'Use PEP 639 plain SPDX string `license = "MIT"` and remove `License ::` classifiers.',
    ),
    RuleMeta(
        "CUT-010",
        "pydantic-v2",
        "pydantic >= 2",
        "error",
        "Removed/deprecated Pydantic v1 model method",
        "Use v2 methods: .model_dump(), .model_validate(), .model_validate_json(), .model_json_schema().",
    ),
    RuleMeta(
        "CUT-011",
        "pydantic-v2",
        "pydantic >= 2",
        "error",
        "Deprecated Pydantic v1 validator decorator",
        "Use @field_validator(...) with @classmethod or @model_validator(mode='after'|'before').",
    ),
    RuleMeta(
        "CUT-012",
        "pydantic-v2",
        "pydantic >= 2",
        "warning",
        "Deprecated Pydantic v1 inner class Config",
        "Replace `class Config:` with `model_config = ConfigDict(...)` (e.g. `from_attributes=True`).",
    ),
    RuleMeta(
        "CUT-013",
        "pydantic-v2",
        "pydantic >= 2",
        "error",
        "Removed Pydantic v1 Field(regex=...) argument",
        "Replace `Field(..., regex=...)` with `Field(..., pattern=...)`.",
    ),
    RuleMeta(
        "CUT-020",
        "fastapi-sqlalchemy",
        "fastapi present",
        "warning",
        "Deprecated FastAPI @app.on_event decorator",
        "Use `@asynccontextmanager async def lifespan(app: FastAPI): ...` passed to `FastAPI(lifespan=lifespan)`.",
    ),
    RuleMeta(
        "CUT-021",
        "fastapi-sqlalchemy",
        "sqlalchemy >= 2",
        "warning",
        "Deprecated SQLAlchemy 1.x declarative_base import",
        "Use `from sqlalchemy.orm import DeclarativeBase` and `class Base(DeclarativeBase): pass`.",
    ),
    RuleMeta(
        "CUT-030",
        "ai-sdks",
        "always active",
        "error",
        "End-of-life google-generativeai SDK",
        "Migrate to `google-genai` (`from google import genai; client = genai.Client()`) or `@google/genai`.",
    ),
    RuleMeta(
        "CUT-031",
        "ai-sdks",
        "openai >= 1 or unpinned",
        "error",
        "Removed openai < 1.0 global client call",
        "Use `from openai import OpenAI; client = OpenAI()` with `client.responses.create(...)` or `client.chat.completions.create(...)`.",
    ),
    RuleMeta(
        "CUT-032",
        "ai-sdks",
        "always active",
        "warning",
        "Hardcoded retired LLM model ID",
        "Update to an active model release or read the model ID from configuration/environment.",
    ),
    RuleMeta(
        "CUT-040",
        "tailwind-v4",
        "tailwindcss >= 4",
        "error",
        "Legacy Tailwind v3 @tailwind directives in CSS",
        'Replace `@tailwind base/components/utilities` with `@import "tailwindcss";` and `@theme { ... }`.',
    ),
    RuleMeta(
        "CUT-041",
        "tailwind-v4",
        "tailwindcss >= 4",
        "warning",
        "Unreferenced tailwind.config.* in Tailwind v4 project",
        'Tailwind v4 ignores `tailwind.config.*` by default; move theme tokens to `@theme` or add `@config` in CSS.',
    ),
    RuleMeta(
        "CUT-050",
        "nextjs-15",
        "next >= 15",
        "error",
        "Synchronous Next.js request API without await",
        "Await `cookies()`, `headers()`, and `draftMode()` (`await cookies()`).",
    ),
    RuleMeta(
        "CUT-060",
        "react-19",
        "react >= 19",
        "error",
        "Removed react-dom useFormState import",
        'Import `useActionState` from `"react"` instead of `useFormState` from `"react-dom"`.',
    ),
    RuleMeta(
        "CUT-070",
        "svelte-5",
        "svelte >= 5",
        "warning",
        "Legacy Svelte 4 component syntax in Svelte 5 project",
        "Use Svelte 5 runes (`$props()`, `$derived()`, `$effect()`) and callback props instead of `export let` / `$:` / `createEventDispatcher`.",
    ),
    RuleMeta(
        "CUT-080",
        "zod-v4",
        "zod >= 4",
        "error",
        "Deprecated/removed Zod v3 API",
        "Use `z.enum(MyEnum)` instead of `z.nativeEnum`, and `{ error: ... }` instead of `invalid_type_error`/`required_error`.",
    ),
    RuleMeta(
        "CUT-090",
        "eslint-v9",
        "eslint >= 9",
        "warning",
        "Deprecated ESLint legacy .eslintrc/.eslintignore config",
        "Migrate to ESLint v9 flat configuration in `eslint.config.js` or `eslint.config.mjs`.",
    ),
)

RULE_MAP: dict[str, RuleMeta] = {rule.id: rule for rule in RULES}


@dataclass
class Finding:
    rule_id: str
    pack: str
    severity: str
    file: str
    line: int
    column: int
    message: str
    replacement: str
    snippet: str = ""


@dataclass
class ManifestContext:
    root: Path
    versions: dict[str, tuple[int, int, int]]
    raw_specs: dict[str, str]
    sources: list[str]
    active_packs: list[str]


def _configure_stdio() -> None:
    """Ensure UTF-8 output on Windows consoles and non-UTF8 environments."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def parse_version_tuple(spec: str) -> tuple[int, int, int] | None:
    """Extract the lower-bound semantic version tuple from a dependency spec."""
    if not spec or not isinstance(spec, str):
        return None
    cleaned = spec.strip()
    if not cleaned or cleaned in {"*", "latest", "next"} or cleaned.startswith("workspace:"):
        return None
    # Split comma-separated constraints and inspect lower-bound / pin clauses first.
    parts = [p.strip() for p in re.split(r"[,&\s]+", cleaned) if p.strip()]
    candidates: list[tuple[int, int, int]] = []
    for part in parts:
        if part.startswith("<") or part.startswith("!="):
            continue
        m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", part)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2) or 0)
            patch = int(m.group(3) or 0)
            candidates.append((major, minor, patch))
    if not candidates:
        return None
    return max(candidates)


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _parse_req_line(line: str) -> tuple[str, str] | None:
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith(("-", "--", "git+", "http://", "https://")):
        return None
    stripped = stripped.split(";", 1)[0].strip()
    m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*(.*)$", stripped)
    if not m:
        return None
    return _normalize_pkg_name(m.group(1)), m.group(2).strip()


def _fallback_parse_pyproject(text: str) -> dict[str, Any]:
    """Minimal TOML subset parser for Python 3.10 when tomllib is unavailable."""
    data: dict[str, Any] = {"project": {"dependencies": []}, "build-system": {"requires": []}}
    m_py = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', text)
    if m_py:
        data["project"]["requires-python"] = m_py.group(1)
    m_lic = re.search(r'^\s*license\s*=\s*\{([^}]+)\}', text, re.MULTILINE)
    if m_lic:
        data["project"]["license"] = {"_raw": m_lic.group(1)}
    else:
        m_lic_str = re.search(r'^\s*license\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if m_lic_str:
            data["project"]["license"] = m_lic_str.group(1)
    for sec in ("dependencies", "requires", "classifiers"):
        m_arr = re.search(rf"^\s*{sec}\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
        if m_arr:
            items = re.findall(r'["\']([^"\']+)["\']', m_arr.group(1))
            if sec == "requires":
                data["build-system"]["requires"] = items
            else:
                data["project"][sec] = items
    return data


def _load_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if tomllib is not None:
        try:
            return tomllib.loads(text)
        except Exception:
            return _fallback_parse_pyproject(text)
    return _fallback_parse_pyproject(text)


def _record_dep(
    versions: dict[str, tuple[int, int, int]],
    raw_specs: dict[str, str],
    name: str,
    spec: str,
    prefer_exact: bool = False,
) -> None:
    norm = _normalize_pkg_name(name)
    ver = parse_version_tuple(spec)
    if norm not in raw_specs or prefer_exact:
        raw_specs[norm] = spec or "*"
    if ver is not None:
        if norm not in versions or prefer_exact or ver > versions[norm]:
            versions[norm] = ver


def _parse_uv_lock(path: Path, versions: dict[str, tuple[int, int, int]], raw_specs: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for block in re.split(r"(?m)^\[\[package\]\]\s*$", text):
        m_name = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', block)
        m_ver = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', block)
        if m_name and m_ver:
            _record_dep(versions, raw_specs, m_name.group(1), m_ver.group(1), prefer_exact=True)


def _parse_package_lock(
    path: Path, versions: dict[str, tuple[int, int, int]], raw_specs: dict[str, str]
) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_path, info in packages.items():
            if not isinstance(info, dict) or "version" not in info:
                continue
            if pkg_path.startswith("node_modules/"):
                pkg_name = pkg_path.split("node_modules/")[-1]
                if pkg_name and "/" not in pkg_name or pkg_name.startswith("@") and pkg_name.count("/") == 1:
                    _record_dep(versions, raw_specs, pkg_name, str(info["version"]), prefer_exact=True)


def _parse_pnpm_lock(
    path: Path, versions: dict[str, tuple[int, int, int]], raw_specs: dict[str, str]
) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^\s{2,6}(['\"]?)(@?[A-Za-z0-9_.\-/]+)@(\d+\.\d+\.\d+[^:\s'\"]*)\1:", text, re.MULTILINE):
        _record_dep(versions, raw_specs, m.group(2), m.group(3), prefer_exact=True)


def _compute_active_packs(versions: dict[str, tuple[int, int, int]], raw_specs: dict[str, str]) -> list[str]:
    packs: list[str] = []
    py_ver = versions.get("python")
    if py_ver is not None and py_ver >= (3, 10, 0):
        packs.append("python-modern")
    if versions.get("pydantic", (0, 0, 0)) >= (2, 0, 0):
        packs.append("pydantic-v2")
    if "fastapi" in raw_specs or versions.get("sqlalchemy", (0, 0, 0)) >= (2, 0, 0):
        packs.append("fastapi-sqlalchemy")
    packs.append("ai-sdks")
    if (
        versions.get("tailwindcss", (0, 0, 0)) >= (4, 0, 0)
        or "@tailwindcss/vite" in raw_specs
        or "@tailwindcss/postcss" in raw_specs
    ):
        packs.append("tailwind-v4")
    if versions.get("next", (0, 0, 0)) >= (15, 0, 0):
        packs.append("nextjs-15")
    if versions.get("react", (0, 0, 0)) >= (19, 0, 0):
        packs.append("react-19")
    if versions.get("svelte", (0, 0, 0)) >= (5, 0, 0):
        packs.append("svelte-5")
    if versions.get("zod", (0, 0, 0)) >= (4, 0, 0):
        packs.append("zod-v4")
    if versions.get("eslint", (0, 0, 0)) >= (9, 0, 0):
        packs.append("eslint-v9")
    return packs


def detect_manifest_context(start: Path) -> ManifestContext:
    """Detect versions from the nearest manifest directory at or above `start`."""
    cur = start if start.is_dir() else start.parent
    cur = cur.resolve()

    manifest_names = (
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
    )

    chosen_dir = cur
    for candidate in [cur, *cur.parents]:
        if any((candidate / name).is_file() for name in manifest_names):
            chosen_dir = candidate
            break
        if (candidate / ".git").exists():
            chosen_dir = candidate
            break

    versions: dict[str, tuple[int, int, int]] = {}
    raw_specs: dict[str, str] = {}
    sources: list[str] = []

    pyproject_path = chosen_dir / "pyproject.toml"
    if pyproject_path.is_file():
        sources.append("pyproject.toml")
        py_data = _load_toml(pyproject_path)
        project = py_data.get("project", {}) if isinstance(py_data.get("project"), dict) else {}
        req_py = project.get("requires-python")
        if isinstance(req_py, str):
            _record_dep(versions, raw_specs, "python", req_py)
        for dep in project.get("dependencies", []) if isinstance(project.get("dependencies"), list) else []:
            if isinstance(dep, str):
                parsed = _parse_req_line(dep)
                if parsed:
                    _record_dep(versions, raw_specs, parsed[0], parsed[1])
        opt_deps = project.get("optional-dependencies", {})
        if isinstance(opt_deps, dict):
            for group in opt_deps.values():
                if isinstance(group, list):
                    for dep in group:
                        if isinstance(dep, str):
                            parsed = _parse_req_line(dep)
                            if parsed:
                                _record_dep(versions, raw_specs, parsed[0], parsed[1])
        dep_groups = py_data.get("dependency-groups", {})
        if isinstance(dep_groups, dict):
            for group in dep_groups.values():
                if isinstance(group, list):
                    for dep in group:
                        if isinstance(dep, str):
                            parsed = _parse_req_line(dep)
                            if parsed:
                                _record_dep(versions, raw_specs, parsed[0], parsed[1])
        build_sys = py_data.get("build-system", {})
        if isinstance(build_sys, dict):
            for dep in build_sys.get("requires", []) if isinstance(build_sys.get("requires"), list) else []:
                if isinstance(dep, str):
                    parsed = _parse_req_line(dep)
                    if parsed:
                        _record_dep(versions, raw_specs, parsed[0], parsed[1])

    for req_file in sorted(chosen_dir.glob("requirements*.txt")):
        sources.append(req_file.name)
        for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _parse_req_line(line)
            if parsed:
                _record_dep(versions, raw_specs, parsed[0], parsed[1])

    uv_lock = chosen_dir / "uv.lock"
    if uv_lock.is_file():
        sources.append("uv.lock")
        _parse_uv_lock(uv_lock, versions, raw_specs)

    pkg_json = chosen_dir / "package.json"
    if pkg_json.is_file():
        sources.append("package.json")
        try:
            pj = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pj = {}
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            deps = pj.get(section)
            if isinstance(deps, dict):
                for pkg_name, pkg_spec in deps.items():
                    if isinstance(pkg_spec, str):
                        _record_dep(versions, raw_specs, pkg_name, pkg_spec)

    pkg_lock = chosen_dir / "package-lock.json"
    if pkg_lock.is_file():
        sources.append("package-lock.json")
        _parse_package_lock(pkg_lock, versions, raw_specs)

    pnpm_lock = chosen_dir / "pnpm-lock.yaml"
    if pnpm_lock.is_file():
        sources.append("pnpm-lock.yaml")
        _parse_pnpm_lock(pnpm_lock, versions, raw_specs)

    active_packs = _compute_active_packs(versions, raw_specs)
    return ManifestContext(
        root=chosen_dir,
        versions=versions,
        raw_specs=raw_specs,
        sources=sources,
        active_packs=active_packs,
    )


def _line_has_ignore(lines: list[str], line_no: int, rule_id: str) -> bool:
    if line_no < 1 or line_no > len(lines):
        return False
    line = lines[line_no - 1]
    prev = lines[line_no - 2] if line_no >= 2 else ""
    for candidate in (line, prev):
        if "uncutoff: ignore" in candidate or "uncutoff-ignore" in candidate:
            m = re.search(r"uncutoff[:\-]\s*ignore\[([^\]]+)\]", candidate)
            if not m:
                return True
            allowed = {item.strip().upper() for item in m.group(1).split(",")}
            if rule_id in allowed:
                return True
    return False


def _make_finding(
    rule_id: str,
    file_display: str,
    line: int,
    column: int,
    message: str | None = None,
    snippet: str = "",
) -> Finding:
    meta = RULE_MAP[rule_id]
    return Finding(
        rule_id=rule_id,
        pack=meta.pack,
        severity=meta.severity,
        file=file_display,
        line=line,
        column=column,
        message=message or meta.title,
        replacement=meta.replacement,
        snippet=snippet.strip(),
    )


def _collect_docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    ids.add(id(val))
    return ids


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return list(reversed(parts))
    return []


def _scan_python_text(
    text: str,
    file_display: str,
    ctx: ManifestContext,
    all_packs: bool,
) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines()
    findings: list[Finding] = []
    docstring_ids = _collect_docstring_ids(tree)

    py_ver = ctx.versions.get("python", (0, 0, 0))
    check_py312 = all_packs or py_ver >= (3, 12, 0)
    check_py310 = all_packs or py_ver >= (3, 10, 0)
    check_pydantic_v2 = all_packs or ctx.versions.get("pydantic", (0, 0, 0)) >= (2, 0, 0)
    check_fastapi = all_packs or "fastapi" in ctx.raw_specs
    check_sqlalchemy_v2 = all_packs or ctx.versions.get("sqlalchemy", (0, 0, 0)) >= (2, 0, 0)
    openai_ver = ctx.versions.get("openai")
    check_openai_v1 = all_packs or openai_ver is None or openai_ver >= (1, 0, 0)

    imports_pydantic = False
    imports_fastapi = False
    imports_openai_names: set[str] = set()
    datetime_aliases: set[str] = set()
    datetime_mod_aliases: set[str] = set()
    asyncio_aliases: set[str] = set()
    pydantic_field_names: set[str] = {"Field"}
    pydantic_validator_names: set[str] = set()
    pydantic_basemodel_names: set[str] = {"BaseModel"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                asname = alias.asname or alias.name.split(".")[0]
                if alias.name == "pydantic" or alias.name.startswith("pydantic."):
                    imports_pydantic = True
                elif alias.name == "fastapi" or alias.name.startswith("fastapi."):
                    imports_fastapi = True
                elif alias.name == "openai":
                    imports_openai_names.add(asname)
                elif alias.name == "datetime":
                    datetime_mod_aliases.add(asname)
                elif alias.name == "asyncio":
                    asyncio_aliases.add(asname)
                elif alias.name == "pkg_resources" and check_py312:
                    findings.append(
                        _make_finding(
                            "CUT-004",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            "Avoid `pkg_resources`; setuptools is omitted from default Python 3.12+ environments.",
                            lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        )
                    )
                elif alias.name == "google.generativeai" or alias.name.startswith("google.generativeai."):
                    findings.append(
                        _make_finding(
                            "CUT-030",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            "`google.generativeai` is end-of-life.",
                            lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported_names = [a.name for a in node.names]
            if mod == "pydantic" or mod.startswith("pydantic."):
                imports_pydantic = True
                for a in node.names:
                    local = a.asname or a.name
                    if a.name == "Field":
                        pydantic_field_names.add(local)
                    if a.name in ("validator", "root_validator"):
                        pydantic_validator_names.add(local)
                    if a.name == "BaseModel":
                        pydantic_basemodel_names.add(local)
            elif mod == "fastapi" or mod.startswith("fastapi."):
                imports_fastapi = True
            elif mod == "datetime":
                for a in node.names:
                    if a.name == "datetime":
                        datetime_aliases.add(a.asname or a.name)
            elif mod == "asyncio":
                for a in node.names:
                    if a.name == "get_event_loop" and check_py312:
                        findings.append(
                            _make_finding(
                                "CUT-002",
                                file_display,
                                node.lineno,
                                node.col_offset + 1,
                                "`asyncio.get_event_loop()` is deprecated in Python 3.12+.",
                                lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                            )
                        )
            elif mod == "typing" and check_py310:
                legacy_hits = [name for name in imported_names if name in LEGACY_TYPING_NAMES]
                if legacy_hits:
                    findings.append(
                        _make_finding(
                            "CUT-003",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            f"Legacy typing imports ({', '.join(legacy_hits)}) can use built-in PEP 585/604 syntax.",
                            lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        )
                    )
            elif (mod == "pkg_resources" or mod.startswith("pkg_resources.")) and check_py312:
                findings.append(
                    _make_finding(
                        "CUT-004",
                        file_display,
                        node.lineno,
                        node.col_offset + 1,
                        "Avoid `pkg_resources`; migrate to `importlib.metadata` / `importlib.resources`.",
                        lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    )
                )
            elif mod == "sqlalchemy.ext.declarative" and "declarative_base" in imported_names and check_sqlalchemy_v2:
                findings.append(
                    _make_finding(
                        "CUT-021",
                        file_display,
                        node.lineno,
                        node.col_offset + 1,
                        "Legacy SQLAlchemy 1.x `declarative_base` import.",
                        lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    )
                )
            elif mod == "google" and any(a.name == "generativeai" for a in node.names):
                findings.append(
                    _make_finding(
                        "CUT-030",
                        file_display,
                        node.lineno,
                        node.col_offset + 1,
                        "`google.generativeai` is end-of-life; use `from google import genai`.",
                        lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    )
                )
            elif mod.startswith("google.generativeai"):
                findings.append(
                    _make_finding(
                        "CUT-030",
                        file_display,
                        node.lineno,
                        node.col_offset + 1,
                        "`google.generativeai` is end-of-life; use `from google import genai`.",
                        lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    )
                )

    for node in ast.walk(tree):
        # CUT-001, CUT-002, CUT-010, CUT-013, CUT-031 via Call AST
        if isinstance(node, ast.Call):
            chain = _attr_chain(node.func)
            snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if check_py312 and chain:
                if (
                    len(chain) == 2
                    and chain[0] in datetime_aliases
                    and chain[1] in ("utcnow", "utcfromtimestamp")
                ) or (
                    len(chain) == 3
                    and chain[0] in datetime_mod_aliases
                    and chain[1] == "datetime"
                    and chain[2] in ("utcnow", "utcfromtimestamp")
                ):
                    findings.append(
                        _make_finding(
                            "CUT-001",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            f"`datetime.{chain[-1]}()` is deprecated in Python 3.12+.",
                            snippet,
                        )
                    )
                if len(chain) == 2 and chain[0] in asyncio_aliases and chain[1] == "get_event_loop":
                    findings.append(
                        _make_finding(
                            "CUT-002",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            "`asyncio.get_event_loop()` is deprecated in Python 3.12+.",
                            snippet,
                        )
                    )

            if check_pydantic_v2 and imports_pydantic and isinstance(node.func, ast.Attribute):
                if node.func.attr in PYDANTIC_V1_METHODS:
                    findings.append(
                        _make_finding(
                            "CUT-010",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            f"Pydantic v1 method `.{node.func.attr}()` was deprecated/removed in v2; use `{PYDANTIC_V1_METHODS[node.func.attr]}`.",
                            snippet,
                        )
                    )
            if check_pydantic_v2 and imports_pydantic:
                func_name = chain[-1] if chain else (node.func.id if isinstance(node.func, ast.Name) else "")
                if func_name in pydantic_field_names:
                    for kw in node.keywords:
                        if kw.arg == "regex":
                            findings.append(
                                _make_finding(
                                    "CUT-013",
                                    file_display,
                                    node.lineno,
                                    node.col_offset + 1,
                                    "`Field(..., regex=...)` was removed in Pydantic v2.",
                                    snippet,
                                )
                            )
            if check_openai_v1 and len(chain) == 3 and chain[0] in imports_openai_names:
                if chain[1] in ("ChatCompletion", "Completion", "Embedding") and chain[2] == "create":
                    findings.append(
                        _make_finding(
                            "CUT-031",
                            file_display,
                            node.lineno,
                            node.col_offset + 1,
                            f"`{'.'.join(chain)}` was removed in openai v1.0+.",
                            snippet,
                        )
                    )

        # CUT-011, CUT-012, CUT-020 on ClassDef / FunctionDef
        elif isinstance(node, ast.ClassDef):
            if check_pydantic_v2 and imports_pydantic:
                base_names = {
                    (_attr_chain(b)[-1] if _attr_chain(b) else (b.id if isinstance(b, ast.Name) else ""))
                    for b in node.bases
                }
                if base_names & pydantic_basemodel_names:
                    for item in node.body:
                        if isinstance(item, ast.ClassDef) and item.name == "Config":
                            findings.append(
                                _make_finding(
                                    "CUT-012",
                                    file_display,
                                    item.lineno,
                                    item.col_offset + 1,
                                    "Pydantic v1 inner `class Config:` is deprecated in v2.",
                                    lines[item.lineno - 1] if item.lineno <= len(lines) else "",
                                )
                            )
                        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for dec in item.decorator_list:
                                target = dec.func if isinstance(dec, ast.Call) else dec
                                d_chain = _attr_chain(target)
                                d_name = d_chain[-1] if d_chain else (target.id if isinstance(target, ast.Name) else "")
                                if d_name in ("validator", "root_validator") and (
                                    d_name in pydantic_validator_names or d_chain
                                ):
                                    findings.append(
                                        _make_finding(
                                            "CUT-011",
                                            file_display,
                                            dec.lineno,
                                            dec.col_offset + 1,
                                            f"Pydantic v1 `@{d_name}` decorator is deprecated in v2.",
                                            lines[dec.lineno - 1] if dec.lineno <= len(lines) else "",
                                        )
                                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if check_fastapi and imports_fastapi:
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "on_event":
                        findings.append(
                            _make_finding(
                                "CUT-020",
                                file_display,
                                dec.lineno,
                                dec.col_offset + 1,
                                "FastAPI `@on_event` is deprecated in favor of `lifespan`.",
                                lines[dec.lineno - 1] if dec.lineno <= len(lines) else "",
                            )
                        )

        # CUT-032 retired model IDs in string literals (excluding docstrings)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids:
            val = node.value.strip()
            if 5 <= len(val) <= 64 and " " not in val:
                for pat, msg in RETIRED_MODEL_PATTERNS:
                    if pat.match(val):
                        findings.append(
                            _make_finding(
                                "CUT-032",
                                file_display,
                                node.lineno,
                                node.col_offset + 1,
                                f"Retired model ID `{val}`: {msg}",
                                lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                            )
                        )
                        break

    return [f for f in findings if not _line_has_ignore(lines, f.line, f.rule_id)]


def _strip_c_style_comments(text: str) -> str:
    """Replace comments with spaces while preserving line and column offsets."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_quote: str | None = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
            i += 1
        else:
            if ch in ("'", '"', "`"):
                in_quote = ch
                out.append(ch)
                i += 1
            elif ch == "/" and nxt == "/":
                while i < n and text[i] != "\n":
                    out.append(" ")
                    i += 1
            elif ch == "/" and nxt == "*":
                out.append(" ")
                out.append(" ")
                i += 2
                while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                    out.append("\n" if text[i] == "\n" else " ")
                    i += 1
                if i < n:
                    out.append(" ")
                    out.append(" ")
                    i += 2
            else:
                out.append(ch)
                i += 1
    return "".join(out)


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl
    return line, col


def _scan_css_text(text: str, file_display: str, ctx: ManifestContext, all_packs: bool) -> list[Finding]:
    check_tw4 = (
        all_packs
        or ctx.versions.get("tailwindcss", (0, 0, 0)) >= (4, 0, 0)
        or "@tailwindcss/vite" in ctx.raw_specs
        or "@tailwindcss/postcss" in ctx.raw_specs
    )
    if not check_tw4:
        return []
    stripped = _strip_c_style_comments(text)
    lines = text.splitlines()
    findings: list[Finding] = []
    for m in re.finditer(r"@tailwind\s+(base|components|utilities)\s*;", stripped):
        line, col = _line_col(stripped, m.start())
        if not _line_has_ignore(lines, line, "CUT-040"):
            findings.append(
                _make_finding(
                    "CUT-040",
                    file_display,
                    line,
                    col,
                    f"Legacy Tailwind v3 directive `@tailwind {m.group(1)};` in Tailwind v4 project.",
                    lines[line - 1] if line <= len(lines) else "",
                )
            )
    return findings


def _scan_js_ts_text(text: str, file_display: str, ctx: ManifestContext, all_packs: bool) -> list[Finding]:
    stripped = _strip_c_style_comments(text)
    lines = text.splitlines()
    findings: list[Finding] = []

    check_next15 = all_packs or ctx.versions.get("next", (0, 0, 0)) >= (15, 0, 0)
    check_react19 = all_packs or ctx.versions.get("react", (0, 0, 0)) >= (19, 0, 0)
    check_zod4 = all_packs or ctx.versions.get("zod", (0, 0, 0)) >= (4, 0, 0)

    # CUT-030 JS/TS google-generativeai
    if re.search(r"""from\s+["']@google/generative-ai["']|require\(["']@google/generative-ai["']\)""", stripped):
        m = re.search(r"""@google/generative-ai""", stripped)
        if m:
            line, col = _line_col(stripped, m.start())
            if not _line_has_ignore(lines, line, "CUT-030"):
                findings.append(
                    _make_finding(
                        "CUT-030",
                        file_display,
                        line,
                        col,
                        "Legacy `@google/generative-ai` SDK; migrate to `@google/genai`.",
                        lines[line - 1] if line <= len(lines) else "",
                    )
                )

    # CUT-032 retired model IDs inside string literals
    for m in re.finditer(r"""(["'])([a-z0-9.\-]+)\1""", stripped):
        val = m.group(2)
        for pat, msg in RETIRED_MODEL_PATTERNS:
            if pat.match(val):
                line, col = _line_col(stripped, m.start())
                if not _line_has_ignore(lines, line, "CUT-032"):
                    findings.append(
                        _make_finding(
                            "CUT-032",
                            file_display,
                            line,
                            col,
                            f"Retired model ID `{val}`: {msg}",
                            lines[line - 1] if line <= len(lines) else "",
                        )
                    )
                break

    # CUT-050 Next.js 15+ sync cookies() / headers() / draftMode()
    if check_next15 and re.search(r"""from\s+["']next/headers["']""", stripped):
        for m in re.finditer(r"\b(cookies|headers|draftMode)\s*\(\s*\)", stripped):
            prefix = stripped[max(0, m.start() - 24) : m.start()]
            if re.search(r"\bawait\s+$", prefix):
                continue
            # Also skip declarations (`function cookies(` or `import { cookies`)
            if re.search(r"\b(?:function|async\s+function|import)\s+$", prefix):
                continue
            line, col = _line_col(stripped, m.start())
            if not _line_has_ignore(lines, line, "CUT-050"):
                findings.append(
                    _make_finding(
                        "CUT-050",
                        file_display,
                        line,
                        col,
                        f"`{m.group(1)}()` is async in Next.js 15+; use `await {m.group(1)}()`.",
                        lines[line - 1] if line <= len(lines) else "",
                    )
                )

    # CUT-060 React 19 useFormState
    if check_react19:
        for m in re.finditer(
            r"""import\s*\{[^}]*\buseFormState\b[^}]*\}\s*from\s*["']react-dom["']""", stripped
        ):
            line, col = _line_col(stripped, m.start())
            if not _line_has_ignore(lines, line, "CUT-060"):
                findings.append(
                    _make_finding(
                        "CUT-060",
                        file_display,
                        line,
                        col,
                        "`useFormState` from `react-dom` moved to `useActionState` in `react` 19.",
                        lines[line - 1] if line <= len(lines) else "",
                    )
                )

    # CUT-080 Zod v4 removed/deprecated options & nativeEnum
    if check_zod4 and re.search(r"""from\s+["']zod(?:/[^"']*)?["']|require\(["']zod["']\)""", stripped):
        for m in re.finditer(r"\bz\.nativeEnum\s*\(|\b(invalid_type_error|required_error)\s*:", stripped):
            line, col = _line_col(stripped, m.start())
            if not _line_has_ignore(lines, line, "CUT-080"):
                findings.append(
                    _make_finding(
                        "CUT-080",
                        file_display,
                        line,
                        col,
                        "Legacy Zod v3 API; use `z.enum(...)` and `{ error: ... }` in Zod v4.",
                        lines[line - 1] if line <= len(lines) else "",
                    )
                )

    return findings


def _scan_svelte_text(text: str, file_display: str, ctx: ManifestContext, all_packs: bool) -> list[Finding]:
    check_svelte5 = all_packs or ctx.versions.get("svelte", (0, 0, 0)) >= (5, 0, 0)
    if not check_svelte5:
        return []
    lines = text.splitlines()
    findings: list[Finding] = []
    for m_script in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.DOTALL | re.IGNORECASE):
        script_body = _strip_c_style_comments(m_script.group(1))
        base_offset = m_script.start(1)
        if re.search(r"\$(?:props|state|derived|effect)\s*\(", script_body):
            continue
        for pat, desc in (
            (r"(?m)^\s*export\s+let\s+[A-Za-z_$][\w$]*", "Legacy `export let` prop in Svelte 5 component"),
            (r"(?m)^\s*\$:\s+", "Legacy `$:` reactive label in Svelte 5 component"),
            (r"\bcreateEventDispatcher\s*\(", "Legacy `createEventDispatcher()` in Svelte 5 component"),
        ):
            m = re.search(pat, script_body)
            if m:
                line, col = _line_col(text, base_offset + m.start())
                if not _line_has_ignore(lines, line, "CUT-070"):
                    findings.append(
                        _make_finding(
                            "CUT-070",
                            file_display,
                            line,
                            col,
                            desc,
                            lines[line - 1] if line <= len(lines) else "",
                        )
                    )
                break
    return findings


def _scan_manifest_text(
    path: Path, text: str, file_display: str, ctx: ManifestContext, all_packs: bool
) -> list[Finding]:
    lines = text.splitlines()
    findings: list[Finding] = []
    name = path.name

    if name == "pyproject.toml":
        py_ver = ctx.versions.get("python", (0, 0, 0))
        if all_packs or py_ver >= (3, 10, 0):
            m = re.search(r"(?m)^\s*license\s*=\s*\{", text)
            if m:
                line, col = _line_col(text, m.start())
                if not _line_has_ignore(lines, line, "CUT-005"):
                    findings.append(
                        _make_finding(
                            "CUT-005",
                            file_display,
                            line,
                            col,
                            'Legacy `license = { ... }` table in `pyproject.toml`; setuptools>=77 prefers `license = "MIT"`.',
                            lines[line - 1] if line <= len(lines) else "",
                        )
                    )
        for m in re.finditer(r'(?m)^[^\n#]*["\']google-generativeai(?:[<>=!~\s"\']|$)', text):
            line, col = _line_col(text, m.start())
            if not _line_has_ignore(lines, line, "CUT-030"):
                findings.append(
                    _make_finding(
                        "CUT-030",
                        file_display,
                        line,
                        col,
                        "`google-generativeai` dependency is end-of-life; replace with `google-genai`.",
                        lines[line - 1] if line <= len(lines) else "",
                    )
                )
    elif name.startswith("requirements") and name.endswith(".txt"):
        for idx, line_str in enumerate(lines, start=1):
            parsed = _parse_req_line(line_str)
            if parsed and parsed[0] == "google-generativeai":
                if not _line_has_ignore(lines, idx, "CUT-030"):
                    findings.append(
                        _make_finding(
                            "CUT-030",
                            file_display,
                            idx,
                            1,
                            "`google-generativeai` dependency is end-of-life; replace with `google-genai`.",
                            line_str,
                        )
                    )
    elif name == "package.json":
        for idx, line_str in enumerate(lines, start=1):
            if '"@google/generative-ai"' in line_str and not _line_has_ignore(lines, idx, "CUT-030"):
                findings.append(
                    _make_finding(
                        "CUT-030",
                        file_display,
                        idx,
                        1,
                        "`@google/generative-ai` is legacy; migrate to `@google/genai`.",
                        line_str,
                    )
                )
    return findings


def _css_uses_tailwind_at_config(root: Path) -> bool:
    for css_file in root.rglob("*.css"):
        if any(part in SKIP_DIRS for part in css_file.parts):
            continue
        try:
            content = css_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"""@config\s+["']""", _strip_c_style_comments(content)):
            return True
    return False


def scan_file_content(
    path: Path,
    text: str,
    ctx: ManifestContext,
    all_packs: bool = False,
    display_root: Path | None = None,
) -> list[Finding]:
    """Scan a single file's text in memory against `ctx`."""
    try:
        file_display = str(path.resolve().relative_to((display_root or ctx.root).resolve()))
    except Exception:
        file_display = str(path)

    name = path.name
    suffix = path.suffix.lower()

    if name.endswith(".min.js") or name.endswith(".min.css"):
        return []

    findings: list[Finding] = []
    lines = text.splitlines()
    check_tw4 = (
        all_packs
        or ctx.versions.get("tailwindcss", (0, 0, 0)) >= (4, 0, 0)
        or "@tailwindcss/vite" in ctx.raw_specs
        or "@tailwindcss/postcss" in ctx.raw_specs
    )
    if name in TAILWIND_CONFIG_NAMES and check_tw4 and not _css_uses_tailwind_at_config(ctx.root):
        if not _line_has_ignore(lines, 1, "CUT-041"):
            findings.append(
                _make_finding(
                    "CUT-041",
                    file_display,
                    1,
                    1,
                    f"Tailwind v4 ignores `{name}` unless CSS loads it with `@config`.",
                    name,
                )
            )
    if name in ESLINT_LEGACY_NAMES and (all_packs or ctx.versions.get("eslint", (0, 0, 0)) >= (9, 0, 0)):
        if not _line_has_ignore(lines, 1, "CUT-090"):
            findings.append(
                _make_finding(
                    "CUT-090",
                    file_display,
                    1,
                    1,
                    f"Legacy ESLint config `{name}` in an ESLint v9+ project.",
                    name,
                )
            )

    if suffix in PYTHON_EXTS:
        findings.extend(_scan_python_text(text, file_display, ctx, all_packs))
    elif suffix in CSS_EXTS:
        findings.extend(_scan_css_text(text, file_display, ctx, all_packs))
    elif suffix in JS_TS_EXTS:
        findings.extend(_scan_js_ts_text(text, file_display, ctx, all_packs))
    elif suffix in SVELTE_EXTS:
        findings.extend(_scan_svelte_text(text, file_display, ctx, all_packs))
    elif name in ("pyproject.toml", "package.json") or (
        name.startswith("requirements") and name.endswith(".txt")
    ):
        findings.extend(_scan_manifest_text(path, text, file_display, ctx, all_packs))

    return findings


def _load_uncutoffignore(root: Path) -> list[str]:
    ignore_file = root / ".uncutoffignore"
    if not ignore_file.is_file():
        return []
    patterns: list[str] = []
    for raw in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line.rstrip("/"))
    return patterns


def _is_ignored_rel(rel_path: str, ignore_patterns: list[str]) -> bool:
    norm = rel_path.replace("\\", "/")
    for pat in ignore_patterns:
        if norm == pat or norm.startswith(pat + "/") or Path(norm).match(pat):
            return True
    return False


def _collect_git_changed_files(root: Path, staged: bool) -> list[Path]:
    cmd = ["git", "-C", str(root), "diff", "--name-only", "--diff-filter=ACMR"]
    if staged:
        cmd.append("--cached")
    else:
        cmd.append("HEAD")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not staged:
        # Fallback for repos without HEAD commit yet
        res = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True
        )
        paths: list[Path] = []
        for line in res.stdout.splitlines():
            if len(line) > 3 and not line.startswith("D"):
                p = root / line[3:].strip()
                if p.is_file():
                    paths.append(p)
        return paths
    paths = []
    for line in res.stdout.splitlines():
        rel = line.strip()
        if rel:
            p = root / rel
            if p.is_file():
                paths.append(p)
    return paths


def _iter_scan_files(targets: list[Path]) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        resolved = target.resolve()
        if resolved.is_file():
            if resolved not in seen:
                seen.add(resolved)
                collected.append(resolved)
        elif resolved.is_dir():
            for dirpath, dirnames, filenames in os.walk(resolved):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                dp = Path(dirpath)
                for fname in sorted(filenames):
                    fp = dp / fname
                    if fp not in seen:
                        seen.add(fp)
                        collected.append(fp)
    return sorted(collected)


def scan_paths(
    targets: list[Path],
    all_packs: bool = False,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    diff: bool = False,
    staged: bool = False,
) -> tuple[list[Finding], dict[Path, ManifestContext]]:
    """Scan paths and return filtered findings plus manifest contexts."""
    base_dir = (targets[0] if targets else Path.cwd()).resolve()
    if base_dir.is_file():
        base_dir = base_dir.parent

    if diff or staged:
        files = _collect_git_changed_files(base_dir, staged=staged)
    else:
        files = _iter_scan_files(targets or [Path.cwd()])

    ctx_cache: dict[Path, ManifestContext] = {}
    ignore_cache: dict[Path, list[str]] = {}
    findings: list[Finding] = []

    for fp in files:
        parent = fp.parent
        if parent not in ctx_cache:
            ctx = detect_manifest_context(fp)
            ctx_cache[parent] = ctx
        else:
            ctx = ctx_cache[parent]

        if ctx.root not in ignore_cache:
            ignore_cache[ctx.root] = _load_uncutoffignore(ctx.root)
        try:
            rel = str(fp.resolve().relative_to(ctx.root.resolve()))
        except Exception:
            rel = fp.name
        if _is_ignored_rel(rel, ignore_cache[ctx.root]):
            continue

        supported = (
            fp.suffix.lower() in (PYTHON_EXTS | JS_TS_EXTS | CSS_EXTS | SVELTE_EXTS)
            or fp.name in ("pyproject.toml", "package.json")
            or (fp.name.startswith("requirements") and fp.name.endswith(".txt"))
            or fp.name in TAILWIND_CONFIG_NAMES
            or fp.name in ESLINT_LEGACY_NAMES
        )
        if not supported:
            continue

        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        file_findings = scan_file_content(fp, text, ctx, all_packs=all_packs, display_root=base_dir)
        for item in file_findings:
            if select and item.rule_id not in select:
                continue
            if ignore and item.rule_id in ignore:
                continue
            findings.append(item)

    findings.sort(key=lambda f: (f.file, f.line, f.column, f.rule_id))
    return findings, ctx_cache


def format_sarif(findings: list[Finding]) -> dict[str, Any]:
    """Render findings as SARIF 2.1.0."""
    used_rules = sorted({f.rule_id for f in findings})
    rules_arr = [
        {
            "id": rid,
            "name": RULE_MAP[rid].title,
            "shortDescription": {"text": RULE_MAP[rid].title},
            "help": {"text": RULE_MAP[rid].replacement},
            "properties": {"tags": ["uncutoff", RULE_MAP[rid].pack]},
        }
        for rid in used_rules
    ]
    results_arr = [
        {
            "ruleId": f.rule_id,
            "level": "error" if f.severity == "error" else "warning",
            "message": {"text": f"{f.message} Fix: {f.replacement}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file.replace("\\", "/")},
                        "region": {"startLine": f.line, "startColumn": f.column},
                    }
                }
            ],
        }
        for f in findings
    ]
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "uncutoff",
                        "version": __version__,
                        "informationUri": "https://github.com/SuzumiyaHaruhi719/uncutoff",
                        "rules": rules_arr,
                    }
                },
                "results": results_arr,
            }
        ],
    }


def _reconstruct_proposed_content(path: Path | None, tool_args: dict[str, Any]) -> str | None:
    for key in ("content", "Content", "file_text"):
        val = tool_args.get(key)
        if isinstance(val, str):
            return val
    # Claude Edit / Gemini replace / Antigravity edit_file
    old_str = tool_args.get("old_string") or tool_args.get("Target")
    new_str = tool_args.get("new_string") or tool_args.get("Replacement")
    if isinstance(new_str, str):
        if path and path.is_file() and isinstance(old_str, str) and old_str:
            existing = path.read_text(encoding="utf-8", errors="replace")
            if old_str in existing:
                return existing.replace(old_str, new_str, 1)
        return new_str
    return None


def run_hook(agent: str, payload_text: str) -> tuple[int, str, str]:
    """Process a hook stdin payload for the target agent; returns (exit_code, stdout, stderr)."""
    try:
        payload = json.loads(payload_text) if payload_text.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str) if isinstance(cwd_str, str) and cwd_str else Path.cwd()

    tool_call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else tool_input

    raw_path = (
        args.get("file_path")
        or args.get("path")
        or args.get("Path")
        or args.get("TargetFile")
        or ""
    )
    if not isinstance(raw_path, str) or not raw_path.strip():
        if agent in ("gemini", "antigravity"):
            return 0, json.dumps({"decision": "allow"}), ""
        return 0, "{}", ""

    target_path = Path(raw_path)
    if not target_path.is_absolute():
        target_path = (cwd / target_path).resolve()

    proposed = _reconstruct_proposed_content(target_path, args)
    if proposed is None:
        if target_path.is_file():
            proposed = target_path.read_text(encoding="utf-8", errors="replace")
        else:
            if agent in ("gemini", "antigravity"):
                return 0, json.dumps({"decision": "allow"}), ""
            return 0, "{}", ""

    ctx = detect_manifest_context(target_path if target_path.exists() else target_path.parent)
    findings = scan_file_content(target_path, proposed, ctx, display_root=ctx.root)

    if not findings:
        if agent in ("gemini", "antigravity"):
            return 0, json.dumps({"decision": "allow"}), ""
        return 0, "{}", ""

    summary_lines = [
        f"uncutoff detected {len(findings)} pre-cutoff API issue(s) in {findings[0].file}:"
    ]
    for item in findings[:8]:
        summary_lines.append(
            f"- L{item.line} [{item.rule_id}] {item.message} -> {item.replacement}"
        )
    summary = "\n".join(summary_lines)

    if agent == "claude":
        out = {
            "decision": "block",
            "reason": f"uncutoff detected {len(findings)} pre-cutoff API issue(s) in {findings[0].file}.",
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": summary,
            },
        }
        return 0, json.dumps(out), ""
    if agent in ("gemini", "antigravity"):
        return 0, json.dumps({"decision": "deny", "reason": summary}), ""
    if agent == "codex":
        event_name = payload.get("hook_event_name", "PostToolUse")
        if event_name == "PreToolUse":
            return 2, "", summary
        return 0, json.dumps({"decision": "block", "reason": summary}), summary
    return 0, "{}", ""


def _resolve_hook_command(agent: str, root: Path, custom_cmd: str | None) -> str:
    if custom_cmd:
        return custom_cmd
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.name == "uncutoff_cli.py":
        try:
            rel = argv0.relative_to(root.resolve())
            script_ref = rel.as_posix()
        except ValueError:
            script_ref = str(argv0)
        return f"python3 {script_ref} hook run --agent {agent}"
    return f"uncutoff hook run --agent {agent}"


def _upsert_matcher_hook(
    entries: list[dict[str, Any]], matcher: str, hook_entry: dict[str, Any]
) -> list[dict[str, Any]]:
    cleaned = [
        e
        for e in entries
        if not (
            isinstance(e, dict)
            and any(
                isinstance(h, dict) and ("uncutoff" in str(h.get("command", "")) or h.get("name") == "uncutoff")
                for h in e.get("hooks", [])
            )
        )
    ]
    cleaned.append({"matcher": matcher, "hooks": [hook_entry]})
    return cleaned


def install_hook(
    agent: str,
    root: Path,
    global_scope: bool = False,
    dry_run: bool = False,
    custom_cmd: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Install or update `uncutoff` hook configuration non-destructively."""
    cmd = _resolve_hook_command(agent, root, custom_cmd)
    home = Path.home()

    if agent == "claude":
        cfg_path = (home / ".claude" / "settings.json") if global_scope else (root / ".claude" / "settings.json")
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        hooks = data.setdefault("hooks", {})
        hooks["PostToolUse"] = _upsert_matcher_hook(
            hooks.get("PostToolUse", []),
            "Write|Edit|MultiEdit",
            {"type": "command", "command": cmd, "timeout": 10},
        )
    elif agent == "codex":
        cfg_path = (home / ".codex" / "hooks.json") if global_scope else (root / ".codex" / "hooks.json")
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        hooks = data.setdefault("hooks", {})
        hooks["PostToolUse"] = _upsert_matcher_hook(
            hooks.get("PostToolUse", []),
            ".*",
            {"type": "command", "command": cmd, "timeout": 10},
        )
    elif agent == "gemini":
        cfg_path = (home / ".gemini" / "settings.json") if global_scope else (root / ".gemini" / "settings.json")
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        hooks = data.setdefault("hooks", {})
        hooks["BeforeTool"] = _upsert_matcher_hook(
            hooks.get("BeforeTool", []),
            "write_file|replace",
            {"name": "uncutoff", "type": "command", "command": cmd, "timeout": 10000},
        )
    elif agent == "antigravity":
        cfg_path = (home / ".gemini" / "config" / "hooks.json") if global_scope else (root / ".agents" / "hooks.json")
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        data["uncutoff"] = {
            "PreToolUse": [
                {
                    "matcher": "write_file|edit_file",
                    "hooks": [{"type": "command", "command": cmd, "timeout": 10}],
                }
            ]
        }
    else:  # pragma: no cover
        raise ValueError(f"Unsupported agent: {agent}")

    if not dry_run:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return cfg_path, data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uncutoff",
        description="Manifest-aware scanner and agent hook that blocks pre-cutoff legacy APIs.",
    )
    parser.add_argument("--version", action="version", version=f"uncutoff {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_detect = sub.add_parser("detect", help="Detect dependency versions and active rule packs.")
    p_detect.add_argument("path", nargs="?", default=".", help="Project directory or file (default: .)")
    p_detect.add_argument("--format", choices=("text", "json"), default="text")

    p_scan = sub.add_parser("scan", help="Scan files or git diff for pre-cutoff API usage.")
    p_scan.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan (default: .)")
    p_scan.add_argument("--diff", action="store_true", help="Scan modified files in git working tree.")
    p_scan.add_argument("--staged", action="store_true", help="Scan staged files in git index.")
    p_scan.add_argument("--all-packs", action="store_true", help="Ignore manifest version gates and run all packs.")
    p_scan.add_argument("--select", default="", help="Comma-separated rule IDs to include.")
    p_scan.add_argument("--ignore", default="", help="Comma-separated rule IDs to skip.")
    p_scan.add_argument("--format", choices=("text", "json", "sarif"), default="text")

    p_rules = sub.add_parser("rules", help="List built-in cutoff rules and replacements.")
    p_rules.add_argument("--format", choices=("text", "json"), default="text")

    p_hook = sub.add_parser("hook", help="Run or install agent lifecycle hooks.")
    hook_sub = p_hook.add_subparsers(dest="hook_command")

    p_hrun = hook_sub.add_parser("run", help="Inspect stdin JSON hook event for an agent.")
    p_hrun.add_argument("--agent", required=True, choices=("claude", "codex", "gemini", "antigravity"))

    p_hinst = hook_sub.add_parser("install", help="Install uncutoff hook config for an agent.")
    p_hinst.add_argument("--agent", required=True, choices=("claude", "codex", "gemini", "antigravity"))
    p_hinst.add_argument("--root", default=".", help="Project root directory (default: .)")
    p_hinst.add_argument("--global", dest="global_scope", action="store_true", help="Install into user global config.")
    p_hinst.add_argument("--dry-run", action="store_true", help="Print resulting config without writing.")
    p_hinst.add_argument("--command", dest="custom_cmd", default=None, help="Custom command override.")

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "detect":
        ctx = detect_manifest_context(Path(args.path))
        payload = {
            "root": str(ctx.root),
            "sources": ctx.sources,
            "versions": {k: ".".join(map(str, v)) for k, v in sorted(ctx.versions.items())},
            "specs": dict(sorted(ctx.raw_specs.items())),
            "active_packs": ctx.active_packs,
        }
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"Root: {payload['root']}")
            print(f"Manifests: {', '.join(ctx.sources) if ctx.sources else '(none detected)'}")
            if payload["versions"]:
                ver_line = "  ".join(f"{k}={v}" for k, v in payload["versions"].items())
                print(f"Versions: {ver_line}")
            else:
                print("Versions: (none pinned)")
            print(f"Active packs: {', '.join(ctx.active_packs)}")
        return 0

    if args.command == "rules":
        if args.format == "json":
            print(json.dumps([asdict(r) for r in RULES], indent=2))
        else:
            for r in RULES:
                print(f"{r.id} [{r.pack} | gate: {r.gate}] {r.title}")
                print(f"    Fix: {r.replacement}")
        return 0

    if args.command == "scan":
        select = {x.strip().upper() for x in args.select.split(",") if x.strip()} or None
        ignore = {x.strip().upper() for x in args.ignore.split(",") if x.strip()} or None
        findings, _ = scan_paths(
            [Path(p) for p in args.paths],
            all_packs=args.all_packs,
            select=select,
            ignore=ignore,
            diff=args.diff,
            staged=args.staged,
        )
        if args.format == "json":
            print(json.dumps([asdict(f) for f in findings], indent=2))
        elif args.format == "sarif":
            print(json.dumps(format_sarif(findings), indent=2))
        else:
            if not findings:
                print("uncutoff: 0 issues")
            else:
                for f in findings:
                    print(f"{f.file}:{f.line}:{f.column} [{f.rule_id}] ({f.severity}) {f.message}")
                    print(f"  Fix: {f.replacement}")
                print(f"\nFound {len(findings)} pre-cutoff API issue(s).")
        return 1 if findings else 0

    if args.command == "hook":
        if args.hook_command == "run":
            stdin_text = sys.stdin.read()
            code, out, err = run_hook(args.agent, stdin_text)
            if out:
                sys.stdout.write(out + ("\n" if not out.endswith("\n") else ""))
            if err:
                sys.stderr.write(err + ("\n" if not err.endswith("\n") else ""))
            return code
        if args.hook_command == "install":
            cfg_path, data = install_hook(
                args.agent,
                Path(args.root).resolve(),
                global_scope=args.global_scope,
                dry_run=args.dry_run,
                custom_cmd=args.custom_cmd,
            )
            if args.dry_run:
                print(json.dumps({"target": str(cfg_path), "config": data}, indent=2))
            else:
                print(f"Installed uncutoff hook for {args.agent} in {cfg_path}")
            return 0
        parser.parse_args(["hook", "--help"])
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
