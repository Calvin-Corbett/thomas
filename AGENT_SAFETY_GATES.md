# Thomas Agent Safety Gates

This document explains the safety mechanisms put in place to prevent AI agents from breaking the codebase.

## Overview

The Thomas project has specific architectural constraints that must be maintained. AI agents, while helpful, can accidentally violate these constraints by:
- Editing dead code files
- Breaking JavaScript syntax
- Creating unparseable Python code
- Accidentally "completing" placeholder implementations
- Modifying monolith stubs

To prevent these issues, we've implemented **safety gates** that automatically reject problematic changes.

## Safety Gate Components

### 1. Pre-Commit Validation Script

**File:** `scripts/validate_agent_changes.py`

This script runs automatically before each commit and checks:

1. **Dead Code Check** — No changes to `thomas/server/web/js/app_parts/`
   - These files are legacy code being migrated
   - Agents must edit `app_runtime_primary.mjs` instead
   - If violated: Commit is REJECTED

2. **JavaScript Syntax Check** — `app_runtime_primary.mjs` has valid JS
   - Uses `node --check` to validate syntax
   - Catches typos and bracket mismatches
   - If violated: Commit is REJECTED

3. **Python Syntax Check** — All modified Python files parse correctly
   - Uses `ast.parse()` to validate Python syntax
   - Catches indentation errors and syntax mistakes
   - If violated: Commit is REJECTED

4. **No .pyc Files** — Compiled Python files are not committed
   - `.pyc` files are auto-generated, never committed
   - If violated: Commit is REJECTED

5. **Monolith Stub Warning** — Alerts if aggregation files are edited
   - Files like `app.js`, `app.css` are build outputs
   - Manual edits may be overwritten
   - Warning only, doesn't block commit

6. **Placeholder File Warning** — Alerts if stubs are modified
   - `episodic.py`, `episodic_store.py`, `summarization.py` are placeholders
   - Should not be "completed" into real features
   - Warning only, doesn't block commit

### 2. Pre-Commit Hook Configuration

**File:** `.pre-commit-config.yaml`

The validation script is registered as a pre-commit hook under:
```yaml
- id: thomas-agent-safety-validation
  name: Thomas Agent Safety Validation
  entry: python scripts/validate_agent_changes.py
```

When you run `git commit`, this hook runs automatically before the commit is created.

### 3. GUARDRAILS.md Files

Strategic GUARDRAILS.md files in critical directories warn agents about constraints:

- **thomas/server/web/js/app_parts/GUARDRAILS.md**
  - Warns agents NOT to edit files in this directory
  - Points them to `app_runtime_primary.mjs` instead

- **thomas/memory/GUARDRAILS.md**
  - Updated with Rule 9 about placeholder files
  - Explains why `episodic.py`, etc. should not be modified
  - Documents the proper approach for implementing new memory features

- **thomas/server/GUARDRAILS.md, thomas/agent/GUARDRAILS.md, etc.**
  - Module-specific constraints for all teams

### 4. Automated Test Suite

**File:** `tests/test_agent_safety.py`

This pytest suite includes:

1. **test_app_parts_not_modified**
   - Verifies no manual edits to dead code files
   - Checks file modification times

2. **test_app_runtime_primary_has_valid_javascript**
   - Validates JavaScript syntax

3. **test_all_python_files_parse_correctly**
   - Ensures no syntax errors in Python

4. **test_placeholder_files_not_modified**
   - Verifies placeholder files remain stubs (under 400 lines)
   - Prevents accidental feature implementation

5. **test_monolith_files_within_limits**
   - Prevents monolith files from growing unbounded
   - Enforces line limits from architecture rules

6. **test_guardrails_files_exist_and_readable**
   - Ensures guardrails documentation is in place
   - Verifies they mention agent constraints

Run tests with:
```bash
python -m pytest tests/test_agent_safety.py -v
```

## What Agents See

When an agent attempts to break a safety gate, they see clear error messages:

### Example: Editing Dead Code

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

### Example: Python Syntax Error

```
❌ SAFETY GATE FAILED: Python Syntax Errors
========================================================
Found 1 Python file(s) with syntax errors:
  - thomas/memory/new_feature.py
    unexpected indent (line 45)

HOW TO FIX IT:
1. Review each file listed above
2. Check for:
   - Indentation errors (Python is strict about whitespace)
   - Missing colons after if/def/class/for/while statements
   - Unclosed parentheses, brackets, or braces
   - Invalid import statements
3. Test each file with: python -m py_compile <filename>
4. Fix all errors until compile succeeds
========================================================
```

