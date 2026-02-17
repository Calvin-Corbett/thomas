# Swarm Mode v2 — Review + Upgrade Notes

This zip replaces the previous Swarm Mode drop with a *fully wired, concurrency-correct*, and more UI-rich version.

## What was wrong in the previous zip (fixed here)

- **Concurrency limit was not enforced** (`max_parallel_tasks` existed but wasn’t applied).  
  ✅ Fixed: tasks are scheduled via a ready-queue + worker loops with a **hard global concurrency cap**.
- **Server integration file was incomplete** (had `...` placeholders, no cancel endpoint).  
  ✅ Fixed: `thomas/server/swarm_mode.py` is complete and includes **localhost-only** cancel.
- **No failure propagation** (deps could wait forever or still run).  
  ✅ Fixed: downstream tasks are marked **blocked** if any dependency fails/cancels.
- **Event stream lacked sequencing metadata** (harder to debug/drive UI).  
  ✅ Fixed: every event includes **seq** and **ts**.
- **Zip contained build artifacts** (`__pycache__`, `.pytest_cache`).  
  ✅ Fixed: this zip is clean.

## Files added / changed

- `thomas/agent/swarm.py`
  - Strict TaskGraph schema (versioned)
  - Dependency-aware scheduler
  - Global + optional per-agent concurrency caps
  - FS-mutating tool call serialization (global lock)
  - Cancellation + blocked task propagation
  - NDJSON events include: `run_id, agent_id, task_id, seq, ts`

- `thomas/server/swarm_mode.py`
  - `handle_swarm_chat(...)` (NDJSON stream helper)
  - `handle_cancel` (POST `/api/runs/{run_id}/cancel`, **localhost-only**)

- `web/swarm_board.js` + `web/swarm_board.css`
  - Task DAG list + **SVG dependency edges**
  - Per-agent tabs
  - Task focus mode (click a task to filter logs/tools)
  - Tool timeline (expandable details)
  - Cancel button

- `tests/*`
  - Concurrency limit enforced
  - Dep failure blocks downstream work
  - Cancellation behavior
  - FS tool-call serialization
  - Strict TaskGraph validation + cycle detection
  - Event shape required fields

## Required server wiring (app.py)

In `thomas/server/app.py`, inside your `/api/chat` handler:

```python
from thomas.server.swarm_mode import handle_swarm_chat, handle_cancel

# register endpoint once at startup:
app.router.add_post("/api/runs/{run_id}/cancel", handle_cancel)

# inside /api/chat
if payload.get("mode") == "swarm":
    # You already generate these in your normal handler:
    # - run_id
    # - session_id
    # - user_request (the prompt/message)
    #
    # And you already have a tool executor used by your normal agents:
    # async def tool_call(name: str, args: dict) -> dict

    subagents = {
        "planner": planner_agent,
        "coder": coder_agent,
        "tester": tester_agent,
        "reviewer": reviewer_agent,
    }

    return await handle_swarm_chat(
        request,
        payload=payload,
        user_request=user_request,
        run_id=run_id,
        session_id=session_id,
        subagents=subagents,
        tool_call=tool_call,
        tool_mutates_fs=tool_mutates_fs_optional,
    )
```

`tool_mutates_fs_optional` is optional; if you already have tool metadata, pass a function:
`def tool_mutates_fs(name,args)->bool` for perfect safety. If omitted, Swarm falls back to a conservative heuristic.

## Required UI wiring

1) Load the assets:
- include `web/swarm_board.css`
- include `web/swarm_board.js`

2) Add “Swarm” to your mode selector.
3) When mode == swarm, mount the board:

```js
const board = new window.SwarmBoard(document.querySelector("#swarmBoardRoot"));

for await (const evt of ndjsonStream) {
  board.ingest(evt);
}
```

## Demo script (manual)

1) Start Thomas normally.
2) In the UI, select **Swarm**.
3) Try a request that naturally parallelizes:

- “Add Swarm Mode with UI board and cancellation, and make sure tests pass.”
- “Refactor X and add tests + docs.”

4) Watch:
- Task list updates (queued → running → done/failed/blocked)
- Per-agent output streaming
- Tool timeline filling in
- Cancel stops remaining work (and marks tasks cancelled/blocked)

## Notes / deliberate design choices

- **Strict planner JSON** is non-negotiable. The orchestrator parses the *first* JSON object it finds, then validates exact keys + types.
- **Blocked** is a first-class terminal state so you can see what didn’t run and why.
- The scheduler is queue-based (not “spawn everything then wait”), so large graphs won’t create a pile of idle coroutines.

