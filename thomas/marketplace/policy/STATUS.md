# Module: policy

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (policy engine with rules, tool categories) |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — imported by production code                      |
| Has real tests   | not fully assessed                                     |
| Blocking issues  | none identified                                        |

## What This Is

Policy/guardrails subsystem. 861 lines across 8 files, zero placeholders.
Off-by-default. When enabled, PolicyEngine evaluates each tool call and
can ALLOW or DENY execution. Includes rule definitions, tool category
classification, config, types, redaction, and run ID tracking.

## Architecture Notes

This is one of the real pieces that the `thomas/guardrails/` module
(currently all placeholder) should build on top of. The PolicyEngine here
already has rule evaluation logic. The guardrails module should be the
runtime layer that invokes this engine at the right interception points.

Also connects to the security vision: the multi-stage security levels
(project priority #1) would be defined as policy rule sets here.

## Known Gaps

- Off by default — not enforced unless explicitly enabled
- No connection to guardrails engine (which is placeholder)
- No internet access gating rules
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `rules.py` (342 lines) — Core rule definitions. Changes affect what
  Thomas is allowed to do. Review carefully.
