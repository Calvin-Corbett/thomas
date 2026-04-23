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

ROOT = Path(__file__).resolve().parent.parent
PRECOMMIT_BREADCRUMB = ROOT / ".git" / "thomas_precommit_ran"
COMMIT_CLASS_ENV = "THOMAS_COMMIT_CLASS"

# Load protected file lists from config (agent_safety.toml).
# Falls back to empty lists if config doesn't exist.
try:
    try:
        from scripts.agent_safety_config import config as _cfg
    except (ImportError, ModuleNotFoundError):
        from agent_safety_config import config as _cfg

    IMMUTABLE_POLICY_FILES: tuple[str, ...] = tuple(
        _cfg.protected_immutable_policy_files() + _cfg.protected_guardrails_files() + _cfg.protected_enforcement_files()
    )
    RUNTIME_SENSITIVE_FILES: tuple[str, ...] = tuple(_cfg.protected_runtime_sensitive_files())
    RELEASE_SENSITIVE_FILES: tuple[str, ...] = tuple(_cfg.protected_release_sensitive_files())
    PROTECTED_FILES: tuple[str, ...] = tuple(
        _cfg.protected_immutable_policy_files()
        + _cfg.protected_runtime_sensitive_files()
        + _cfg.protected_release_sensitive_files()
        + _cfg.protected_guardrails_files()
        + _cfg.protected_enforcement_files()
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
        "agent_safety_config import failed — using hardcoded fallback. "
        "This may indicate a compromised config loader.",
        stacklevel=2,
    )
    IMMUTABLE_POLICY_FILES = (
        "GUARDRAILS.md",
        "AGENTS.md",
        "AGENT_RULES_QUICK_REFERENCE.md",
        "AGENT_SAFETY_GATES.md",
        "WORKTREE_RULES.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "agent_safety.toml",
        ".pre-commit-config.yaml",
        "tests/test_architecture.py",
        "thomas/_architecture.py",
        "docs/monolith_guard_baseline.json",
        "scripts/breakglass_auth.py",
        "thomas/tools/windows_auth.py",
        "docs/CHAT_EXECUTION_MODEL.md",
    )
    RUNTIME_SENSITIVE_FILES = (
        "thomas/core/task_bot_runtime.py",
        "thomas/agent/dispatch.py",
        "thomas/agent/chat_dispatcher.py",
        "thomas/preferences/_db.py",
        "thomas/preferences/_prefs.py",
        "thomas/preferences/guardrails_policy.py",
        "thomas/server/chat_acknowledgment.py",
        "thomas/server/chat_delegation.py",
        "thomas/server/routes/chat_aiohttp_streaming.py",
        "thomas/server/routes/chat_v2.py",
        "thomas/server/routes/task_events.py",
        "thomas/server/routes/preferences_aiohttp.py",
        "thomas/server/routes/third_party_agent_access_aiohttp.py",
    )
    RELEASE_SENSITIVE_FILES = (
        "thomas.toml",
        "thomas.prod.toml",
        "pyproject.toml",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "Dockerfile",
        ".gitignore",
    )
    PROTECTED_FILES = IMMUTABLE_POLICY_FILES + RUNTIME_SENSITIVE_FILES + RELEASE_SENSITIVE_FILES
    PROTECTED_ENFORCEMENT_SCRIPTS = (
        "scripts/validate_agent_changes.py",
        "scripts/check_protected_files_gate.py",
        "scripts/check_precommit_skip_policy.py",
        "scripts/check_exception_handler_gate.py",
        "scripts/agent_safety_config.py",
        "scripts/post_commit_audit.py",
        "scripts/agent_commit.py",
    )


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
    return _is_immutable_policy_doc(path)


def _commit_class() -> str:
    return str(os.getenv(COMMIT_CLASS_ENV, "") or "").strip().lower()


def _protected_category(path: str) -> str:
    normalized = _normalize_repo_path(path)
    if _is_immutable_policy_doc(path):
        return "immutable_policy"
    if normalized in set(PROTECTED_ENFORCEMENT_SCRIPTS):
        return "enforcement"
    if normalized in set(IMMUTABLE_POLICY_FILES):
        return "immutable_policy"
    if normalized in set(RUNTIME_SENSITIVE_FILES):
        return "runtime_sensitive"
    if normalized in set(RELEASE_SENSITIVE_FILES):
        return "release_sensitive"
    if normalized in set(PROTECTED_FILES):
        return "immutable_policy"
    return ""


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
    """Check if a human has temporarily disabled runtime protection."""
    try:
        try:
            from scripts.runtime_protection_toggle import runtime_protection_is_disabled
        except (ImportError, ModuleNotFoundError):
            from runtime_protection_toggle import runtime_protection_is_disabled  # type: ignore
    except ImportError:
        return False
    return bool(runtime_protection_is_disabled(ROOT))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    _drop_precommit_breadcrumb()

    # Honour the runtime protection toggle (requires Windows auth to disable).
    if _runtime_protection_disabled():
        if args.json:
            print(json.dumps({"gate": "protected_files_gate", "ok": True, "bypass": "runtime_protection_disabled"}))
        else:
            print("Protected files gate: PASS (runtime protection disabled by human)")
        return 0

    staged = _staged_files()
    all_protected = set(PROTECTED_FILES) | set(PROTECTED_ENFORCEMENT_SCRIPTS)
    violations: list[str] = []
    for path in staged:
        if not _is_protected_path(path, all_protected):
            continue
        violations.append(path)
    ok = len(violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "protected_files_gate",
                    "ok": ok,
                    "violations": violations,
                    "commit_class": _commit_class(),
                    "protected_file_count": len(all_protected),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print("Protected files gate: PASS")
        else:
            print("SAFETY GATE FAILED: Protected Policy Files Modified")
            print("=" * 70)
            print(f"You modified {len(violations)} protected file(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for path in violations:
                category = _protected_category(path)
                if _is_immutable_policy_doc(path):
                    print(f"  - {path}  (immutable policy document)")
                elif path == "tests/test_architecture.py":
                    print(f"  - {path}  (architecture enforcement - fix your code, not the test)")
                elif path.startswith("scripts/"):
                    print(f"  - {path}  (enforcement script - modifying this bypasses safety)")
                elif category == "runtime_sensitive":
                    print(f"  - {path}  (runtime-sensitive path)")
                elif category == "release_sensitive":
                    print(f"  - {path}  (release-sensitive path)")
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
            print()
            print("3. If a test in test_architecture.py fails:")
            print("   Fix your code to comply with the architecture.")
            print("   Do NOT modify the test to make your code pass.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
