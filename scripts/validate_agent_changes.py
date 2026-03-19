#!/usr/bin/env python3
"""
Agent Safety Gate: Validate that AI agent changes don't break the codebase.

This script prevents common mistakes by AI agents:
- Editing dead code (app_parts/)
- Breaking JavaScript syntax (app_runtime_primary.mjs)
- Creating invalid Python files
- Editing monolith stub files
- Committing .pyc files
- Accidentally modifying placeholder files

Exit codes:
  0 = All checks passed
  1 = One or more checks failed
"""

import ast
import subprocess
import sys


def check_dead_code_not_edited(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Check that NO changes were made to thomas/server/web/js/app_parts/ (dead code).

    Returns: (passed, errors)
    """
    errors = []
    dead_code_dir = "thomas/server/web/js/app_parts/"

    edited_dead_files = [f for f in staged_files if f.startswith(dead_code_dir)]

    if edited_dead_files:
        errors.append("\n❌ SAFETY GATE FAILED: Dead Code Files Edited")
        errors.append("=" * 70)
        errors.append(f"You edited {len(edited_dead_files)} files in {dead_code_dir}")
        errors.append("These are DEAD CODE being migrated to modules.")
        errors.append("")
        errors.append("WHAT YOU DID WRONG:")
        for f in edited_dead_files:
            errors.append(f"  - {f}")
        errors.append("")
        errors.append("HOW TO FIX IT:")
        errors.append("1. Undo your changes to app_parts/ files:")
        errors.append("   git checkout -- thomas/server/web/js/app_parts/")
        errors.append("")
        errors.append("2. If you need to update app functionality, edit:")
        errors.append("   thomas/server/web/js/app_runtime_primary.mjs")
        errors.append("")
        errors.append("3. If adding new features, follow the module migration plan in GUARDRAILS.md")
        errors.append("=" * 70)
        return False, errors

    return True, []


def check_javascript_syntax(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Check that app_runtime_primary.mjs still has valid JS (no syntax errors).

    Returns: (passed, errors)
    """
    errors = []
    js_file = "thomas/server/web/js/app_runtime_primary.mjs"

    # Only check if the file was edited
    if js_file not in staged_files:
        return True, []

    # Use node.js to check syntax if available
    try:
        result = subprocess.run(["node", "--check", js_file], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            errors.append("\n❌ SAFETY GATE FAILED: JavaScript Syntax Error")
            errors.append("=" * 70)
            errors.append(f"File: {js_file}")
            errors.append("")
            errors.append("WHAT YOU DID WRONG:")
            errors.append("Your changes introduced JavaScript syntax errors.")
            errors.append("")
            errors.append("Error output:")
            errors.append(result.stderr)
            errors.append("")
            errors.append("HOW TO FIX IT:")
            errors.append("1. Review your changes to app_runtime_primary.mjs")
            errors.append("2. Check for:")
            errors.append("   - Missing semicolons")
            errors.append("   - Unmatched brackets or parentheses")
            errors.append("   - Invalid import/export syntax")
            errors.append("   - Typos in function or variable names")
            errors.append("3. Run: node --check thomas/server/web/js/app_runtime_primary.mjs")
            errors.append("4. Fix all errors until the check passes")
            errors.append("=" * 70)
            return False, errors
    except FileNotFoundError:
        # node.js not available, skip this check
        pass
    except subprocess.TimeoutExpired:
        errors.append("\n⚠️  WARNING: JavaScript syntax check timed out (node.js took too long)")
        pass

    return True, []


def check_python_syntax(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Check that all modified Python files parse correctly.

    Returns: (passed, errors)
    """
    errors = []
    python_files = [f for f in staged_files if f.endswith(".py")]

    if not python_files:
        return True, []

    failed_files = []
    for py_file in python_files:
        try:
            with open(py_file, encoding="utf-8") as f:
                code = f.read()
            ast.parse(code)
        except SyntaxError as e:
            failed_files.append((py_file, str(e)))
        except Exception as e:
            failed_files.append((py_file, f"Parse error: {str(e)}"))

    if failed_files:
        errors.append("\n❌ SAFETY GATE FAILED: Python Syntax Errors")
        errors.append("=" * 70)
        errors.append(f"Found {len(failed_files)} Python file(s) with syntax errors:")
        errors.append("")
        errors.append("WHAT YOU DID WRONG:")
        for py_file, error_msg in failed_files:
            errors.append(f"  - {py_file}")
            errors.append(f"    {error_msg}")
        errors.append("")
        errors.append("HOW TO FIX IT:")
        errors.append("1. Review each file listed above")
        errors.append("2. Check for:")
        errors.append("   - Indentation errors (Python is strict about whitespace)")
        errors.append("   - Missing colons after if/def/class/for/while statements")
        errors.append("   - Unclosed parentheses, brackets, or braces")
        errors.append("   - Invalid import statements")
        errors.append("3. Test each file with: python -m py_compile <filename>")
        errors.append("4. Fix all errors until compile succeeds")
        errors.append("=" * 70)
        return False, errors

    return True, []


def check_no_pyc_files(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Check that .pyc files aren't committed.

    Returns: (passed, errors)
    """
    errors = []
    pyc_files = [f for f in staged_files if f.endswith(".pyc")]

    if pyc_files:
        errors.append("\n❌ SAFETY GATE FAILED: Compiled Python Files Staged")
        errors.append("=" * 70)
        errors.append(f"Found {len(pyc_files)} .pyc file(s) in staging:")
        errors.append("")
        errors.append("WHAT YOU DID WRONG:")
        for f in pyc_files:
            errors.append(f"  - {f}")
        errors.append("")
        errors.append("HOW TO FIX IT:")
        errors.append("1. Remove compiled files from staging:")
        errors.append("   git reset HEAD -- '*.pyc'")
        errors.append("")
        errors.append("2. Delete local compiled files:")
        errors.append("   find . -name '__pycache__' -type d -exec rm -rf {} +")
        errors.append("   find . -name '*.pyc' -delete")
        errors.append("")
        errors.append("3. Ensure .gitignore includes:")
        errors.append("   __pycache__/")
        errors.append("   *.pyc")
        errors.append("=" * 70)
        return False, errors

    return True, []


def check_monolith_stubs_not_edited(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Check that no monolith stub files were directly edited (only parts should be edited).

    Monolith stub files are like __init__.py files that aggregate from parts.
    They should not be manually edited for feature work.

    Returns: (passed, errors)
    """
    errors = []

    # Monolith stub patterns (these are aggregation files, not feature files)
    monolith_stubs = [
        "thomas/server/web/js/app.js",
        "thomas/server/web/css/app.css",
    ]

    edited_stubs = [f for f in staged_files if f in monolith_stubs]

    if edited_stubs:
        errors.append("\n⚠️  WARNING: Monolith Stub Files Edited")
        errors.append("=" * 70)
        errors.append(f"You edited {len(edited_stubs)} monolith stub file(s):")
        errors.append("")
        errors.append("FILES EDITED:")
        for f in edited_stubs:
            errors.append(f"  - {f}")
        errors.append("")
        errors.append("WHAT THIS MEANS:")
        errors.append("These are aggregation/stub files that combine multiple modules.")
        errors.append("Direct edits to these files may be overwritten by build processes.")
        errors.append("")
        errors.append("RECOMMENDED APPROACH:")
        errors.append("1. If you're adding new features: create new module files")
        errors.append("2. If editing existing logic: find the appropriate module file")
        errors.append("3. Let the build system regenerate the stub files")
        errors.append("")
        errors.append("If you REALLY need to edit these, make sure you understand the build system.")
        errors.append("=" * 70)
        # Note: This is a warning, not a failure

    return True, []


def check_placeholder_files_not_modified(staged_files: list[str]) -> tuple[bool, list[str]]:
    """
    Warn if placeholder files (episodic.py, etc.) were modified.

    These are stub implementations that agents often accidentally "fix".

    Returns: (passed, errors) - Returns True because this is a warning, not a failure
    """
    errors = []

    placeholder_files = [
        "thomas/memory/episodic.py",
        "thomas/memory/episodic_store.py",
        "thomas/memory/summarization.py",
    ]

    modified_placeholders = [f for f in staged_files if f in placeholder_files]

    if modified_placeholders:
        errors.append("\n⚠️  WARNING: Placeholder Files Modified")
        errors.append("=" * 70)
        errors.append(f"You modified {len(modified_placeholders)} placeholder file(s):")
        errors.append("")
        errors.append("FILES MODIFIED:")
        for f in modified_placeholders:
            errors.append(f"  - {f}")
        errors.append("")
        errors.append("WHAT THIS MEANS:")
        errors.append("These files are PLACEHOLDER STUBS. They are not real implementations.")
        errors.append("They are intentionally minimal and should not be developed into real features.")
        errors.append("")
        errors.append("If you need to implement this functionality:")
        errors.append("1. Create a NEW file with a descriptive name (not in this list)")
        errors.append("2. Implement the full feature")
        errors.append("3. Update imports to use your new implementation")
        errors.append("4. Ask the user before deleting the placeholder file")
        errors.append("")
        errors.append("If you accidentally modified these, undo with:")
        errors.append("  git checkout HEAD -- " + " ".join(modified_placeholders))
        errors.append("=" * 70)
        # Note: Warning only, returns True

    return True, errors


def get_staged_files() -> list[str]:
    """Get list of files currently staged for commit."""
    try:
        result = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        pass
    return []


def main() -> int:
    """Run all safety checks. Return exit code."""
    staged_files = get_staged_files()

    if not staged_files:
        print("No staged files to check.")
        return 0

    print(f"Validating {len(staged_files)} staged file(s)...\n")

    all_errors = []
    all_warnings = []

    # Run all checks
    passed, errors = check_dead_code_not_edited(staged_files)
    if not passed:
        all_errors.extend(errors)

    passed, errors = check_javascript_syntax(staged_files)
    if not passed:
        all_errors.extend(errors)

    passed, errors = check_python_syntax(staged_files)
    if not passed:
        all_errors.extend(errors)

    passed, errors = check_no_pyc_files(staged_files)
    if not passed:
        all_errors.extend(errors)

    passed, errors = check_monolith_stubs_not_edited(staged_files)
    if errors:
        all_warnings.extend(errors)

    passed, errors = check_placeholder_files_not_modified(staged_files)
    if errors:
        all_warnings.extend(errors)

    # Print warnings
    if all_warnings:
        for line in all_warnings:
            print(line)
        print()

    # Print errors
    if all_errors:
        for line in all_errors:
            print(line)
        print()
        return 1

    if not all_warnings:
        print("✅ All safety checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
