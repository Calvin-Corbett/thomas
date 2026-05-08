"""Green-side self-improvement runtime for Thomas evolve mode."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shlex
import shutil
import subprocess  # nosec
import sys
import uuid
from dataclasses import dataclass, field
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

DEFAULT_EVOLVE_OBJECTIVE = (
    "Continuously improve Thomas across reliability, UI polish, safety, latency, and maintainability."
)
DEFAULT_EVOLVE_GOAL = "Choose the single highest-leverage safe improvement you can implement right now, then verify it."
DEFAULT_EVOLVE_PRINCIPLES = [
    "Operate only in the green doppelganger mirror. Never assume blue/live edits are safe.",
    "Prefer user-visible improvements, reliability, and maintainability over novelty.",
    "Respect existing work. Do not revert unrelated edits or broaden scope without evidence.",
    "Run targeted verification before you stop, and leave clear evidence in artifacts.",
    "If verification fails, fix it or stop with an honest failure record instead of hand-waving.",
]
DEFAULT_VERIFY_COMMANDS = ["python -m pytest tests/test_architecture.py -q"]


@dataclass(frozen=True)
class EvolveCharter:
    objective: str = DEFAULT_EVOLVE_OBJECTIVE
    default_goal: str = DEFAULT_EVOLVE_GOAL
    principles: list[str] = field(default_factory=lambda: list(DEFAULT_EVOLVE_PRINCIPLES))
    verify_commands: list[str] = field(default_factory=lambda: list(DEFAULT_VERIFY_COMMANDS))
    max_passes: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "default_goal": self.default_goal,
            "principles": list(self.principles),
            "verify_commands": list(self.verify_commands),
            "max_passes": int(self.max_passes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> EvolveCharter:
        payload = dict(payload or {})
        principles = payload.get("principles")
        verify_commands = payload.get("verify_commands")
        return cls(
            objective=str(payload.get("objective") or DEFAULT_EVOLVE_OBJECTIVE),
            default_goal=str(payload.get("default_goal") or DEFAULT_EVOLVE_GOAL),
            principles=[str(x).strip() for x in (principles or []) if str(x).strip()]
            or list(DEFAULT_EVOLVE_PRINCIPLES),
            verify_commands=[str(x).strip() for x in (verify_commands or []) if str(x).strip()]
            or list(DEFAULT_VERIFY_COMMANDS),
            max_passes=max(1, min(int(payload.get("max_passes") or 1), 8)),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_repo_root(project_root: Path | None = None) -> Path:
    if project_root is None:
        return find_project_root().resolve()
    return Path(project_root).expanduser().resolve()


def resolve_evolve_root(project_root: Path | None = None) -> Path:
    return resolve_repo_root(project_root) / ".thomas" / "evolve"


def _charter_json_path(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "charter.json"


def _charter_markdown_path(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "charter.md"


def _sessions_root(project_root: Path | None = None) -> Path:
    return resolve_evolve_root(project_root) / "sessions"


def has_evolve_charter(project_root: Path | None = None) -> bool:
    return _charter_json_path(project_root).exists()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_charter_markdown(charter: EvolveCharter) -> str:
    lines = [
        "# Thomas Evolve Charter",
        "",
        f"## Objective\n{charter.objective}",
        "",
        f"## Default Goal\n{charter.default_goal}",
        "",
        "## Principles",
    ]
    lines.extend(f"- {item}" for item in charter.principles)
    lines.append("")
    lines.append("## Verification")
    lines.extend(f"- `{cmd}`" for cmd in charter.verify_commands)
    lines.append("")
    lines.append(f"## Max Passes\n{int(charter.max_passes)}")
    return "\n".join(lines).strip() + "\n"


def ensure_evolve_charter(
    project_root: Path | None = None,
    charter: EvolveCharter | None = None,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    repo_root = resolve_repo_root(project_root)
    evolve_root = resolve_evolve_root(repo_root)
    json_path = _charter_json_path(repo_root)
    markdown_path = _charter_markdown_path(repo_root)
    if json_path.exists() and not overwrite:
        return evolve_root, json_path, markdown_path
    next_charter = charter or EvolveCharter()
    evolve_root.mkdir(parents=True, exist_ok=True)
    _sessions_root(repo_root).mkdir(parents=True, exist_ok=True)
    _write_json(json_path, next_charter.to_dict())
    _write_text(markdown_path, build_charter_markdown(next_charter))
    return evolve_root, json_path, markdown_path


def load_evolve_charter(project_root: Path | None = None) -> EvolveCharter:
    repo_root = resolve_repo_root(project_root)
    json_path = _charter_json_path(repo_root)
    if not json_path.exists():
        ensure_evolve_charter(repo_root)
    return EvolveCharter.from_dict(_read_json(json_path))


def list_evolve_sessions(project_root: Path | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    root = _sessions_root(project_root)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
        if not path.is_dir():
            continue
        payload_path = path / "session.json"
        if not payload_path.exists():
            continue
        try:
            rows.append(_read_json(payload_path))
        except Exception:
            continue
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def load_latest_evolve_session(project_root: Path | None = None) -> dict[str, Any] | None:
    rows = list_evolve_sessions(project_root, limit=1)
    return rows[0] if rows else None


def load_evolve_session(project_root: Path | None, session_token: str) -> dict[str, Any]:
    root = _sessions_root(project_root)
    token = str(session_token or "").strip()
    if not token:
        raise RuntimeError("session_id is required")
    exact = root / token / "session.json"
    if exact.exists():
        return _read_json(exact)
    matches = sorted(root.glob(f"{token}*/session.json"), key=lambda item: item.parent.name, reverse=True)
    if not matches:
        raise RuntimeError(f"evolve session '{token}' was not found")
    return _read_json(matches[0])


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
    backup = promote_green_to_blue(paths, stop_port=int(stop_port))
    session["promoted"] = True
    session["promotion_backup"] = str(backup)
    session["status"] = "promoted"
    session["finished_at"] = utc_now_iso()
    session_dir = _sessions_root(repo_root) / str(session["session_id"])
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": True, "session": session, "backup_path": str(backup)}
