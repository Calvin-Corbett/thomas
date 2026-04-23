# Chat Execution Model

> **This is the authoritative document for how Thomas chat works.**
> If you're an AI agent working on the chat system, read this first.

Last updated: 2026-03-18

## Three-Tier Dispatch Architecture

Thomas uses a **dispatch-first** model for chat. When a user sends a message:

```
User sends message
       │
       ▼
  dispatch.py — is this casual or actionable?
       │
       ├── CASUAL (greetings, thanks, filler)
       │     └── Thomas replies directly via the agent loop
       │         Fast, no tools, personality only
       │
       └── ACTIONABLE (everything else)
             └── Thomas immediately says "On it."
                 └── chat_dispatcher.py posts task to WORKBOARD.md
                       └── Task Manager picks up the task
                             └── Breaks it down, assigns to workers
                                   └── Workers execute via workboard_worker.py
                                         └── Results stream back as events
```

## Key Files

| File | Role |
|------|------|
| `thomas/agent/dispatch.py` | Binary router: casual vs actionable |
| `thomas/agent/chat_dispatcher.py` | Bridge from chat → WORKBOARD.md |
| `thomas/server/routes/task_events.py` | Watches workboard, emits chat events |
| `thomas/server/routes/chat_aiohttp_part02.py` | HTTP route that wires it all together |
| `thomas/server/routes/chat_modes.py` | Fast-reply handler for casual messages |
| `thomas/agent/routing.py` | DEPRECATED — old 8-path intent router |
| `plans/thomas/WORKBOARD.md` | Task state, agent claims, messages |
| `scripts/workboard_task_manager.py` | Task lifecycle management |
| `scripts/workboard_worker.py` | Worker execution loop |
| `scripts/workboard_message.py` | Inter-agent messaging |

## How Dispatch Works

### Step 1: Classification (dispatch.py)
- Pattern-matches against casual patterns (greetings, thanks, filler)
- Everything that doesn't match a casual pattern = actionable
- When in doubt, dispatches (better to over-dispatch than block Thomas)

### Step 2: Fast Acknowledgment
- For actionable messages, Thomas immediately streams "On it."
- This happens BEFORE any LLM call or tool execution
- The user sees a response in milliseconds, not seconds

### Step 3: Workboard Dispatch (chat_dispatcher.py)
- Creates a task entry in `## Up For Grabs` on WORKBOARD.md
- Sends a coordination message to `task-manager-agent`
- Task ID format: `chat-<slug>-<random>` (e.g. `chat-fix-login-bug-a3f2c1`)

### Step 4: Task Manager Picks Up
- The workboard task manager monitors `## Up For Grabs`
- Claims the task, moves it to `## Active Tasks`
- Breaks complex tasks into sub-tasks if needed
- Assigns workers via the workboard dispatch protocol

### Step 5: Workers Execute
- Workers poll WORKBOARD.md for assigned tasks
- Execute commands from the worker command catalog
- Report progress via workboard messages
- Report completion/failure back to task manager

### Step 6: Events Stream Back
- `task_events.py` polls WORKBOARD.md for changes
- Emits SSE events to the chat session
- UI renders task progress inline in the conversation

## Event Types

| Event | When |
|-------|------|
| `task_dispatched` | Task posted to workboard |
| `task_claimed` | An agent claimed the task |
| `task_progress` | Worker reported progress |
| `task_worker_started` | A sub-task worker was spawned |
| `task_worker_done` | A sub-task worker completed |
| `task_complete` | All work is done |
| `task_failed` | Task could not be completed |
| `task_blocked` | Task hit a blocker |

## Fallback Behavior

If dispatch fails (workboard not found, write error, etc.), the chat route
falls through to the normal inline `AgentLoop` execution. This ensures
chat never breaks even if the workboard infrastructure is down.

The `force_inline` payload flag can bypass dispatch for testing:
```json
{"text": "fix the bug", "force_inline": true}
```

## Relationship to Swarm Mode

There are TWO separate "swarm" systems. They are NOT the same:

1. **`thomas/agent/swarm.py`** — In-process async task graph orchestrator.
   Runs concurrent tasks in a single Python process. Well-tested but NOT
   integrated into the chat pipeline. This is for future use when a single
   chat request needs parallel in-process execution (e.g. "research X and
   build Y simultaneously").

2. **`scripts/workboard_swarm.py`** — Multi-terminal agent spawner.
   Launches separate agent processes (Codex, Claude, etc.) that each run
   independently. This IS the production multi-agent system used by the
   workboard.

The dispatch-first architecture uses system #2 (workboard) by default.
System #1 (in-process swarm) remains available for future integration.

## For AI Agents: Common Tasks

### "I need to change how Thomas responds to chat"
→ Edit `thomas/agent/dispatch.py` (classification) or the agent loop (response generation)

### "I need to change how tasks get dispatched"
→ Edit `thomas/agent/chat_dispatcher.py`

### "I need to change what events the UI sees"
→ Edit `thomas/server/routes/task_events.py` and `thomas/core/events.py`

### "I need to add a new chat feature"
→ Start with `thomas/server/routes/chat_aiohttp_part02.py` (the HTTP route)

### "I need to change how workers execute tasks"
→ Edit `scripts/workboard_worker.py` and `plans/thomas/worker_command_catalog.json`
