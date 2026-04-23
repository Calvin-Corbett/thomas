# Thomas Library

This folder stores durable external knowledge for research-heavy tasks.

- `catalog.json`: machine index of entries
- `INDEX.md`: human table of contents
- `entries/<category>/*.md`: categorized entry files

The library is intentionally separate from short-term memory.
Use it for long references (papers, docs, findings) that should not bloat
every chat turn.

CLI:
- `thomas library where`
- `thomas library list --query "..." --limit 25`
- `thomas library add --title "..." --category research --source "..." --content-file notes.md`
- `thomas library show <entry_id>`
- `thomas library reindex`