## How the Safety System Works

1. **Staging Phase**
   - Agent makes changes to files
   - Agent runs `git add <files>` to stage changes

2. **Pre-Commit Hook Triggers**
   - `git commit` automatically runs the validation script
   - Script gets list of staged files from `git diff --cached --name-only`

3. **Validation Checks**
   - Script runs all checks listed above
   - If any check fails: commit is REJECTED and agent sees error message
   - If all checks pass: commit proceeds normally

4. **Test Suite Verification**
   - Tests run in CI/CD and on developer machines
   - Provides redundant safety verification
   - Catches issues the pre-commit script might miss

## Architecture Files This Protects

The safety gates enforce rules documented in:

- **GUARDRAILS.md** — Master guardrails for all agents
  - Rule 1: File size limits (no monoliths)
  - Rule 2: Don't modify guards/tests
  - Rule 3: Specific exception handling
  - And more...

- **Module-specific GUARDRAILS.md**
  - Server constraints (`thomas/server/GUARDRAILS.md`)
  - Memory constraints (`thomas/memory/GUARDRAILS.md`)
  - Agent constraints (`thomas/agent/GUARDRAILS.md`)
  - And more for each module...

## For Developers

### If Your Commit Is Rejected

1. **Read the error message carefully** — It tells you EXACTLY what went wrong
2. **Follow the "HOW TO FIX IT" section** — Step-by-step instructions
3. **Fix the issue** and commit again

Example:
```bash
# You get an error about editing app_parts/
$ git commit
❌ SAFETY GATE FAILED: Dead Code Files Edited
...
# Follow the HOW TO FIX IT section:
$ git checkout -- thomas/server/web/js/app_parts/
$ git add thomas/server/web/js/app_runtime_primary.mjs
$ git commit
# Now it works!
```

### Disabling Safety Gates (Not Recommended)

If you absolutely must bypass a safety gate, you can:

```bash
git commit --no-verify
```

**⚠️ WARNING:** This disables ALL pre-commit hooks, not just the safety gates.
Only do this if:
- You understand the architectural constraints
- You have a valid reason to violate them
- You've discussed it with the team

### Adding New Safety Gates

To add a new safety gate:

1. Edit `scripts/validate_agent_changes.py`
2. Add a new check function following the pattern:
   ```python
   def check_your_constraint(staged_files: List[str]) -> Tuple[bool, List[str]]:
       """Your check here."""
       errors = []
       # ... validation logic ...
       if violation_detected:
           errors.append("❌ SAFETY GATE FAILED: Your constraint")
           errors.append("HOW TO FIX IT: ...")
       return len(errors) == 0, errors
   ```
3. Call it from `main()`:
   ```python
   passed, errors = check_your_constraint(staged_files)
   if not passed:
       all_errors.extend(errors)
   ```

4. Add a corresponding test to `tests/test_agent_safety.py`

## FAQ

### Q: Can I disable the validation script?

A: Technically yes (use `--no-verify`), but you shouldn't. These gates exist because agents have repeatedly broken the codebase. They protect your code.

### Q: What if a safety gate is wrong?

A: If you believe a safety gate is incorrectly rejecting valid changes:
1. Discuss it with the team
2. Show why the constraint doesn't apply to your case
3. Update the safety gate with better logic
4. Document the exception in GUARDRAILS.md

### Q: Do agents see these files?

A: Yes! Agents see GUARDRAILS.md files when they navigate directories. The validation script error messages are also clear and actionable.

### Q: What happens if I bypass the gate?

A: The CI/CD pipeline should catch the violation with `test_agent_safety.py`. If not, the codebase may break and future developers will have a harder time.

### Q: How do I test my changes before committing?

A: Run the validation script manually:
```bash
python scripts/validate_agent_changes.py
```

Or run the test suite:
```bash
python -m pytest tests/test_agent_safety.py -v
```

## Summary

The Thomas safety gates provide defense-in-depth protection:

1. **GUARDRAILS.md files** — Passive warnings visible to agents
2. **Validation script** — Active blocker at commit time
3. **Test suite** — Continuous verification and documentation
4. **Clear error messages** — Guides agents to the fix

Together, these mechanisms create a "culture of safety" where agents understand the constraints and can fix issues quickly.
