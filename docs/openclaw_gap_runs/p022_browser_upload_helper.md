# P022 – Browser upload helper

This gap-run implements a **browser upload staging helper** inside the Thomas codebase.

## Why this exists

Automated browser sessions often run inside a controlled runtime (container, sandbox, or a shared workspace). Uploading a local file to a website requires that the browser runtime can *see* the file path you provide.

This helper makes that reliable by:

- Validating the local source file
- Copying it into a configured “browser upload” directory
- Returning a structured result (and deterministic errors) for automation

## Core API

Python module:

- `thomas.browser.p022_browser_upload_helper`

Key types:

- `BrowserUploadRequest`
- `BrowserUploadResult`

Key function:

- `stage_file_for_browser(request) -> BrowserUploadResult`

### Configuration resolution

If `destination_dir` is not provided, the helper resolves it in this order:

1. `THOMAS_BROWSER_UPLOAD_DIR` (preferred)
2. `THOMAS_BROWSER_UPLOAD_ROOT`
3. `THOMAS_WORKSPACE` / `THOMAS_PROJECT_ROOT` / `THOMAS_HOME` with a `browser_uploads/` suffix
4. Best-effort: constants/zero-arg helpers exposed by `thomas.cli.live_browser` or `thomas.tools.browser`

If none are available, it raises `BrowserUploadMissingConfigError` with code `missing_upload_directory`.

## CLI

Command module:

- `thomas.cli.commands.browser.p022_browser_upload_helper`

Standalone usage:

```bash
python -m thomas.cli.commands.browser.p022_browser_upload_helper ./report.pdf --dest ./browser_uploads
```

JSON output for automation:

```bash
python -m thomas.cli.commands.browser.p022_browser_upload_helper ./report.pdf --dest ./browser_uploads --json
```

Schema (for tooling):

```bash
python -m thomas.cli.commands.browser.p022_browser_upload_helper --schema
```

Safer writes (optional):

```bash
python -m thomas.cli.commands.browser.p022_browser_upload_helper ./report.pdf --dest ./browser_uploads --fsync
```

## Error codes

Errors are raised as `BrowserUploadHelperError` subclasses and include a stable `code`:

- `missing_source`
- `source_not_found`
- `source_not_file`
- `invalid_destination_name`
- `missing_upload_directory`
- `destination_not_directory`
- `destination_is_directory`
- `destination_exists`
- `mkdir_failed`
- `copy_failed`
- `file_too_large`
