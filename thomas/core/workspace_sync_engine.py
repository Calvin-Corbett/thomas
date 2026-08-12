"""Workspace sync engine: automatic safe commits for normie-friendly workflow."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from thomas.core.workspace_sync_coordination import WorkspaceSyncCoordinationClient

log = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".thomas"
ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_IDLE_THRESHOLD_S = 4 * 60.0
_DEFAULT_POLL_INTERVAL_S = 45.0
_DEFAULT_CYCLE_INTERVAL_S = 8 * 60.0
_DEFAULT_MAX_CYCLES = 500
_DEFAULT_MAX_FILES_PER_COMMIT = 200
_DEFAULT_STABLE_AGE_S = 45.0
_DEFAULT_COMMIT_PREFIX = "chore(thomas): auto-sync workspace"
_DEFAULT_COORDINATION_CLAIM_TTL_S = 30 * 60
_DEFAULT_COORDINATION_TIMEOUT_S = 20.0
_DEFAULT_COORDINATION_NOTE = "workspace sync auto-claim"
_DEFAULT_COORDINATION_RETRY_ENABLED = True
_DEFAULT_COORDINATION_RETRY_BASE_SECONDS = 30.0
_DEFAULT_COORDINATION_RETRY_MAX_SECONDS = 900.0

_DEFAULT_EXCLUDE_GLOBS = (
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    ".thomas/*",
    "runtime/*",
    "output/*",
    "__pycache__/*",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    "node_modules/*",
    ".open-next/*",
)


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 86_400.0) -> float:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    return float(max(min_value, min(max_value, value)))


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 10_000) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return int(max(min_value, min(max_value, value)))


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, limit: int = 800) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n... (truncated)"


def _normalize_rel_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    while text.startswith("/"):
        text = text[1:]
    return text


def _parse_extra_globs(raw: str) -> list[str]:
    items: list[str] = []
    for piece in str(raw or "").split(","):
        val = _normalize_rel_path(piece).lower()
        if not val:
            continue
        items.append(val)
    return sorted(set(items))


def _safe_file_age_s(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:
        return 0.0


class WorkspaceSyncEngine:
    """Continuously creates safe git commits so end users do not manage git manually."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        idle_threshold_s: float | None = None,
        poll_interval_s: float | None = None,
        cycle_interval_s: float | None = None,
        max_cycles_per_session: int | None = None,
        max_files_per_commit: int | None = None,
        stable_age_s: float | None = None,
        auto_push: bool | None = None,
        exclude_globs: Iterable[str] | None = None,
        coordination_enabled: bool | None = None,
        coordination_claim_ttl_s: int | None = None,
        coordination_script: Path | None = None,
        notify_fn: Callable[[str], None] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._repo_root = Path(repo_root or ROOT).resolve()
        self._idle_threshold_s = float(
            _DEFAULT_IDLE_THRESHOLD_S if idle_threshold_s is None else max(0.0, float(idle_threshold_s))
        )
        self._poll_interval_s = float(
            _DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else max(1.0, float(poll_interval_s))
        )
        self._cycle_interval_s = float(
            _DEFAULT_CYCLE_INTERVAL_S if cycle_interval_s is None else max(1.0, float(cycle_interval_s))
        )
        self._max_cycles_per_session = int(
            _DEFAULT_MAX_CYCLES if max_cycles_per_session is None else max(1, int(max_cycles_per_session))
        )
        self._max_files_per_commit = int(
            _DEFAULT_MAX_FILES_PER_COMMIT if max_files_per_commit is None else max(1, int(max_files_per_commit))
        )
        self._stable_age_s = float(_DEFAULT_STABLE_AGE_S if stable_age_s is None else max(0.0, float(stable_age_s)))
        self._auto_push = bool(_env_bool("THOMAS_WORKSPACE_SYNC_AUTO_PUSH", False) if auto_push is None else auto_push)
        self._coordination_enabled = bool(
            _env_bool("THOMAS_WORKSPACE_SYNC_COORDINATION_ENABLED", True)
            if coordination_enabled is None
            else coordination_enabled
        )
        self._coordination_claim_ttl_s = int(
            _env_int(
                "THOMAS_WORKSPACE_SYNC_COORDINATION_TTL",
                _DEFAULT_COORDINATION_CLAIM_TTL_S,
                min_value=30,
                max_value=86_400,
            )
            if coordination_claim_ttl_s is None
            else max(30, int(coordination_claim_ttl_s))
        )
        self._coordination_note = (
            str(os.environ.get("THOMAS_WORKSPACE_SYNC_COORDINATION_NOTE") or "").strip() or _DEFAULT_COORDINATION_NOTE
        )
        self._coordination_timeout_s = float(
            _env_float(
                "THOMAS_WORKSPACE_SYNC_COORDINATION_TIMEOUT_S",
                _DEFAULT_COORDINATION_TIMEOUT_S,
                min_value=5.0,
                max_value=120.0,
            )
        )
        self._coordination_retry_enabled = bool(
            _env_bool("THOMAS_WORKSPACE_SYNC_COORDINATION_RETRY_ENABLED", _DEFAULT_COORDINATION_RETRY_ENABLED)
        )
        self._coordination_retry_base_s = float(
            _env_float(
                "THOMAS_WORKSPACE_SYNC_COORDINATION_RETRY_BASE_SECONDS",
                _DEFAULT_COORDINATION_RETRY_BASE_SECONDS,
                min_value=5.0,
                max_value=3_600.0,
            )
        )
        self._coordination_retry_max_s = float(
            _env_float(
                "THOMAS_WORKSPACE_SYNC_COORDINATION_RETRY_MAX_SECONDS",
                _DEFAULT_COORDINATION_RETRY_MAX_SECONDS,
                min_value=self._coordination_retry_base_s,
                max_value=86_400.0,
            )
        )
        script = Path(coordination_script or (self._repo_root / "scripts" / "active_folders.py")).resolve()
        self._coordination = WorkspaceSyncCoordinationClient(
            repo_root=self._repo_root,
            enabled=self._coordination_enabled,
            claim_ttl_s=self._coordination_claim_ttl_s,
            note=self._coordination_note,
            timeout_s=self._coordination_timeout_s,
            script_path=script,
        )
        self._coordination_retry_until = 0.0
        self._coordination_conflict_count = 0
        self._coordination_conflict_agent = ""
        self._commit_prefix = str(os.environ.get("THOMAS_WORKSPACE_SYNC_COMMIT_PREFIX") or "").strip()
        if not self._commit_prefix:
            self._commit_prefix = _DEFAULT_COMMIT_PREFIX
        self._notify_fn = notify_fn
        self._log_path = Path(log_path or (STATE_DIR / "workspace_sync_engine.jsonl"))

        extra_globs = _parse_extra_globs(str(os.environ.get("THOMAS_WORKSPACE_SYNC_EXCLUDE_GLOBS") or ""))
        explicit_globs = [_normalize_rel_path(v).lower() for v in list(exclude_globs or []) if str(v or "").strip()]
        all_globs = list(_DEFAULT_EXCLUDE_GLOBS) + extra_globs + explicit_globs
        self._exclude_globs = sorted(set(_normalize_rel_path(v).lower() for v in all_globs if str(v).strip()))

        self._running = False
        self._thread: threading.Thread | None = None
        self._active_cycle = False
        self._lock = threading.Lock()
        self._mutation_lock = threading.Lock()
        self._activity_leases: set[str] = set()
        self._last_user_ts = time.monotonic()
        self._last_cycle_ts = 0.0
        self._cycle_count = 0
        self._last_report: dict[str, Any] = {}
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._enabled = _env_bool("THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED", False)

    def start(self, *, notify_fn: Callable[[str], None] | None = None) -> None:
        if notify_fn is not None:
            self._notify_fn = notify_fn
        if self._running or not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thomas-workspace-sync")
        self._thread.start()
        log.info("WorkspaceSyncEngine started (repo=%s, auto_push=%s).", self._repo_root, self._auto_push)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        self._last_user_ts = time.monotonic()

    def acquire_activity_lease(self, label: str = "") -> str:
        """Block auto-commit cycles while interactive work owns the workspace."""
        token = str(label or f"interactive-{time.time_ns()}").strip()
        # Waiting on this lock lets an in-flight commit finish before the caller
        # releases its worker start gate. No new cycle can mutate while leased.
        with self._mutation_lock:
            with self._lock:
                self._activity_leases.add(token)
            self.record_user_message()
        return token

    def release_activity_lease(self, token: str) -> None:
        with self._lock:
            self._activity_leases.discard(str(token or ""))

    def is_idle(self) -> bool:
        with self._lock:
            leased = bool(self._activity_leases)
        return not leased and (time.monotonic() - self._last_user_ts) >= self._idle_threshold_s

    def last_report(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_report)

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._running),
                "enabled": bool(self._enabled),
                "auto_push": bool(self._auto_push),
                "coordination_enabled": bool(self._coordination.enabled()),
                "coordination_retry_count": int(self._coordination_conflict_count),
                "coordination_retry_wait_s": round(max(0.0, self._coordination_retry_seconds()), 1),
                "coordination_blocking_agent": str(self._coordination_conflict_agent or ""),
                "cycles_completed": int(self._cycle_count),
                "active_cycle": bool(self._active_cycle),
                "activity_leases": len(self._activity_leases),
                "last_cycle_at": str(self._last_report.get("timestamp") or ""),
                "last_committed": bool(self._last_report.get("committed")) if self._last_report else False,
                "last_commit_sha": str(self._last_report.get("commit_sha") or ""),
                "last_skip_reason": str(self._last_report.get("skip_reason") or ""),
                "last_error": str(self._last_error or ""),
                "last_error_at": str(self._last_error_at or ""),
            }

    def summary_text(self) -> str:
        snap = self.status_snapshot()
        return (
            f"WorkspaceSyncEngine: running={snap['running']} "
            f"cycles={snap['cycles_completed']} "
            f"last_commit={snap['last_commit_sha'] or 'none'} "
            f"last_skip={snap['last_skip_reason'] or 'none'}"
        )

    def run_cycle_once(self, *, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        if not force:
            if not self._enabled:
                return {"ok": False, "reason": "engine_disabled"}
            if not self.is_idle():
                return {"ok": False, "reason": "not_idle"}
        with self._lock:
            if self._active_cycle:
                return {"ok": False, "reason": "busy"}
            self._active_cycle = True
            self._last_cycle_ts = time.monotonic()
        try:
            return self._run_cycle_checked(reason=reason, force=force)
        finally:
            with self._lock:
                self._active_cycle = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_interval_s)
            try:
                self._tick()
            except Exception as exc:
                log.warning("WorkspaceSyncEngine tick failed: %s", exc)

    def _tick(self) -> None:
        if not self._enabled:
            return
        if not self.is_idle():
            return
        now = time.monotonic()
        with self._lock:
            if self._active_cycle:
                return
            if self._cycle_count >= self._max_cycles_per_session:
                return
            if (now - self._last_cycle_ts) < self._cycle_interval_s:
                return
            self._active_cycle = True
            self._last_cycle_ts = now
        threading.Thread(
            target=self._run_cycle_threadsafe,
            args=("idle",),
            daemon=True,
            name="thomas-workspace-sync-cycle",
        ).start()

    def _run_cycle_threadsafe(self, reason: str) -> None:
        try:
            self._run_cycle_checked(reason=reason, force=False)
        finally:
            with self._lock:
                self._active_cycle = False

    def _run_cycle_checked(self, *, reason: str, force: bool) -> dict[str, Any]:
        started = time.monotonic()
        try:
            report = self._run_cycle_with_activity_guard(reason=reason, force=force, started=started)
            self._clear_last_error()
            return report
        except Exception as exc:  # pragma: no cover - defensive path
            return self._error_report(reason=reason, force=force, exc=exc, started=started)

    def _run_cycle_with_activity_guard(self, *, reason: str, force: bool, started: float) -> dict[str, Any]:
        with self._mutation_lock:
            with self._lock:
                lease_count = len(self._activity_leases)
            if lease_count:
                return self._finish(
                    reason=reason,
                    committed=False,
                    skip_reason="interactive_work_active",
                    details={"activity_leases": lease_count},
                    elapsed_ms=started,
                )
            return self._run_cycle(reason=reason, force=force)

    def _run_cycle(self, *, reason: str, force: bool) -> dict[str, Any]:
        started = time.monotonic()
        retry_wait_s = self._coordination_retry_seconds(now=started)
        if not force and retry_wait_s > 0:
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="coordination_retry_wait",
                details={
                    "coordination_retry_wait_s": round(retry_wait_s, 1),
                    "coordination": self._coordination_retry_status(reason="retry_wait"),
                },
                elapsed_ms=started,
            )
        issues = self._preflight_issues()
        if issues:
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="preflight_blocked",
                details={"issues": issues},
                elapsed_ms=started,
            )

        staged_now = self._git_lines("diff", "--cached", "--name-only")
        if staged_now:
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="staged_changes_present",
                details={"staged_files": staged_now[:50]},
                elapsed_ms=started,
            )

        status_rows = self._git_lines("status", "--porcelain")
        candidates = self._select_candidate_files(status_rows)
        if not candidates:
            return self._finish(reason=reason, committed=False, skip_reason="no_meaningful_changes", elapsed_ms=started)

        stable_files = self._stable_candidates(candidates)
        if not stable_files:
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="changes_not_stable_yet",
                details={"candidate_count": len(candidates)},
                elapsed_ms=started,
            )

        files = stable_files[: self._max_files_per_commit]
        py_check = self._validate_python_syntax(files)
        if not py_check.get("ok"):
            self._clear_coordination_retry()
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="python_syntax_invalid",
                details={"syntax": py_check},
                elapsed_ms=started,
            )

        coordination = self._acquire_coordination_claim(files)
        if not coordination.get("ok"):
            const_reason = str(coordination.get("reason") or "").strip().lower()
            if const_reason in {"folder_conflict", "folder_conflicts"}:
                self._record_coordination_conflict(coordination)
                coordination.update(self._coordination_retry_status(reason="folder_conflicts"))
            else:
                self._clear_coordination_retry()
            return self._finish(
                reason=reason,
                committed=False,
                skip_reason="coordination_blocked",
                details={"coordination": coordination},
                elapsed_ms=started,
            )

        claim_id = str(coordination.get("claim_id") or "")
        self._clear_coordination_retry()

        try:
            self._ensure_author_identity()
            add_result = self._git("add", "--", *files)
            if add_result.returncode != 0:
                return self._finish(
                    reason=reason,
                    committed=False,
                    skip_reason="git_add_failed",
                    details={
                        "stderr": _truncate(add_result.stderr),
                        "stdout": _truncate(add_result.stdout),
                        "coordination": coordination,
                    },
                    elapsed_ms=started,
                )

            staged_after_add = self._git_lines("diff", "--cached", "--name-only")
            if not staged_after_add:
                return self._finish(
                    reason=reason,
                    committed=False,
                    skip_reason="nothing_staged",
                    details={"coordination": coordination},
                    elapsed_ms=started,
                )

            title, body = self._build_commit_message(staged_after_add, reason=reason)
            commit_result = self._git("commit", "-m", title, "-m", body)
            output_joined = f"{commit_result.stdout}\n{commit_result.stderr}".lower()
            if commit_result.returncode != 0:
                if "nothing to commit" in output_joined or "no changes added to commit" in output_joined:
                    return self._finish(
                        reason=reason,
                        committed=False,
                        skip_reason="nothing_to_commit",
                        details={"coordination": coordination},
                        elapsed_ms=started,
                    )
                return self._finish(
                    reason=reason,
                    committed=False,
                    skip_reason="git_commit_failed",
                    details={
                        "stderr": _truncate(commit_result.stderr),
                        "stdout": _truncate(commit_result.stdout),
                        "coordination": coordination,
                    },
                    elapsed_ms=started,
                )

            commit_sha = str(self._git_text("rev-parse", "--short", "HEAD") or "").strip()
            push = self._push_latest()
            details: dict[str, Any] = {
                "files": staged_after_add[:50],
                "commit_message": title,
                "push": push,
                "coordination": coordination,
            }
            return self._finish(
                reason=reason,
                committed=True,
                skip_reason="",
                commit_sha=commit_sha,
                details=details,
                elapsed_ms=started,
            )
        finally:
            self._release_coordination_claim(claim_id)

    def _preflight_issues(self) -> list[str]:
        issues: list[str] = []
        inside = self._git_text("rev-parse", "--is-inside-work-tree").strip().lower()
        if inside != "true":
            issues.append("not_git_repo")
            return issues
        unmerged = self._git_lines("diff", "--name-only", "--diff-filter=U")
        if unmerged:
            issues.append("unmerged_paths")
        git_dir = self._git_text("rev-parse", "--git-dir").strip()
        if git_dir:
            state_dir = (self._repo_root / git_dir).resolve()
            for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD", "BISECT_LOG"):
                if (state_dir / marker).exists():
                    issues.append(f"git_state:{marker.lower()}")
        return issues

    def _select_candidate_files(self, status_rows: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for raw in status_rows:
            line = str(raw or "")
            if len(line) < 4:
                continue
            code = line[:2]
            path_field = line[3:].strip()
            if " -> " in path_field:
                path_field = path_field.split(" -> ", 1)[1].strip()
            if path_field.startswith('"') and path_field.endswith('"') and len(path_field) >= 2:
                path_field = path_field[1:-1].replace('\\"', '"')
            rel = _normalize_rel_path(path_field)
            if not rel:
                continue
            if self._is_excluded(rel):
                continue
            deleted = "D" in code
            out.append({"path": rel, "deleted": bool(deleted), "code": code})
        dedup: dict[str, dict[str, Any]] = {}
        for row in out:
            dedup[str(row["path"])] = row
        return [dedup[key] for key in sorted(dedup.keys())]

    def _stable_candidates(self, rows: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for row in rows:
            rel = str(row.get("path") or "")
            deleted = bool(row.get("deleted"))
            if deleted:
                out.append(rel)
                continue
            full = (self._repo_root / rel).resolve()
            age = _safe_file_age_s(full)
            if age >= self._stable_age_s:
                out.append(rel)
        return out

    def _is_excluded(self, rel_path: str) -> bool:
        normalized = _normalize_rel_path(rel_path).lower()
        if not normalized:
            return True
        for pat in self._exclude_globs:
            if fnmatch(normalized, pat):
                return True
        return False

    def _validate_python_syntax(self, files: list[str]) -> dict[str, Any]:
        py_files: list[str] = []
        for rel in files:
            if str(rel).lower().endswith(".py"):
                py_files.append(rel)
        if not py_files:
            return {"ok": True, "checked": 0, "errors": []}
        errors: list[dict[str, Any]] = []
        for rel in py_files:
            path = (self._repo_root / rel).resolve()
            if not path.exists():
                continue
            cmd = [os.environ.get("PYTHON", os.sys.executable), "-m", "py_compile", str(path)]
            try:
                proc = subprocess.run(cmd, cwd=str(self._repo_root), capture_output=True, text=True, timeout=30.0)
            except Exception as exc:
                errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if proc.returncode != 0:
                errors.append(
                    {
                        "path": rel,
                        "stdout": _truncate(str(proc.stdout or "")),
                        "stderr": _truncate(str(proc.stderr or "")),
                    }
                )
        return {"ok": not bool(errors), "checked": len(py_files), "errors": errors}

    def _ensure_author_identity(self) -> None:
        name = self._git_text("config", "--get", "user.name").strip()
        email = self._git_text("config", "--get", "user.email").strip()
        if not name:
            fallback_name = (
                str(os.environ.get("THOMAS_WORKSPACE_SYNC_GIT_NAME") or "Thomas Bot").strip() or "Thomas Bot"
            )
            self._git("config", "user.name", fallback_name)
        if not email:
            fallback_email = str(os.environ.get("THOMAS_WORKSPACE_SYNC_GIT_EMAIL") or "thomas@local.invalid").strip()
            if not fallback_email:
                fallback_email = "thomas@local.invalid"
            self._git("config", "user.email", fallback_email)

    def _build_commit_message(self, files: list[str], *, reason: str) -> tuple[str, str]:
        scope_parts = [str(item).split("/", 1)[0] for item in files[:12] if "/" in str(item)]
        scopes = sorted(set(scope_parts))
        scope_hint = ", ".join(scopes[:3]) if scopes else "workspace"
        title = f"{self._commit_prefix} ({len(files)} files)"
        body_lines = [
            "[auto-managed] Workspace Sync Engine",
            f"- reason: {str(reason or 'manual')}",
            f"- scope: {scope_hint}",
            "- files:",
        ]
        for rel in files[:20]:
            body_lines.append(f"  - {rel}")
        if len(files) > 20:
            body_lines.append(f"  - ... and {len(files) - 20} more")
        return title, "\n".join(body_lines)

    def _push_latest(self) -> dict[str, Any]:
        push: dict[str, Any] = {
            "enabled": bool(self._auto_push),
            "attempted": False,
            "ok": False,
            "reason": "",
            "stderr": "",
        }
        if not self._auto_push:
            push["reason"] = "disabled"
            return push
        remotes = self._git_lines("remote")
        if not remotes:
            push["reason"] = "no_remote"
            return push
        branch = self._git_text("rev-parse", "--abbrev-ref", "HEAD").strip()
        if not branch or branch == "HEAD":
            push["reason"] = "detached_head"
            return push

        push["attempted"] = True
        proc = self._git("push")
        if proc.returncode == 0:
            push["ok"] = True
            push["reason"] = "pushed"
            return push

        err = f"{proc.stdout}\n{proc.stderr}".lower()
        if "no upstream branch" in err and "origin" in remotes:
            proc2 = self._git("push", "--set-upstream", "origin", branch)
            if proc2.returncode == 0:
                push["ok"] = True
                push["reason"] = "pushed_set_upstream"
                return push
            push["stderr"] = _truncate(str(proc2.stderr or proc2.stdout or ""))
            push["reason"] = "push_failed"
            return push

        push["stderr"] = _truncate(str(proc.stderr or proc.stdout or ""))
        push["reason"] = "push_failed"
        return push

    def _acquire_coordination_claim(self, files: list[str]) -> dict[str, Any]:
        return self._coordination.acquire(files)

    def _release_coordination_claim(self, claim_id: str) -> None:
        self._coordination.release(claim_id)

    def _coordination_retry_seconds(self, now: float | None = None) -> float:
        if not self._coordination_retry_enabled:
            return 0.0
        if self._coordination_retry_until <= 0.0:
            return 0.0
        now = float(time.monotonic() if now is None else now)
        if self._coordination_retry_until <= now:
            return 0.0
        return self._coordination_retry_until - now

    def _coordination_retry_status(self, reason: str = "retry_wait") -> dict[str, Any]:
        return {
            "enabled": bool(self._coordination_retry_enabled),
            "reason": reason,
            "retry_count": int(self._coordination_conflict_count),
            "retry_wait_s": round(max(0.0, self._coordination_retry_seconds()), 1),
            "blocking_agent": str(self._coordination_conflict_agent or ""),
        }

    def _record_coordination_conflict(self, payload: dict[str, Any]) -> None:
        self._coordination_conflict_count += 1
        self._coordination_conflict_agent = ""
        conflicts = payload.get("conflicts") or []
        if conflicts and isinstance(conflicts, list):
            first = conflicts[0]
            if isinstance(first, dict):
                self._coordination_conflict_agent = str(first.get("agent_id") or "")
        delay = min(
            self._coordination_retry_max_s,
            self._coordination_retry_base_s * (2 ** max(0, self._coordination_conflict_count - 1)),
        )
        self._coordination_retry_until = time.monotonic() + delay

    def _clear_coordination_retry(self) -> None:
        self._coordination_retry_until = 0.0
        self._coordination_conflict_count = 0
        self._coordination_conflict_agent = ""

    def _finish(
        self,
        *,
        reason: str,
        committed: bool,
        skip_reason: str = "",
        commit_sha: str = "",
        details: dict[str, Any] | None = None,
        elapsed_ms: float,
    ) -> dict[str, Any]:
        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)
        report: dict[str, Any] = {
            "ok": True,
            "cycle": cycle_id,
            "reason": str(reason or "manual"),
            "timestamp": _now_iso(),
            "committed": bool(committed),
            "commit_sha": str(commit_sha or ""),
            "skip_reason": str(skip_reason or ""),
            "elapsed_ms": round((time.monotonic() - elapsed_ms) * 1000.0, 1),
        }
        if details:
            report["details"] = details
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = report
            self._last_error = None
            self._last_error_at = None
        if self._notify_fn is not None:
            try:
                if committed:
                    self._notify_fn(f"[WorkspaceSyncEngine] auto-committed {commit_sha or 'changes'}")
                elif skip_reason:
                    self._notify_fn(f"[WorkspaceSyncEngine] skipped: {skip_reason}")
            except Exception:
                pass
        return report

    def _write_cycle_log(self, report: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug("WorkspaceSyncEngine failed to write log: %s", exc)

    def _error_report(self, *, reason: str, force: bool, exc: BaseException, started: float) -> dict[str, Any]:
        with self._lock:
            cycle_id = int(self._cycle_count) + 1
            self._cycle_count = cycle_id
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_error_at = _now_iso()

        report = {
            "ok": False,
            "cycle": cycle_id,
            "reason": "engine_error",
            "requested_reason": str(reason or "manual"),
            "force": bool(force),
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
            "timestamp": _now_iso(),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
            "committed": False,
            "skip_reason": "engine_exception",
        }
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = report

        if self._notify_fn is not None:
            try:
                self._notify_fn(f"[WorkspaceSyncEngine] cycle {cycle_id} failed: {type(exc).__name__}: {exc}")
            except Exception:
                pass
        return report

    def _clear_last_error(self) -> None:
        self._last_error = None
        self._last_error_at = None

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = ["git", *[str(a) for a in args]]
        return subprocess.run(
            cmd,
            cwd=str(self._repo_root),
            capture_output=True,
            text=True,
            timeout=60.0,
        )

    def _git_text(self, *args: str) -> str:
        proc = self._git(*args)
        if proc.returncode != 0:
            return ""
        return str(proc.stdout or "")

    def _git_lines(self, *args: str) -> list[str]:
        out = self._git_text(*args)
        rows = [line.strip() for line in str(out or "").splitlines() if str(line or "").strip()]
        return rows

    def debug_command(self, *args: str) -> str:
        return " ".join(shlex.quote(str(a)) for a in ("git", *args))


_engine: WorkspaceSyncEngine | None = None
_engine_lock = threading.Lock()


def get_workspace_sync_engine() -> WorkspaceSyncEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = WorkspaceSyncEngine()
    return _engine
