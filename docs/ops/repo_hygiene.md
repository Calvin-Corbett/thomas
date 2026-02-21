# Repo Hygiene Guard

This guard keeps Thomas scalable by preventing root-file sprawl and tracked runtime artifacts.

## Why

- Prevent silent drift into a hard-to-maintain monolith repo layout.
- Keep tracked source focused on code, docs, tests, and scripts.
- Stop accidental commits of runtime/task/output artifacts.

## Enforced Policy

- Tracked root files must stay within a fixed allowlist and count cap.
- Tracked files must not be committed under artifact-heavy prefixes:
  - `runtime/`
  - `output/`
  - `pack/`
  - `patches/`
  - `.inbox_extract_*`
- Block tracked transient suffixes (`.pyc`, `.tmp`, `.log`).

Canonical baseline:
- `docs/repo_hygiene_baseline.json`

Gate command:

```bash
python scripts/check_repo_hygiene.py
```

Local cleanup helper (untracked + ignored junk artifacts):

```bash
python scripts/cleanup_local_junk.py --apply
```

## Updating Baseline Intentionally

If the repo intentionally adds a new tracked root file or adjusts policy:

1. Update `docs/repo_hygiene_baseline.json`.
2. Explain why in `CHANGELOG.md`.
3. Keep additions minimal and tied to clear ownership.
