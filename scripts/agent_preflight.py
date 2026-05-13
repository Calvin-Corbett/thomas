#!/usr/bin/env python3
"""Classify local environment readiness for Thomas agent work."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from thomas.benchmarks.benchmark_lane import get_benchmark_context

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_safety_config import load_config
from scripts.forge.gates.repo_hygiene import evaluate_worktree_change_budget

REPO_MARKERS = (
    "pyproject.toml",
    "thomas/__init__.py",
    "AGENTS.md",
)
STATUS_ORDER = {"ok": 0, "degraded": 1, "blocked": 2}
DIRTY_WORKTREE_OVERRIDE_ENV_KEYS = ("THOMAS_ALLOW_DIRTY_WORKTREE", "THOMAS_DIRTY_WORKTREE_OVERRIDE")


def _is_truthy(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _dirty_worktree_override_enabled() -> bool:
    return any(_is_truthy(os.getenv(key, "")) for key in DIRTY_WORKTREE_OVERRIDE_ENV_KEYS)


def _result(check_id: str, status: str, message: str, *, user_action: str = "") -> dict[str, str]:
    return {
        "id": check_id,
        "status": status,
        "message": message,
        "user_action": user_action,
    }


def _overall_status(checks: list[dict[str, str]]) -> str:
    highest = max((STATUS_ORDER.get(str(check.get("status") or "ok"), 0) for check in checks), default=0)
    for name, rank in STATUS_ORDER.items():
        if rank == highest:
            return name
    return "ok"


def _summary(checks: list[dict[str, str]]) -> str:
    counts = {
        "blocked": sum(1 for check in checks if check["status"] == "blocked"),
        "degraded": sum(1 for check in checks if check["status"] == "degraded"),
        "ok": sum(1 for check in checks if check["status"] == "ok"),
    }
    parts = [f"{counts[name]} {name}" for name in ("blocked", "degraded", "ok") if counts[name]]
    return ", ".join(parts) if parts else "0 checks"


def _policy(status: str) -> dict[str, Any]:
    if status == "blocked":
        summary = "Stop before editing. Tell the user which environment blockers must be resolved or explicitly waived."
    elif status == "degraded":
        summary = "Tell the user the environment is degraded before using slower or lower-confidence fallbacks."
    else:
        summary = "Environment checks passed. Normal edit and verification flow is allowed."
    return {
        "summary": summary,
        "can_edit": status != "blocked",
        "report_before_fallback": status == "degraded",
        "stop_before_edit": status == "blocked",
    }


def _check_repo_layout(root: Path) -> dict[str, str]:
    missing = [marker for marker in REPO_MARKERS if not (root / marker).exists()]
    if missing:
        return _result(
            "repo-layout",
            "blocked",
            f"Missing repo markers: {', '.join(missing)}.",
            user_action="Reopen the Thomas repository root before editing.",
        )
    return _result("repo-layout", "ok", f"Repo markers found under {root}.")


def _check_git_root(root: Path) -> dict[str, str]:
    git_path = shutil.which("git")
    if not git_path:
        return _result(
            "git-root",
            "degraded",
            "git is not available on PATH.",
            user_action="Install git or start the session in an environment where git is available.",
        )
    try:
        result = subprocess.run(
            [git_path, "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return _result(
            "git-root",
            "degraded",
            f"git could not resolve the repository root: {exc}.",
            user_action="Fix git access before relying on commit or diff based workflows.",
        )
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip() or "git rev-parse failed"
        return _result(
            "git-root",
            "degraded",
            f"git could not resolve the repository root: {stderr_text}.",
            user_action="Fix git access before relying on commit or diff based workflows.",
        )
    actual_root = Path((result.stdout or "").strip()).resolve()
    expected_root = root.resolve()
    if actual_root != expected_root:
        return _result(
            "git-root",
            "blocked",
            f"git resolved a different repository root: {actual_root}.",
            user_action=f"Open the intended worktree at {expected_root}.",
        )
    return _result("git-root", "ok", f"git repo root resolves to {actual_root}.")


def _check_cwd(root: Path, cwd: Path | None = None) -> dict[str, str]:
    expected_root = root.resolve()
    actual_cwd = (cwd or Path.cwd()).resolve()
    if actual_cwd == expected_root:
        return _result("cwd", "ok", f"Current working directory matches repo root: {actual_cwd}.")
    try:
        relative = actual_cwd.relative_to(expected_root)
    except ValueError:
        return _result(
            "cwd",
            "degraded",
            f"Current working directory is outside repo root: {actual_cwd}.",
            user_action=f"Start commands from {expected_root} to avoid path-sensitive drift.",
        )
    return _result(
        "cwd",
        "degraded",
        f"Current working directory is nested under repo root: {relative}.",
        user_action=f"Start commands from {expected_root} so repo-relative tooling is predictable.",
    )


def _check_ripgrep() -> dict[str, str]:
    rg_path = shutil.which("rg")
    if not rg_path:
        return _result(
            "rg",
            "degraded",
            "ripgrep (rg) is not available on PATH.",
            user_action="Install ripgrep or fix PATH before relying on repo-wide search.",
        )
    try:
        result = subprocess.run(
            [rg_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return _result(
            "rg",
            "degraded",
            f"ripgrep exists but could not execute: {exc}.",
            user_action="Repair ripgrep permissions before using search fallbacks.",
        )
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip() or "rg --version failed"
        return _result(
            "rg",
            "degraded",
            f"ripgrep exists but did not start cleanly: {stderr_text}.",
            user_action="Repair ripgrep before using slower search fallbacks.",
        )
    lines = (result.stdout or "").splitlines()
    first_line = lines[0].strip() if lines else "ripgrep available"
    return _result("rg", "ok", f"{first_line} ({rg_path}).")


def _repo_python_path(root: Path) -> Path:
    """Return the repo virtualenv Python path, platform-aware."""
    import platform

    if platform.system() == "Windows":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _check_repo_python(root: Path) -> dict[str, str]:
    python_path = _repo_python_path(root)
    if not python_path.exists():
        return _result(
            "repo-python",
            "degraded",
            f"Repo virtualenv interpreter is missing: {python_path}.",
            user_action="Create or restore the repo .venv before using non-canonical interpreters.",
        )
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import sys; print(sys.version.split()[0])"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return _result(
            "repo-python",
            "degraded",
            f"Repo virtualenv interpreter could not start: {exc}.",
            user_action="Repair the repo .venv before switching to a fallback interpreter.",
        )
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip() or "repo python startup failed"
        return _result(
            "repo-python",
            "degraded",
            f"Repo virtualenv interpreter failed to start: {stderr_text}.",
            user_action="Repair the repo .venv before switching to a fallback interpreter.",
        )
    version = (result.stdout or "").strip() or "unknown"
    return _result("repo-python", "ok", f"Repo virtualenv interpreter is available ({version}).")


def _check_repo_pytest(root: Path) -> dict[str, str]:
    python_path = _repo_python_path(root)
    if not python_path.exists():
        return _result(
            "repo-pytest",
            "degraded",
            "Cannot verify pytest in the repo virtualenv because the repo interpreter is missing.",
            user_action="Install test dependencies in the repo .venv before using another interpreter.",
        )
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import pytest; print(pytest.__version__)"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return _result(
            "repo-pytest",
            "degraded",
            f"pytest validation could not start in the repo virtualenv: {exc}.",
            user_action="Repair the repo .venv before using a fallback test runner.",
        )
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip() or "pytest import failed"
        return _result(
            "repo-pytest",
            "degraded",
            f"pytest is unavailable in the repo virtualenv: {stderr_text}.",
            user_action="Install pytest in the repo .venv before falling back to another interpreter.",
        )
    version = (result.stdout or "").strip() or "unknown"
    return _result("repo-pytest", "ok", f"pytest is available in the repo virtualenv ({version}).")


def _check_worktree_clean(root: Path) -> dict[str, str]:
    """Check that the git worktree has no uncommitted changes.

    WORKTREE_RULES.md Rule 8 says agents must not start implementation
    work in a dirty worktree. This check makes the state visible so agents
    know what they're working with.

    Returns 'blocked' by default because AGENTS.md forbids normal
    implementation work in a dirty worktree. An explicit override downgrades
    the result to 'degraded' for cleanup/remediation lanes only.

    Audit reference: Adversarial Audit Finding 11 (2026-03-19)
    """
    git_path = shutil.which("git")
    if not git_path:
        return _result(
            "worktree-clean",
            "degraded",
            "Cannot check worktree state: git is not available.",
        )
    try:
        result = subprocess.run(
            [git_path, "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _result(
            "worktree-clean",
            "degraded",
            "git status timed out — worktree state unknown (large repo or slow filesystem).",
            user_action="Run git status manually to check for uncommitted changes.",
        )
    except OSError as exc:
        return _result(
            "worktree-clean",
            "degraded",
            f"Cannot check worktree state: {exc}.",
        )
    if result.returncode != 0:
        return _result(
            "worktree-clean",
            "degraded",
            "git status failed — cannot verify worktree state.",
        )
    dirty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if dirty_lines:
        config = load_config()
        try:
            change_budget = evaluate_worktree_change_budget(
                root,
                dirty_lines,
                max_changed_lines=config.worktree_max_uncommitted_changed_lines(),
                ignore_prefixes=config.worktree_change_budget_ignore_prefixes(),
            )
        except Exception:
            change_budget = {
                "ok": True,
                "threshold": config.worktree_max_uncommitted_changed_lines(),
                "total_changed_lines": 0,
                "violations": [],
            }
        # Categorize the dirty state
        modified = sum(1 for line in dirty_lines if line[0:2].strip() in ("M", "MM", "AM"))
        untracked = sum(1 for line in dirty_lines if line.startswith("??"))
        staged = sum(1 for line in dirty_lines if line[0] in ("A", "M", "D", "R") and line[1] == " ")
        summary_parts = []
        if modified:
            summary_parts.append(f"{modified} modified")
        if untracked:
            summary_parts.append(f"{untracked} untracked")
        if staged:
            summary_parts.append(f"{staged} staged")
        summary = ", ".join(summary_parts) if summary_parts else f"{len(dirty_lines)} changed"
        total_changed_lines = int(change_budget.get("total_changed_lines", 0) or 0)
        threshold = int(change_budget.get("threshold", 0) or 0)
        if total_changed_lines > threshold:
            return _result(
                "worktree-clean",
                "blocked",
                (
                    "Worktree checkpoint required: "
                    f"{summary}, {total_changed_lines} changed lines exceeds "
                    f"max_uncommitted_changed_lines={threshold}."
                ),
                user_action=(
                    "Commit or stash the current branch state before continuing. "
                    "Use a checkpoint/WIP commit if needed so the next agent does not build on hidden uncommitted work."
                ),
            )
        benchmark_context, benchmark_error = get_benchmark_context(root)
        if benchmark_context is not None:
            allowed_root = str(benchmark_context.get("root") or "")
            return _result(
                "worktree-clean",
                "degraded",
                f"Worktree is dirty but benchmark lane is enabled: {summary}. Allowed benchmark root: {allowed_root}.",
                user_action=("Limit writes to the audited benchmark root and report that benchmark lane is active."),
            )
        if benchmark_error:
            return _result(
                "worktree-clean",
                "blocked",
                f"Worktree is dirty and benchmark mode is invalid: {benchmark_error}.",
                user_action=("Fix the benchmark env contract or disable benchmark mode before editing."),
            )
        if _dirty_worktree_override_enabled():
            return _result(
                "worktree-clean",
                "degraded",
                f"Worktree is dirty but explicit override is set: {summary}. See WORKTREE_RULES.md Rule 8.",
                user_action=(
                    "Limit work to audited cleanup/remediation and tell the user "
                    "you are using a dirty-worktree override."
                ),
            )
        return _result(
            "worktree-clean",
            "blocked",
            f"Worktree is dirty: {summary}. See WORKTREE_RULES.md Rule 8.",
            user_action=(
                "Stop before normal implementation work. Commit/stash changes or use "
                "an explicit dirty-worktree override for cleanup/remediation lanes only."
            ),
        )
    return _result("worktree-clean", "ok", "Worktree is clean — no uncommitted changes.")


def evaluate_preflight(*, root: Path = ROOT, cwd: Path | None = None) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_cwd = (cwd or Path.cwd()).resolve()
    checks = [
        _check_repo_layout(resolved_root),
        _check_git_root(resolved_root),
        _check_worktree_clean(resolved_root),
        _check_cwd(resolved_root, resolved_cwd),
        _check_ripgrep(),
        _check_repo_python(resolved_root),
        _check_repo_pytest(resolved_root),
    ]
    status = _overall_status(checks)
    return {
        "status": status,
        "summary": _summary(checks),
        "root": str(resolved_root),
        "cwd": str(resolved_cwd),
        "checks": checks,
        "policy": _policy(status),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify Thomas agent environment readiness.")
    parser.add_argument("--cwd", default="", help="Override the working directory used for the preflight check.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def _text_output(payload: dict[str, Any]) -> str:
    lines = [
        "Thomas agent preflight",
        f"status: {payload['status']}",
        f"summary: {payload['summary']}",
        f"root: {payload['root']}",
        f"cwd: {payload['cwd']}",
        f"policy: {payload['policy']['summary']}",
        "checks:",
    ]
    for check in payload["checks"]:
        action = str(check.get("user_action") or "").strip()
        suffix = f" | action: {action}" if action and check["status"] != "ok" else ""
        lines.append(f"  - {check['status']} {check['id']}: {check['message']}{suffix}")
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cwd = Path(str(args.cwd)).expanduser() if args.cwd else None
    payload = evaluate_preflight(cwd=cwd)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_text_output(payload))
    return 2 if payload["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(run())
