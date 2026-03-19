# Agent Router

Use this before loading long repo docs.

Canonical startup entrypoint:

```bash
python scripts/agent_startup_router.py --summary "<task summary>" [--path <repo/path>]...
```

What the router does:
- Shows workboard awareness first.
- Classifies the task into one lane.
- Lists only the next required reads.
- Lists only the required checks for that lane.
- Tells the agent when to escalate into a heavier lane.

Lane names:
- `chat`
- `simple-edit`
- `risky-edit`
- `multi-file`
- `multi-agent`
- `ui-proof`

Hard rule:
- The router reduces reading overhead. It does not weaken guardrails, proof gates, or release hygiene.

Default flow:
1. Run the router.
2. Read the returned lane card.
3. Read only the referenced guardrails for touched areas.
4. Run the listed checks before handoff or commit.