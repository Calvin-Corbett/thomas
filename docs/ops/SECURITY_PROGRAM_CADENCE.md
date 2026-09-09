# Security Program Cadence

This file defines recurring security maturity checks and drill cadence.

## Weekly controls

1. Dependency policy check:

```bash
python scripts/dependency_policy_check.py --json --strict
```

2. Threat-model cadence check:

```bash
python scripts/threat_model_cadence_check.py --path docs/THREAT_MODEL_WEB_API.md --max-age-days 30 --json --strict
```

3. Incident drill (artifact + command verification):

```bash
python scripts/security_incident_drill.py --repo-root . --json
```

## Expected outcomes

1. No dependency policy errors.
2. Threat model reviewed within cadence window.
3. Drill report returns `ok=true` with all required steps passing.

## Escalation

1. Any dependency-policy error blocks release.
2. Stale threat model blocks security sign-off.
3. Incident drill failure requires remediation and rerun before release cut.
