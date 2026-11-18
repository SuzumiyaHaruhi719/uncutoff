# Python Backend & AI SDK Reference

## Pydantic v2 (`pydantic >= 2`)

- **CUT-010 (Model methods)**:
  - `.dict()` -> `.model_dump()`
  - `.json()` -> `.model_dump_json()`
  - `.parse_obj(data)` -> `.model_validate(data)`
  - `.parse_raw(raw)` -> `.model_validate_json(raw)`
  - `.from_orm(obj)` -> `.model_validate(obj)` (with `ConfigDict(from_attributes=True)`)
  - `.schema()` / `.schema_json()` -> `.model_json_schema()`
- **CUT-011 (Validators)**:
  - `@validator(...)` -> `@field_validator(...)` + `@classmethod`
  - `@root_validator(...)` -> `@model_validator(mode="after" | "before")`
- **CUT-012 (Model config)**:
  - `class Config:` inside `BaseModel` -> `model_config = ConfigDict(...)` (`orm_mode` -> `from_attributes`, `allow_population_by_field_name` -> `populate_by_name`)
- **CUT-013 (`Field` regex)**:
  - `Field(..., regex=...)` -> `Field(..., pattern=...)`

## FastAPI & SQLAlchemy 2.0

- **CUT-020 (`on_event` deprecated)**:
  - `@app.on_event("startup")` / `@app.on_event("shutdown")` -> `@asynccontextmanager async def lifespan(app: FastAPI): ...; app = FastAPI(lifespan=lifespan)`
- **CUT-021 (Declarative base in SQLAlchemy 2.0)**:
  - `from sqlalchemy.ext.declarative import declarative_base` -> `from sqlalchemy.orm import DeclarativeBase` (`class Base(DeclarativeBase): pass`)

## AI SDKs & Model IDs

- **CUT-030 (Google Gemini Python SDK)**:
  - `google-generativeai` (`import google.generativeai`) reached end of life -> install `google-genai` and use `from google import genai; client = genai.Client()`
- **CUT-031 (OpenAI Python SDK v1+)**:
  - `openai.ChatCompletion.create(...)` / `openai.Completion.create(...)` / `openai.Embedding.create(...)` removed -> `from openai import OpenAI; client = OpenAI(); client.responses.create(...)` or `client.chat.completions.create(...)`
- **CUT-032 (Retired hardcoded model IDs)**:
  - Avoid hardcoded retired IDs such as `claude-3-*`, `claude-3-5-sonnet-*`, `claude-sonnet-4-20250514`, `gpt-3.5-turbo*`, `gpt-4-0613`, `gpt-4-32k*`, `text-davinci-*`, `gemini-1.0-pro*`, `gemini-1.5-pro*`, `gemini-1.5-flash*`. Read model selection from configuration or environment variables and default to an active release.
