# P019 Browser profile create/delete/list

This gap run adds first-class **browser profile management** to the Thomas CLI.

A *browser profile* is stored on disk under a configurable *profiles root* directory.

- Normal profiles are directories created by Thomas.
- If a symlink with a valid profile name exists under the profiles root, Thomas will list it
  and can delete it safely (by unlinking the symlink), but Thomas will never create symlinks.

## CLI

The commands live under `thomas browser profile`:

- `thomas browser profile create <name>`
- `thomas browser profile delete <name>`
- `thomas browser profile list`

### Machine-readable output

All commands support `--json` for automation.

Examples:

```bash
thomas browser profile create work --json
thomas browser profile list --json
thomas browser profile delete work --json
```

Success payload shape (example):

```json
{
  "ok": true,
  "action": "create",
  "profile": {"name": "work", "path": "/.../work", "kind": "dir"}
}
```

Error payload shape (example):

```json
{
  "ok": false,
  "error": {"code": "invalid_profile_name", "message": "..."}
}
```

## Storage location

Resolution order for the *profiles root* directory:

1. `--root` (per-command override)
2. `THOMAS_BROWSER_PROFILES_DIR`
3. A browser-tool provided path (if exposed by `thomas.tools.browser`)
4. Default: `THOMAS_HOME/browser/profiles` or `~/.thomas/browser/profiles`

## Deterministic errors

The implementation raises deterministic error codes for:

- `invalid_profile_name` (exit code 2)
- `profile_already_exists`
- `profile_not_found`
- `browser_profile_config_error`
- `browser_profile_external_error`
