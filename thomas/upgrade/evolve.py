"""Green-side self-improvement runtime for Thomas evolve mode."""

from __future__ import annotations

import difflib
import hashlib
import os
import shlex
import shutil
import subprocess  # nosec
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib

from thomas.core.config import load_config
from thomas.core.model_resolution import resolve_effective_model

from .doppelganger import (
    _IGNORE_NAMES,
    _INCLUDE_DIRS,
    _INCLUDE_FILES,
    ensure_green_venv,
    find_project_root,
    get_paths,
    promote_green_to_blue,
    sync_blue_to_green,
)
from .evolve_storage import (
    DEFAULT_EVOLVE_GOAL,
    EvolveCharter,
    _write_json,
    _write_text,
    utc_now_iso,
)
from .evolve_storage import (
    DEFAULT_EVOLVE_OBJECTIVE as _DEFAULT_EVOLVE_OBJECTIVE,
)
from .evolve_storage import (
    DEFAULT_EVOLVE_PRINCIPLES as _DEFAULT_EVOLVE_PRINCIPLES,
)
from .evolve_storage import (
    DEFAULT_VERIFY_COMMANDS as _DEFAULT_VERIFY_COMMANDS,
)
from .evolve_storage import (
    _sessions_root as _storage_sessions_root,
)
from .evolve_storage import (
    build_charter_markdown as _build_charter_markdown,
)
from .evolve_storage import (
    ensure_evolve_charter as _ensure_evolve_charter,
)
from .evolve_storage import (
    has_evolve_charter as _has_evolve_charter,
)
from .evolve_storage import (
    list_evolve_sessions as _list_evolve_sessions,
)
from .evolve_storage import (
    load_evolve_charter as _load_evolve_charter,
)
from .evolve_storage import (
    load_evolve_session as _load_evolve_session,
)
from .evolve_storage import (
    load_latest_evolve_session as _load_latest_evolve_session,
)
from .evolve_storage import (
    resolve_evolve_root as _resolve_evolve_root,
)
from .evolve_storage import (
    resolve_repo_root as _resolve_repo_root,
)

DEFAULT_EVOLVE_OBJECTIVE = _DEFAULT_EVOLVE_OBJECTIVE
DEFAULT_EVOLVE_PRINCIPLES = list(_DEFAULT_EVOLVE_PRINCIPLES)
DEFAULT_VERIFY_COMMANDS = list(_DEFAULT_VERIFY_COMMANDS)
DEFAULT_SELF_HOST_TASK_SUMMARY = "Self-host acceptance fresh task"
DEFAULT_SELF_HOST_TASK_PROMPT = (
    "Use your tools to read pyproject.toml and write "
    "runtime/agentic_bench/self_host_acceptance/task_pyproject.json "
    "with JSON keys project_name and project_version. Return one line confirming "
    "task_pyproject.json was written."
)
DEFAULT_SELF_HOST_TASK_POLICY = {
    "capability_class": "artifact_only",
    "allowed_write_roots": ["runtime/agentic_bench/self_host_acceptance/task_pyproject.json"],
}


def resolve_repo_root(project_root: Path | None = None) -> Path:
    return _resolve_repo_root(project_root=project_root, find_project_root=find_project_root)


def resolve_evolve_root(project_root: Path | None = None) -> Path:
    return _resolve_evolve_root(repo_root=resolve_repo_root(project_root))


def has_evolve_charter(project_root: Path | None = None) -> bool:
    return _has_evolve_charter(repo_root=resolve_repo_root(project_root))


def build_charter_markdown(charter: EvolveCharter) -> str:
    return _build_charter_markdown(charter)


