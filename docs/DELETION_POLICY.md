# Thomas Deletion Policy

Deletion operations in this repository must follow a verify-first rule.

## Rules

1. Default mode is non-destructive.
2. Before any deletion, run end-to-end verification and require success.
3. Deletion tooling must block `--apply` unless at least one verification command is provided.
4. Tracked files must never be deleted by default.
5. Deletion scope must remain explicit and narrow (known local artifact patterns only).

## Current Enforcement

- `scripts/clean_dev_artifacts.py`:
  - dry-run by default
  - requires `--verify-command` for `--apply`
  - supports `--include-tracked` only with explicit opt-in

## Example

```bash
python scripts/clean_dev_artifacts.py \
  --apply \
  --verify-command "python -m thomas browser artifact-dom-snapshot --run --json"
```
