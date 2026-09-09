# Thomas Autonomy Engine

A production-grade background job engine for Thomas:

- **Job Queue**: SQLite-backed, migration-safe schema, WAL mode, row-locking via optimistic updates.
- **Scheduling**: once / interval / daily / weekly schedules.
- **Retry Policy**: exponential backoff + jitter; transient error detection.
- **Dead Letter Handling**: jobs exceeding max attempts end in `dead` with error trace.
- **Approvals**: policy-driven approvals by risk class; pending approvals appear in UI and API.
- **Audit Trail**: every major event persisted (job lifecycle, approvals, engine start/stop, errors).
- **UI**: `/autonomy.html` page to create jobs, inspect queue, approve/deny, view audit.

## Safety model

*Default policy*:
- low: allow
- medium: require approval
- high: deny
- critical: deny

Override policy via `autonomy_policy.toml` next to the DB (default: `runtime/.thomas/autonomy/autonomy_policy.toml`).

## Integration
See `INTEGRATION_REPORT.md` in the patch zip.


## Planner/Executor/Reviewer

The engine includes a built-in `autonomy_task` job kind:

- Planner: calls Thomas `/api/chat` (via `ChatAdapter`) and demands a strict JSON plan.
- Reviewer: deterministic checks; flags risky kinds.
- Executor: enqueues each plan action as a child job (which then flows through policy + approvals + audit).

For each planned action:
- if policy mode is **approve**, the child job is created in `awaiting_approval` and an approval row is created immediately
- if policy mode is **deny**, the action is skipped (recorded in the parent job result) and will not run
