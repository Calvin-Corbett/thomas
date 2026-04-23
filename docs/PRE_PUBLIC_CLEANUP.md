# Pre-Public Cleanup: Competitor References

**Created:** 2026-03-18
**Priority:** BLOCKER — must be completed before the repo goes public
**Owner:** Unassigned

## Problem

The repo contains 538 occurrences of a competitor name ("OpenClaw") across
51 files. This includes direct comparison files, compatibility layers,
competitive research documents, architecture references, and scattered
mentions in scaffold code. None of this should be visible when the repo
goes public.

## Affected Areas

### Must delete entirely:
- `thomas_vs_openclaw_subcommands.json` (168 occurrences, root-level file)
- `thomas/openclaw_compat/` directory (3 files: `__init__.py`, `core.py`, `tools.py`)
- `library/entries/competitive-research/1771907866-openclaw-*.md` (2 files)
- `.tmp_*` files at root (7 temp files with references — should be gitignored anyway)

### Must scrub references from:
- `thomas/_architecture.py` (2 occurrences)
- `apps/site/src/lib/featureComparisonData.ts` (177 occurrences — feature comparison table)
- `apps/site/src/app/globals.css` + `globals_part02.css` (4+4 occurrences)
- `.github/workflows/robustness-gates.yml` (3 occurrences)
- `library/catalog.json` (12 occurrences)
- `library/INDEX.md` (10 occurrences)
- `thomas/server/tool_extensions.py` (1 occurrence)
- `thomas/cli/parity_*.py` files (~5 files — refactor to describe target features generically)
- `thomas/cli/compat_*.py` files (~8 files — check for references)
- Various `thomas/plugins/p*.py` files (1 occurrence each in ~8 files)
- Various `thomas/nodes/p*.py` files (1 occurrence each in ~8 files)
- Various `thomas/messages/p*.py` files (1 occurrence each in ~5 files)
- Gateway route files (2-3 files)
- `module_analysis.csv` (1 occurrence)
- `.dockerignore` (1 occurrence)
- `MODULE_REGISTRY.md` (auto-generated — will be clean after openclaw_compat removed)

### Approach:
1. Delete the files/directories listed under "must delete"
2. For parity/compat files: replace competitor name with generic terms
   like "reference CLI" or "target feature set"
3. For scattered 1-occurrence mentions in scaffold files: remove the line
   or replace with generic description
4. For the website feature comparison: either remove or genericize
5. Re-run `scripts/build_module_registry.py` after cleanup
6. Grep again to verify zero occurrences remain

### What to preserve:
- The parity/compat FUNCTIONALITY matters — just not the naming
- Feature comparison data is useful — just strip the competitor identity
- Architecture notes about compatibility goals — rephrase generically

## Estimated Scope
~4-6 hours of careful find-and-replace plus testing to ensure nothing breaks.
