# Active Folders Coordination

Use this when multiple agents are editing the same repository.

## Goal

- Prevent edit collisions by letting each agent claim folder scopes.
- Make active work visible before anyone edits files.

## Backing State

- Registry file: `runtime/coordination/active_folders.json`
- Lock file: `runtime/coordination/active_folders.lock`
- Tool: `python scripts/active_folders.py ...`

Claims use TTL leases and heartbeats. Expired claims are auto-pruned.

## Basic Workflow

1. Claim the folders you own.
2. Check target folders for conflicts before editing.
3. Heartbeat while working (daemon/run modes do this automatically).
4. Release claim when done.

## Commands

List active claims:

```bash
python scripts/active_folders.py list
```

Claim folders:

```bash
python scripts/active_folders.py claim --agent codex-main --path thomas/server --path tests --note "routing fixes"
```

Check if your target overlaps active claims:

```bash
python scripts/active_folders.py check --agent codex-main --path thomas/server/routes
```

Release your claims:

```bash
python scripts/active_folders.py release --agent codex-main
```

Run command under automatic claim + heartbeat + release:

```bash
python scripts/active_folders.py run --agent codex-main --path thomas/server -- python scripts/auto_checks.py --quick
```

## Background Mode

Foreground daemon (keeps claim alive until stopped):

```bash
python scripts/active_folders.py daemon --agent codex-main --path thomas/server --note "API route work"
```

## Team Policy (Recommended)

- No edits before `check` passes.
- One active claim per agent id.
- Keep claims narrow (folders, not repo root).
- Always release claims at end of task.
- If an agent crashes, claims expire automatically by TTL.