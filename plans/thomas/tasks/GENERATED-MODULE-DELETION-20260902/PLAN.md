# PLAN for GENERATED-MODULE-DELETION-20260902

- Owner: codex-cleanup
- Status: in_progress
- Updated At: 2026-09-02T02:24:00+00:00
- Scope: 119 audited burst-generated modules and their re-export shims/module-only tests; CHANGELOG.md; focused deletion guard

## Summary

Remove the 119 marketplace modules that were generated in the 2026-03-23 burst,
disabled from tool registration by `8d0501ac`, and never invoked in the audited
202 MB usage corpus. Preserve all wired, independently developed, or protected
modules.

## Approach

- Re-verify the recovered manifest against live HEAD, current importers,
  focused history, feature-registry rows, and protected-file policy.
- Preserve the 13 wired survivors plus `app_provisioning`, `companion`,
  `investigation`, and protected `approvals`, `gateway`, and `watcher`.
- Delete one coherent module group at a time, capped at 45 tracked deletions so
  each commit remains below the 50-file bulk guard after its changelog entry.
- Run deletion/reference gates, architecture, focused tests, and boot proof per
  group; commit only through `scripts/crew/brief/commit.py`.
- Add a no-resurrection test after all 119 paths are absent. Prepare permanent
  graveyard records from the landed SHAs, but do not modify the protected
  graveyard without the separately confirmed owner-authorized path.

## Deferred protected-contract repairs

- `db_internals` is audited for deletion but temporarily retained. Removing it
  makes `tests/test_architecture.py::test_health_annotations` fail because the
  protected `thomas/_architecture.py` marketplace debt annotation still names
  `db_internals/query_parser.py exceeds 890 lines`. Do not bypass or edit that
  protected contract in an ordinary cleanup batch. Aggregate this exact stale
  fragment into the owner-authorized breakglass repair, then delete the module,
  re-export shim, and six module-only `tests/test_db_*.py` files in a governed
  follow-up batch.
- `doc_processing` is likewise audited but temporarily retained because the
  same protected marketplace debt annotation names
  `doc_processing/extraction.py exceeds 801 lines`. Aggregate that fragment in
  the same owner-authorized repair, then delete the module, re-export shim, and
  six module-only `tests/test_docproc_*.py` files in the governed follow-up.
