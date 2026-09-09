# Landed-History Waiver Policy

This policy controls `docs/ops/landed_history_waivers.json`.

## Why

Gates that measure **per commit** cannot be satisfied retroactively. A commit
that already merged cannot be given an approval trailer — its message is
immutable history. Without a waiver path the only ways to get a red range green
are the ones that destroy the gate: raise the threshold, allowlist a path, or
add an environment bypass. A waiver is the narrow, dated, attributed
alternative.

## Registry

Waivers live in:

- `docs/ops/landed_history_waivers.json`

Shape mirrors `docs/ops/monolith_baseline_approvals.json`: a `version` plus a
list of fully-attributed entries.

```json
{
  "version": 1,
  "waivers": [
    {
      "id": "2026-08-12-example",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "guard": "commit-growth-guard",
      "approved_by": "core-platform",
      "approved_on": "2026-08-12",
      "expires_on": "2026-11-12",
      "reason": "Landed before the guard measured per commit; cannot be re-trailered."
    }
  ]
}
```

Every field is required. An entry missing any field does not apply.

## Scope rules

A waiver applies **only** when all of these hold:

1. `commit` is one exact 40-character hex SHA and equals the commit being
   judged. There is no prefix, wildcard, or `all` form — an abbreviated SHA
   does not match.
2. `guard` names the gate exactly. One registry serves several gates; an entry
   for one gate never covers another.
3. `expires_on` parses as `YYYY-MM-DD` and is strictly in the future. A waiver
   expiring today has expired.

## Reporting

A waived run **passes but does not report a clean pass.** The waiver id,
approver and expiry appear in the output, and the underlying violation stays in
the JSON payload. If a run's output does not mention a waiver, no waiver was
used.

## Operating rule

Default posture is to split the commit or carry an approval trailer on the
commit itself. Waivers are for history that already landed and therefore can no
longer do either. Give every waiver the shortest expiry that covers the
remediation, and delete it when the history is no longer in range.

`commit-growth-guard` reads this registry in diff-range mode only. Local staged
commits can still be split or trailered, so waivers do not apply to them.
