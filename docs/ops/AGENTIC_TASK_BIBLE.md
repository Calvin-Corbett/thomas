# Agentic Task Bible

Last updated: 2026-02-25

This runbook defines how parent and child agents coordinate work on `plans/thomas/WORKBOARD.md`.

## 1) Identity Is Mandatory

Every claim must carry:

- `agent=<id>`: stable machine identifier (`Codex 3`, `Codex 3-Worker-1`)
- `name=<callsign>`: human-readable name used in coordination chats
- `role=<solo|parent|worker>`
- `parent=<agent id|none>`: required for worker roles

Examples:

```bash
python scripts/workboard_claim.py --claim \
  --agent "Codex 3" \
  --name "Prime-Orchestrator" \
  --role parent \
  --scope "scripts,tests,docs/ops" \
  --task "[WIP][HSK-BIBLE] agentic task bible rollout"
```

```bash
python scripts/workboard_claim.py --claim \
  --agent "Codex 3-Worker-1" \
  --name "Prompt-Scout" \
  --role worker \
  --parent "Codex 3" \
  --scope "tests/prompt_pack,thomas/core" \
  --task "[WIP][HSK-BIBLE-A] gateway edge probes"
```

## 2) Parent Orchestration Loop

Parent runs this loop continuously:

1. Inspect active claims and open tasks.
2. Generate non-overlapping delegation candidates.
3. Claim child tasks with explicit worker identities.
4. Pull status from workers and reassign if blocked.
5. Mark claims `READY` or release when complete.

Delegation helper:

```bash
python scripts/workboard_claim.py --suggest-delegation --agent "Codex 3"
```

JSON mode for automation:

```bash
python scripts/workboard_claim.py --suggest-delegation --agent "Codex 3" --json
```

Parent auto-dispatch helper (recommended under contention):

```bash
python scripts/workboard_claim.py \
  --dispatch-workers \
  --agent "Codex 3" \
  --dispatch-release-ready \
  --dispatch-target-workers 2 \
  --task-manager-agent "task-manager-agent"
```

No-task fallback:

- If dispatch finds zero non-overlapping lanes, parent auto-claims a temporary task-creator lease.
- The parent sends a coordination notice to task manager when lease is acquired.
- Lease is strictly single-owner (first successful claimant wins; others see `held_by_other`).
- Task manager ends the backup role with:

```bash
python scripts/workboard_claim.py --release-temp-task-creator --agent "task-manager-agent" --task-manager-agent "task-manager-agent"
```

## 3) Scope Safety Rules

- Parent and workers must keep non-overlapping scopes.
- Worker claims must include `parent=...`.
- Use `scripts/check_workboard_claims.py` after updates.
- If blocked, move ownership state via `scripts/workboard_issue.py`.

## 4) Naming Convention

- Parent name: short orchestration identity (`Prime-Orchestrator`).
- Worker name: `{parent-name}-worker-{n}` or function-specific callsign (`Latency-Scout`).
- Keep names stable across a session for consistent auditability.

## 5) Default Delegation Strategy

When multiple `Up For Grabs` tasks exist:

1. Pick non-overlapping tasks first.
2. Prefer tasks with concrete scope boundaries.
3. Keep one worker per task unless task is explicitly split.
4. Parent keeps the integration/review task.

## 6) Hard Enforcement

These checks now gate commits/CI:

- `python scripts/check_workboard_claims.py --require-identity-metadata`
- `python scripts/check_workboard_changed_files.py --staged --require-identity-metadata` (pre-commit)
- `python scripts/check_workboard_changed_files.py --base <base> --head <head> --require-identity-metadata` (CI)
- `python scripts/check_workboard_agent_claim.py --enforce-staged-scope --enforce-parent-throughput --parent-target-workers 2 --parent-min-ready-suggestions 2`

## 7) Throughput Policy

- Parent-role claims are expected to fan out when delegation candidates exist.
- If at least two non-overlapping `Up For Grabs` tasks are ready, parent should have at least two active worker claims.
- Use:
  - `python scripts/workboard_claim.py --suggest-delegation --agent "<parent>"`
  - Or use one-command dispatch:  
    `python scripts/workboard_claim.py --dispatch-workers --agent "<parent>" --dispatch-release-ready --dispatch-target-workers 2 --task-manager-agent "task-manager-agent"`

## 8) Review Simplicity Preference

- User profile now supports `profile.review_depth`:
  - `adaptive` (default)
  - `simple` (plain good/bad + next action)
  - `technical`
- Non-coder profile defaults adaptive review depth to simple output.

## 9) Known Downsides

- More gates means higher coordination overhead and occasional false positives.
- Parent throughput checks can force extra delegation churn during tiny tasks.
- Strict metadata checks require migration of legacy hand-written claim rows.
- Changed-file scope gates can still be gamed if someone edits inside another agent's claimed path.
- Temp task-creator lease can become a bottleneck if manager forgets to release it after backlog recovery.

## 10) Message Traffic (Required)

Use `scripts/workboard_message.py` for any cross-agent coordination:

- Worker to task manager: scope-change request, blocker escalation, approval request.
- Worker to worker: conflict notice, lane handoff, pause/resume request.
- Task manager to worker: decision response, inactivity ping, reassignment notice.

Commands:

```bash
python scripts/workboard_message.py --send --from-agent "Codex 3-Worker-1" --to-agent "task-manager-agent" --summary "need scope extension" --task-id "task-x" --kind scope_change --priority p0
python scripts/workboard_message.py --ack --msg-id "<msg_id>" --by "task-manager-agent" --decision approved
python scripts/workboard_message.py --resolve --msg-id "<msg_id>" --by "Codex 3-Worker-1"
```

## 11) Alias + Session Identity

- Keep human-facing alias stable (`Codex 1`, `Codex 2`, etc.).
- Keep runtime session id unique per run.
- Sync registry into `## Agent Sessions`:

```bash
python scripts/workboard_task_manager.py --sync-sessions --apply
```

This lets agents reuse familiar aliases while preserving auditable per-run identity.

## 12) User Preference Capture For Orchestration

When a user describes how tasks should be conducted, capture both:

1. Summary (weighted as primary policy: 0.8)
2. Verbatim instruction (weighted as audit/fallback context: 0.2)

```bash
python scripts/workboard_task_manager.py --capture-preference --preference-summary "<summary>" --preference-verbatim "<verbatim>"
```

Stored path: `preferences.onboarding.answers.task_ecosystem`.