def ensure_evolve_charter(
    project_root: Path | None = None,
    charter: EvolveCharter | None = None,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    return _ensure_evolve_charter(
        repo_root=resolve_repo_root(project_root),
        charter=charter,
        overwrite=overwrite,
    )


def load_evolve_charter(project_root: Path | None = None) -> EvolveCharter:
    return _load_evolve_charter(repo_root=resolve_repo_root(project_root))


def list_evolve_sessions(project_root: Path | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    return _list_evolve_sessions(repo_root=resolve_repo_root(project_root), limit=limit)


def load_latest_evolve_session(project_root: Path | None = None) -> dict[str, Any] | None:
    return _load_latest_evolve_session(repo_root=resolve_repo_root(project_root))


def load_evolve_session(project_root: Path | None = None, session_id: str = "") -> dict[str, Any]:
    return _load_evolve_session(repo_root=resolve_repo_root(project_root), session_token=session_id)


def _sessions_root(project_root: Path | None = None) -> Path:
    return _storage_sessions_root(repo_root=resolve_repo_root(project_root))


def _iter_scope_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for name in _INCLUDE_FILES:
        candidate = root / name
        if candidate.is_file():
            files[candidate.relative_to(root).as_posix()] = candidate
    for dirname in _INCLUDE_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for candidate in base.rglob("*"):
            if candidate.is_dir():
                continue
            if candidate.name.endswith(".pyc"):
                continue
            if any(part in _IGNORE_NAMES for part in candidate.parts):
                continue
            files[candidate.relative_to(root).as_posix()] = candidate
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for rel, path in sorted(_iter_scope_files(root).items()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def _normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _load_evolve_protected_paths(repo_root: Path) -> set[str]:
    config_path = repo_root / "agent_safety.toml"
    if not config_path.exists():
        return set()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    protected = payload.get("protected")
    if not isinstance(protected, dict):
        return set()
    relpaths: set[str] = set()
    for key in ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts"):
        rows = protected.get(key) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            rel = _normalize_relpath(str(item or "")).strip()
            if rel:
                relpaths.add(rel)
    return relpaths


def _restore_green_path_from_blue(paths, rel: str) -> None:
    rel_path = Path(_normalize_relpath(rel))
    blue_path = paths.blue_root / rel_path
    green_path = paths.green_root / rel_path
    if blue_path.exists():
        green_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blue_path, green_path)
        return
    if green_path.exists():
        green_path.unlink()


def _revert_protected_changes(
    paths,
    delta: dict[str, Any],
    protected_paths: set[str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    violations = sorted(rel for rel in (delta.get("changed_files") or []) if _normalize_relpath(rel) in protected_paths)
    reverted: list[str] = []
    for rel in violations:
        _restore_green_path_from_blue(paths, rel)
        reverted.append(rel)
    if violations:
        delta = _collect_tree_delta(paths)
    return delta, violations, reverted


def _collect_tree_delta(paths) -> dict[str, Any]:
    blue = _iter_scope_files(paths.blue_root)
    green = _iter_scope_files(paths.green_root)
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for rel in sorted(set(blue) | set(green)):
        blue_path = blue.get(rel)
        green_path = green.get(rel)
        if blue_path is None and green_path is not None:
            added.append(rel)
        elif green_path is None and blue_path is not None:
            removed.append(rel)
        elif blue_path is not None and green_path is not None and _sha256(blue_path) != _sha256(green_path):
            modified.append(rel)
    changed = list(added) + list(modified) + list(removed)
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "changed_files": changed,
        "changed_count": len(changed),
    }


def _diff_preview(paths, delta: dict[str, Any], *, limit: int = 32) -> str:
    out: list[str] = []
    for rel in list(delta.get("modified") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        after = _read_text(paths.green_root / rel)
        if before is None or after is None:
            out.append(f"*** {rel} (binary or undecodable)\n")
            continue
        out.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
    for rel in list(delta.get("added") or [])[:limit]:
        after = _read_text(paths.green_root / rel)
        if after is None:
            out.append(f"*** {rel} (new binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff([], after.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    for rel in list(delta.get("removed") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        if before is None:
            out.append(f"*** {rel} (removed binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff(before.splitlines(keepends=True), [], fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    return "".join(out)


def _truncate(text: str, limit: int = 6000) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


def _display_command(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(str(part)) for part in command)


def _resolve_evolve_profile(repo_root: Path, requested_profile: str = "") -> str:
    config = load_config(repo_root / "thomas.toml")
    resolved_profile, _ = resolve_effective_model(
        config,
        cli_profile=str(requested_profile or "").strip() or None,
        env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip() or None,
    )
    resolved = str(resolved_profile or "").strip()
    if not resolved and "codex" in config.models:
        return "codex"
    if not str(requested_profile or "").strip() and resolved.lower() == "local" and "codex" in config.models:
        return "codex"
    return resolved


def _run_exec(
    command: str | list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    shell = isinstance(command, str)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            shell=shell,
        )
        return {
            "command": _display_command(command),
            "returncode": int(completed.returncode),
            "stdout_tail": _truncate(completed.stdout),
            "stderr_tail": _truncate(completed.stderr),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": _display_command(command),
            "returncode": 124,
            "stdout_tail": _truncate(exc.stdout or ""),
            "stderr_tail": _truncate(exc.stderr or ""),
            "timed_out": True,
        }


def _build_agent_prompt(charter: EvolveCharter, goal: str, *, pass_index: int, pass_count: int) -> str:
    lines = [
        "You are Thomas running inside evolve mode on the green doppelganger mirror of the Thomas repository.",
        "",
        f"Objective: {charter.objective}",
        f"Goal for this pass: {goal or charter.default_goal}",
        f"Pass: {pass_index} of {pass_count}",
        "",
        "Rules:",
        "- Work only inside the current cwd, which is the green mirror of Thomas.",
        "- The green mirror intentionally has no .git metadata. Do not rely on git commands.",
        "- Do not touch runtime/doppelganger, .thomas/evolve, secrets, or external machine state.",
        "- Never modify policy, guardrail, or verification files such as tests/test_architecture.py, thomas/_architecture.py, agent_safety.toml, GUARDRAILS.md, or scripts/check_*.py.",
        "- If verification fails because of environment limits or missing metadata, report that honestly instead of editing the guard.",
        "- Prefer concrete code improvements over commentary-only work.",
        "- Run targeted verification yourself before you stop.",
        "- End with a concise summary of files changed and verification run.",
        "",
        "Principles:",
    ]
    lines.extend(f"- {item}" for item in charter.principles)
    if charter.verify_commands:
        lines.append("")
        lines.append("Post-run verification ladder:")
        lines.extend(f"- {cmd}" for cmd in charter.verify_commands)
    return "\n".join(lines).strip()


def _build_verify_commands(charter: EvolveCharter, delta: dict[str, Any]) -> list[str | list[str]]:
    commands: list[str | list[str]] = []
    changed_py = [rel for rel in (delta.get("changed_files") or []) if str(rel).endswith(".py")]
    if changed_py:
        commands.append([sys.executable, "-m", "py_compile", *changed_py])
    commands.extend(cmd for cmd in charter.verify_commands if str(cmd).strip())
    return commands


def _session_status(
    pass_results: list[dict[str, Any]],
    verification: list[dict[str, Any]],
    changed_count: int,
    promoted: bool,
    *,
    policy_violation: bool,
) -> str:
    if any(int(item.get("returncode") or 0) != 0 for item in pass_results):
        return "agent_failed"
    if policy_violation:
        return "policy_violation"
    if any(int(item.get("returncode") or 0) != 0 for item in verification):
        return "verification_failed"
    if changed_count <= 0:
        return "no_change"
    if promoted:
        return "promoted"
    return "ready"


def _render_session_markdown(session: dict[str, Any]) -> str:
    lines = [
        f"# Evolve Session {session['session_id']}",
        "",
        f"- Status: `{session['status']}`",
        f"- Goal: {session['goal']}",
        f"- Changed files: {session['delta']['changed_count']}",
        f"- Promotable: `{str(session['promotable']).lower()}`",
        f"- Promoted: `{str(session['promoted']).lower()}`",
    ]
    if session.get("verified_tree_hash"):
        lines.append(f"- Verified tree hash: `{session['verified_tree_hash']}`")
    if session.get("policy_violations"):
        lines.append(f"- Policy violations: {len(session['policy_violations'])}")
    lines.extend(
        [
            "",
            "## Verification",
        ]
    )
    if session.get("verification"):
        for item in session["verification"]:
            lines.append(f"- `{item['command']}` -> `{item['returncode']}`")
    else:
        lines.append("- No verification commands recorded.")
    if session.get("policy_violations"):
        lines.append("")
        lines.append("## Policy Violations")
        lines.extend(f"- `{rel}`" for rel in session["policy_violations"])
    lines.append("")
    lines.append("## Files")
    if session["delta"]["changed_files"]:
        lines.extend(f"- `{rel}`" for rel in session["delta"]["changed_files"])
    else:
        lines.append("- No tracked file changes.")
    return "\n".join(lines).strip() + "\n"


def _attempt_maintenance_checkpoint(repo_root: Path, *, agent: str, total_changed_lines: int) -> dict[str, Any]:
    from scripts.agent_maintenance import attempt_maintenance_checkpoint

    return attempt_maintenance_checkpoint(root=repo_root, agent=agent, total_changed_lines=total_changed_lines)


def _run_self_host_fresh_task(
    repo_root: Path,
    *,
    worker_agent: str,
    summary: str = DEFAULT_SELF_HOST_TASK_SUMMARY,
    prompt: str = DEFAULT_SELF_HOST_TASK_PROMPT,
    task_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts import worker_run_chat_task

    from thomas.core import task_bot_runtime

    task_id = f"self-host-{uuid.uuid4().hex[:8]}"
    task_bot_runtime.create_execution(
        session_id=f"self-host-{uuid.uuid4().hex[:8]}",
        summary=str(summary or "").strip() or DEFAULT_SELF_HOST_TASK_SUMMARY,
        request_text=str(prompt or "").strip() or DEFAULT_SELF_HOST_TASK_PROMPT,
        task_id=task_id,
        actor="self-host-acceptance",
        task_policy=dict(task_policy or DEFAULT_SELF_HOST_TASK_POLICY),
        repo_root=repo_root,
    )
    rc = worker_run_chat_task.run(["--task-id", task_id, "--worker-agent", str(worker_agent or "").strip()])
    payload = task_bot_runtime.find_by_task_id(task_id, repo_root=repo_root) or {}
    return {
        "ok": rc == 0,
        "task_id": task_id,
        "worker_agent": str(worker_agent or "").strip(),
        "rc": rc,
        "progress_summary": str(payload.get("progress_summary") or "").strip(),
        "execution_id": str(payload.get("execution_id") or "").strip(),
    }


def run_evolve_session(
    project_root: Path | None = None,
    *,
    goal: str = "",
    profile: str = "",
    passes: int | None = None,
    promote_on_pass: bool = False,
    timeout_seconds: int = 1800,
    refactor_first: bool = True,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(project_root)
    evolve_root, _, _ = ensure_evolve_charter(repo_root)
    charter = load_evolve_charter(repo_root)
    requested_passes = max(1, min(int(passes or charter.max_passes or 1), 8))
    effective_profile = _resolve_evolve_profile(repo_root, profile)
    session_id = f"evolve-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    session_dir = _sessions_root(repo_root) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()

    paths = get_paths(repo_root)
    sync_blue_to_green(paths)

    # Ensure the green environment can run Thomas.
    # Prefer the dedicated green venv; fall back to the system Python with
    # PYTHONPATH pointed at the green mirror (works in sandboxed envs where
    # venv creation or network access may be blocked).
    try:
        green_python = str(ensure_green_venv(paths))
    except (OSError, RuntimeError, subprocess.SubprocessError):
        green_python = sys.executable

    green_env = dict(os.environ)
    green_env["THOMAS_MEMORY_ROOT"] = str(paths.green_runtime)
    green_env["THOMAS_SPEND_PATH"] = str(
        Path(os.environ.get("THOMAS_SPEND_PATH") or (repo_root / "thomas_spend.jsonl"))
    )
    # Always set PYTHONPATH so that `python -m thomas` resolves from the
    # green mirror, even when using the system interpreter as fallback.
    green_env["PYTHONPATH"] = str(paths.green_root)

    # Phase 0: Mandatory refactor pass (runs before creative passes)
    refactor_results: dict[str, Any] = {}
    if refactor_first:
        try:
            from .refactor_pass import run_refactor_pass

            refactor_results = run_refactor_pass(
                repo_root,
                paths,
                green_env=green_env,
                green_python=green_python,
                timeout_seconds=timeout_seconds,
                profile=effective_profile,
            )
        except (ImportError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Refactor pass failed (non-fatal, continuing): %s",
                exc,
            )
            refactor_results = {"phase": "refactor", "error": str(exc)}

    # Phase 1: Creative / goal-directed passes
    pass_results: list[dict[str, Any]] = []
    goal_used = str(goal or charter.default_goal).strip() or DEFAULT_EVOLVE_GOAL
    for idx in range(requested_passes):
        prompt = _build_agent_prompt(charter, goal_used, pass_index=idx + 1, pass_count=requested_passes)
        command = [green_python, "-m", "thomas", "chat", "--autonomy-level", "4"]
        if effective_profile:
            command.extend(["-m", effective_profile])
        command.append(prompt)
        result = _run_exec(command, cwd=paths.green_root, env=green_env, timeout_seconds=timeout_seconds)
        result["pass_index"] = idx + 1
        result["prompt"] = prompt
        pass_results.append(result)
        if int(result.get("returncode") or 0) != 0:
            break

    pre_policy_delta = _collect_tree_delta(paths)
    protected_paths = _load_evolve_protected_paths(repo_root)
    delta, policy_violations, reverted_policy_paths = _revert_protected_changes(
        paths,
        pre_policy_delta,
        protected_paths,
    )
    verify_commands = _build_verify_commands(charter, delta)
    verification = [
        _run_exec(command, cwd=paths.green_root, env=green_env, timeout_seconds=timeout_seconds)
        for command in verify_commands
    ]
    current_green_tree_hash = _tree_hash(paths.green_root)

    diff_path = session_dir / "changes.patch"
    _write_text(diff_path, _diff_preview(paths, delta) or "# No tracked changes\n")

    promotable = (
        bool(delta["changed_count"])
        and not policy_violations
        and all(int(item.get("returncode") or 0) == 0 for item in verification)
    )
    promoted = False
    promotion_backup = ""
    if promote_on_pass and promotable:
        promotion_backup = str(promote_green_to_blue(paths))
        promoted = True

    session = {
        "session_id": session_id,
        "repo_root": str(repo_root),
        "evolve_root": str(evolve_root),
        "green_root": str(paths.green_root),
        "goal": goal_used,
        "profile": effective_profile,
        "passes_requested": requested_passes,
        "refactor_results": refactor_results,
        "pass_results": pass_results,
        "verification": verification,
        "policy_violations": policy_violations,
        "reverted_policy_paths": reverted_policy_paths,
        "delta": delta,
        "changed_files": list(delta["changed_files"]),
        "promotable": promotable,
        "promoted": promoted,
        "promotion_backup": promotion_backup,
        "current_green_tree_hash": current_green_tree_hash,
        "verified_tree_hash": current_green_tree_hash if promotable else "",
        "verified_at": utc_now_iso() if promotable else "",
        "diff_path": str(diff_path),
        "charter": charter.to_dict(),
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "status": _session_status(
            pass_results,
            verification,
            delta["changed_count"],
            promoted,
            policy_violation=bool(policy_violations),
        ),
    }
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": session["status"] not in {"agent_failed", "policy_violation"}, "session": session}


def promote_evolve_session(
    project_root: Path | None = None,
    *,
    session_id: str = "",
    stop_port: int = 8899,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(project_root)
    session = (
        load_evolve_session(repo_root, session_id) if str(session_id).strip() else load_latest_evolve_session(repo_root)
    )
    if session is None:
        raise RuntimeError("no evolve sessions found")
    if session.get("promoted"):
        return {"ok": True, "session": session, "already_promoted": True}
    if not bool(session.get("promotable")):
        raise RuntimeError("latest evolve session is not promotable")
    paths = get_paths(repo_root)
    if not paths.green_root.exists():
        raise RuntimeError("green doppelganger slot does not exist")
    verified_tree_hash = str(session.get("verified_tree_hash") or "").strip()
    if not verified_tree_hash:
        raise RuntimeError("evolve session does not include a verified tree hash; rerun evolve verification before promotion")
    current_green_tree_hash = _tree_hash(paths.green_root)
    session["current_green_tree_hash"] = current_green_tree_hash
    if current_green_tree_hash != verified_tree_hash:
        session["promotable"] = False
        session["status"] = "stale_verification"
        session["finished_at"] = utc_now_iso()
        session_dir = _sessions_root(repo_root) / str(session["session_id"])
        _write_json(session_dir / "session.json", session)
        _write_text(session_dir / "session.md", _render_session_markdown(session))
        raise RuntimeError("green tree changed after verification; rerun evolve verification before promotion")
    backup = promote_green_to_blue(paths, stop_port=int(stop_port))
    session["promoted"] = True
    session["promotion_backup"] = str(backup)
    session["status"] = "promoted"
    session["finished_at"] = utc_now_iso()
    session_dir = _sessions_root(repo_root) / str(session["session_id"])
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": True, "session": session, "backup_path": str(backup)}


def run_self_hosting_acceptance_cycle(
    project_root: Path | None = None,
    *,
    maintenance_agent: str,
    worker_agent: str = "thomas-chat-worker",
    goal: str = "",
    profile: str = "",
    passes: int | None = None,
    timeout_seconds: int = 1800,
    maintenance_changed_lines: int = 1000,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(project_root)
    maintenance = _attempt_maintenance_checkpoint(
        repo_root,
        agent=str(maintenance_agent or "").strip(),
        total_changed_lines=max(int(maintenance_changed_lines or 0), 0),
    )
    if not bool(maintenance.get("ok")):
        return {
            "ok": False,
            "stage": "maintenance",
            "maintenance": maintenance,
        }

    evolve_payload = run_evolve_session(
        repo_root,
        goal=goal,
        profile=profile,
        passes=passes,
        promote_on_pass=False,
        timeout_seconds=timeout_seconds,
    )
    session = dict(evolve_payload.get("session") or {})
    if not bool(session.get("promotable")):
        return {
            "ok": False,
            "stage": "evolve",
            "maintenance": maintenance,
            "evolve": evolve_payload,
        }

    promotion = promote_evolve_session(repo_root, session_id=str(session.get("session_id") or ""))
    fresh_task = _run_self_host_fresh_task(repo_root, worker_agent=worker_agent)
    return {
        "ok": bool(promotion.get("ok")) and bool(fresh_task.get("ok")),
        "stage": "completed" if bool(promotion.get("ok")) and bool(fresh_task.get("ok")) else "fresh_task",
        "maintenance": maintenance,
        "evolve": evolve_payload,
        "promotion": promotion,
        "fresh_task": fresh_task,
    }
