#!/usr/bin/env python3
"""Enforce specific exception handling in new/modified Python code.

Scans staged Python files for bare `except:`, `except Exception:`, and
`except BaseException:` handlers. Broad handlers follow the policy in
`agent_safety.toml` and can require logging, re-raise, or both.

Uses a ratchet approach when enabled: only flags NEW violations in staged code
by comparing against HEAD. Existing violations in unchanged code are not
flagged, so this hook won't block work on legacy files while still keeping the
debt from growing.

See: GUARDRAILS.md Rule 3 - "Exception Handling - Be Specific"
Audit reference: Adversarial Audit Finding 1 (2026-03-19)
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path

try:
    from agent_safety_config import load_config
except ImportError:  # pragma: no cover
    from scripts.agent_safety_config import load_config  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

BROAD_EXCEPTION_TYPES = {"Exception", "BaseException"}
LOG_FUNCTION_NAMES = {"exception", "error", "critical", "fatal", "warning", "warn"}


def _config():
    return load_config()


def _require_specific_exceptions() -> bool:
    return bool(_config().require_specific_exceptions())


def _broad_catch_requires() -> set[str]:
    raw = _config().broad_catch_requires() or ["logging", "reraise"]
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _exception_ratchet() -> bool:
    return bool(_config().exception_ratchet())


def _staged_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _added_line_ranges(rel_path: str) -> set[int]:
    """Get the set of line numbers that are NEW in the staged version.

    Uses git diff --cached -U0 -M to find which lines were actually added
    (not just shifted). The -M flag enables rename detection so a moved
    file is not reported as a wholesale add+delete pair (which would mark
    every line of the destination as ``new``).

    Returns a set of line numbers (1-based) that are genuinely new.
    """
    import re

    proc = subprocess.run(
        ["git", "diff", "--cached", "-U0", "-M", "--", rel_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return set()

    added_lines: set[int] = set()
    for line in proc.stdout.splitlines():
        # Parse @@ hunk headers: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if hunk_match:
            start = int(hunk_match.group(1))
            count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            for i in range(start, start + count):
                added_lines.add(i)
    return added_lines


def _is_pure_rename(rel_path: str) -> bool:
    """True if rel_path is the destination of a pure rename (R100).

    A pure rename has identical content to its source -- the broad-except
    clauses inside it were not introduced by this commit, they were merely
    moved. The ratchet should not flag pre-existing violations as new.
    """
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M", "--", rel_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        # name-status output for rename: "R<similarity>\told_path\tnew_path"
        # R100 = identical content; R<100 means edits in addition to the move.
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith("R"):
            similarity_str = parts[0][1:]
            try:
                similarity = int(similarity_str)
            except ValueError:
                continue
            if similarity == 100 and parts[2] == rel_path:
                return True
    return False


def _git_show_head(rel_path: str) -> str | None:
    """Get the HEAD version of a file, or None if it doesn't exist."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _staged_content(rel_path: str) -> str | None:
    """Get the staged version of a file."""
    proc = subprocess.run(
        ["git", "show", f":{rel_path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _has_logging_call(body: list[ast.stmt]) -> bool:
    """Check if a handler body contains a logging call."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in LOG_FUNCTION_NAMES:
                return True
    return False


def _has_reraise(body: list[ast.stmt]) -> bool:
    """Check if a handler body contains a raise statement."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
    return False


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """Check if this catches Exception or BaseException."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name) and handler.type.id in BROAD_EXCEPTION_TYPES:
        return True
    return False


def _handler_satisfies_policy(handler: ast.ExceptHandler) -> bool:
    requires = _broad_catch_requires()
    if not requires:
        return True
    checks = {
        "logging": _has_logging_call(handler.body),
        "reraise": _has_reraise(handler.body),
    }
    return all(checks.get(requirement, False) for requirement in requires)


def _find_broad_handlers(source: str) -> list[int]:
    """Find line numbers of broad exception handlers that violate policy."""
    if not _require_specific_exceptions():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad_except(node):
            continue
        if not _handler_satisfies_policy(node):
            violations.append(node.lineno)
    return violations


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    staged = _staged_files()
    python_files = [f for f in staged if f.endswith(".py")]

    all_violations: list[dict[str, object]] = []
    ratchet_enabled = _exception_ratchet()

    for rel_path in python_files:
        staged_source = _staged_content(rel_path)
        if staged_source is None:
            continue

        staged_violations = set(_find_broad_handlers(staged_source))
        if not staged_violations:
            continue

        if ratchet_enabled:
            # Pure renames (R100) carry pre-existing violations forward by
            # definition -- nothing was introduced in this commit. Skip.
            if _is_pure_rename(rel_path):
                continue
            # Use diff hunks to determine which violations are truly new.
            # Only flag handlers whose line numbers fall within added hunks.
            # This eliminates false positives from handlers that merely
            # shifted position due to code inserted above them.
            added_lines = _added_line_ranges(rel_path)
            if added_lines:
                new_violations = {ln for ln in staged_violations if ln in added_lines}
            else:
                # No diff hunks available (new file or git issue) — flag all
                new_violations = staged_violations
        else:
            new_violations = staged_violations

        for lineno in sorted(new_violations):
            all_violations.append({"path": rel_path, "line": lineno})

    ok = len(all_violations) == 0
    requirements = sorted(_broad_catch_requires())

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "exception_handler_gate",
                    "ok": ok,
                    "violations": all_violations,
                    "files_scanned": len(python_files),
                    "require_specific_exceptions": _require_specific_exceptions(),
                    "broad_catch_requires": requirements,
                    "ratchet_enabled": ratchet_enabled,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Exception handler gate: PASS ({len(python_files)} file(s) scanned)")
        else:
            print("SAFETY GATE FAILED: Broad Exception Handlers Added")
            print("=" * 70)
            print(f"Found {len(all_violations)} new broad exception handler(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for violation in all_violations[:15]:
                print(
                    f"  - {violation['path']}:{violation['line']}  (except Exception / except: / except BaseException)"
                )
            if len(all_violations) > 15:
                print(f"  ... and {len(all_violations) - 15} more")
            print()
            print("HOW TO FIX IT:")
            print("1. Use a SPECIFIC exception type:")
            print("   OK   except ValueError:")
            print("   OK   except ConnectionError:")
            print("   OK   except sqlite3.DatabaseError:")
            print("   BAD  except Exception:")
            print("   BAD  except:")
            print()
            if requirements:
                print("2. If you genuinely need a broad catch (e.g., top-level error boundary),")
                req_phrase = " and ".join(requirements)
                print(f"   you MUST include {req_phrase}:")
                print("   except Exception as e:")
                if "logging" in requirements:
                    print('       logger.exception("Description of what failed")')
                if "reraise" in requirements:
                    print("       raise")
                print()
            print("See: GUARDRAILS.md Rule 3 and agent_safety.toml [exceptions]")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
