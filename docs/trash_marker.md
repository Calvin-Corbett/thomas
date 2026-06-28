# Thomas Trash and Private Markers

This document defines the marker comments referenced by the
[Thomas Bible](THOMAS_BIBLE.md).
Use these markers when a file must stay in the tree temporarily, but agents
need to know its status without relying on memory or stale STATUS files.

Current status: this file is the checked-in convention source. Public publish
marker parsing lives in `scripts/forge/publish/private_markers.py` and is used
by `scripts/forge/publish/preflight.py` and
`scripts/forge/publish/snapshot.py`; keep those checks aligned with the exact
marker names and required fields below.

## THOMAS_TRASH

Use `THOMAS_TRASH` when a file is intentionally retired but cannot be deleted
in the same change.

Required fields:

- `THOMAS_TRASH`
- `delete-after: YYYY-MM-DD`
- `reason: <short reason>`
- `owner: <agent or human>`

Preferred format in Python:

```python
# THOMAS_TRASH delete-after: 2026-07-02
# reason: Superseded by thomas/new_path.py; kept temporarily for migration.
# owner: codex-upgrade-worker
```

Preferred format in Markdown or text:

```text
THOMAS_TRASH delete-after: 2026-07-02
reason: Superseded by docs/new_doc.md; kept temporarily for inbound links.
owner: codex-upgrade-worker
```

Rules:

- Do not use `THOMAS_TRASH` for code that still runs on the primary path.
- Remove imports, registrations, and live route references before marking a file.
- Mention the retirement in the relevant Bible section.
- Delete the file after the `delete-after` date once verification confirms no live callers remain.

## THOMAS_PRIVATE

Use `THOMAS_PRIVATE` when a file must remain local/private and should not be
included in public release snapshots.

Required fields:

- `THOMAS_PRIVATE`
- `reason: <short reason>`
- `owner: <agent or human>`

Preferred format:

```text
THOMAS_PRIVATE
reason: Local deployment notes; not part of the public baseline.
owner: Calvin
```

Preferred format in Python:

```python
# THOMAS_PRIVATE
# reason: Local deployment notes; not part of the public baseline.
# owner: codex-upgrade-worker
```

Preferred format in JavaScript:

```javascript
// THOMAS_PRIVATE
// reason: Local deployment notes; not part of the public baseline.
// owner: codex-upgrade-worker
```

Preferred format in CSS:

```css
/* THOMAS_PRIVATE */
/* reason: Local deployment notes; not part of the public baseline. */
/* owner: codex-upgrade-worker */
```

Preferred format in HTML:

```html
<!-- THOMAS_PRIVATE -->
<!-- reason: Local deployment notes; not part of the public baseline. -->
<!-- owner: codex-upgrade-worker -->
```

Rules:

- Use the narrowest file-level marker possible.
- Do not mark broad directories private when a single file marker is enough.
- Prefer removing or redacting private content over keeping it indefinitely.
- If a Bible section references the private file, describe the public behavior without copying private details.
- Public publish preflight rejects tracked files containing a line that is exactly `THOMAS_PRIVATE`, `# THOMAS_PRIVATE`, `// THOMAS_PRIVATE`, `/* THOMAS_PRIVATE */`, or `<!-- THOMAS_PRIVATE -->`.
- Public snapshot generation strips files containing a line that is exactly `THOMAS_PRIVATE`, `# THOMAS_PRIVATE`, `// THOMAS_PRIVATE`, `/* THOMAS_PRIVATE */`, or `<!-- THOMAS_PRIVATE -->`.

## Agent Workflow

Before adding either marker:

1. Verify the live code path or release path that makes the marker necessary.
2. Use an exact `YYYY-MM-DD` date for `delete-after`.
3. Keep the reason specific enough for the next agent to re-check quickly.
4. Update the relevant Bible section when the marker changes operational truth.
