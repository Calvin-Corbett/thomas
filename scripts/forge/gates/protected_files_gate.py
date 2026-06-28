#!/usr/bin/env python3
"""Prevent agent modification of protected policy and enforcement files.

Protected files include:
- GUARDRAILS.md (all instances) - immutable policy docs
- AGENTS.md and related policy docs - startup and repo rules
- tests/test_architecture.py - architecture enforcement tests
- thomas/_architecture.py RULES section - architecture limits

These files contain rules that agents must follow but must not change.
An agent modifying these files is either:
  (a) trying to relax a rule to make their code pass, or
  (b) making an honest mistake.
Either way, the commit should be blocked and the human should decide.

Audit reference: Adversarial Audit Findings 12, 13, 16 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
PRECOMMIT_BREADCRUMB = ROOT / ".git" / "thomas_precommit_ran"
APPROVAL_TRAILERS = ("thomas-protected-files-approved:", "thomas-breakglass:")
COMMIT_MESSAGE_ENV = "THOMAS_COMMIT_MESSAGE"

# Load protected file lists from config (agent_safety.toml).
# Falls back to empty lists if config doesn't exist.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.brief.safety_config import config as _cfg

    PROTECTED_FILES: tuple[str, ...] = tuple(
        _cfg.protected_policy_files() + _cfg.protected_guardrails_files() + _cfg.protected_enforcement_files()
    )
    PROTECTED_ENFORCEMENT_SCRIPTS: tuple[str, ...] = tuple(_cfg.protected_enforcement_scripts())
except ImportError:
    # Fail-closed fallback: if config can't load, protect the critical files
    # that an attacker would most want to modify. This list must be kept in
    # sync with agent_safety.toml but provides a safety net if the config
    # loader itself is compromised.
    # Audit Finding 4 (Cowork Adversarial Audit, 2026-03-19).
    import warnings

    warnings.warn(
        "agent_safety_config import failed — using hardcoded fallback. This may indicate a compromised config loader.",
        stacklevel=2,
    )
    PROTECTED_FILES = (
        "GUARDRAILS.md",
        "AGENTS.md",
        "AGENT_RULES_QUICK_REFERENCE.md",
        "AGENT_SAFETY_GATES.md",
        "WORKTREE_RULES.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "agent_safety.toml",
        "pyproject.toml",
        ".pre-commit-config.yaml",
        ".gitignore",
        "tests/test_architecture.py",
        "thomas/_architecture.py",
        "docs/monolith_guard_baseline.json",
    )
    PROTECTED_ENFORCEMENT_SCRIPTS = (
        "scripts/validate_agent_changes.py",
        "scripts/forge/gates/protected_files_gate.py",
        "scripts/forge/gates/precommit_skip_policy.py",
        "scripts/forge/gates/exception_handler_gate.py",
        "scripts/crew/brief/safety_config.py",
        "scripts/post_commit_audit.py",
        "scripts/crew/brief/commit.py",
    )


def _changed_files(*, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Fail closed: a git error must not present as an empty change set --
        # for THIS gate that would let protected-file edits slip through as a
        # clean PASS. Surface it so run() FAILs instead.
        raise RuntimeError(proc.stderr.strip() or "git diff --name-only failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _staged_files() -> list[str]:
    return _changed_files()


def _commit_messages(base: str, head: str) -> list[str]:
    """Return commit messages for a CI/server-side diff range."""
    if base == head:
        return []
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%B%n---END---", f"{base}..{head}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [chunk.strip() for chunk in str(proc.stdout or "").split("---END---") if chunk.strip()]


def _protected_files_approval(messages: list[str]) -> tuple[bool, str, str]:
    """Find an explicit protected-file approval trailer in commit messages.

    Local staged commits still fail closed. This trailer path is only for
    server-side diff-range checks, where OS-native approval is unavailable but
    the authorization reason can be preserved in immutable commit history.
    """
    for msg in messages:
        for line in msg.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            for trailer in APPROVAL_TRAILERS:
                if not lowered.startswith(trailer):
                    continue
                reason = stripped.split(":", 1)[1].strip()
                if reason:
                    return True, trailer.rstrip(":"), reason
    return False, "", ""


def _normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def _is_protected_path(path: str, protected: set[str]) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    if normalized in protected:
        return True
    for item in protected:
        prefix = _normalize_repo_path(item)
        if prefix and str(item).replace("\\", "/").endswith("/") and normalized.startswith(f"{prefix}/"):
            return True
    return _is_immutable_policy_doc(path)


def _is_immutable_policy_doc(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    basename = PurePosixPath(normalized).name
    return basename in {"AGENTS.md", "GUARDRAILS.md"}


def _drop_precommit_breadcrumb() -> None:
    """Signal to post-commit audit that pre-commit hooks ran."""
    try:
        PRECOMMIT_BREADCRUMB.parent.mkdir(parents=True, exist_ok=True)
        PRECOMMIT_BREADCRUMB.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Presence alone is not enough — an unsigned planted flag must not
    disable this gate. Mirrors thomas.tools.filesystem signed-flag validation."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    _drop_precommit_breadcrumb()

    # Honour the runtime protection toggle (requires Windows auth to disable).
    if _runtime_protection_disabled():
        if args.json:
            print(json.dumps({"gate": "protected_files_gate", "ok": True, "bypass": "runtime_protection_disabled"}))
        else:
            print("Protected files gate: PASS (runtime protection disabled by human)")
        return 0

    try:
        staged = _changed_files(base=args.base, head=args.head) if args.base else _staged_files()
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"gate": "protected_files_gate", "ok": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"Protected files gate: FAIL ({exc})")
        return 1
    all_protected = set(PROTECTED_FILES) | set(PROTECTED_ENFORCEMENT_SCRIPTS)
    violations = [path for path in staged if _is_protected_path(path, all_protected)]
    approved = False
    approval_trailer = ""
    approval_reason = ""
    if violations and args.base and args.head:
        # Server-side (diff-range) approval lives in reviewed, immutable commit
        # history — that is a legitimate, human-reviewed authorization path.
        approved, approval_trailer, approval_reason = _protected_files_approval(_commit_messages(args.base, args.head))
    # NOTE (R4, praxis-unbypassable-2026-05-29): local staged commits have NO
    # env-based self-approval. An earlier THOMAS_COMMIT_MESSAGE path let an
    # agent self-approve a protected-file edit by setting an env var. Local
    # protected-file edits must go through the native-auth breakglass SKIP path
    # (Windows sign-in, audited) — see precommit_skip_policy / commit_breakglass_guard.
    ok = len(violations) == 0 or approved

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "protected_files_gate",
                    "ok": ok,
                    "violations": violations,
                    "approved_protected_files": approved,
                    "approval_trailer": approval_trailer,
                    "approval_reason": approval_reason,
                    "protected_file_count": len(all_protected),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            if approved:
                print(
                    "Protected files gate: PASS "
                    f"(protected-file approval via {approval_trailer}: {approval_reason[:120]})"
                )
            else:
                print("Protected files gate: PASS")
        else:
            print("SAFETY GATE FAILED: Protected Policy Files Modified")
            print("=" * 70)
            print(f"You modified {len(violations)} protected file(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for path in violations:
                if _is_immutable_policy_doc(path):
                    print(f"  - {path}  (immutable policy document)")
                elif path == "tests/test_architecture.py":
                    print(f"  - {path}  (architecture enforcement - fix your code, not the test)")
                elif path.startswith("scripts/"):
                    print(f"  - {path}  (enforcement script - modifying this bypasses safety)")
                else:
                    print(f"  - {path}  (protected policy document)")
            print()
            print("HOW TO FIX IT:")
            print("1. Undo your changes to protected files:")
            print("   git checkout HEAD -- " + " ".join(violations))
            print()
            print("2. If you believe a rule needs changing:")
            print("   STOP and ask the user. Do not proceed.")
            print("   Explain what rule you want to change and why.")
            if args.base and args.head:
                print()
                print("   For CI/server-side review after explicit human approval,")
                print("   include a non-empty commit trailer such as:")
                print("   Thomas-Protected-Files-Approved: <ticket or approval reason>")
            print()
            print("3. If a test in test_architecture.py fails:")
            print("   Fix your code to comply with the architecture.")
            print("   Do NOT modify the test to make your code pass.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
