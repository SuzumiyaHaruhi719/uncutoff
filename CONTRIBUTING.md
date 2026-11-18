# Contributing to uncutoff

Thank you for helping improve `uncutoff`!

## Development Setup

`uncutoff` runs on Python 3.10+ using only the Python standard library.

```bash
git clone https://github.com/SuzumiyaHaruhi719/uncutoff.git
cd uncutoff
python3 -m unittest discover -s tests -v
```

## Adding or Updating a Rule

1. Every rule must correspond to a **documented deprecation, removal, or breaking API shift** in a major release or official migration guide.
2. Version-gate framework rules so older projects pinned to prior major versions produce zero false positives.
3. Keep `skills/uncutoff/scripts/uncutoff_cli.py` and `src/uncutoff/cli.py` synchronized (`test_cli_and_skill.py` enforces parity).
4. Add both positive regression tests and negative false-positive tests (including comments, docstrings, and older version pins).
5. Run the full test suite before opening a pull request:

```bash
python3 -m compileall -q src skills tests
python3 -m unittest discover -s tests -v
```

## Pull Request Checklist

- Include a concise summary of the cutoff API change and its replacement.
- Link to the upstream changelog or migration guide when adding a rule.
- Ensure all unit tests pass across supported Python versions.
