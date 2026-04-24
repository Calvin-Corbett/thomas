# Module: guardrails

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | scaffold (ALL files are source placeholders)           |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | internal product review|
| Used in prod     | no — nothing imports this module                       |
| Has real tests   | no                                                     |
| Blocking issues  | 100% placeholder, zero functional code                 |

## What This Is

Supposed to be the runtime guardrails enforcement layer for Thomas. Currently
4 files, all source placeholders with zero functional code. 28 total lines
(all placeholder comments and `#` padding).

## What's In Here Right Now

- `__init__.py` — **PLACEHOLDER.** Comment + padding.
- `engine.py` — **PLACEHOLDER.** Comment + padding.
- `policies.py` — **PLACEHOLDER.** Comment + padding.
- `validators.py` — **PLACEHOLDER.** Comment + padding.

**Nothing imports this module.** Zero references anywhere in production code.

## What This Is Supposed To Be

Based on the naming convention, the broader security architecture, and
The product vision makes security PRIORITY #1, so this module should be
the **runtime enforcement layer** — the thing that actually stops Thomas
from doing dangerous stuff without permission:

### `engine.py` — Guardrails Engine
The runtime interceptor. Sits between Thomas's decision to act and the
actual execution. Every action Thomas takes should pass through this engine.
It checks the action against policies and decides: allow, require approval,
or block.

This is where internet-access gating would live: Thomas is about
to make an HTTP request → engine intercepts → checks policy → requires
password if policy says so.

The engine should integrate with:
- `thomas/policy/` (PolicyEngine, rules) — already has real rule definitions
- `thomas/tools/windows_auth.py` — already has real OS-level auth gate
- `thomas/server/guardrails_api.py` — already has real approval API routes
- `thomas/agent/approval.py` (ApprovalBroker) — already has approval plumbing

### `policies.py` — Policy Definitions
The rules that the engine enforces. What's allowed without asking, what needs
a simple confirm, what needs OS-level password authentication. the product's
multi-stage security levels would be defined here:

- Level 1: "Let AI do whatever" — all policies permissive
- Level 2: "Require approval for dangerous actions" — internet, file delete,
  system changes require confirm
- Level 3: "Require password for everything external" — any outbound
  request needs OS-level auth
- Custom: user defines their own policy per action category

### `validators.py` — Input/Output Validation
Validates Thomas's inputs and outputs against safety rules before they
execute or get returned to the user:

- Prompt injection detection (more advanced than the current 10-string check)
- PII detection and redaction
- Content filtering
- Output safety checks
- Tool argument validation (is this file path safe? is this URL trusted?)

## Related Modules That Already Exist

These have REAL code that this module should connect to:

| Module | What it has | Lines |
|--------|------------|-------|
| `thomas/policy/` | PolicyEngine, rules, tool categories, redaction | 342+ |
| `thomas/tools/windows_auth.py` | Windows PIN/password auth gate | 292 |
| `thomas/server/guardrails_api.py` | Approval API routes | exists |
| `thomas/core/redaction.py` | PII/secret redaction | exists |
| `thomas/security/` | Audit tools, threat model, dependency policy | 1,111 |

The pieces exist. This module is the missing glue that connects them into
a runtime enforcement pipeline.

## Known Gaps

- 100% placeholder — zero functional code
- Not imported by anything
- No runtime action interception exists anywhere
- No internet access gating
- No multi-stage security level configuration
- Engine/policy/validator architecture is designed but not built
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

Nothing to protect — it's all placeholder. But when this gets built,
do NOT bypass the existing `thomas/policy/` module. Build on top of it.
