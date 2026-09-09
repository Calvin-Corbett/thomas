# Focus Program Operating Model

This document operationalizes the ruthless three-bet plan into weekly execution.

## Execution bets

1. Setup-to-success engine.
2. Trust/governance/safety core.
3. Reliability under burst and duration.

## Workstream to outcome mapping

1. Onboarding + recovery rewrite -> activation and retention.
2. Commercial support docs + validators -> support load reduction.
3. Multi-day soak + fault injection -> production reliability proof.
4. Threat modeling cadence + dependency policy + drills -> security maturity.
5. Performance budgets and queue behavior -> predictable operator UX under load.
6. RBAC/approvals/audit -> multi-user governance confidence.
7. Versioned contracts + deprecation policy -> upgrade safety.
8. Stable extension SDK + conformance tests -> ecosystem leverage.
9. Telemetry + interviews + weekly reprioritization -> outcome-driven roadmap.

## Weekly rhythm

1. Monday: KPI review and priority lock.
2. Tuesday: onboarding/support/governance implementation.
3. Wednesday: soak/perf/security drill execution.
4. Thursday: bug burn-down and migration/release safety checks.
5. Friday: outcome review, rollback rehearsal, next-week scope cut.

## Mandatory scorecard

1. Activation: first-run completion, time-to-ready, repair success.
2. Reliability: soak pass status, queue latency percentiles, failure rates.
3. Security: open high-sev count, abuse-case suite pass rate, drill MTTC.
4. Governance: authz/approval coverage, audit completeness.
5. Release: migration pass/rollback pass, required checks health.
6. Ecosystem: extension compatibility pass rate.

## Operational commands

1. Config validation: `python scripts/config_validator.py --json`
2. Soak run: `python scripts/soak_runner.py --command "python -m thomas.cli.main chat \"health\"" --iterations 500 --inject-failure-every 25 --failure-command "python scripts/repair.cmd" --json`
3. Perf probe: `python scripts/perf_probe.py --command "python -m thomas.cli.main chat \"ping\"" --runs 50 --json`
4. Onboarding outcomes: `python scripts/onboarding_outcomes_report.py --days 7 --json` or `thomas onboarding-outcomes --days 7 --json`
5. Weekly focus scorecard: `python scripts/focus_scorecard.py --days 7 --json`
6. Security cadence checks: `python scripts/dependency_policy_check.py --json --strict`, `python scripts/threat_model_cadence_check.py --path docs/THREAT_MODEL_WEB_API.md --max-age-days 30 --json --strict`, `python scripts/security_incident_drill.py --repo-root . --json`

## Scope cut rules

1. Any task without measurable scorecard impact is cut.
2. New parity-only asks are queued behind scorecard regressions.
3. Releases are blocked on unresolved high-severity security findings.
