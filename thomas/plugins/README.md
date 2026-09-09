# Thomas Plugin System

Last reviewed: 2026-05-29.

Thomas has one canonical Python plugin package: `thomas/plugins/`.

Do not add new plugin runtime code under repo-root `plugins/`, repo-root
`cli/`, or repo-root `prompt_pack/`. Those roots were retired because they
duplicated the active package and made agents guess which copy mattered.

## Runtime Surfaces

`thomas/plugins/` is the in-process Python plugin package. It owns plugin
registry models, hook contracts, lifecycle helpers, diagnostics, certification,
and catalog validation.

`thomas/cli/commands/plugins/` is the CLI adapter layer. CLI files should stay
thin and call implementation code from `thomas/plugins/`.

`extensions/` contains bundled marketplace extension packs. These are custom
Thomas packs with `manifest.json`, `hooks.py`, and `README.md`; they are loaded
through `thomas.plugins.extension_catalog_runtime` and served by marketplace
routes. They are not the same thing as Python plugin modules.

`thomas/server/plugins_registry/plugins/` contains hosted desktop-plugin
manifests and bundle payloads used by the plugin-store API. Runtime bundles may
be generated or installed into the user data directory.

`skills/` and `thomas/skills/` are skill runtimes, not plugins. They can be
used by agents, but they should not be wired through the plugin registry unless
an explicit adapter is being built.

## Adding A Python Plugin

1. Put implementation code in `thomas/plugins/`.
2. Add a thin CLI wrapper under `thomas/cli/commands/plugins/` only if users
   need a command.
3. Put tests under `tests/prompt_pack/` for prompt-pack parity behavior or
   `tests/test_plugin_*.py` for package-level behavior.
4. If it affects marketplace extension packs, update `extensions/catalog.json`
   and run `python scripts/export_site_marketplace_snapshot.py`.

## Adding An Extension Pack

1. Add a directory under `extensions/<pack-id>/`.
2. Include `manifest.json`, `hooks.py`, and `README.md`.
3. Add the pack to `extensions/catalog.json`.
4. Validate with `python -m pytest tests/test_extension_catalog_runtime.py`.

## Verification

Useful focused checks:

```powershell
python -m pytest tests/test_plugin_catalog_index.py tests/test_extension_catalog_runtime.py -q
python -m pytest tests/prompt_pack/test_p105_plugin_registry_core_model.py tests/prompt_pack/test_p121_plugin_list_command_runtime_backed.py -q
```
