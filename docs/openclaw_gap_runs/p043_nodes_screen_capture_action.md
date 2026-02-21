# P043 — Nodes screen capture action

This document describes the **Thomas-native** implementation of the *nodes screen capture* capability.

## What it does

The action requests a screenshot from a target **node** and returns:

- a file path where the screenshot was written (optional), and/or
- the screenshot bytes as a **base64** string (optional; intended for automation).

The action is implemented as a transport-agnostic node operation (so it can be wired to HTTP, an in-process node client, or test doubles).

## Contracts

### Input

`NodesScreenCaptureRequest` (validated via `parse_nodes_screen_capture_request`):

| Field | Type | Required | Default | Notes |
|------|------|----------|---------|-------|
| `node_id` | `str` | ✅ | — | Non-empty node identifier |
| `image_format` | `str` | ❌ | `png` | One of `png`, `jpg`, `jpeg`, `webp` |
| `save_path` | `str\|None` | ❌ | `None` | File path (or directory) to write the screenshot |
| `include_image_b64` | `bool` | ❌ | `False` | Include base64 image bytes in output |
| `timeout_s` | `float` | ❌ | `30.0` | Timeout for the capture request |

Notes:

- If `save_path` is a file path **without an extension**, the extension is appended based on `image_format`.
- If `save_path` is a directory (or ends with `/`), a filename is inferred and the screenshot is written inside that directory.

### Output

`NodesScreenCaptureResult`:

| Field | Type | Notes |
|------|------|-------|
| `node_id` | `str` | Target node |
| `image_format` | `str` | Format used |
| `captured_at` | ISO-8601 string | UTC timestamp |
| `bytes_captured` | `int` | Size of returned image |
| `saved_path` | `str\|None` | Where the file was written (if requested) |
| `image_b64` | `str\|None` | Base64 image bytes (only when `include_image_b64=True`) |

## CLI usage

A CLI command is provided under the `nodes` command group:

```bash
thomas nodes screen-capture <node_id> --out ./shot.png
```

Machine-readable output:

```bash
thomas nodes screen-capture <node_id> --json --out ./shot.png
```

Include inline base64 (useful when you don't want to write a file):

```bash
thomas nodes screen-capture <node_id> --json --include-image
```

## Error behavior

Errors are deterministic and machine-readable:

- `NodesScreenCaptureInputError` (`code="invalid_input"`) — invalid request parameters
- `NodesScreenCaptureConfigError` (`code="missing_config"`) — required node configuration missing
- `NodesScreenCaptureExternalError` (`code="external_failure"`) — node/transport failed to capture or write

In `--json` mode, errors are emitted as:

```json
{"ok": false, "error": {"code": "...", "message": "..."}}
```

## Transport

The default transport is `HttpScreenCaptureTransport`, which calls:

- `POST {base_url}/nodes/{node_id}/screen-capture` with JSON body `{"image_format": "png"}`

Configuration sources:

- `nodes_base_url` (or `THOMAS_NODES_BASE_URL`)
- `nodes_api_key` (or `THOMAS_NODES_API_KEY`) optional

Optional configuration:

- `nodes_screen_capture_path_template` (or `THOMAS_NODES_SCREEN_CAPTURE_PATH_TEMPLATE`)
- `nodes_screen_capture_method` (or `THOMAS_NODES_SCREEN_CAPTURE_METHOD`) — supports `POST` and `GET`
