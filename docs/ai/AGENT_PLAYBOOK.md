# Agent Playbook

This repository uses strict additive-change rules for AI and human contributors.

## Hard Rules

1. Never delete domain scope by assumption.
2. Domain modules are intentional product features, even when skeleton.
3. Do not cause import-time side effects for normal module imports.
4. Generated artifacts are not source of truth.
5. Never bypass failures by shrinking test scope.

## Domain Scope Rule

The following product surfaces are intentional and must remain present:

- `thomas/agriculture`
- `thomas/autonomous_vehicles`
- `thomas/food_tech`
- `thomas/hr_platform`
- `thomas/legal`
- `thomas/quantfin`
- `thomas/real_estate`
- `thomas/supply_chain`
- `thomas/travel`
- `thomas/groupchat`
- `thomas/conversations`
- `thomas/human_loop`
- `thomas/learning`
- `thomas/sandbox`

## Runtime Policy

- Live browser boot uses `thomas/server/web/js/app_runtime_primary.mjs`.
- `thomas/server/web/js/app.js` must not reintroduce joined-runtime or `app_parts`
  fallbacks.
- Source modules under `thomas/server/web/js/src/runtime_modules/` may still
  exist during extraction work, but they are not an alternate boot runtime.
- When a product surface gets replaced, delete or disconnect the legacy route,
  renderer, and demo backend in the same change. Do not keep two data-backed
  marketplace or editor implementations alive at once.
- Marketplace source of truth is the companion contract:
  `/api/companion/v1/app-store` and `/api/companion/v1/modules`.
  Do not reintroduce `/api/plugins/*` demo catalogs.

## Deletion Protocol

Any deletion/rename under `thomas/` or `tests/` requires an explicit record in
`docs/deletions/*.json` with human approval metadata.

Validate locally:

```bash
python scripts/forge/gates/deletions.py --staged-only
```

## Required Local Gates Before PR

```bash
pytest --collect-only -q
python scripts/test_stepup_protocol.py
python scripts/forge/gates/monolith_guard.py
python scripts/forge/gates/feature_registry.py
python scripts/forge/gates/release_hygiene.py
python scripts/forge/gates/deletions.py --staged-only
```
