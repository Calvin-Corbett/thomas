# Evidence Pack Runbook

Use this when you need proof-by-default output for local checks.

Command:

```powershell
python scripts/evidence_pack.py --name "quick-gate-proof" `
  --command "python scripts/auto_checks.py --quick" `
  --command "python -m pytest -q tests/test_ci_workflow_guards.py" `
  --json
```

What it writes:
- `artifacts/evidence/<timestamp>-<name>/summary.json`
- `artifacts/evidence/<timestamp>-<name>/SUMMARY.md`
- per-step logs:
  - `steps/001/stdout.txt`
  - `steps/001/stderr.txt`
  - `steps/001/step.json`

Behavior:
- exits `0` only when all commands pass
- exits non-zero on first failure by default
- add `--continue-on-fail` to run every command and collect full evidence
