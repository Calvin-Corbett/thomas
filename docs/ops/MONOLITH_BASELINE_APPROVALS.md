# Monolith Baseline Approval Policy

This policy controls relaxations in `docs/monolith_guard_baseline.json`.

## Why

Large-file baseline bumps should be explicit and auditable. Without an approval gate,
`max_lines` can drift upward silently and disable the monolith guard over time.

## Gate

CI enforces:

```bash
python scripts/forge/gates/monolith_baseline_approval_gate.py --base <base> --head <head>
```

The gate fails when any of the following are detected in the diff range unless approved:

1. New entry added under `allowed_large_files`.
2. `max_lines` increased for an existing entry.
3. `max_growth_lines` removed.
4. `max_growth_lines` increased (weaker growth cap).

## Approval Registry

Approvals live in:

- `docs/ops/monolith_baseline_approvals.json`

Each approval must include:

1. `id`
2. `path`
3. `change`
4. `new_value` (when applicable)
5. `approved_by`
6. `approved_on`
7. `reason`

The approval must match the exact file/change/value.

## Operating Rule

Default posture is to split large files, not raise caps.
Cap increases are temporary exceptions and should include a follow-up split plan.

