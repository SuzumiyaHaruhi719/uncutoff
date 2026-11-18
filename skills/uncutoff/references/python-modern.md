# Modern Python Reference (Python 3.10+ / 3.12+)

## CUT-001: Timezone-Aware UTC (`datetime.utcnow` deprecated in 3.12)
- **Avoid**: `datetime.utcnow()`, `datetime.utcfromtimestamp(ts)`
- **Use**: `datetime.now(datetime.UTC)` (or `datetime.now(timezone.utc)` on 3.10+), `datetime.fromtimestamp(ts, tz=datetime.UTC)`

## CUT-002: Event Loop Lookup (`asyncio.get_event_loop` deprecated in 3.12+)
- **Avoid**: `asyncio.get_event_loop()` inside coroutines or startup helpers
- **Use**: `asyncio.get_running_loop()` inside async code, or `asyncio.run(main())` at the entry point

## CUT-003: Built-in Generic & Union Types (PEP 585 / PEP 604, Python 3.10+)
- **Avoid**: `from typing import List, Dict, Set, Tuple, FrozenSet, Type, Optional, Union`
- **Use**: `list[T]`, `dict[K, V]`, `set[T]`, `tuple[T, ...]`, `type[T]`, `T | None`, `A | B`

## CUT-004: Replace `pkg_resources` (Removed from default Python 3.12+ environments)
- **Avoid**: `import pkg_resources` / `from pkg_resources import ...`
- **Use**: `from importlib.metadata import version, entry_points` and `from importlib.resources import files`

## CUT-005: PEP 639 License Metadata (`setuptools>=77`)
- **Avoid**: `license = { text = "MIT" }` paired with `License :: OSI Approved :: ...` classifiers in `pyproject.toml`
- **Use**: `license = "MIT"` as a plain SPDX expression string and omit legacy `License ::` classifiers
