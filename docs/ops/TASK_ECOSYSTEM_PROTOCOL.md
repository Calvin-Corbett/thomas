# Task Ecosystem Protocol

Last updated: 2026-02-27

This is the canonical start-to-finish workflow for Thomas task orchestration.

## Roles

- `thomas`: intake + orchestration entrypoint.
- `task-manager-agent`: single owner of task ecosystem control-plane.
- `parent agent`: coordinates one or more worker agents.
- `worker agent`: executes one claimed task lane.

## Mandatory behavior

1. Thomas does not execute implementation work directly when delegation is possible.
2. Thomas routes tasks through `task-manager-agent`.
3. Every contributing agent must check in with a claim before edits.
4. Every active or queued task must exist on `plans/thomas/WORKBOARD.md`.
5. Agent-to-agent communication must use workboard message traffic.
6. Task manager must maintain a task-type to specialist routing map.
7. Every tracked task must have a canonical problem record under `plans/thomas/problems/<task_id>/PROBLEM.md`.
8. Agents must operate from the canonical Thomas clone and remote identity defined in `docs/ops/repo_identity_policy.json`.

## Task manager priority loop

1. Create tasks:
   - user-requested tasks first
   - background improvement tasks second
2. Verify ecosystem:
   - task/claim/issue consistency
   - liveness and inactivity recovery
   - plan coverage and gate status
3. Improve ecosystem:
   - messaging quality
   - dispatch quality
   - automation quality
4. Repeat continuously.

## End-to-end execution flow

1. Intake:
   - parse user objective
   - identify immediate (`P0`) and deferred (`P1/P2`) work
2. Preference capture:
   - record summary + verbatim user instruction
   - apply weighted interpretation (summary 0.8, verbatim 0.2)
3. Task creation:
   - create/update board tasks with scope, priority, and urgency
4. Specialist routing:
   - infer specialist from task id/scope/summary
   - sync `Task Specialist Routing` rows on the workboard
   - include dedicated route for OpenAI specialist-framework work (`openai_specialist_framework`)
5. Claim + assign:
   - parent agent claims orchestration scope
   - workers claim non-overlapping execution scopes
6. Session sync:
   - maintain alias identity (`Codex 1`, `Codex 2`, etc.)
   - maintain unique session id per run
7. Active execution:
   - agents run in parallel where safe and non-overlapping
8. Messaging traffic:
   - workers request scope decisions or conflict resolution
   - task manager approves/rejects via message updates
9. Brainstorm escalation:
   - if scope is ambiguous or project is blank-slate, task manager starts a brainstorm session
   - all invited agents contribute proposals/risks until session reaches `decision_ready`
   - task manager resolves session and dispatches follow-up tasks
10. Inactivity handling:
   - detect stale agents
   - send ping
   - block/move/reassign if inactive
   - auto-split partially blocked queued scope into non-overlap child lanes for idle agents
11. Verification:
   - run board and task-manager gates
12. Closeout:
   - mark resolved
   - release claims
   - keep board ordered by importance

## Commands

Check-in and release:

```bash
python scripts/workboard_claim.py --claim --agent "<agent>" --scope "<paths>" --task "<summary>"
python scripts/workboard_claim.py --release --agent "<agent>"
```

Task manager automation:

```bash
python scripts/workboard_task_manager.py --sync-plans --apply
python scripts/check_workboard_task_problems.py
python scripts/workboard_task_manager.py --sync-sessions --apply
python scripts/workboard_task_manager.py --sync-specialists --apply
python scripts/workboard_task_manager.py --specialist-for-task --task-id "<task_id>"
python scripts/workboard_task_manager.py --specialist-for-task --task-scope "<scope>" --task-summary "<summary>"
python scripts/workboard_task_manager.py --sweep-inactive --max-idle-minutes 1 --apply --task-manager-agent "task-manager-agent"
python scripts/workboard_task_manager.py --monitor --apply --cycles 0 --interval-seconds 30 --task-manager-agent "task-manager-agent"
python scripts/workboard_task_manager.py --reactivate --task-id "<task_id>" --agent "<agent>"
python scripts/workboard_task_manager.py --capture-preference --preference-summary "<summary>" --preference-verbatim "<verbatim>"
python scripts/check_repo_identity.py
```

Monitor behavior highlights:
- Recovers missing swarm terminals with `launch-missing`.
- Pings active-task agents that go silent past threshold.
- Dispatches online idle agents to up-for-grabs tasks.
- Auto-splits partially blocked queued tasks into child lanes (`<task_id>-split-N`) when only part of a scope can run without overlap.

Persistent worker execution:

```bash
python scripts/workboard_worker.py --agent "<agent>" --cycles 0 --poll-seconds 15 --catalog "plans/thomas/worker_command_catalog.json"
```

Worker behavior highlights:
- Stays online and waits for tasks assigned to its agent alias.
- Executes task command pipelines from the worker command catalog (task id, prefix, or default match).
- Posts completion/blocker messages to `task-manager-agent`.
- Releases claim on success by default so task manager can dispatch the next task automatically.

Brainstorm orchestration:

```bash
python scripts/workboard_brainstorm.py --start --task-id "<task_id>" --summary "<brief>" --objective "<desired outcome>" --facilitator "task-manager-agent" --all-hands --priority p0
python scripts/workboard_brainstorm.py --contribute --session-id "<session_id>" --agent "<agent>" --kind proposal --summary "<idea or risk>"
python scripts/workboard_brainstorm.py --status --session-id "<session_id>"
python scripts/workboard_brainstorm.py --resolve-session --session-id "<session_id>" --summary "<final decision>" --dispatch-item "task-id|scope/path|summary"
```

Terminal swarm orchestration:

```bash
python scripts/workboard_swarm.py --create --task-id "<task_id>" --size 8 --agent-prefix "Codex" --agent-start 1 --spawn-command "codex" --priority p0
python scripts/workboard_swarm.py --launch --swarm-id "<swarm_id>"
python scripts/workboard_swarm.py --launch-missing --swarm-id "<swarm_id>"
python scripts/workboard_swarm.py --status --swarm-id "<swarm_id>"
python scripts/workboard_swarm.py --complete --swarm-id "<swarm_id>"
```

Agent messaging:

```bash
python scripts/workboard_message.py --send --from-agent "<agent>" --to-agent "<agent|task-manager-agent>" --summary "<text>" --task-id "<task_id>"
python scripts/workboard_message.py --ack --msg-id "<msg_id>" --by "<agent>"
python scripts/workboard_message.py --resolve --msg-id "<msg_id>" --by "<agent>"
python scripts/workboard_message.py --list --to-agent "<agent>" --state open
```

## Decision model for scope-change requests

1. Worker sends `kind=scope_change` message to `task-manager-agent`.
2. Task manager responds with `decision=approved` or `decision=rejected`.
3. If approved, task manager updates claim scope and task summary.
4. If rejected, worker proceeds with original scope.
