# Root Doc Archive Index

This file is the canonical archive map for root-level summary/report documents that are not part of the active operational doc set.

- generated_at_utc: `2026-02-25T17:24:18+00:00`
- source_inventory: `docs/ops/repo_orphan_inventory.json`
- scope: tracked root files currently classified as `tracked_root_sprawl`

## Active Doc Index (Canonical)

These are the primary operational docs to use first.

- `README.md`
- `PROJECT_INDEX.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `ONBOARDING.md`
- `KNOWN_ISSUES.md`
- `docs/ops/repo_hygiene.md`
- `docs/REPO_STRUCTURE_PROTOCOL.md`
- `plans/thomas/WORKBOARD.md`

## Root Archive Map

| Root Path | Decision | Target |
| --- | --- | --- |
| `AUDIO_ENGINE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `AUTONOMOUS_VEHICLES_README.txt` | archive | `docs/archive/root-summaries/` |
| `BLOCKCHAIN_IMPLEMENTATION.md` | archive | `docs/archive/root-summaries/` |
| `BUILD_REPORT.md` | archive | `docs/archive/root-summaries/` |
| `CODEX_PROMPT_ROBOT_PORTAL.md` | archive | `docs/archive/root-summaries/` |
| `COLUMNAR_MODULE.md` | archive | `docs/archive/root-summaries/` |
| `COMPILER_INFRA_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `COMPLETION_REPORT.md` | archive | `docs/archive/root-summaries/` |
| `CQRS_MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `DSL_MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `IMPLEMENTATION_SUMMARY.txt` | archive | `docs/archive/root-summaries/` |
| `KVSTORE_ARCHITECTURE.md` | archive | `docs/archive/root-summaries/` |
| `LOGGING_FRAMEWORK_INDEX.md` | archive | `docs/archive/root-summaries/` |
| `LOGGING_FRAMEWORK_SUMMARY.txt` | archive | `docs/archive/root-summaries/` |
| `MANIFEST.in` | review | `scripts/packaging/` or archive if unused |
| `MODULE_INDEX.txt` | archive | `docs/archive/root-summaries/` |
| `MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `MODULE_VERIFICATION.txt` | archive | `docs/archive/root-summaries/` |
| `PIPELINE_FRAMEWORK_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `QUICK_START.md` | consolidate | merge into `README.md` and archive source |
| `RECOMMENDER_MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `SIMULATION_MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `SMART_HOME_README.md` | archive | `docs/archive/root-summaries/` |
| `SOCIAL_PLATFORM_README.md` | archive | `docs/archive/root-summaries/` |
| `STRUCTURE.md` | consolidate | `PROJECT_INDEX.md` |
| `TELECOM_MODULE_SUMMARY.md` | archive | `docs/archive/root-summaries/` |
| `THOMAS_BUILD_SUMMARY.txt` | archive | `docs/archive/root-summaries/` |
| `THOMAS_EVENT_BUS_README.md` | archive | `docs/archive/root-summaries/` |
| `VERIFICATION.txt` | archive | `docs/archive/root-summaries/` |
| `install.cmd` | review | keep root launcher or move to `scripts/install/` |
| `install.sh` | review | keep root launcher or move to `scripts/install/` |
| `large_files.txt` | archive | `docs/archive/root-summaries/` |

## Archive Protocol

1. Move `archive` rows to `docs/archive/root-summaries/`.
2. Replace moved files with one-line pointer stubs only if external references require compatibility.
3. For `consolidate` rows, merge useful content into the listed target before archiving source files.
4. Re-run:
   - `python scripts/repo_orphan_inventory.py --write --json`
   - `python scripts/check_repo_hygiene.py --no-require-clean-worktree --json`
