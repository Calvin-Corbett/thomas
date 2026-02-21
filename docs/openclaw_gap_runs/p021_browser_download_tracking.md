# P021 - Browser download tracking

This adds **download tracking** as a Thomas-native browser capability.

## What it does

Given a download directory, Thomas will wait for the **next completed download**
to appear and returns:

- file path + file name
- file size in bytes
- SHA-256 checksum
- detection timestamp and total duration

A file is considered “completed” once its **size and modification time** have
remained stable for `stable_checks` consecutive polls.

> In a full browser automation stack you would hook into browser-level download
> events (e.g., Playwright download events). For this prompt-pack task, a portable
> and dependency-free directory watcher is used.

## CLI

`thomas browser download-tracking --download-dir <dir> [--timeout 30] [--poll 0.1] [--stable-checks 2] [--json]`

### Machine-readable output

With `--json`, the command prints a single JSON object to stdout.

Success:

```json
{"ok": true, "result": {"file_path": "...", "file_name": "...", "bytes": 123, "sha256": "...", "detected_at": 0.0, "duration_s": 0.0}}
```

Failure:

```json
{"ok": false, "error": {"code": "BROWSER.DOWNLOAD_TIMEOUT", "message": "..."}}
```

### Schema

`thomas browser download-tracking --schema` prints a JSON-schema-like description
of the `--json` payload.

## Deterministic errors

The implementation raises `DownloadTrackingError` with stable `code` values:

- `BROWSER.DOWNLOAD_DIR_NOT_CONFIGURED`
- `BROWSER.DOWNLOAD_DIR_NOT_FOUND`
- `BROWSER.DOWNLOAD_DIR_NOT_DIRECTORY`
- `BROWSER.DOWNLOAD_DIR_NOT_READABLE`
- `BROWSER.INVALID_TIMEOUT`
- `BROWSER.INVALID_POLL_INTERVAL`
- `BROWSER.INVALID_STABLE_CHECKS`
- `BROWSER.DOWNLOAD_TIMEOUT`
- `BROWSER.DOWNLOAD_STABILIZE_TIMEOUT`
