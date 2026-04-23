# Active Folders Coordination

Use this system when multiple agents or humans edit the Thomas repo at the same time.

## Goal

- Prevent edit collisions by claiming folder scopes.
- Block commits that overlap another active claim.
- Keep in-progress ownership visible in one shared registry.

## Backing State

- Registry file: `runtime/coordination/active_folders.json`
- Lock file: `runtime/coordination/active_folders.lock`
- Tool: `python scripts/active_folders.py ...`
- Auto hook: `.pre-commit-config.yaml` runs
  `guard-staged --auto-claim-staged --no-require-explicit-agent`

Claims use TTL leases with heartbeats. Expired claims are auto-pruned.

## Agent Identity (Important)

Set a stable agent id once per terminal before claiming folders.

For external tools:

```powershell
$env:AGENT_ID = "codexc"
$env:AGENT_ID = "gemini"
```

For Thomas-native flows:

```powershell
$env:THOMAS_AGENT_ID = "codex-main"
```

If no explicit id is set, the script falls back to `user@host-ppid...`.

See resolved id/source:

```bash
python scripts/active_folders.py whoami
```

## Fast Workflow

1. Check target folder before editing.
2. Claim folders you will change.
3. Work (or run commands through `run` mode).
4. Release when done.

Check conflicts:

```bash
python scripts/active_folders.py check --path thomas/server/routes
```

Claim folders:

```bash
python scripts/active_folders.py claim --path thomas/server --note "routing fixes"
```

Release all claims for your agent:

```bash
python scripts/active_folders.py release --agent "$env:AGENT_ID"
```

## Recommended Command Wrapper

Run a command with automatic claim + heartbeat + release:

```bash
python scripts/active_folders.py run --path thomas/server --note "server checks" -- python scripts/auto_checks.py --quick
```

## Background Lease Mode

Keep a claim alive in the foreground until interrupted:

```bash
python scripts/active_folders.py daemon --path thomas/server --note "API route work"
```

## Automatic Commit Blocking

Pre-commit now runs:

```bash
python scripts/active_folders.py guard-staged --auto-claim-staged --no-require-explicit-agent
```

Behavior:

- Reads staged files from `git diff --cached --name-only`.
- Auto-claims staged paths for the current agent before checking conflicts.
- Fails commit if staged paths overlap another active claim.
- Uses explicit `AGENT_ID`/`THOMAS_AGENT_ID` when set, else falls back automatically.
- Ignores your own claim by current agent id unless `--no-ignore-self` is used.

## Conflict Rules

- `claim`/`run`/`daemon` block on overlap by default.
- Use `--allow-conflicts` only for intentional override.
- Keep scopes narrow (specific folders, not repo root).

## Useful Commands

List claims:

```bash
python scripts/active_folders.py list
```

Check staged files manually:

```bash
python scripts/active_folders.py guard-staged --auto-claim-staged
```

Force-check including your own claims:

```bash
python scripts/active_folders.py check --path thomas/server --no-ignore-self
```
