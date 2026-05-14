# Agent File Editing Rules — READ BEFORE CHANGING ANYTHING

> **CRITICAL FOR ALL AI AGENTS WORKING ON THIS PROJECT.**
> If you skip this doc, your changes WILL NOT WORK.

Last updated: 2026-04-02

## The #1 Rule

**Before editing any file, verify you're editing the file that ACTUALLY runs in production.**

This project has had multiple runtime architectures over time. Old files still exist in the repo. If you edit a dead file, your changes do nothing and you create version confusion.

## JavaScript — WHERE TO EDIT

### The ACTIVE runtime (what the browser actually loads):

```
thomas/server/web/js/app_runtime_loader.js   ← Loader (loads all split files in order)
thomas/server/web/js/runtime/001_preamble.js  ← Global DOM refs and constants
thomas/server/web/js/runtime/002_*.js         ← Virtual office data
thomas/server/web/js/runtime/003-008_*.js     ← Setup/onboarding
thomas/server/web/js/runtime/009_*.js         ← Initialization composer
thomas/server/web/js/runtime/010-011_*.js     ← Chat games
thomas/server/web/js/runtime/012-014_*.js     ← Actions/interactions
thomas/server/web/js/runtime/015_*.js         ← Debug dock
thomas/server/web/js/runtime/016_*.js         ← Session/chat persistence
thomas/server/web/js/runtime/017-022_*.js     ← Virtual office
thomas/server/web/js/runtime/023-024_*.js     ← Mission control
thomas/server/web/js/runtime/025-028_*.js     ← Module system/command center
thomas/server/web/js/runtime/029-037_*.js     ← Workbench editors
thomas/server/web/js/runtime/038-039_*.js     ← Module rendering dispatch
thomas/server/web/js/runtime/040-045_*.js     ← Model/setup/settings
```

`app_runtime_loader.js` loads these 45 files **sequentially** into global scope. They all share `window` — a `const` in `001_preamble.js` is visible in `045_model_setup_settings_06.js`.

**Edit the numbered files in `js/runtime/`.** That is where the live UI code is.

### Standalone scripts loaded directly by index.html:

```
thomas/server/web/js/theme_rules.js           ← Theme engine
thomas/server/web/js/token_economy_space.js    ← Space background engine
thomas/server/web/js/token_economy.js          ← Token Economy module
thomas/server/web/js/templates/tpl_settings.js ← Settings HTML template
```

These are loaded by `<script>` tags in `index.html` and ARE active. Check `index.html` to confirm what's loaded.

### DEAD FILES — Do NOT edit:

```
thomas/server/web/js/app_runtime_primary.mjs   ← OLD monolith, NOT loaded by index.html
thomas/server/web/js/app_parts/part-*.js        ← Legacy string arrays, dead code
```

**`app_runtime_primary.mjs` is a pre-split monolith.** It was the runtime before the split into `js/runtime/` files. It is NOT loaded by `index.html`. Editing it does nothing. Do NOT add features here.

### How to verify which JS files are live:
```bash
# Check what index.html loads:
grep '<script' thomas/server/web/index.html

# Check the runtime loader manifest:
grep "'" thomas/server/web/js/app_runtime_loader.js | head -50

# Find which runtime file contains a function:
grep -rn "function myFunction" thomas/server/web/js/runtime/
```

## Rule: UI Cleanup — Delete Old Before Adding New

**When you create new UI code, you MUST remove or disable the old version it replaces.**

This is the single most common agent mistake in this codebase. The pattern:
1. Agent A builds a feature in file X
2. Agent B comes along, builds the same feature in file Y
3. Both versions are live. The browser renders whichever loads last, or both fight
4. User sees wrong/broken UI. Next agent is confused about which version is real.

**Before writing any new UI rendering code:**
1. Search for existing implementations: `grep -rn "<function_or_feature>" thomas/server/web/js/`
2. If you find one, FIX IT or REPLACE IT in-place. Do not create a parallel version.
3. If you must create a new file, DELETE or DISABLE the old rendering path in the same commit.
4. Verify with `grep` that no other file still calls the old version.

**You may NOT:**
- Create `feature_v2.js` alongside `feature.js`
- Add a new `mount()` function without removing the old one
- Leave old `window.__moduleName` exports live when you've moved the logic elsewhere
- Create new HTML template sections without removing the old HTML they replace

