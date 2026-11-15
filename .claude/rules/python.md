---
paths:
  - "**/*.py"
---

# Python rules

- Typed code: annotate public functions; mypy runs in strict mode.
- Use `uv add <pkg>` / `uv add --group dev <pkg>`; never `pip install`.
- Tests live in `tests/`, use pytest, and use Hypothesis for parsers and data transforms.
- No `assert` for runtime checks outside tests; raise explicit exceptions.
- Use `subprocess` with argument lists, never `shell=True` with interpolated input.
