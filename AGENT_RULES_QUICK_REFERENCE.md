# Quick Reference: Rules for AI Agents Working on Thomas

## TL;DR — MUST-FOLLOW RULES

### ❌ DO NOT Edit These Files

1. **thomas/server/web/js/app_parts/** — DEAD CODE
   - Edit files in `thomas/server/web/js/runtime/` instead
   - Your changes WILL BE REJECTED by pre-commit

2. **thomas/server/web/js/app_runtime_primary.mjs** — DEAD CODE (LEGACY)
   - Pre-split monolith, not loaded by index.html
   - Edit files in `thomas/server/web/js/runtime/` instead
   - Your changes WILL BE REJECTED by pre-commit

3. **thomas/memory/episodic.py** — PLACEHOLDER STUB
   - Create a NEW file if you need real implementation
   - See: `thomas/memory/GUARDRAILS.md` Rule 9

4. **thomas/memory/episodic_store.py** — PLACEHOLDER STUB
   - Don't try to "complete" it
   - Create a new real implementation file instead

5. **thomas/memory/summarization.py** — PLACEHOLDER STUB
   - Same as above

6. **tests/test_architecture.py** — PROTECTED
   - Don't modify this to make tests pass
   - FIX YOUR CODE instead

7. **.pyc files** — NEVER
   - These are auto-compiled files
   - They will be rejected by pre-commit

### ✅ DO These Things

1. **Check GUARDRAILS.md in every directory you edit**
   - They document constraints for that module
   - They tell you what you can't do and why

2. **Keep Python files under 800 lines**
   - This is a HARD limit for new code
   - Existing monoliths are documented in GUARDRAILS.md
   - Don't add to them without planning a split

3. **Keep JavaScript files under 2000 lines**
   - Soft limit: 800 lines
   - Hard limit: 2000 lines

4. **Use specific exception handlers**
   - ✅ `except ValueError:`
   - ❌ `except Exception:`
   - ❌ `except:`

5. **Test your code**
   ```bash
   # Syntax check Python files
   python -m py_compile thomas/your_file.py

   # Run architecture tests
   python -m pytest tests/test_architecture.py -x --tb=short -q

   # Run agent safety tests
   python -m pytest tests/test_agent_safety.py -v
   ```

6. **Verify before committing**
   ```bash
   # Check what you're about to commit
   python scripts/validate_agent_changes.py
   ```

## File Size Limits by Type

| File Type | Soft Limit | Hard Limit |
|-----------|-----------|-----------|
| Python | 800 lines | 1200 lines |
| JavaScript | 800 lines | 2000 lines |
| CSS | 600 lines | 1200 lines |
| HTML | 2000 lines | 3000 lines |

## Pre-Commit Safety Gates

When you run `git commit`, these checks run automatically:

1. ✅ No edits to `thomas/server/web/js/app_parts/`
2. ✅ No JavaScript syntax errors in `app_runtime_primary.mjs`
3. ✅ No Python syntax errors in any modified files
4. ✅ No `.pyc` files being committed
5. ⚠️  Warning if placeholder files are edited
6. ⚠️  Warning if monolith stubs are edited

**If a check fails, your commit is REJECTED.**

The error message tells you:
- WHAT YOU DID WRONG
- HOW TO FIX IT

## Error Message: Example

```
❌ SAFETY GATE FAILED: Dead Code Files Edited
========================================================
You edited 1 files in thomas/server/web/js/app_parts/
These are DEAD CODE being migrated to modules.

WHAT YOU DID WRONG:
  - thomas/server/web/js/app_parts/part-001.js

HOW TO FIX IT:
1. Undo your changes to app_parts/ files:
   git checkout -- thomas/server/web/js/app_parts/

2. If you need to update app functionality, edit:
   thomas/server/web/js/app_runtime_primary.mjs

3. If adding new features, follow the module migration plan in GUARDRAILS.md
========================================================
```

## Where to Find Rules

- **Master rules:** `/Thomas/GUARDRAILS.md`
- **Server rules:** `thomas/server/GUARDRAILS.md`
- **Memory rules:** `thomas/memory/GUARDRAILS.md`
- **Agent rules:** `thomas/agent/GUARDRAILS.md`
- **Module rules:** Look for `GUARDRAILS.md` in each module directory
- **Safety gate details:** `/Thomas/AGENT_SAFETY_GATES.md`

## If You Get Stuck

1. **Read the GUARDRAILS.md in your module**
   - It explains what you can and can't do
   - It has suggested solutions

2. **Look at your error message**
   - It tells you exactly what's wrong
   - It tells you how to fix it

3. **Ask the user**
   - If you're unsure about a constraint
   - If you think a rule needs to change
   - If the error message isn't clear

## Key Files to Know

- `scripts/validate_agent_changes.py` — The safety gate script
- `.pre-commit-config.yaml` — Where safety gates are registered
- `tests/test_agent_safety.py` — Continuous safety verification
- `GUARDRAILS.md` — Rules for all agents (master file)
- `AGENT_SAFETY_GATES.md` — Explanation of the safety system

## One More Thing

**These rules exist because agents have repeatedly broken the codebase.**

They protect:
- Code stability
- Architecture integrity
- Readability and maintainability
- Future developer productivity

Following them isn't punishment—it's how we keep things working.