## Python — WHERE TO EDIT

### Direct source files (edit these):
```
thomas/orchestrator/brain.py       <- Direct file, changes take effect
thomas/specialists/*.py            <- Direct files
thomas/agent/dispatch.py           <- Direct file (new)
thomas/agent/chat_dispatcher.py    <- Direct file (new)
thomas/core/events.py              <- Direct file
```

### Monolith-loaded files (edit the PARTS, not the stub):
```
thomas/agent/loop.py               <- STUB — loads from loop_part01/02/03.py
thomas/server/routes/chat_aiohttp.py <- STUB — loads from chat_aiohttp_part01/02/03.py
scripts/crew/tasks/manager.py  <- STUB — loads from workboard_task_manager_part01/02/03/04.py
```

For monolith-loaded files, the stub file (e.g. `loop.py`) does NOT contain code. It loads from part files (e.g. `loop_part01.py`, `loop_part02.py`). Edit the PARTS.

### ALWAYS clear bytecache after editing:
```bash
find thomas -name "*.pyc" -delete
```

Python caches compiled `.pyc` files in `__pycache__/` directories. If you don't clear them, Python may load OLD code even after you edit the source.

### Placeholder files (CANNOT be edited):
```
thomas/memory/episodic.py          <- PLACEHOLDER (stub with hash padding)
thomas/memory/episodic_store.py    <- PLACEHOLDER
thomas/memory/summarization.py     <- PLACEHOLDER
```

These files are NOT real implementations. They're stubs. The runtime uses `.pyc` bytecache OR falls back to in-memory implementations defined in `thomas/memory/__init__.py`.

## Verification Checklist

Before committing any change:

1. **Is the file I edited the one that actually runs?**
   - JS runtime: Is it in `thomas/server/web/js/runtime/`? (the numbered files)
   - JS standalone: Is it loaded by a `<script>` tag in `index.html`?
   - JS dead code: `app_runtime_primary.mjs` and `app_parts/` are NOT live
   - Python: Is it a direct file or a monolith part?

2. **Did I remove the old version?**
   - If I added new UI code, is there an old version still live? REMOVE IT.
   - `grep` for the function/feature name across all JS files to confirm no duplicates.

3. **Did I clear the Python bytecache?**
   ```bash
   find thomas -name "*.pyc" -delete
   ```

4. **Does the user need to hard-refresh the browser?**
   - Yes, for any JS change: `Ctrl+Shift+R`

5. **Does the user need to restart the server?**
   - Yes, for any Python change: kill Python processes, run `run-ui.cmd`

## How the Monolith Source Loader Works (Python only)

```python
# In loop.py (the stub):
load_monolith_source(
    base_path=Path(__file__),
    part_files=("loop_part01.py", "loop_part02.py", "loop_part03.py"),
    namespace=globals(),
)
```

This reads the part files, concatenates them, and exec()s the result. The stub file's namespace gets populated with all the classes/functions from the parts. So `from thomas.agent.loop import AgentLoop` works even though AgentLoop is defined in `loop_part02.py`.

## Architecture Quick Reference

| Component | Where To Edit | How It Loads |
|-----------|--------------|-------------|
| Chat UI behavior | `js/runtime/010-014_*.js` | Split runtime loader |
| Settings UI | `js/runtime/040-045_*.js` | Split runtime loader |
| DOM refs & constants | `js/runtime/001_preamble.js` | Split runtime loader |
| Module rendering | `js/runtime/038-039_*.js` | Split runtime loader |
| Token Economy widget | `js/token_economy.js` | Direct `<script>` in index.html |
| Space background | `js/token_economy_space.js` | Direct `<script>` in index.html |
| Settings template | `js/templates/tpl_settings.js` | Direct `<script>` in index.html |
| Orchestrator brain | `thomas/orchestrator/brain.py` | Direct import |
| Specialists | `thomas/specialists/*.py` | Direct import |
| Agent loop | `thomas/agent/loop_part01/02/03.py` | Monolith loader |
| Chat route | `thomas/server/routes/chat_aiohttp_part01/02/03.py` | Monolith loader |
| Dispatch router | `thomas/agent/dispatch.py` | Direct import |
| Memory engine | `thomas/memory/__init__.py` | Direct (episodic is placeholder) |
| Workboard scripts | `scripts/workboard_*_part*.py` | Monolith loader |
