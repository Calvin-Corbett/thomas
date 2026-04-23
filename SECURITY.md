# SECURITY.md

## Runtime Data Directory Rule

Thomas runtime data must stay inside configured runtime roots, never in the repo
root.

Use `THOMAS_DATA_DIR` and `THOMAS_MEMORY_ROOT` to control where persistent state
lands. The config loaders in `thomas/core/config.py` already resolve these paths;
new code should use those APIs rather than writing to hard-coded project files.

Recommended defaults:

- `THOMAS_DATA_DIR`: base data root for runtime caches and metadata.
- `THOMAS_MEMORY_ROOT`: optional explicit path for memory + runtime artifacts.
- `THOMAS_STATE_DIR`/`THOMAS_LOG_FILE`: for app state and logs.

If you add new runtime artifacts, route them under one of those resolved paths.

Never add runtime artifacts to committed root-level files (for example `*.db`,
`*.log`, `runtime/*`, `.thomas/*`, `tmp/*`).

## Secret Handling

Never commit secrets, tokens, or credentials. Keep provider keys in runtime secret
stores, environment variables, or approved key management surfaces.

Before opening a PR or sharing a branch snapshot, run one of the local or
installed scanners:

- `python scripts/audit_secrets.py --strict`
- `gitleaks detect --source . --no-git --verbose`
- `trufflehog filesystem . --no-git -f json`

Also review obvious artifacts in working directories:

- `.thomas/*`
- `runtime/*`
- `logs/*`
- `dist/*`, `tmp/*`
- `thomas_state.json`, `thomas.db*`, `*.sqlite*`, `*.env*`

If a secret is discovered:

1. Revoke/rotate immediately.
2. Remove the secret from working files and history (if committed).
3. Add prevention notes to `CONTRIBUTING_AI.md` and validate with one of the
   scan commands above before retry.

Use `scripts/audit_secrets.py` for repo-local quick checks and keep scan output
in your PR notes.
