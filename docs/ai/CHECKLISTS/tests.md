# Tests Checklist

- Always run `pytest --collect-only -q` first.
- Use `python scripts/test_stepup_protocol.py` as the repo-wide pytest path.
- Keep the default `--max-stage large` flow: collect -> small shards -> larger shard bundles.
- Only add `--max-stage full` after the shard and large stages are green and you need the final monolithic proof.
- Do not hide failures by shrinking curated test lists.
- If deferring behavior, use explicit `xfail`/`skip` with reason and tracking reference.
- Keep `tests/conftest.py` plugin targets valid and import-safe.
- Preserve test files for intentional product scope.
