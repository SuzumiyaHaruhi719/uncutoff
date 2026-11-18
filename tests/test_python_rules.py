from pathlib import Path
import tempfile
import unittest

from uncutoff.cli import detect_manifest_context, scan_file_content, scan_paths


class TestPythonRules(unittest.TestCase):
    def test_catches_modern_python_pydantic_fastapi_ai_sdks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="svc"\nrequires-python=">=3.12"\n'
                'license = {text = "MIT"}\n'
                'dependencies=["pydantic>=2.8", "fastapi>=0.115", "sqlalchemy>=2.0"]\n',
                encoding="utf-8",
            )
            code = """from datetime import datetime
import asyncio
from typing import List, Optional
import pkg_resources
import google.generativeai as genai
import openai
from fastapi import FastAPI
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
app = FastAPI()

@app.on_event("startup")
async def on_start():
    _ = asyncio.get_event_loop()

class User(BaseModel):
    name: Optional[str] = Field(default=None, regex="^[a-z]+$")
    created: datetime = datetime.utcnow()

    class Config:
        orm_mode = True

    @validator("name")
    def strip_name(cls, v):
        return v

def dump(u: User) -> List[dict]:
    _ = openai.ChatCompletion.create(model="claude-sonnet-4-20250514", messages=[])
    return [u.dict()]
"""
            (root / "app.py").write_text(code, encoding="utf-8")
            findings, _ = scan_paths([root])
            rule_ids = {f.rule_id for f in findings}
            expected = {
                "CUT-001",
                "CUT-002",
                "CUT-003",
                "CUT-004",
                "CUT-005",
                "CUT-010",
                "CUT-011",
                "CUT-012",
                "CUT-013",
                "CUT-020",
                "CUT-021",
                "CUT-030",
                "CUT-031",
                "CUT-032",
            }
            self.assertEqual(expected - rule_ids, set())

    def test_ignores_docstrings_comments_and_non_pydantic_methods(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="clean"\nrequires-python=">=3.12"\nlicense = "MIT"\n'
                'dependencies=["pydantic>=2.9"]\n',
                encoding="utf-8",
            )
            code = '''"""Module mentioning datetime.utcnow() and claude-3-opus-20240229 in docstring."""

class PlainMap:
    def dict(self):
        return {}

def run():
    """Docstring with @validator and claude-sonnet-4-20250514."""
    # datetime.utcnow() in comment should be ignored
    m = PlainMap()
    return m.dict()
'''
            (root / "clean.py").write_text(code, encoding="utf-8")
            findings, _ = scan_paths([root])
            self.assertEqual(findings, [])

    def test_inline_suppression_and_legacy_pin_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                '[project]\nname="legacy"\nrequires-python=">=3.9"\ndependencies=["pydantic==1.10.18"]\n',
                encoding="utf-8",
            )
            code = """from datetime import datetime
from typing import Optional
from pydantic import BaseModel, validator

class OldModel(BaseModel):
    x: Optional[int] = None
    created: datetime = datetime.utcnow()

    class Config:
        orm_mode = True

    @validator("x")
    def ok(cls, v):
        return v

def f(m: OldModel):
    return m.dict()
"""
            (root / "old.py").write_text(code, encoding="utf-8")
            findings, _ = scan_paths([root])
            self.assertEqual(findings, [])

            # Inline suppression check under modern manifest
            (root / "pyproject.toml").write_text(
                '[project]\nname="mod"\nrequires-python=">=3.12"\nlicense="MIT"\n',
                encoding="utf-8",
            )
            ctx = detect_manifest_context(root)
            suppressed = "from datetime import datetime\nx = datetime.utcnow()  # uncutoff: ignore[CUT-001]\n"
            self.assertEqual(scan_file_content(root / "x.py", suppressed, ctx), [])


if __name__ == "__main__":
    unittest.main()
