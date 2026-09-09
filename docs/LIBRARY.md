# Library System

The Thomas library stores long-form external knowledge separately from short-term chat memory.

## Why
- Prevent large papers/docs from polluting every prompt.
- Keep research artifacts durable and searchable.
- Inject library context only for relevant routes.

## Layout
- `library/catalog.json` - machine-readable index
- `library/INDEX.md` - human table of contents
- `library/entries/<category>/<id>.md` - categorized source artifacts

## Runtime behavior
- Research-oriented routes can read from library context.
- Optional auto-capture stores research answers as deduped notes.
- Curator runs in the background and promotes high-confidence chat/library
  artifacts into durable memory facts/profile hints.
- Contradictions from promoted memory can be reviewed in the UI Memory tab and
  resolved via API.

Env toggles:
- `THOMAS_LIBRARY_ENABLED=1`
- `THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH=1`
- `THOMAS_MEMORY_CURATOR_ENABLED=1`
- `THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS=180`
- `THOMAS_MEMORY_CURATOR_MAX_EPISODE_SCAN=120`
- `THOMAS_MEMORY_CURATOR_MAX_LIBRARY_SCAN=40`
- `THOMAS_MEMORY_CURATOR_MAX_PROMOTIONS_PER_RUN=120`

## CLI
- `thomas library where`
- `thomas library list --query "..."`
- `thomas library add --title "..." --category research --content-file notes.md`
- `thomas library show <entry_id>`
- `thomas library reindex`
- `thomas library curate [--force]`
