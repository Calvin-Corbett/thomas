# Repo Hygiene Guard

This guard keeps Thomas scalable by preventing root-file sprawl, tracked runtime artifacts, and dirty pushes.

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
- Clean worktree enforcement (default): fail when staged, unstaged, or untracked paths exist.
- Canonical repo identity: fail when clone path or remote slug drifts from `docs/ops/repo_identity_policy.json`.

Canonical baseline:
- `docs/repo_hygiene_baseline.json`

Gate command:

```bash
python scripts/forge/gates/repo_hygiene.py
```

Canonical identity guard:

```bash
python scripts/forge/gates/repo_identity.py
```

Layout-only mode (skip clean-worktree enforcement):

```bash
python scripts/forge/gates/repo_hygiene.py --no-require-clean-worktree
```

Local cleanup helper (untracked + ignored junk artifacts):

```bash
python scripts/cleanup_local_junk.py --apply
```

CLI helper (cleanup + worktree summary):

```bash
thomas repo-clean --apply --strict
```

Status helper (config + worktree cleanliness):

```bash
thomas status --json --strict-worktree
```

Local hook installation (recommended):

```bash
pre-commit install
pre-commit install --hook-type pre-push
```

## Updating Baseline Intentionally

If the repo intentionally adds a new tracked root file or adjusts policy:

1. Update `docs/repo_hygiene_baseline.json`.
2. Explain why in `CHANGELOG.md`.
3. Keep additions minimal and tied to clear ownership.
