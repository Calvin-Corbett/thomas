# Thomas Extension Standard

Last reviewed: 2026-06-11.
Status: **binding** for all new and official extensions. Existing
`pack-*` inventory is grandfathered until regenerated.

Every item in the Thomas marketplace has a **type**, and every type has a
ruleset. If a module doesn't meet its type's ruleset, it doesn't ship.
The validator enforces this mechanically:

```bash
python scripts/validate_extension.py --all          # whole catalog
python scripts/validate_extension.py inkwell        # one plugin
python scripts/validate_extension.py inkwell --strict   # official-grade
```

## The four marketplace types

Declared via `marketplace_type` in `manifest.json`
(see `thomas/server/desktop_plugins_manifest.py`). The workspace type was
renamed `command_center` → `app` on 2026-06-11; the legacy value is still
accepted everywhere and normalizes to `app` on read:

| Type | What it is | Example |
|---|---|---|
| `app` | A full workspace with its own screen (legacy name: `command_center`, still accepted) | Life Manager, Inkwell |
| `plugin` | Behavior that hooks into Thomas runs | alert/triage packs |
| `dependency` | A foundation other packs require; no UI | life-manager-foundation |
| `integration` | A bridge to an external service | Discord/Slack/email packs |

## Rules for every type (the common law)

1. **Manifest is the contract.** `manifest.json` must parse under
   `load_desktop_plugin_manifest_from_data` (for desktop plugins) or the
   catalog loader, with: `id`/`plugin_id`, `name`/`display_name`,
   `version`, `kind`, `marketplace_type`, `description`, `entrypoint`,
   `categories`, `tags`. Files referenced by the manifest must exist and
   must not escape the pack directory.
2. **Local-first state.** Persistent data lives under
   `.thomas/plugin-data/<id>/` in the configured memory root, written
   atomically (temp file + replace). NEVER under `.thomas/plugins/<id>/`
   — that is the installed-plugin directory and is wiped on every
   install/upgrade (data loss). Never inside the repo tree either.
3. **Namespaced API.** Server routes live under `/api/plugins/<id>/...`
   and are gated by `is_plugin_enabled(config, "<id>")` — disabled or
   uninstalled plugins return 404 from their own API.
4. **Degrade, don't die.** If the model, network, or server is missing,
   the module keeps doing whatever doesn't need it, and says so in plain
   English (e.g., Inkwell returns 503 + friendly copy from `/analyze`,
   and its UI falls back to a local draft mode). A module that
   hard-crashes without an API key fails review.
5. **AI through the engine, not around it.** Model calls go through
   `thomas.core.llm_client.LLMClient` with profile resolution
   (`resolve_model_profile_name` → `config.get_model`). No direct
   provider SDKs, no separate keys, no hardcoded model ids. Whatever
   API powers Thomas powers the module.
6. **No magic words.** Module chat/intent surfaces are organic — the
   model interprets, controls are tools. Keyword/command-trigger UX is
   banned (Calvin design law, 2026-06-07).
7. **Tests ship with the module.** Minimum: manifest/catalog consistency,
   route CRUD round-trip, disabled-plugin 404, and parsing/normalization
   fuzz for anything that reads model output.
8. **No secrets in the pack.** Credentials come from the environment or
   the secrets store. The leak-guard applies to extensions like
   everything else.
9. **Catalog row matches manifest.** `extensions/catalog.json` entry and
   `manifest.json` must agree on id, version, mode, and marketplace_type.

## Per-type rulesets

### `app` (workspaces)
- Must declare `surface.entry_html` (a real file inside the pack),
  `surface.title`, and `surface_mode`.
- `left_nav_behavior: "workspace"`, `default_nav_section: "apps"`,
  and a `default_nav_order`.
- **Must be standalone-capable** (see below): the surface must work as
  the whole app — it cannot assume Thomas chrome exists around it.
- Web assets are plain files under the pack (served via
  `/plugins/<id>/...`); no build step required at install time.

### `plugin`
- `entrypoint` (`hooks.py`) must expose the hook contract it claims
  (`before_tool` / `after_tool` today), accept a dict, return a dict,
  and never raise on empty payloads.
- No UI surface required; if one exists, app surface rules apply to it.

### `dependency`
- No UI surface, no nav presence (`left_nav_behavior: "none"`).
- Must list nothing in `requires` (dependencies don't have
  dependencies) and be safe to install alone.

### `integration`
- All egress goes through the canonical guards
  (`thomas/tools/url_safety.py` for outbound URLs).
- Credentials per common-law rule 8; a missing credential degrades per
  rule 4 (clear "connect your X account" copy, not a stack trace).

## The standalone principle (Thomas as engine)

**Every app module must be openable as its own window.** Two doors,
same module:

- **Through Thomas** — the module appears in the left nav as a
  workspace, full Thomas chrome, normal flow.
- **Standalone** — `GET /app/<plugin-id>` opens the module's surface
  directly, with no Thomas nav, no chat, nothing else. A desktop
  shortcut (generated by `scripts/standalone_shortcut.py <plugin-id>`)
  opens it in an app-style window. Thomas runs underneath as the
  engine; the user just sees their app.

Requirements this puts on an app module:

1. The surface owns its whole viewport (no dependence on Thomas layout,
   navigation, or globals).
2. The standalone entry route appends `?standalone=1` — the surface MAY
   read it to hide "back to Thomas" affordances, but must not require it.
3. Declare it in the manifest (informational; validator warns when
   missing on app modules):

```json
"standalone": { "enabled": true, "window_title": "Inkwell" }
```

4. The module's API must be the only contact surface with the engine,
   so the same page works in both doors unchanged.

`/app/<id>` behavior (implemented in
`thomas/server/routes/standalone_app_aiohttp.py`):
- installed + enabled + has surface → redirect to the surface entry
  with `?standalone=1`
- not installed / disabled / no surface → friendly plain-English HTML
  page that says what to do (not a JSON error), because the person
  double-clicking a desktop shortcut may never have seen Thomas.

## Review checklist (what "done" means for a module)

- [ ] `python scripts/validate_extension.py <id> --strict` passes
- [ ] Module tests green; neighboring marketplace suites green
- [ ] Verified live in a browser (app modules: both doors)
- [ ] Degradation paths exercised (no model, server down, disabled)
- [ ] Catalog row added; docs/README inside the pack explain storage
      and API in plain English
