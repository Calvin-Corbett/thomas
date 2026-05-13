# Thomas Guardrails — Immutable Rules for All Agents

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## What This File Is

This file contains rules that ALL AI agents (Claude, Codex, GPT, Gemini, etc.) MUST follow when working on Thomas. These rules exist because agents have repeatedly broken the codebase by:
- Making files too large (monoliths)
- Changing guard tests to pass instead of fixing the code
- Swallowing errors with bare `except Exception:`
- Creating duplicate code instead of checking existing code

## Rule 1: File Size Limits — ABSOLUTE, NO EXCEPTIONS

### Python Files
- **No Python file may exceed 800 lines (soft limit).** This triggers review.
- **No file may exceed 1500 lines under ANY circumstance (hard limit)** — not even with a debt annotation.
- The evolve loop's refactor pass will automatically target files exceeding these limits.

### Frontend Files
- **JavaScript (.js, .mjs, .cjs, .jsx, .ts, .tsx):** Max 800 lines (soft), 1500 lines (hard)
- **CSS (.css):** Max 600 lines (soft), 1600 lines (hard)
- **HTML (.html):** Max 1000 lines (hard)

### Per-Commit Growth Cap
- **No single file may grow by more than 300 lines in one commit.**
- This applies to ALL monitored file types (Python, JS, CSS, HTML).
- If you need to add more than 300 lines, split the work across multiple files or multiple commits with meaningful intermediate states.
- New files over 300 lines are also blocked — design smaller modules from the start.
- Enforced by: `scripts/forge/gates/commit_growth_guard.py`

### Bulk Commit Ban
- **No commit may stage more than 50 files.**
- "Snapshot", "checkpoint", or "dump" commits that touch hundreds of files are the #1 vector for smuggling monolith files past guards.
- If you genuinely need to commit 50+ files (e.g. a real migration), you must get explicit human approval and document the reason.
- Enforced by: `scripts/forge/gates/bulk_commit_guard.py`

### No Split/Part Files — ANY Language
- **Do not create files matching any of these patterns, in ANY language:**
  - `*_partNN.*` (e.g. `app_part3.py`, `styles_part1.css`)
  - `*.partNN.*` (e.g. `app.part2.js`)
  - `part-NNN.*` (e.g. `part-001.js`, `part-032b.js`)
  - Files inside directories named `*_parts/` or `*-parts/`
- This ban covers Python, JavaScript, CSS, HTML, TypeScript, and every other language.
- Chopping a large file into numbered chunks is not decomposition. Real decomposition means splitting by responsibility into modules with descriptive names and proper imports/exports.
- Enforced by: `scripts/forge/gates/monolith_filename_guard.py`

### General Rules
- If your implementation would exceed soft limits, you MUST split it into multiple files BEFORE writing it.
- **YOU MAY NOT:**
  - Add your file to the debt annotations in `_architecture.py` to bypass the limit
  - Modify `test_architecture.py` to increase the limit
  - Modify `MONOLITH_CEILING` or `max_file_lines_hard`
  - Create a "temporary exception" or "TODO to split later"
  - Use `--no-verify` to skip pre-commit hooks
  - Create a "snapshot" or "checkpoint" commit to dump bulk changes
- If you find yourself wanting to do any of the above, your design is wrong. Split the file.

## Rule 2: No Modifying Guards

- **`tests/test_architecture.py` is protected.** You may not modify it to make your code pass.
- **`thomas/_architecture.py` RULES dict is protected.** You may not change limits, add exceptions, or modify known_cycles to accommodate new circular dependencies.
- **Debt annotations:** You may ONLY add a debt annotation if the file ALREADY exceeds limits and you are DOCUMENTING existing debt, not creating new debt.
- If a test fails, fix your code. Not the test.

## Rule 3: Exception Handling — Be Specific

- **No bare `except Exception:` in new code.** Every new exception handler must catch a specific exception type.
- Acceptable: `except ConnectionError:`, `except ValueError:`, `except sqlite3.DatabaseError:`
- Unacceptable: `except Exception:`, `except BaseException:`, `except:`
- If you genuinely need a broad catch (e.g., top-level error boundary), you MUST:
  1. Log the exception with `logger.exception()`
  2. Add a comment: `# Broad catch: <reason why specific types aren't possible>`
  3. Re-raise if the error is not recoverable

## Rule 4: No Duplicate Work

- Before creating ANY new file, search for existing implementations.
- Check: `thomas/tools/`, `thomas/core/`, `thomas/integrations/`, `Inbox/`
- If a similar file exists, READ IT FIRST. Then extend or fix it.
- Do not create `utils_v2.py` or `helper_new.py`. Fix the original.

## Rule 5: Follow the Verification Protocol

After ANY change:
1. `python -c "import py_compile; py_compile.compile('path/to/file.py', doraise=True)"`
2. `python -m pytest tests/test_architecture.py -x --tb=short -q`
3. `python -m thomas serve --port 0` (verify boot)

If step 2 fails, FIX YOUR CODE. Do not modify the test.

## Rule 6: Changelog Is Mandatory

- After each logical unit of work, add a CHANGELOG.md entry IMMEDIATELY.
- Do not batch entries. Do not skip entries. Do not "add changelog later."
- Use Keep a Changelog format: [Added], [Changed], [Fixed], [Removed]

## Rule 7: No Numbered Stub Files

- Do not create files named `p001_*.py`, `p002_*.py`, etc.
- This legacy pattern is banned. Use descriptive names.

## Rule 8: Ask Before Deleting

- Before deleting ANY file: `grep -r '<filename>' thomas/ tests/ scripts/`
- If anything imports it, DO NOT DELETE IT.
- Stub with safe fallbacks first, then delete after confirming nothing breaks.

## Enforcement

These rules are enforced by:
- `tests/test_architecture.py` — Automated checks on every commit
- `thomas/_architecture.py` — Module registry and dependency rules
- Per-module `GUARDRAILS.md` files — Module-specific constraints
- **Human review** — The user reviews agent work and will reject violations

**Modifying enforcement mechanisms to bypass rules is itself a rule violation.**
**If you modify a guard to pass, you have NOT fixed the problem. You have hidden it.**
