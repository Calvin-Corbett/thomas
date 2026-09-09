# Thomas Extensions

Last reviewed: 2026-06-11.

**Building or reviewing a module? Read `docs/EXTENSION_STANDARD.md` first.**
It is the binding ruleset: per-type requirements (app / plugin /
dependency / integration), the standalone principle (every workspace module
must open as its own app via `/app/<id>`), and the validator
(`python scripts/validate_extension.py <id> --strict`).

The directories in `extensions/` are custom Thomas marketplace extension packs.
They are not third-party packages copied from an external marketplace.

The active extension feature is:

- `extensions/catalog.json` lists available bundled packs.
- `extensions/<pack-id>/manifest.json` describes each pack.
- `extensions/<pack-id>/hooks.py` provides hook behavior.
- `thomas.plugins.extension_catalog_runtime` loads and validates the catalog.
- `thomas.server.routes.marketplace_catalog_aiohttp` exposes packs through the
  marketplace and install routes.
- `scripts/export_site_marketplace_snapshot.py` exports the catalog into the
  public site snapshot.

The `pack-*-*-*` families are repetitive by design. Their catalog timestamp is
`2026-02-21T00:00:00Z`, which means they are old, but they still back the
current bundled marketplace extension path. Do not delete them unless the
catalog, site snapshot, and tests are updated in the same change.

## Generator Option

A generator is not a different runtime extension system. It is a maintenance
tool for repetitive packs.

The current source of truth is the checked-in pack directories plus
`extensions/catalog.json`. If these packs keep growing, the cleaner model is:

1. Store a small matrix of categories, targets, and modes.
2. Generate `manifest.json`, `hooks.py`, `README.md`, and catalog rows from
   that matrix.
3. Commit generated output only if the runtime still expects concrete pack
   directories.

That would make the extension catalog easier to audit without changing how
Thomas loads extensions at runtime.
