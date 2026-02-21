# P009 — Browser artifact screenshot

## Goal

Add a Thomas-native capability to produce a **PNG screenshot** from a saved **browser artifact** (HTML/PDF/image/etc) without requiring a live interactive browser session.

This is meant to be automation-friendly and deterministic: invalid input, missing configuration, and rendering failures are reported with stable error codes.

## What shipped

- Programmatic API:
  - `thomas.browser.p009_browser_artifact_screenshot.take_artifact_screenshot()`
  - Typed request/response dataclasses:
    - `BrowserArtifactScreenshotRequest`
    - `BrowserArtifactScreenshotResult`
  - Deterministic error:
    - `BrowserArtifactScreenshotError` with `BrowserArtifactScreenshotErrorCode`

- CLI:
  - `thomas browser artifact screenshot ...`
  - Supports `--json` for machine-readable automation output.

## Rendering strategy

- **Images** (`.png/.jpg/.jpeg/.webp/...`) are converted to **PNG** using Pillow (renderer=`pillow`).
- **PDFs** are rendered using PyMuPDF (renderer=`pymupdf`).
- **Other artifacts** (HTML, etc.) are rendered using Playwright/Chromium (renderer=`playwright`).

If the required renderer dependency cannot be imported, the operation fails with `MISSING_CONFIG`.

## CLI usage

```bash
thomas browser artifact screenshot <artifact> \
  [--out PATH] \
  [--artifact-root DIR] \
  [--full-page/--viewport-only] \
  [--width N] [--height N] \
  [--wait-ms N] [--timeout-ms N] \
  [--json]
```

### Examples

Screenshot a direct artifact file:

```bash
thomas browser artifact screenshot ./runs/123/artifacts/page.html --out page.png
```

Screenshot by artifact id relative to an artifact root:

```bash
thomas browser artifact screenshot page.html --artifact-root ./runs/123/artifacts --out page.png
```

Machine-readable output:

```bash
thomas browser artifact screenshot page.html --artifact-root ./runs/123/artifacts --json
```

## Output contract

Success (`--json`):

```json
{"ok": true, "artifact_path": "...", "renderer": "playwright|pymupdf|pillow", "screenshot_path": "..."}
```

Failure (`--json`):

```json
{"ok": false, "error": {"code": "INVALID_INPUT|MISSING_CONFIG|EXTERNAL_FAILURE", "message": "...", "details": {}}}
```

## Notes

- Output is always a **PNG**; the CLI rejects output paths that don’t end in `.png` for predictability.
- When resolving an artifact id via `--artifact-root`, paths are prevented from escaping the root directory via `..` traversal.
