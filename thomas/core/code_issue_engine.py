"""Autonomous code issue engine for iterative detect/fix loops.

This engine is intentionally deterministic and token-free:
- Runs heartbeat checks (with optional auto-fixes)
- Runs optional command checks
- Re-runs until no issues remain or no further auto-fix is possible
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path.home() / ".thomas"

_DEFAULT_IDLE_THRESHOLD_S = 5 * 60.0
_DEFAULT_POLL_INTERVAL_S = 60.0
_DEFAULT_CYCLE_INTERVAL_S = 10 * 60.0
_DEFAULT_MAX_PASSES = 4
_DEFAULT_MAX_CYCLES = 200
_DEFAULT_COMMAND_TIMEOUT_S = 120.0


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


def _truncate_text(text: str, limit: int = 800) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n... (truncated)"


@dataclass(frozen=True)
class CommandCheck:
    name: str
    check_command: str
    fix_command: str = ""
    timeout_seconds: float = _DEFAULT_COMMAND_TIMEOUT_S


def _load_command_checks_from_env() -> list[CommandCheck]:
    raw = str(os.environ.get("THOMAS_CODE_ISSUE_COMMANDS_JSON", "") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[CommandCheck] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip() or f"check-{len(out) + 1}"
        check_command = str(row.get("check") or row.get("check_command") or "").strip()
        if not check_command:
            continue
        fix_command = str(row.get("fix") or row.get("fix_command") or "").strip()
        timeout_s = _DEFAULT_COMMAND_TIMEOUT_S
        with_timeout = row.get("timeout_seconds")
        if with_timeout is not None:
            try:
                timeout_s = float(with_timeout)
            except Exception:
                timeout_s = _DEFAULT_COMMAND_TIMEOUT_S
        timeout_s = max(1.0, min(1800.0, float(timeout_s)))
        out.append(
            CommandCheck(
                name=name,
                check_command=check_command,
                fix_command=fix_command,
                timeout_seconds=timeout_s,
            )
        )
    return out


class CodeIssueEngine:
    """Runs iterative code issue checks and auto-fixes."""

    def __init__(
        self,
        *,
        idle_threshold_s: float | None = None,
        poll_interval_s: float | None = None,
        cycle_interval_s: float | None = None,
        max_passes_per_cycle: int | None = None,
        max_cycles_per_session: int | None = None,
        command_checks: list[CommandCheck] | None = None,
        notify_fn: Callable[[str], None] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._idle_threshold_s = float(
            _DEFAULT_IDLE_THRESHOLD_S if idle_threshold_s is None else max(0.0, float(idle_threshold_s))
        )
        self._poll_interval_s = float(
            _DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else max(1.0, float(poll_interval_s))
        )
        self._cycle_interval_s = float(
            _DEFAULT_CYCLE_INTERVAL_S if cycle_interval_s is None else max(1.0, float(cycle_interval_s))
        )
        self._max_passes_per_cycle = int(
            _DEFAULT_MAX_PASSES if max_passes_per_cycle is None else max(1, int(max_passes_per_cycle))
        )
        self._max_cycles_per_session = int(
            _DEFAULT_MAX_CYCLES if max_cycles_per_session is None else max(1, int(max_cycles_per_session))
        )
        self._command_checks = list(command_checks or _load_command_checks_from_env())
        self._notify_fn = notify_fn
        self._log_path = Path(log_path or (STATE_DIR / "code_issue_engine.jsonl"))

        self._running = False
        self._thread: threading.Thread | None = None
        self._active_cycle = False
        self._lock = threading.Lock()
        self._last_user_ts = time.monotonic()
        self._last_cycle_ts = 0.0
        self._cycle_count = 0
        self._last_report: dict[str, Any] = {}
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._enabled = _env_bool("THOMAS_CODE_ISSUE_ENGINE_ENABLED", True)

    def start(self, *, notify_fn: Callable[[str], None] | None = None) -> None:
        if notify_fn is not None:
            self._notify_fn = notify_fn
        if self._running or not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thomas-code-issue")
        self._thread.start()
        log.info("CodeIssueEngine started (idle threshold %.0fs).", self._idle_threshold_s)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        self._last_user_ts = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_user_ts) >= self._idle_threshold_s

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._running),
                "enabled": bool(self._enabled),
                "cycles_completed": int(self._cycle_count),
                "active_cycle": bool(self._active_cycle),
                "last_cycle_at": str(self._last_report.get("timestamp") or ""),
                "last_clean": bool(self._last_report.get("clean")) if self._last_report else None,
                "last_unresolved_count": int(self._last_report.get("unresolved_count") or 0)
                if self._last_report
                else 0,
                "last_error": str(self._last_error or ""),
                "last_error_at": str(self._last_error_at or ""),
            }

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
            return self._run_cycle_checked(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def summary_text(self) -> str:
        snap = self.status_snapshot()
        return (
            f"CodeIssueEngine: running={snap['running']} "
            f"cycles={snap['cycles_completed']} "
            f"last_clean={snap['last_clean']} "
            f"unresolved={snap['last_unresolved_count']}"
        )

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_interval_s)
            try:
                self._tick()
            except Exception as exc:
                log.warning("CodeIssueEngine tick failed: %s", exc)

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
            name="thomas-code-issue-cycle",
        ).start()

    def _run_cycle_threadsafe(self, reason: str) -> None:
        try:
            self._run_cycle_checked(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def _run_cycle_checked(self, *, reason: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            report = self._run_cycle(reason=reason)
            self._clear_last_error()
            return report
        except Exception as exc:  # pragma: no cover - defensive path
            return self._error_report(reason=reason, exc=exc, started=started)

    def _run_cycle(self, *, reason: str) -> dict[str, Any]:
        started = time.monotonic()
        max_passes = int(
            _env_int("THOMAS_CODE_ISSUE_MAX_PASSES", self._max_passes_per_cycle, min_value=1, max_value=20)
        )
        include_warn_as_issue = _env_bool("THOMAS_CODE_ISSUE_WARN_AS_ISSUE", False)

        pass_rows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        total_fix_attempts = 0
        clean = False

        for pass_idx in range(1, max_passes + 1):
            pre = self._heartbeat_report(fix=False)
            pre_failures = self._heartbeat_unresolved(pre, include_warn=include_warn_as_issue)
            has_fixable = any(bool(item.get("auto_fixable")) for item in pre_failures)

            heartbeat_fix_attempted = False
            post = pre
            if pre_failures and has_fixable:
                heartbeat_fix_attempted = True
                post = self._heartbeat_report(fix=True)

            heartbeat_unresolved = self._heartbeat_unresolved(post, include_warn=include_warn_as_issue)

            command_rows, command_unresolved, command_fix_attempts = self._run_command_checks()
            unresolved = heartbeat_unresolved + command_unresolved
            fixes_attempted = int(command_fix_attempts + (1 if heartbeat_fix_attempted else 0))
            total_fix_attempts += fixes_attempted

            pass_row = {
                "pass_index": pass_idx,
                "heartbeat": {
                    "pre_summary": dict(pre.get("summary") or {}),
                    "post_summary": dict(post.get("summary") or {}),
                    "fix_attempted": bool(heartbeat_fix_attempted),
                    "unresolved_count": len(heartbeat_unresolved),
                },
                "command_checks": command_rows,
                "unresolved_count": len(unresolved),
                "fixes_attempted": int(fixes_attempted),
            }
            pass_rows.append(pass_row)

            if not unresolved:
                clean = True
                break
            if fixes_attempted <= 0:
                break

        elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)

        report = {
            "ok": True,
            "cycle": cycle_id,
            "reason": str(reason or "manual"),
            "timestamp": _now_iso(),
            "clean": bool(clean),
            "passes": pass_rows,
            "unresolved_count": len(unresolved),
            "unresolved": unresolved,
            "fixes_attempted": int(total_fix_attempts),
            "elapsed_ms": elapsed_ms,
        }
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = report

        if self._notify_fn is not None:
            try:
                if clean:
                    self._notify_fn(f"[CodeIssueEngine] cycle {cycle_id}: clean after {len(pass_rows)} pass(es).")
                elif unresolved:
                    preview = ", ".join(str(item.get("name") or "?") for item in unresolved[:4])
                    self._notify_fn(
                        f"[CodeIssueEngine] cycle {cycle_id}: unresolved {len(unresolved)} issue(s): {preview}"
                    )
            except Exception:
                pass

        return report

    def _error_report(self, *, reason: str, exc: BaseException, started: float) -> dict[str, Any]:
        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_error_at = _now_iso()

        report = {
            "ok": False,
            "cycle": cycle_id,
            "reason": "engine_error",
            "requested_reason": str(reason or "manual"),
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
            "timestamp": _now_iso(),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        }
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = dict(report)
        if self._notify_fn is not None:
            try:
                self._notify_fn(f"[CodeIssueEngine] cycle {cycle_id} failed: {type(exc).__name__}: {exc}")
            except Exception:
                pass
        return report

    def _clear_last_error(self) -> None:
        self._last_error = None
        self._last_error_at = None

    def _heartbeat_report(self, *, fix: bool) -> dict[str, Any]:
        script = ROOT / "scripts" / "heartbeat.py"
        if not script.exists():
            return {
                "ok": False,
                "results": [
                    {
                        "name": "heartbeat",
                        "status": "fail",
                        "message": "scripts/heartbeat.py not found",
                        "auto_fixable": False,
                    }
                ],
                "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
            }
        cmd = [sys.executable, str(script), "--json"]
        if fix:
            cmd.append("--fix")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180.0,
            )
        except Exception as exc:
            return {
                "ok": False,
                "results": [
                    {
                        "name": "heartbeat",
                        "status": "fail",
                        "message": f"heartbeat subprocess failed: {type(exc).__name__}: {exc}",
                        "auto_fixable": False,
                    }
                ],
                "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
            }
        text = str(proc.stdout or "").strip()
        if not text:
            return {
                "ok": False,
                "results": [
                    {
                        "name": "heartbeat",
                        "status": "fail",
                        "message": f"heartbeat emitted no JSON (exit {proc.returncode})",
                        "auto_fixable": False,
                    }
                ],
                "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
            }
        try:
            payload = json.loads(text)
        except Exception:
            payload = {
                "ok": False,
                "results": [
                    {
                        "name": "heartbeat",
                        "status": "fail",
                        "message": f"heartbeat returned non-JSON output (exit {proc.returncode})",
                        "auto_fixable": False,
                        "details": {"stdout": _truncate_text(text), "stderr": _truncate_text(str(proc.stderr or ""))},
                    }
                ],
                "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
            }
        if not isinstance(payload, dict):
            payload = {"ok": False, "results": [], "summary": {"total": 0, "pass": 0, "warn": 0, "fail": 0}}
        return payload

    def _heartbeat_unresolved(self, report: dict[str, Any], *, include_warn: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in list(report.get("results") or []):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status not in {"fail", "warn"}:
                continue
            if status == "warn" and not include_warn:
                continue
            out.append(
                {
                    "source": "heartbeat",
                    "name": str(row.get("name") or "heartbeat"),
                    "status": status,
                    "message": str(row.get("message") or "").strip(),
                    "auto_fixable": bool(row.get("auto_fixable")),
                }
            )
        return out

    def _run_command_checks(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        fix_attempts = 0
        for spec in self._command_checks:
            check_before = self._run_shell_command(spec.check_command, timeout_seconds=spec.timeout_seconds)
            fix_row: dict[str, Any] = {}
            check_after = check_before
            if check_before.returncode != 0 and spec.fix_command:
                fix_attempts += 1
                fix_run = self._run_shell_command(spec.fix_command, timeout_seconds=spec.timeout_seconds)
                fix_row = {
                    "command": spec.fix_command,
                    "exit_code": int(fix_run.returncode),
                    "stdout": _truncate_text(str(fix_run.stdout or "")),
                    "stderr": _truncate_text(str(fix_run.stderr or "")),
                }
                check_after = self._run_shell_command(spec.check_command, timeout_seconds=spec.timeout_seconds)

            row = {
                "name": spec.name,
                "check_command": spec.check_command,
                "exit_code": int(check_after.returncode),
                "ok": bool(check_after.returncode == 0),
                "stdout": _truncate_text(str(check_after.stdout or "")),
                "stderr": _truncate_text(str(check_after.stderr or "")),
                "fix": fix_row,
            }
            rows.append(row)
            if check_after.returncode != 0:
                unresolved.append(
                    {
                        "source": "command",
                        "name": spec.name,
                        "status": "fail",
                        "message": f"check failed: {spec.check_command}",
                        "auto_fixable": bool(spec.fix_command),
                    }
                )
        return rows, unresolved, fix_attempts

    def _run_shell_command(self, command: str, *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            str(command),
            cwd=str(ROOT),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_seconds)),
        )

    def _write_cycle_log(self, report: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug("CodeIssueEngine failed to write log: %s", exc)


_engine: CodeIssueEngine | None = None
_engine_lock = threading.Lock()


def get_code_issue_engine() -> CodeIssueEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = CodeIssueEngine()
    return _engine
