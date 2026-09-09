# Thomas data directory and profiles

Thomas now keeps runtime/state data outside the git repo by default.

## Data directory resolution

Precedence:
1. `--data-dir <path>` (CLI/server flag)
2. `THOMAS_DATA_DIR` (env var)
3. `memory.data_dir` in `thomas.toml`
4. OS default:
 - Windows: `%LOCALAPPDATA%\Thomas`
 - macOS: `~/Library/Application Support/Thomas`
 - Linux: `${XDG_DATA_HOME:-~/.local/share}/thomas`

## Profile resolution

- `--profile <name>` or `THOMAS_PROFILE` (or `memory.profile`) scopes state to:
  - `<THOMAS_DATA_DIR>/<profile>/...`
- `--profile demo --reset` deletes that profile directory on startup, then starts fresh.

## What is routed under the data dir

Runtime writes are now defaulted under the active data/profile directory, including:
- memory/hippocampus databases
- conversations/transcripts/state
- logs
- caches
- downloads
- runs/artifacts
- webhook JSON stores and DB-connection JSON state

## Verification checklist

1. Run Thomas with a profile:
   - `thomas --profile demo repl`
2. Send a chat message and let it write normal runtime state.
3. Exit Thomas.
4. Run:
   - `git status --short`
5. Confirm no new runtime/state files were created in the repo working tree.
