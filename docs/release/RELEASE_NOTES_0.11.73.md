# Release Notes: v0.11.73

**Date:** 2026-02-23

## Highlights

- **Server decomposition**: Split `app.py` from 3,957 to 1,487 lines by extracting 7 route modules
- **Route wiring**: Converted 3 orphaned FastAPI route modules (spend, goals, search) to aiohttp and registered them
- **Frontend KPI pipeline**: Connected spend and goals data to the module system's KPI cards
- **Test coverage**: Added 54 new route-level tests across 4 test files (runs, search, spend, goals)
- **Architecture enforcement**: All 10 fitness tests pass; CLI security dependency declared

## Breaking Changes

None.

## New API Endpoints

- `/api/spend/*` (7 endpoints) -- cost tracking and spend history
- `/api/goals/*` (6 endpoints) -- goal/OKR management
- `/api/search/*` (12 endpoints) -- FTS5 full-text conversation search, bookmarks, saved searches

## Removed

- `server/routes/replay_debugger.py` -- redundant duplicate of `runs.py`; all replay functionality remains via `/api/runs/*/replay`

## Internal

- Decomposed app.js, components.css, layout.css into ordered split parts
- Extracted mission content hub into separate modules
- Hardened monolith governance (waiver metadata/expiry policy)
- Fixed Unicode corruption in 4 backend files
- Fixed startup bind-retry crash in server
