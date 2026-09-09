# Agent Messaging Reliability

Thomas workboard messages are not optional status text. They are an inbox with
receipts and gates.

## Startup

Run the startup router with your agent id:

```bash
python scripts/crew/brief/startup_router.py --summary "<task>" --agent <agent-id>
```

The first lines include unread workboard messages for that agent. Claude also
gets the same unread inbox through the `.claude` `SessionStart` hook.

## Reading And Acking

Use:

```bash
python scripts/crew/workboard/message.py --list --agent <agent-id>
python scripts/crew/workboard/message.py --ack --msg-id <msg-id> --agent <agent-id>
```

`--list` defaults to unread messages addressed to the current agent. Use
`--all` for a board audit and `--sent --agent <agent-id>` to check receipts for
messages you sent.

Ack means "seen and accepted for action or explicit handling." Resolve only when
the thread no longer needs active attention.

## Hard Barrier

`scripts/forge/gates/workboard_inbox.py` blocks coordinated action while an
agent has any unread message. It is wired into:

- `.pre-commit-config.yaml` early, final, and commit-message hooks
- `scripts/crew/brief/commit.py` early and final local gates
- `scripts/active_folders.py` claim, run, daemon, and guard-staged flows
- `scripts/forge/commit_master.py` cage submissions
- Claude `PreToolUse` via `scripts/forge/gates/workboard_inbox_hook.py`

This prevents an agent from committing or claiming/editing shared scope before
seeing coordination messages such as "do not touch this file."

The Claude hook adapter deliberately allows a single `message.py --list`,
`--ack`, or `--resolve` command through while unread messages exist, so the
agent can clear the inbox without opening a bypass for unrelated edits.

## Escalation

Open P0 and P1 messages become `ESCALATED` in inbox output when they are stale.
Escalation does not replace acking; it makes missed urgent mail louder at
startup and in gate failures.

## Red-Team Notes

- Concurrent message writes are serialized through the workboard message lock.
- The cage submit path blocks on any unread message, not only path-relevant
  messages, because "irrelevant" messages are exactly where missed coordination
  bugs hide.
- A background notifier can be layered on later, but it must call the same
  inbox/gate primitives rather than maintaining a separate message store.
