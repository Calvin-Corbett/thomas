# Module: plugins

| Field            | Value                                                     |
|------------------|-----------------------------------------------------------|
| Status           | functional core install/hook system, extras partial        |
| Last assessed    | 2026-04-24                                                |
| Used in prod     | yes, local install/enable/disable/uninstall works          |
| Has real tests   | partial                                                   |
| Blocking issues  | several generated helper files need individual verification |

## What This Is

The plugin and extension runtime for Thomas. It handles plugin packaging,
manifest validation, discovery, install, uninstall, enable/disable, hooks,
tool injection, config validation, diagnostics, and CLI commands.

The marketplace UI and install routes live in `thomas/server/`
(`marketplace_catalog_aiohttp.py`, `plugin_hosting.py`, and desktop plugin
facades). This module is the underlying plugin runtime.

## What Actually Works

- **Plugin packaging** (`p097_plugin_package_bootstrap.py`): bundle creation.
- **Manifest validation** (`p098_plugin_manifest_schema.py`): schema checking.
- **Install/uninstall** (`p102`, `p103`): local install from path and cleanup.
- **Enable/disable** (`p101`): state store for toggling plugins.
- **Hook system** (`p107` through `p112`): before/after model, before/after
  tool, and after-response hooks.
- **Extension catalog** (`extension_catalog_runtime.py`): loads and validates
  extension pack catalogs from disk.
- **Desktop plugin facade** (`thomas/server/desktop_plugins*.py`): install,
  enable, and uninstall from the web UI.
- **Life Manager plugin** (`extensions/life-manager/`): first real installable
  plugin with tasks, agenda, habits, and goals.

## What Is Placeholder Or Needs Verification

- `github_marketplace.py`: placeholder for remote catalog work.
- `platform_scanner.py`: placeholder for platform/integration scanning.
- `external_skill_adapter.py`: placeholder for adapting external skills.
- Several numbered `p*` files have real code but need focused tests before
  they should be considered stable.

## Known Gaps

- Conversational install is not fully implemented.
- Remote catalog sync is not part of the public local-first release.
- Category filtering in the marketplace UI needs verification.

## Do Not Touch Without A Focused Refactor

- `extension_catalog_runtime.py`: stable catalog loader.
- `desktop_plugins.py` in `thomas/server/`: facade only; edit the split
  manifest/runtime files for implementation changes.
