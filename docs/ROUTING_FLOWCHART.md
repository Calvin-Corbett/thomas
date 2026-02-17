# Routing Flowchart (Token-Efficient Autonomy)

This document defines the turn router used by Thomas to reduce token waste while preserving coding quality.

## Goals
- Avoid spending coding/tool/system tokens on casual turns.
- Keep high context quality for coding/debug/security work.
- Apply one consistent routing policy across web, CLI, REPL, and Telegram.

## Decision Flow
```text
New User Turn
-> IntentRouter.decide(text)
  -> Select path
  -> Assign policy:
     - mode
     - tools_policy
     - include_purpose
     - memory scope (global/profile)
     - memory budget
     - library retrieval (research-oriented paths)
-> Apply thread memory policy
-> Run AgentLoop with selected policy
-> Emit route trace in AGENT_START + token_report
```

## Paths And Policies
| Path | mode | tools | include_purpose | memory_global | memory_profile | budget |
|---|---|---|---|---|---|---|
| `casual_chat` | `auto` | `never` | `false` | `false` | `true` | `480` |
| `personal_context` | `auto` | `never` | `false` | `false` | `true` | `700` |
| `planning` | `auto` | `auto` | `false` | `false` | `true` | `850` |
| `coding_task` | `auto` | `auto` | `true` | `true` | `true` | `1300` |
| `debug_audit` | `thinking` | `always` | `true` | `true` | `true` | `1500` |
| `research` | `auto` | `auto` | `false` | `true` | `false` | `900` |
| `assistant_meta` | `auto` | `never` | `false` | `false` | `true` | `550` |
| `general` | `auto` | `auto` | `false` | `false` | `true` | `760` |

## Transparency
- Route decision is attached to:
  - `AGENT_START.data.route`
  - `AGENT_DONE.data.token_report.route`
- Server streaming exposes route data as `type=route`.
- Library data is stored in `library/` and only injected when path policy allows it.

## Tuning Notes
- If responses feel too shallow on non-coding turns, increase `include_purpose` for `planning` or `general`.
- If token usage is still high, lower memory budgets first before lowering model quality.
- For stricter privacy/isolation, set `memory_global=false` for additional paths.
