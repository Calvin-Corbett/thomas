# Scalable file-access permission ladder

**Built 2026-06-17.** Answers "let Thomas write to my PC" with a dial-able permission
ladder (like Codex sandbox modes / Claude Code permission tiers), not a single toggle.
It is a **separate axis from autonomy**: autonomy = how much Thomas *asks*; file-access
= what its worker is *allowed to touch*.

## The ladder

| Level | Name | Can write to |
|---|---|---|
| 0 | `read_only` | nothing (reads only) |
| 1 | `workspace` | its own task workspace (sandbox) — **default** |
| 2 | `project` | + the Thomas project tree |
| 3 | `pc` | + your personal folders (Desktop, Documents, Downloads…) |
| 4 | `full` | + anywhere |

**Invariants at EVERY level (cannot be disabled by the ladder):**
- OS system directories (Windows, Program Files, /etc, /usr, …) are never writable.
- Thomas's own runtime code (`thomas/tools`, `thomas/core`, `thomas/server`, `scripts`, policy files) stays protected by the existing runtime guard.

So "put a file on my desktop" works at level **`pc`** or higher; at `workspace` (default) it lands in the sandbox (with an openable link), as it does today.

## How to set it (3 ways, all live)

1. **Config (persistent):** in `thomas.toml`
   ```toml
   [tools]
   file_access = "pc"     # or read_only / workspace / project / full / 0-4
   ```
2. **Per session (API / UI):** include `file_access` in the `/api/v2/chat` payload
   (`"file_access": "pc"` or `3`). Overrides the config for that session. This is the
   field a UI toggle/slider binds to.
3. **Default:** `workspace` — unchanged behavior unless you dial up.

## Where it lives (code)
- `thomas/core/file_access.py` — the level model + `authorize_write()` (the security logic).
- `thomas/tools/filesystem.py` — `WriteFileTool` enforces the ladder + keeps runtime/system protection.
- `thomas/core/config.py` — `ToolsConfig.file_access` + loader.
- `thomas/server/app_helpers.py` — `_build_tools` passes the level to the worker's tools.
- `thomas/server/worker_runtime.py`, `chat_delegation.py`, `routes/chat_v2.py` — thread the per-session override from the chat payload to the worker (mirrors `autonomy_level`).

## Tests
- `tests/stress/sweep_file_access.py` — 10/10: read_only blocks; workspace confines; pc allows Desktop; full allows elsewhere; system dirs + Thomas's own code blocked even at full.
- Existing filesystem-protection suite: 39/39 still pass (runtime/control-file protection intact).

## Remaining (last mile)
The visible **UI toggle/slider** in the chat interface (frontend `web/js/runtime`) is not
yet built — the backend it binds to (the `file_access` payload field) is done. Building the
on-screen control + wiring it to the payload is the next step.
