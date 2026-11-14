# Module: marketplace

| Field            | Value                                                       |
|------------------|-------------------------------------------------------------|
| Status           | mixed — a small wired top level over 19 subpackages          |
| Last assessed    | 2026-09-25                                                   |
| Assessed by      | claude-opus-5 (commerce-engine removal)                      |
| Used in prod     | partially — see "What Is Actually Called" below              |
| Has real tests   | partial — some subpackages tested, top level uneven          |
| Blocking issues  | none identified                                              |

## What This Is

Two unrelated things share this directory name, and confusing them is the
mistake this file exists to prevent:

1. **This Python package** — domain modules under `thomas/marketplace/`.
   Most were generated in the 2026-03-23 burst and are listed in
   `MANIFEST.json` as plugin content.
2. **The marketplace product feature** — the installable-plugin system in
   `extensions/` and the `/api/marketplace/*` routes. It does not live here
   and never depended on the commerce engine removed below.

## What Is Actually Called

Top-level modules with a proven caller:

- `surface_policy.py` — `thomas/server/routes/marketplace_catalog_aiohttp.py`
  imports `classify_marketplace_row` and `row_is_visible`;
  `thomas/cli/pack_bridge.py` imports `family_requires_strict_entrypoint`.
  This is the live catalog-visibility path.
- `publisher.py` — driven by `scripts/publish_marketplace_wave.py`.

Subpackages with proven callers include `observability` (the crew workboard
and several `scripts/` entry points), `security` (`scripts/security_audit.py`,
`scripts/security_incident_drill.py`), plus `autonomy` and `asset_studio`,
each covered by tests.

Ten subpackages register tools at every boot through
`thomas/server/tool_extensions.py`: `paper_trading` by its full
`thomas.marketplace.` path, `asset_studio`, `orchestrator`, `realtime`, `security`, `vision` and `webhooks` through the `thomas.marketplace.` fallback in `_try_import`, and `channels`, `nodes` and `policy` directly, through their backward-compatible bridge packages (`thomas/channels`, `thomas/nodes` and `thomas/policy` add `thomas/marketplace/<name>` to their `__path__`).

`__init__.py` deliberately re-exports nothing, so importing this package is
import-free and cheap.

## What Is Here Without A Caller

- `governed_distribution.py` and `org_inventory.py` — scoped item
  distribution with approval workflow and seat accounting. Both have real
  tests (`tests/test_governed_distribution.py`, `tests/test_org_inventory.py`)
  and `org_inventory` composes `governed_distribution`, but nothing in
  `thomas/`, `scripts/`, or `extensions/` imports either one. Tested is not
  the same as called. They are left in place pending a decision: give them a
  caller, or remove them with their tests.

## What Was Removed (2026-09-25)

The multi-vendor e-commerce engine that occupied this package's top level.
It registered nine `marketplace.*` tools into every boot and could not
complete a single call: `tools.py` imported `VendorManager`, `ListingManager`,
`OrderManager`, `ReviewManager` and `SearchEngine` from sibling modules that
define no such classes, and the import sat above the `try:` in `execute()`,
so every call raised `ImportError` straight out of the tool.

- `vendors.py`, `listings.py`, `orders.py`, `payments.py`, `reviews.py`,
  `search.py`, `recommendations.py`, `analytics.py`, `disputes.py`,
  `tools.py`, `_types.py`, `_exceptions.py` — **REMOVED.**
- Six module-only tests (`tests/test_marketplace_{vendors,listings,orders,`
  `payments,reviews,search}.py`) — **REMOVED.** They exercised nothing else.

Decision D8 in `plans/thomas/PRODUCT_READY_PUSH_2026-07-15.md:128` had already
called for these tools to be "unregistered by default (default: unregister
until real backend exists)". It was recorded on 2026-07-15, still listed as
pending, and the registration outlived it by ten weeks. No backend arrived, so
the modules went with the registration.

`tests/test_marketplace_commerce_engine_is_gone.py` is the ratchet that keeps
it gone. See the `claude-nine-marketplace-tools-that-never-worked` changelog
fragment for the proof of no caller.

## Known Gaps

- The `MANIFEST.json` "do not modify" list covers subpackage directories only;
  it never covered the top-level modules.
- Subpackage test coverage is uneven — several have no test at all.
- `governed_distribution` / `org_inventory` are uncalled (above).

## Do Not Touch

- `surface_policy.py` — a live server route and the CLI pack bridge both read
  it. Changing its classification logic changes what the catalog shows.
- `MANIFEST.json` — the plugin-content registry for the subpackages.
