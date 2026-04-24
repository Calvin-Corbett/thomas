# Module: security

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (audit/policy tools work, auth gate works)  |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | internal product review|
| Used in prod     | yes — imported by production code                      |
| Has real tests   | partial                                                |
| Blocking issues  | reasoning_audit.py is placeholder, vision much bigger  |

## What This Is

Security auditing, threat modeling, dependency policy, incident drills, and
tools for Thomas. 1,100 lines across 8 files. This module is PART of the
security story — the full security picture spans multiple modules (see below).

## Product Vision

**Security is PRIORITY #1 for the entire project.** Above memory, above
everything else. The vision:

- **Password-gated internet access.** Anytime Thomas tries to access the
  internet, it should require password/authentication from the user. Not
  silent. Not automatic. The user must approve.
- **Multi-stage security levels.** Users choose their own security posture:
  - "Let AI do whatever it wants" (low security, user's choice)
  - "Require password for dangerous actions" (medium)
  - "Require password for everything involving internet/system" (high)
  - Specific actions flagged as "too serious" require system-level auth
    (computer password, encrypted credential store)
- **System-level authentication.** Using the OS credential system (Windows
  PIN/password dialog, macOS Keychain, etc.) for the highest-security actions.
  This already partially exists in `thomas/tools/windows_auth.py`.
- **Tiered approval.** Not everything needs the same level of auth. Browsing
  a URL might need a simple confirm. Deleting files needs OS-level password.
  Sending money needs multi-factor.

## The Full Security Picture (across modules)

Security is NOT just this module. It's spread across:

1. **`thomas/security/`** (this module) — Audit, threat model, dependency
   policy, incident drills. GOVERNANCE layer.
2. **`thomas/tools/windows_auth.py`** — Windows native PIN/password gate for
   high-risk actions. Uses CredUI dialog. Zero disk persistence. Session-based
   with configurable expiry. **This is real and works on Windows.**
3. **`thomas/policy/`** — PolicyEngine with rules, tool categories, redaction.
   Real code (342 lines of rules, 251 lines of tools). Decides what actions
   need approval vs. can run automatically.
4. **`thomas/guardrails/`** — **MOSTLY PLACEHOLDER.** engine.py, policies.py,
   validators.py are all source placeholders. Only __init__.py has content
   (and it's just "Scaffold package for accelerated catch-up work").
5. **`thomas/approvals/`** — **EMPTY.** Just an __init__.py with 1 line.
6. **`thomas/core/redaction.py`** — PII/secret redaction. Exists in core.
7. **Prompt injection resistance** — tested in `testing_suite.py` (narrow but
   real, catches 8/10 hardcoded probes).

## What Actually Works in This Module

- `mutating_route_policy.py` (377 lines) — Audits API routes for mutating
  operations, checks against an exception manifest with expiry dates. Real
  governance tooling.
- `tools.py` (220 lines) — SecurityAuditTool, ThreatModelTool,
  DependencyPolicyTool, IncidentDrillTool. Tool wrappers that call the
  other files. Real.
- `dependency_policy.py` (117 lines) — Checks dependencies for policy
  compliance. Real.
- `security_audit.py` (120 lines) — Aggregated audit report. Real.
- `threat_model_cadence.py` (99 lines) — Checks if threat model is stale.
  Real.
- `incident_drill.py` (170 lines) — Simulates security incident responses.
  Real.

## What Is Placeholder

- `reasoning_audit.py` — **PLACEHOLDER.** Source placeholder. Was supposed
  to audit AI reasoning chains for safety. Not implemented.

## Known Gaps (vs. the vision)

- **No internet access gating.** Thomas does not currently require password
  to access the internet. This is the biggest missing piece per product planning.
- **No multi-stage security levels.** No UI for users to choose their
  security posture.
- **Windows-only OS auth.** `windows_auth.py` only works on Windows. Needs
  macOS (Keychain/Touch ID) and Linux (polkit/PAM) equivalents.
- **Guardrails module is placeholder.** engine.py, policies.py, validators.py
  are all source placeholders.
- **Approvals module is empty.** Just an __init__.py.
- **No action severity classification.** No system to automatically classify
  which actions are "too serious" and need higher auth.
- reasoning_audit.py is placeholder
- No STATUS.md existed before this one (added 2026-03-18)

## Priority Implementation Order

Product direction: security is the **#1 priority for the entire project:**

1. Internet access gating (password required for any outbound request)
2. Multi-stage security level configuration (user chooses their posture)
3. Cross-platform OS-level auth (macOS, Linux — Windows already works)
4. Action severity classification (auto-tiering what needs what level)
5. Guardrails engine (real policy enforcement, not placeholder)
6. Approvals system (real approval workflow)

## Do Not Touch

- `tools/windows_auth.py` — Working auth gate. Don't change the credential
  handling or session model without explicit user approval.
- `policy/rules.py` — Policy rules. Changes affect what Thomas can do
  autonomously. Review carefully.
