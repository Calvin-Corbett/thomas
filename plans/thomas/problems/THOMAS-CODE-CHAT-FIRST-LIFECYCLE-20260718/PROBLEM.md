# PROBLEM for THOMAS-CODE-CHAT-FIRST-LIFECYCLE-20260718

task_id: `THOMAS-CODE-CHAT-FIRST-LIFECYCLE-20260718`

- Owner: claude
- Status: in_progress
- Updated At: 2026-07-19T00:30:00+00:00
- Scope: thomas/,tests/,scripts/,plans/thomas/,CHANGELOG.md,docs/

## Current Problem

Thomas 0.19.0's unified Chat/Code/Work product failed every organic use despite
green unit suites: fresh chats refused to execute (autonomy default 1),
multi-part asks produced duplicate deliverable storms, Code builds died at the
600-second wall, the Code feed compressed to 4 visible notes, new Code
conversations edited Thomas's own source tree by default, a Canvas "keepalive"
burned ~4,800 ChatGPT subscription calls per day from boot, and the
release_update gate catch-22 stranded every product commit since 2026-06-26.

## Blocking Details

- Runtime recon 2026-07-18 (workflow wf_6ce339e0-ae9): every recent agent run
  exited 1; task ledger frozen at "Session created." for 25 sessions; all
  three real jobs had empty dashboards; exec-173a10415d7f held 7 duplicate
  deliverables for one two-part ask.
- Idle POST loop: one POST to chatgpt.com/backend-api/codex/responses every
  ~19s, traced via caller-stack instrumentation to
  chat_delegation_canvas_client._keepalive_loop; zero posts after retirement.
- Resolution: claude repair batch + codex WIP committed as scoped commits,
  dev merged in, landing PR in flight (Calvin full go-ahead, 2026-07-18).
  See plans/thomas/WT2_LANDING_MAP_2026-07-15.md and CHANGELOG [Unreleased].
