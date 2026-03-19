# Tests Checklist

- Always run `pytest --collect-only -q` first.
- Do not hide failures by shrinking curated test lists.
- If deferring behavior, use explicit `xfail`/`skip` with reason and tracking reference.
- Keep `tests/conftest.py` plugin targets valid and import-safe.
- Preserve test files for intentional product scope.
