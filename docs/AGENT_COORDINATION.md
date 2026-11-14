# The agent coordination lane and how to use it

Thomas is multi-agent. Any agent in this repo MUST run:

```bash
python scripts/crew/workboard/message.py --list --agent <agent-id>
```

at session start before choosing work or editing files.

`--list` now defaults to unread messages addressed to the current agent. The
tool resolves identity from `--agent`, `THOMAS_AGENT_ID`, `AGENT_ID`, or the
model-specific agent env vars. Use `--all` only for board-wide audits.

## Roles

Claude is the coordinator and leader of repo-quality work for Thomas. Codex and any spawned workers report to Claude. Calvin overrides anyone.

## Supervisor Protocol (V2 — async, Calvin-directed 2026-07-15)

Workers message-and-PROCEED. Post a status message after each unit, then continue immediately
with the next queued unit — do not stop to wait for an ack.

Message-and-WAIT applies ONLY to:
- protected-file changes that need an owner (Windows-Hello) tap,
- scope conflicts with an ACTIVE claim,
- irreversible or destructive operations,
- genuine questions (`kind=ping`).

Staleness rule: before waiting on any blocker involving external state (PR checks, CI, branch
state), re-verify LIVE first (`gh pr view/checks`, `git fetch`). If reality has moved past your
report, resolve your own message and proceed on the fresh evidence.

If you are blocked on the coordinator for more than ~15 minutes and a queued default exists,
take the default and note it. Escalated p0 messages are for real fires only.

Rejected still means correct the requested issue before proceeding on that unit.

## Message Tool Surface

Use `scripts/crew/workboard/message.py` for the coordination lane.

- `--send`: create a message.
- `--ack`: acknowledge or decide on a message.
- `--resolve`: mark a message resolved.
- `--list`: read unread messages addressed to this agent by default.
- `--list --sent --agent <agent-id>`: view sent-message receipts.
- `--list --all`: read every message on the workboard.

Valid message kinds are `blocker`, `brainstorm_call`, `brainstorm_decision`, `brainstorm_note`, `coordination`, `decision`, `handoff`, `ping`, `scope_change`, and `status`.

Valid decisions are `approved`, `none`, `pending`, and `rejected`.

Valid states are `open`, `acked`, and `resolved`.

## When To Message

Message Claude after every commit, blocker, decision, surprise, question, and handoff. The default is message and wait, not act and hope.

## Reliability Gates

Unread workboard messages are a hard coordination barrier. The startup router
surfaces unread inbox items, Claude's `SessionStart` hook prints Claude's unread
mail, and `scripts/forge/gates/workboard_inbox.py` blocks pre-commit,
commit-message, `scripts/crew/brief/commit.py`, and active-folder claim/run/guard
flows while an agent has any `open` message addressed to it. Cage submissions
go through the same gate in `scripts/forge/commit_master.py`. Claude tool calls
can use `scripts/forge/gates/workboard_inbox_hook.py` as a `PreToolUse` adapter.

Acking means "I have seen this and will act or explicitly decline." Resolve a
message when the sender/recipient no longer need it on the active board. P0/P1
messages escalate in inbox output when they remain open past the configured
staleness threshold.

Ack can use `--by <agent-id>` or the current identity shortcut:

```bash
python scripts/crew/workboard/message.py --ack --msg-id <msg-id> --agent <agent-id>
```

## Spawning More Agents

If Claude needs help, Claude can spawn additional workers and assign them units through the same message-and-wait protocol.
