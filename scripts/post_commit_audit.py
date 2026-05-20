#!/usr/bin/env python3
"""Post-commit audit: detect when pre-commit hooks were bypassed.

This script runs as a post-commit hook and checks whether the commit
that just happened was made with --no-verify (bypassing all pre-commit
gates). It cannot PREVENT the commit, but it:

1. Writes an audit record to .git/thomas_noverify_audit.jsonl
2. Prints a visible WARNING to the terminal
3. Tags the commit with a refnote so `git log` can surface bypasses

The goal is to make --no-verify usage visible and auditable, even if
it can't be blocked.

Detection method: Post-commit hooks always run (even with --no-verify).
We check whether the pre-commit hook's "I ran successfully" breadcrumb
exists. If it doesn't, pre-commit was bypassed.

Audit reference: Adversarial Audit Finding 7 (2026-03-19)
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BREADCRUMB_FILE = ROOT / ".git" / "thomas_precommit_ran"
AUDIT_LOG = ROOT / ".git" / "thomas_noverify_audit.jsonl"
AGENT_ENV_KEYS = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)
AGENT_CONTEXT_ENV_KEYS = AGENT_ENV_KEYS + (
    "CODEX_HOME",
    "CODEX_SESSION_ID",
)

# Keep this aligned with scripts/forge/gates/changelog_gate.py so post-commit
# audit can detect a bypassed missing changelog and auto-revert agent commits.
try:
    from scripts.crew.brief.safety_config import config as _cfg

    CHANGELOG_THRESHOLD = _cfg.changelog_threshold()
    CHANGELOG_PATH = _cfg.changelog_file()
    CODE_PREFIXES = tuple(d if d.endswith("/") else d + "/" for d in _cfg.source_dirs())
except ImportError:
    CHANGELOG_THRESHOLD = 3
    CHANGELOG_PATH = "CHANGELOG.md"
    CODE_PREFIXES = ("src/", "scripts/")

CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def _resolve_agent() -> str:
    for key in AGENT_ENV_KEYS:
        val = os.getenv(key, "").strip()
        if val:
            return val
    import getpass

    return getpass.getuser() or "unknown"


def _is_agent_context() -> bool:
    return any(os.getenv(key, "").strip() for key in AGENT_CONTEXT_ENV_KEYS)


def _staged_file_count_from_commit() -> int:
    """Count files changed in the commit that just happened."""
    output = _git(["diff", "--name-only", "HEAD~1", "HEAD"])
    if not output:
        return 0
    return len([line for line in output.splitlines() if line.strip()])


def _commit_changed_files() -> list[str]:
    output = _git(["diff", "--name-only", "HEAD~1", "HEAD"])
    if not output:
        return []
    return [line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()]


def _is_code_file(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/")
    if not any(normalized.startswith(prefix) for prefix in CODE_PREFIXES):
        return False
    return Path(normalized).suffix.lower() in CODE_EXTENSIONS


def _commit_missing_required_changelog() -> bool:
    changed = _commit_changed_files()
    code_files = [path for path in changed if _is_code_file(path)]
    threshold = max(1, CHANGELOG_THRESHOLD)
    return len(code_files) >= threshold and CHANGELOG_PATH.replace("\\", "/") not in changed


def main() -> None:
    # Check if pre-commit left its breadcrumb
    precommit_ran = BREADCRUMB_FILE.exists()

    if precommit_ran:
        # Pre-commit ran normally — clean up breadcrumb and exit
        with contextlib.suppress(OSError):
            BREADCRUMB_FILE.unlink()
        return

    # Pre-commit did NOT run — this commit bypassed hooks
    commit_hash = _git(["rev-parse", "HEAD"])
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    agent = _resolve_agent()
    file_count = _staged_file_count_from_commit()
    commit_msg = _git(["log", "-1", "--pretty=%s"])

    audit_record = {
        "gate": "noverify_audit",
        "timestamp_utc": _now_utc(),
        "commit": commit_hash,
        "branch": branch,
        "agent": agent,
        "files_changed": file_count,
        "commit_message": commit_msg[:200],
        "bypass_detected": True,
        "missing_changelog": _commit_missing_required_changelog(),
    }

    # Write audit log
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_record, sort_keys=True) + "\n")
    except OSError:
        pass

    # ── Auto-revert for agent bypasses ──────────────────────────────
    # If an agent (not a human) bypassed hooks, automatically revert
    # the commit. Humans can bypass intentionally; agents should not.
    # The reverted commit stays in reflog for forensics.
    # Audit reference: Cowork Adversarial Audit, Layer 2 (2026-03-19)
    is_agent = _is_agent_context()
    auto_reverted = False

    if is_agent:
        print()
        print("🛑" * 30)
        print("  AGENT HOOK BYPASS DETECTED — AUTO-REVERTING COMMIT")
        print("🛑" * 30)
        print()
        print(f"  Agent '{agent}' committed without pre-commit hooks.")
        print(f"  Commit {commit_hash[:12]} is being reverted automatically.")
        if audit_record["missing_changelog"]:
            print("  Reason: bypassed commit also skipped a required CHANGELOG update.")
        print()

        # Soft reset: undo the commit but keep the changes staged.
        # This way the agent's work isn't destroyed — it just can't
        # sneak it past the hooks.
        revert_result = subprocess.run(
            ["git", "reset", "--soft", "HEAD~1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if revert_result.returncode == 0:
            auto_reverted = True
            print("  Commit reverted (soft reset). Your changes are still staged.")
            print("  To commit properly, run WITHOUT --no-verify:")
            print('    python scripts/crew/brief/commit.py --message "<msg>"')
        else:
            print("  WARNING: Auto-revert failed. Manual review required.")
            print(f"  Error: {revert_result.stderr.strip()}")

        # Update audit record
        audit_record["auto_reverted"] = auto_reverted
        try:
            with AUDIT_LOG.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            **audit_record,
                            "event": "auto_revert",
                            "revert_success": auto_reverted,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        except OSError:
            pass

        print()
        print("🛑" * 30)
        return

    # ── Human bypass: warn but allow ────────────────────────────────
    print()
    print("⚠️" * 30)
    print("  WARNING: PRE-COMMIT HOOKS WERE BYPASSED")
    print("⚠️" * 30)
    print()
    print(f"  Commit:  {commit_hash[:12]}")
    print(f"  Branch:  {branch}")
    print(f"  Agent:   {agent}")
    print(f"  Files:   {file_count}")
    print(f"  Message: {commit_msg[:80]}")
    print()
    print("  This commit was made with --no-verify or pre-commit was")
    print("  otherwise bypassed. Safety gates did NOT run.")
    print()
    print("  Audit record written to: .git/thomas_noverify_audit.jsonl")
    print()
    print("  TO VERIFY THIS COMMIT IS SAFE:")
    print("    python scripts/validate_agent_changes.py")
    print("    python scripts/forge/gates/monolith_guard.py")
    print("    python scripts/forge/gates/exception_handler_gate.py")
    print("    python -m pytest tests/test_architecture.py -x --tb=short -q")
    print()
    print("⚠️" * 30)


if __name__ == "__main__":
    main()
