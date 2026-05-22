# The agent coordination lane and how to use it

Thomas is multi-agent. Any agent in this repo MUST run:

```bash
python scripts/crew/workboard/message.py --list
```

at session start before choosing work or editing files.

## Roles

Claude is the coordinator and leader of repo-quality work for Thomas. Codex and any spawned workers report to Claude. Calvin overrides anyone.

## Supervisor Protocol

Workers do one unit at a time, then message Claude with `state=open` and STOP. Workers do not start the next unit until Claude uses `--ack` with `decision=approved`.

Approved means proceed. Rejected means correct the requested issue. Use `kind=ping` for questions and wait for Claude's answer before acting.

## Message Tool Surface

Use `scripts/crew/workboard/message.py` for the coordination lane.

- `--send`: create a message.
- `--ack`: acknowledge or decide on a message.
- `--resolve`: mark a message resolved.
- `--list`: read current messages.

Valid message kinds are `blocker`, `brainstorm_call`, `brainstorm_decision`, `brainstorm_note`, `coordination`, `decision`, `handoff`, `ping`, `scope_change`, and `status`.

Valid decisions are `approved`, `none`, `pending`, and `rejected`.

Valid states are `open`, `acked`, and `resolved`.

## When To Message

Message Claude after every commit, blocker, decision, surprise, question, and handoff. The default is message and wait, not act and hope.

## Spawning More Agents

If Claude needs help, Claude can spawn additional workers and assign them units through the same message-and-wait protocol.
