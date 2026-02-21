# P010 - Browser artifact PDF export (and ZIP bundle)

This adds a **Thomas-native** way to export a saved browser artifact into:

- a single **multi-page PDF**, or
- a **ZIP bundle** containing the PDF (and optionally the original images + a manifest).

The implementation is intentionally deterministic:

- it discovers screenshot images inside an artifact directory (recursively),
- sorts them in stable “natural” order,
- renders one image per page into a PDF,
- and (when requested) packages that PDF into a ZIP bundle with stable timestamps/permissions.

## CLI usage

PDF output:

```bash
thomas browser artifact-pdf-export <artifact_ref> --output out.pdf
```

ZIP output (bundle):

```bash
thomas browser artifact-pdf-export <artifact_ref> --output out.zip --zip
```

Include original images in the ZIP as well:

```bash
thomas browser artifact-pdf-export <artifact_ref> --output out.zip --zip --include-images
```

Where `artifact_ref` can be:

- a **filesystem path** to an artifact directory (or a single image file), or
- an **artifact id**, resolved relative to an artifacts root.

Artifacts root resolution order:

1. `THOMAS_BROWSER_ARTIFACTS_DIR`
2. `THOMAS_ARTIFACTS_DIR`
3. A best-effort default exposed by `thomas.tools.browser` (if available)

## Options

- `--output/-o PATH` - Output `.pdf` or `.zip` path.
- `--overwrite` - Replace the output file if it already exists.
- `--page-size {letter,a4,auto}` - Page sizing mode:
  - `letter` (default): scale/center onto Letter, with auto-orientation per page
  - `a4`: scale/center onto A4, with auto-orientation per page
  - `auto`: page size matches the image dimensions (in points)
- `--format {auto,pdf,zip}` - Output format resolution:
  - `auto` (default): infer from `--output` extension, else defaults to `pdf`
  - `pdf`: force PDF output
  - `zip`: force ZIP output
- `--zip` - Shortcut for `--format zip`
- `--include-images` - When producing a ZIP bundle, include original images under `images/`
- `--artifacts-root PATH` - Override artifacts root for resolving artifact ids.
- `--json` - Emit machine-readable JSON.

## JSON output schema

Success:

```json
{
  "ok": true,
  "output_format": "zip",
  "output_path": "out.zip",
  "zip_path": "out.zip",
  "pdf_name_in_zip": "artifact.pdf",
  "manifest_name_in_zip": "manifest.json",
  "artifact_path": "...",
  "pages": 3,
  "images": 3,
  "image_paths": [".../step_1.png", ".../step_2.png", ".../step_3.png"],
  "sha256": "..."
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "ARTIFACT_NOT_FOUND",
    "message": "Artifact not found: ...",
    "details": {
      "resolved_path": "...",
      "artifacts_root": "..."
    }
  }
}
```

## Error codes

- `INVALID_INPUT`
- `MISSING_CONFIG`
- `ARTIFACT_NOT_FOUND`
- `NO_IMAGES_FOUND`
- `OUTPUT_EXISTS`
- `PDF_RENDER_FAILED`
