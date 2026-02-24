"""Self-upgrade engine that creates and maintains meaningful upgrade goals."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from thomas.core.code_issue_engine import CodeIssueEngine, get_code_issue_engine
from thomas.core.persistence import get_persistence
from thomas.core.ui_workflow_engine import get_ui_workflow_engine

log = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".thomas"
_GOAL_PREFIX = "self-upgrade:"

_DEFAULT_IDLE_THRESHOLD_S = 10 * 60.0
_DEFAULT_POLL_INTERVAL_S = 60.0
_DEFAULT_CYCLE_INTERVAL_S = 30 * 60.0
_DEFAULT_MAX_CYCLES = 120


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


class SelfUpgradeEngine:
    """Background engine that keeps a durable self-upgrade backlog current."""

    def __init__(
        self,
        *,
        idle_threshold_s: Optional[float] = None,
        poll_interval_s: Optional[float] = None,
        cycle_interval_s: Optional[float] = None,
        max_cycles_per_session: Optional[int] = None,
        issue_engine: Optional[CodeIssueEngine] = None,
        notify_fn: Optional[Callable[[str], None]] = None,
        log_path: Optional[Path] = None,
    ) -> None:
        self._idle_threshold_s = float(
            _DEFAULT_IDLE_THRESHOLD_S if idle_threshold_s is None else max(0.0, float(idle_threshold_s))
        )
        self._poll_interval_s = float(_DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else max(1.0, float(poll_interval_s)))
        self._cycle_interval_s = float(
            _DEFAULT_CYCLE_INTERVAL_S if cycle_interval_s is None else max(1.0, float(cycle_interval_s))
        )
        self._max_cycles_per_session = int(
            _DEFAULT_MAX_CYCLES if max_cycles_per_session is None else max(1, int(max_cycles_per_session))
        )
        self._issue_engine = issue_engine
        self._notify_fn = notify_fn
        self._log_path = Path(log_path or (STATE_DIR / "self_upgrade_engine.jsonl"))

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._active_cycle = False
        self._lock = threading.Lock()
        self._last_user_ts = time.monotonic()
        self._last_cycle_ts = 0.0
        self._cycle_count = 0
        self._last_report: Dict[str, Any] = {}
        self._enabled = _env_bool("THOMAS_SELF_UPGRADE_ENGINE_ENABLED", True)

    def start(
        self,
        *,
        notify_fn: Optional[Callable[[str], None]] = None,
        issue_engine: Optional[CodeIssueEngine] = None,
    ) -> None:
        if notify_fn is not None:
            self._notify_fn = notify_fn
        if issue_engine is not None:
            self._issue_engine = issue_engine
        if self._running or not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thomas-self-upgrade")
        self._thread.start()
        log.info("SelfUpgradeEngine started (idle threshold %.0fs).", self._idle_threshold_s)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        self._last_user_ts = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_user_ts) >= self._idle_threshold_s

    def status_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._running),
                "enabled": bool(self._enabled),
                "cycles_completed": int(self._cycle_count),
                "active_cycle": bool(self._active_cycle),
                "last_cycle_at": str(self._last_report.get("timestamp") or ""),
                "last_opportunity_count": int(self._last_report.get("opportunity_count") or 0)
                if self._last_report
                else 0,
            }

    def summary_text(self) -> str:
        snap = self.status_snapshot()
        return (
            f"SelfUpgradeEngine: running={snap['running']} "
            f"cycles={snap['cycles_completed']} "
            f"opportunities={snap['last_opportunity_count']}"
        )

    def run_cycle_once(self, *, reason: str = "manual", force: bool = False) -> Dict[str, Any]:
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
            return self._run_cycle(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_interval_s)
            try:
                self._tick()
            except Exception as exc:
                log.warning("SelfUpgradeEngine tick failed: %s", exc)

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
            name="thomas-self-upgrade-cycle",
        ).start()

    def _run_cycle_threadsafe(self, reason: str) -> None:
        try:
            self._run_cycle(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def _run_cycle(self, *, reason: str) -> Dict[str, Any]:
        started = time.monotonic()
        issue_engine = self._issue_engine or get_code_issue_engine()
        issue_report = issue_engine.run_cycle_once(reason="self_upgrade", force=True)
        ui_report = self._run_ui_workflow_check()

        config_report = self._run_json_module_check("thomas.system.config_validator")
        contract_report = self._run_json_module_check("thomas.system.release_contracts")

        opportunities = self._collect_opportunities(issue_report, ui_report, config_report, contract_report)
        open_goal_ids = self._sync_upgrade_goals(opportunities)

        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)

        elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
        report = {
            "ok": True,
            "cycle": cycle_id,
            "reason": str(reason or "manual"),
            "timestamp": _now_iso(),
            "issue_report": issue_report,
            "ui_report_summary": {
                "ok": bool(ui_report.get("ok")),
                "score": int(ui_report.get("score") or 0),
                "warning_count": int(ui_report.get("warning_count") or 0),
            },
            "config_report_summary": dict(config_report.get("summary") or {}),
            "release_contract_report_summary": dict(contract_report.get("summary") or {}),
            "opportunities": opportunities,
            "opportunity_count": len(opportunities),
            "active_upgrade_goals": sorted(open_goal_ids),
            "elapsed_ms": elapsed_ms,
        }

        self._write_cycle_log(report)
        with self._lock:
            self._last_report = report

        if self._notify_fn is not None:
            try:
                if opportunities:
                    kinds = ", ".join(str(item.get("kind") or "upgrade") for item in opportunities[:4])
                    self._notify_fn(
                        f"[SelfUpgradeEngine] cycle {cycle_id}: tracked {len(opportunities)} upgrade opportunities ({kinds})."
                    )
                else:
                    self._notify_fn(f"[SelfUpgradeEngine] cycle {cycle_id}: no upgrade opportunities detected.")
            except Exception:
                pass

        return report

    def _run_json_module_check(self, module: str) -> Dict[str, Any]:
        cmd = [sys.executable, "-m", module, "--json"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                timeout=120.0,
            )
        except Exception as exc:
            return {
                "ok": False,
                "summary": {"error_count": 1, "warning_count": 0},
                "errors": [{"code": "subprocess.error", "message": f"{type(exc).__name__}: {exc}"}],
            }

        text = str(proc.stdout or "").strip()
        if not text:
            return {
                "ok": False,
                "summary": {"error_count": 1, "warning_count": 0},
                "errors": [{"code": "empty_output", "message": f"{module} emitted no JSON"}],
            }
        try:
            payload = json.loads(text)
        except Exception:
            payload = {
                "ok": False,
                "summary": {"error_count": 1, "warning_count": 0},
                "errors": [{"code": "invalid_json", "message": _truncate(text)}],
            }
        if not isinstance(payload, dict):
            payload = {"ok": False, "summary": {"error_count": 1, "warning_count": 0}, "errors": []}
        return payload

    def _collect_opportunities(
        self,
        issue_report: Dict[str, Any],
        ui_report: Dict[str, Any],
        config_report: Dict[str, Any],
        contract_report: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        opportunities: List[Dict[str, Any]] = []

        unresolved_count = int(issue_report.get("unresolved_count") or 0)
        if unresolved_count > 0:
            unresolved = list(issue_report.get("unresolved") or [])
            sample = ", ".join(str(row.get("name") or "?") for row in unresolved[:5])
            opportunities.append(
                {
                    "kind": "code_issues",
                    "severity": "high",
                    "summary": f"{unresolved_count} unresolved code issue(s): {sample}",
                }
            )

        ui_warnings = int(ui_report.get("warning_count") or 0)
        ui_score = int(ui_report.get("score") or 0)
        if ui_warnings > 0:
            warning_rows = [row for row in list(ui_report.get("warnings") or []) if isinstance(row, dict)]
            sample = ", ".join(str(row.get("id") or "?") for row in warning_rows[:5])
            severity = "high" if ui_score < 70 or ui_warnings >= 5 else "medium"
            opportunities.append(
                {
                    "kind": "ui_quality_hardening",
                    "severity": severity,
                    "summary": f"UI workflow audit score={ui_score} with {ui_warnings} warning(s): {sample}",
                }
            )

        cfg_summary = dict(config_report.get("summary") or {})
        cfg_errors = int(cfg_summary.get("error_count") or 0)
        cfg_warnings = int(cfg_summary.get("warning_count") or 0)
        if cfg_errors > 0 or cfg_warnings > 0:
            severity = "high" if cfg_errors > 0 else "medium"
            opportunities.append(
                {
                    "kind": "config_hardening",
                    "severity": severity,
                    "summary": f"config validator reports {cfg_errors} error(s), {cfg_warnings} warning(s)",
                }
            )

        rel_summary = dict(contract_report.get("summary") or {})
        rel_errors = int(rel_summary.get("error_count") or 0)
        rel_warnings = int(rel_summary.get("warning_count") or 0)
        if rel_errors > 0 or rel_warnings > 0:
            severity = "high" if rel_errors > 0 else "medium"
            opportunities.append(
                {
                    "kind": "release_contract_quality",
                    "severity": severity,
                    "summary": f"release contracts report {rel_errors} error(s), {rel_warnings} warning(s)",
                }
            )

        return opportunities

    def _run_ui_workflow_check(self) -> Dict[str, Any]:
        try:
            engine = get_ui_workflow_engine()
            report = engine.run_cycle_once(reason="self_upgrade", force=True)
            if isinstance(report, dict):
                return report
        except Exception as exc:
            return {
                "ok": False,
                "score": 0,
                "warning_count": 1,
                "warnings": [{"id": "ui_engine.error", "message": f"{type(exc).__name__}: {exc}"}],
            }
        return {"ok": False, "score": 0, "warning_count": 0, "warnings": []}

    def _sync_upgrade_goals(self, opportunities: List[Dict[str, Any]]) -> set[str]:
        persistence = get_persistence()
        desired_ids: set[str] = set()

        for item in opportunities:
            kind = str(item.get("kind") or "upgrade").strip().lower()
            summary = str(item.get("summary") or "").strip()
            goal_id = self._goal_id(kind=kind, summary=summary)
            desired_ids.add(goal_id)
            persistence.upsert_goal(goal_id, f"[self-upgrade] {summary}", status="open")

        existing = list(persistence.open_goals() or [])
        for goal in existing:
            goal_id = str(goal.get("id") or "")
            if not goal_id.startswith(_GOAL_PREFIX):
                continue
            if goal_id not in desired_ids:
                persistence.close_goal(goal_id)

        persistence.set_fact(
            "self_upgrade.last_report",
            {
                "timestamp": _now_iso(),
                "opportunity_count": len(opportunities),
                "goal_ids": sorted(desired_ids),
            },
        )
        return desired_ids

    def _goal_id(self, *, kind: str, summary: str) -> str:
        blob = f"{kind}|{summary}".encode("utf-8", errors="ignore")
        digest = hashlib.sha1(blob).hexdigest()[:12]
        return f"{_GOAL_PREFIX}{kind}:{digest}"

    def _write_cycle_log(self, report: Dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug("SelfUpgradeEngine failed to write log: %s", exc)


_engine: Optional[SelfUpgradeEngine] = None
_engine_lock = threading.Lock()


def get_self_upgrade_engine() -> SelfUpgradeEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SelfUpgradeEngine()
    return _engine
