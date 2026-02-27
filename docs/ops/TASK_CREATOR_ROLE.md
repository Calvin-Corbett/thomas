# Task Manager Role

Purpose:
- Own the task ecosystem end-to-end for Thomas.
- Ensure Thomas delegates execution to agents instead of doing task work directly.

Operating rule:
- If task-manager ownership is unassigned in `plans/thomas/WORKBOARD.md`, the first agent touching the board claims it.

Priority loop (always in order of need):
1. Task creation:
   - Translate user requests and repo gaps into clear, scoped, testable tasks.
2. Task ecosystem verification:
   - Validate active/blocked/complete states and run guard checks.
3. Task ecosystem improvement:
   - Improve orchestration, messaging, dispatch, and recovery workflows.
4. Repeat:
   - New improvements usually create new validation and task-creation needs.

Live need signals (highest to lowest):
1. Failing board/workflow gates and broken CI checks.
2. Open blockers tied to active tasks.
3. Competitor regression deltas in latest benchmark artifacts.
4. Monolith and large-file guard violations.
5. Repository hygiene debt (orphaned files, stale generated output, dead docs/UI residue).

Dispatch rules:
1. User-requested tasks always outrank background improvement tasks.
2. Keep `P0` short and urgent; move deferred work to `P1/P2`.
3. Do not place tasks in `Up For Grabs` if an equivalent active task already exists.
4. Assign the first available agent to the highest-priority unblocked `P0` task.
5. Every new task must include clear scope paths and `[P0|P1|P2][NOW|NEXT|LATER]` tags in summary.
6. Every task must be routed to a specialist lane using task id + scope + summary classification.
7. OpenAI specialist-framework tasks should route to `specialist-openai-framework` when `OpenAI/Agents SDK/Responses API` signals are present.
8. Brainstorm tasks should route to `specialist-brainstorm-facilitator` and run through an explicit brainstorm session lifecycle.
9. If no queued task fully avoids overlap, auto-split partially blocked up-for-grabs scope into `<task_id>-split-N` lanes and dispatch the non-overlap slice.

Messaging and identity requirements:
1. Use `scripts/workboard_message.py` for agent-to-agent and agent-to-manager requests.
2. Keep alias identity stable (`Codex 1`, `Codex 2`, etc.) and track unique run `session_id` separately.
3. Use `scripts/workboard_task_manager.py --sync-sessions --apply` to keep session registry current.
4. Use `scripts/workboard_task_manager.py --sync-specialists --apply` to keep task-to-specialist routing current.
5. Use `scripts/workboard_task_manager.py --specialist-for-task --task-id "<task_id>"` to inspect one board task route before assignment.
6. Keep monitor loop active during heavy multi-agent execution:
   - `python scripts/workboard_task_manager.py --monitor --apply --cycles 0 --interval-seconds 30 --task-manager-agent "task-manager-agent"`
7. Keep persistent worker loops active so dispatched tasks are executed continuously:
   - `python scripts/workboard_worker.py --agent "Codex 2" --cycles 0 --poll-seconds 15 --catalog "plans/thomas/worker_command_catalog.json"`
   - `python scripts/workboard_worker.py --agent "Codex 3" --cycles 0 --poll-seconds 15 --catalog "plans/thomas/worker_command_catalog.json"`

Brainstorm protocol requirements:
1. Start brainstorm with task-manager as facilitator:
   - `python scripts/workboard_brainstorm.py --start --task-id "<task_id>" --summary "<brief>" --objective "<outcome>" --facilitator "task-manager-agent" --all-hands`
2. Collect structured contributions from agents:
   - `python scripts/workboard_brainstorm.py --contribute --session-id "<session_id>" --agent "<agent>" --kind proposal --summary "<idea>"`
3. Resolve to a concrete dispatch plan:
   - `python scripts/workboard_brainstorm.py --resolve-session --session-id "<session_id>" --summary "<decision>" --dispatch-item "task_id|scope|summary"`

Swarm terminal protocol requirements:
1. Create a swarm manifest bound to a board task:
   - `python scripts/workboard_swarm.py --create --task-id "<task_id>" --size 8 --agent-prefix "Codex" --agent-start 1 --spawn-command "codex"`
2. Launch or dry-run launch of terminals:
   - `python scripts/workboard_swarm.py --launch --swarm-id "<swarm_id>"`
   - `python scripts/workboard_swarm.py --launch --swarm-id "<swarm_id>" --dry-run`
3. Track closeout state:
   - `python scripts/workboard_swarm.py --status --swarm-id "<swarm_id>"`
   - `python scripts/workboard_swarm.py --complete --swarm-id "<swarm_id>"`

Persistent worker loop requirements:
1. Worker alias must stay alive and poll for assigned tasks until explicitly stopped.
2. Worker must post completion/blocker message for each executed task.
3. Worker should release claim automatically on successful execution to keep dispatch moving.
4. Worker command mappings are sourced from `plans/thomas/worker_command_catalog.json` by default.

Preference capture requirements:
1. Any user instruction about "how tasks should run" must be captured.
2. Store both summary and verbatim forms using:
   - `python scripts/workboard_task_manager.py --capture-preference --preference-summary "<summary>" --preference-verbatim "<verbatim>"`
3. Task manager applies weighted interpretation:
   - Summary weight: `0.8`
   - Verbatim weight: `0.2`
