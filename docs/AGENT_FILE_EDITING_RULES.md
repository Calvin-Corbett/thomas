# Agent File Editing Rules — READ BEFORE CHANGING ANYTHING

> **CRITICAL FOR ALL AI AGENTS WORKING ON THIS PROJECT.**
> If you skip this doc, your changes WILL NOT WORK.

Last updated: 2026-03-18

## The #1 Rule

**Before editing any file, verify you're editing the file that ACTUALLY runs in production.**

This project uses a monolith source loader pattern that splits large files into parts. There are MULTIPLE copies of the same code in different locations. If you edit the wrong copy, your changes do nothing.

## JavaScript — WHERE TO EDIT

### The ONLY file the browser loads:
```
thomas/server/web/js/app_runtime_primary.mjs  (41K lines)
```
This is THE runtime. All UI behavior lives here. Edit this file.

### Files that look like source but ARE NOT loaded by the browser:
```
thomas/server/web/js/app_parts/part-*.js       ← STRING ARRAYS, not real JS
thomas/server/web/js/src/runtime_modules/*.js   ← Loaded separately, some work
```

The `app_parts/` files are string arrays (arrays of strings that look like code). They are template fragments. Editing them **DOES NOT** change what the browser runs. They may have been used by a build tool at some point but `app_runtime_primary.mjs` is the live file now.

The `src/runtime_modules/` files ARE loaded separately and DO take effect. Check if the function you're editing is in `app_runtime_primary.mjs` or in a runtime module.

### How to verify:
```bash
# Is my function in the runtime file?
grep -n "function myFunction" thomas/server/web/js/app_runtime_primary.mjs

# Or in a runtime module?
grep -rn "function myFunction" thomas/server/web/js/src/runtime_modules/
```

## Python — WHERE TO EDIT

### Direct source files (edit these):
```
thomas/orchestrator/brain.py       ← Direct file, changes take effect
thomas/specialists/*.py            ← Direct files
thomas/agent/dispatch.py           ← Direct file (new)
thomas/agent/chat_dispatcher.py    ← Direct file (new)
thomas/core/events.py              ← Direct file
```

### Monolith-loaded files (edit the PARTS, not the stub):
```
thomas/agent/loop.py               ← STUB — loads from loop_part01/02/03.py
thomas/server/routes/chat_aiohttp.py ← STUB — loads from chat_aiohttp_part01/02/03.py
scripts/workboard_task_manager.py  ← STUB — loads from workboard_task_manager_part01/02/03/04.py
```

For monolith-loaded files, the stub file (e.g. `loop.py`) does NOT contain code. It loads from part files (e.g. `loop_part01.py`, `loop_part02.py`). Edit the PARTS.

### ALWAYS clear bytecache after editing:
```bash
find thomas -name "*.pyc" -delete
```

Python caches compiled `.pyc` files in `__pycache__/` directories. If you don't clear them, Python may load OLD code even after you edit the source.

### Placeholder files (CANNOT be edited):
```
thomas/memory/episodic.py          ← PLACEHOLDER (stub with hash padding)
thomas/memory/episodic_store.py    ← PLACEHOLDER
thomas/memory/summarization.py     ← PLACEHOLDER
```

These files are NOT real implementations. They're stubs. The runtime uses `.pyc` bytecache OR falls back to in-memory implementations defined in `thomas/memory/__init__.py`.

## Verification Checklist

Before committing any change:

1. **Is the file I edited the one that actually runs?**
   - JS: Is it `app_runtime_primary.mjs` or a `src/runtime_modules/` file?
   - Python: Is it a direct file or a monolith part?

2. **Did I clear the Python bytecache?**
   ```bash
   find thomas -name "*.pyc" -delete
   ```

3. **Does the user need to hard-refresh the browser?**
   - Yes, for any JS change: `Ctrl+Shift+R`

4. **Does the user need to restart the server?**
   - Yes, for any Python change: kill Python processes, run `run-ui.cmd`

## How the Monolith Source Loader Works

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
| Chat UI behavior | `app_runtime_primary.mjs` | Browser loads directly |
| Chat UI init | `src/runtime_modules/008_init.js` | Loaded as module |
| Orchestrator brain | `thomas/orchestrator/brain.py` | Direct import |
| Specialists | `thomas/specialists/*.py` | Direct import |
| Agent loop | `thomas/agent/loop_part01/02/03.py` | Monolith loader |
| Chat route | `thomas/server/routes/chat_aiohttp_part01/02/03.py` | Monolith loader |
| Dispatch router | `thomas/agent/dispatch.py` | Direct import |
| Memory engine | `thomas/memory/__init__.py` | Direct (episodic is placeholder) |
| Workboard scripts | `scripts/workboard_*_part*.py` | Monolith loader |
