# Deletion Records

Any PR that deletes or renames files under `thomas/` or `tests/` must include a
record in this folder.

Record format: `*.json` with:

- `approved_by_human`: `true`
- `files`: list of deleted/renamed protected paths
- `reason`: why deletion is needed
- `verification`: list of checks proving safety

Example:

```json
{
  "id": "2026-03-04-example",
  "approved_by_human": true,
  "files": [
    "thomas/example_module.py"
  ],
  "reason": "Replaced by thomas/new_module.py after migration.",
  "verification": [
    "rg references checked",
    "pytest --collect-only",
    "targeted regression tests"
  ]
}
```
