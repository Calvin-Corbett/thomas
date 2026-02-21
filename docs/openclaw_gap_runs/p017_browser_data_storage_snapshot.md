# P017 — Browser data storage snapshot

This adds a **browser data storage snapshot** operation to Thomas.

A _data storage snapshot_ is a point-in-time archive of the browser’s **persisted profile data** (cookies, local storage, IndexedDB files, caches, etc.) as stored on disk. The output is a **ZIP archive** that can be saved, moved, or restored elsewhere.

## CLI

The command is registered under the `browser` command group:

```bash
thomas browser data-storage-snapshot --data-dir /path/to/browser-data -o snapshot.zip
```

### Options

- `--data-dir PATH`  
  Directory to snapshot. If omitted, Thomas attempts to resolve it from config/env.
- `--profile NAME`  
  Optional profile name used during resolution.
- `--output, -o PATH`  
  Where to write the `.zip` file. If the path is an existing directory, a timestamped name is used.
- `--overwrite`  
  Overwrite an existing output file.
- `--compress-level N`  
  ZIP deflate compression level (0–9).  
  - `0` = store (no compression)
  - `6` = default balance (recommended)
  - `9` = smallest output (slowest)
- `--strict/--no-strict`  
  Strict mode fails on the first unreadable file. Non-strict mode skips unreadable files and reports them.
- `--hash/--no-hash`  
  Compute SHA-256 for the archive (default: on).
- `--json`  
  Machine-readable output to stdout.
- `--schema`  
  Print JSON input/output schema for automation.

### JSON output

Success output example:

```json
{
  "ok": true,
  "data_dir": "/tmp/profile",
  "snapshot_path": "/tmp/snapshot.zip",
  "format": "zip",
  "bytes_written": 12345,
  "file_count": 42,
  "skipped_files": [],
  "sha256": "…",
  "created_at": "2026-02-20T00:00:00+00:00",
  "manifest_path_in_archive": "thomas_browser_data_storage_snapshot_manifest.json"
}
```

Failure output example:

```json
{
  "ok": false,
  "error": {
    "code": "missing_config",
    "message": "Browser data directory could not be resolved. Provide --data-dir or configure THOMAS_BROWSER_DATA_DIR.",
    "details": {
      "attempted_paths": ["…"]
    }
  }
}
```

## Tool schema

This prompt also defines JSON schemas for automation:

- `TOOL_INPUT_SCHEMA`
- `TOOL_OUTPUT_SCHEMA`

They live in `thomas/browser/p017_browser_data_storage_snapshot.py`.

Suggested test commands:
python -m pytest -q tests/prompt_pack/test_p017_browser_data_storage_snapshot.py
python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Risk list:
- CLI discovery integration is inferred; if the codebase uses a different registration convention than `register()`/package-level `app`/`add_subparser()`, the command might not be discoverable.
- Browser data-dir resolution is heuristic across env/config/default paths; if Thomas stores this setting under different keys/locations, users may need to pass `--data-dir` explicitly.
- Snapshotting an in-use browser profile can hit OS-level file access issues (especially on Windows); strict mode (default) will fail fast—use `--no-strict` to skip unreadable files.

Risk list:
- Compression defaults to level 6 (balanced). For “smallest possible zip”, use `--compress-level 9` (slower).
- If the browser is actively writing to its profile, strict mode may still fail (by design); `--no-strict` trades completeness for robustness.
- Some platforms (notably Windows) can block `os.replace` when the destination zip is open in another program, yielding a deterministic `external_failure`.
