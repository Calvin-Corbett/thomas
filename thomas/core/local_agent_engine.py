"""Local background-agent engine for hardware-aware autonomous maintenance."""

from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.local_agent_engine_utils import (
    env_bool,
    env_int,
    extract_topic_tokens,
    now_iso,
    parse_iso_utc,
    safe_int,
)
from thomas.core.persistence import get_persistence

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path.home() / ".thomas"

_DEFAULT_IDLE_THRESHOLD_S = 5 * 60.0
_DEFAULT_POLL_INTERVAL_S = 45.0
_DEFAULT_CYCLE_INTERVAL_S = 8 * 60.0
_DEFAULT_MAX_CYCLES = 500
_DEFAULT_MIN_GPU_HEADROOM_PCT = 35


def detect_local_hardware_profile() -> dict[str, Any]:
    """Resolve hardware profile without a static core->models import edge."""
    try:
        mod = importlib.import_module("thomas.models.local_recommendations")
        fn = getattr(mod, "detect_local_hardware_profile", None)
        if callable(fn):
            value = fn()
            if isinstance(value, dict):
                return value
    except Exception as exc:
        log.debug("Local hardware profile fallback activated: %s", exc)
    return {"device_tier": "unknown", "gpu": {}, "cpu": {}, "ram": {}}


def build_local_runtime_plan(
    *,
    hardware: dict[str, Any],
    local_profile_exists: bool,
    ollama_installed: bool,
    ollama_running: bool,
) -> dict[str, Any]:
    """Resolve runtime plan without a static core->models import edge."""
    try:
        mod = importlib.import_module("thomas.models.local_recommendations")
        fn = getattr(mod, "build_local_runtime_plan", None)
        if callable(fn):
            value = fn(
                hardware=hardware,
                local_profile_exists=local_profile_exists,
                ollama_installed=ollama_installed,
                ollama_running=ollama_running,
            )
            if isinstance(value, dict):
                return value
    except Exception as exc:
        log.debug("Local runtime plan fallback activated: %s", exc)
    return {
        "recommended_mode": "cloud_only",
        "recommended_models": [],
        "reasons": ["local_recommendations_unavailable"],
    }


class LocalAgentEngine:
    """Runs local-only background maintenance when settings + hardware allow it."""

    def __init__(
        self,
        *,
        idle_threshold_s: float | None = None,
        poll_interval_s: float | None = None,
        cycle_interval_s: float | None = None,
        max_cycles_per_session: int | None = None,
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
        self._max_cycles_per_session = int(
            _DEFAULT_MAX_CYCLES if max_cycles_per_session is None else max(1, int(max_cycles_per_session))
        )
        self._notify_fn = notify_fn
        self._log_path = Path(log_path or (STATE_DIR / "local_agent_engine.jsonl"))

        self._running = False
        self._thread: threading.Thread | None = None
        self._active_cycle = False
        self._lock = threading.Lock()
        self._last_user_ts = time.monotonic()
        self._last_cycle_ts = 0.0
        self._cycle_count = 0
        self._last_report: dict[str, Any] = {}
        self._enabled = env_bool("THOMAS_LOCAL_AGENT_ENGINE_ENABLED", True)

    def start(self, *, notify_fn: Callable[[str], None] | None = None) -> None:
        if notify_fn is not None:
            self._notify_fn = notify_fn
        if self._running or not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thomas-local-agent")
        self._thread.start()
        log.info("LocalAgentEngine started (idle threshold %.0fs).", self._idle_threshold_s)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        self._last_user_ts = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_user_ts) >= self._idle_threshold_s

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            report = dict(self._last_report) if isinstance(self._last_report, dict) else {}
            return {
                "running": bool(self._running),
                "enabled": bool(self._enabled),
                "cycles_completed": int(self._cycle_count),
                "active_cycle": bool(self._active_cycle),
                "log_path": str(self._log_path),
                "last_cycle_at": str(report.get("timestamp") or ""),
                "last_reason": str(report.get("reason") or ""),
                "last_skip_reason": str(report.get("skip_reason") or ""),
                "last_plan_mode": str((report.get("plan") or {}).get("recommended_mode") or ""),
                "settings_enabled": bool((report.get("settings") or {}).get("enabled")),
                "min_gpu_headroom_pct": safe_int((report.get("settings") or {}).get("min_gpu_headroom_pct"), 0),
                "last_gpu_headroom_pct": safe_int(report.get("gpu_headroom_pct"), 0),
                "last_task_count": len(list(report.get("tasks") or [])),
            }

    def recent_reports(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_cycle_reports(limit=limit)

    def health_snapshot(self, *, history_limit: int = 20) -> dict[str, Any]:
        rows = self._read_cycle_reports(limit=max(1, int(history_limit)))
        if not rows:
            return {
                "history_count": 0,
                "failure_rate": 0.0,
                "failed_cycles": 0,
                "skipped_cycles": 0,
                "task_failures": 0,
                "skip_reasons": {},
                "last_success_at": "",
                "last_failure_at": "",
            }

        failed_cycles = sum(1 for row in rows if not bool(row.get("ok", False)))
        skipped_cycles = sum(1 for row in rows if str(row.get("skip_reason") or "").strip())
        task_failures = 0
        skip_reasons: dict[str, int] = {}
        last_success_at = ""
        last_failure_at = ""
        for row in rows:
            if bool(row.get("ok", False)):
                last_success_at = str(row.get("timestamp") or last_success_at)
            else:
                last_failure_at = str(row.get("timestamp") or last_failure_at)
            skip_reason = str(row.get("skip_reason") or "").strip()
            if skip_reason:
                skip_reasons[skip_reason] = skip_reasons.get(skip_reason, 0) + 1
            for task in list(row.get("tasks") or []):
                if isinstance(task, dict) and not bool(task.get("ok", False)):
                    task_failures += 1

        failure_rate = round(float(failed_cycles) / float(max(1, len(rows))), 3)
        return {
            "history_count": int(len(rows)),
            "failure_rate": float(failure_rate),
            "failed_cycles": int(failed_cycles),
            "skipped_cycles": int(skipped_cycles),
            "task_failures": int(task_failures),
            "skip_reasons": skip_reasons,
            "last_success_at": last_success_at,
            "last_failure_at": last_failure_at,
        }

    def summary_text(self) -> str:
        snap = self.status_snapshot()
        return (
            f"LocalAgentEngine: running={snap['running']} "
            f"cycles={snap['cycles_completed']} "
            f"mode={snap['last_plan_mode'] or 'unknown'} "
            f"skip={snap['last_skip_reason'] or 'none'}"
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
            return self._run_cycle(reason=reason, force=force)
        finally:
            with self._lock:
                self._active_cycle = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_interval_s)
            try:
                self._tick()
            except Exception as exc:
                log.warning("LocalAgentEngine tick failed: %s", exc)

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
            name="thomas-local-agent-cycle",
        ).start()

    def _run_cycle_threadsafe(self, reason: str) -> None:
        try:
            self._run_cycle(reason=reason, force=False)
        finally:
            with self._lock:
                self._active_cycle = False

    def _load_runtime_settings(self) -> dict[str, Any]:
        enabled_default = env_bool("THOMAS_LOCAL_BACKGROUND_AGENTS_ENABLED_DEFAULT", False)
        headroom_default = env_int(
            "THOMAS_LOCAL_BACKGROUND_MIN_GPU_HEADROOM_PCT_DEFAULT",
            _DEFAULT_MIN_GPU_HEADROOM_PCT,
            min_value=5,
            max_value=95,
        )
        try:
            pref_mod = importlib.import_module("thomas.preferences.store")
            prefs_cls = getattr(pref_mod, "PreferencesStore", None)
            db_path_fn = getattr(pref_mod, "get_db_path", None)
            if not callable(prefs_cls) or not callable(db_path_fn):
                raise RuntimeError("preferences store entrypoints unavailable")
            prefs = prefs_cls(db_path_fn()).get(user_id="default")
            runtime = getattr(getattr(prefs, "advanced", None), "runtime", None)
            enabled = bool(getattr(runtime, "local_background_agents_enabled", enabled_default))
            headroom = safe_int(
                getattr(runtime, "local_background_min_gpu_headroom_pct", headroom_default), headroom_default
            )
        except Exception:
            enabled = bool(enabled_default)
            headroom = int(headroom_default)
        headroom = max(5, min(95, int(headroom)))
        return {
            "enabled": enabled,
            "min_gpu_headroom_pct": headroom,
        }

    def _run_cycle(self, *, reason: str, force: bool) -> dict[str, Any]:
        started = time.monotonic()
        settings = self._load_runtime_settings()
        hardware = detect_local_hardware_profile()
        plan = build_local_runtime_plan(
            hardware=hardware,
            local_profile_exists=True,
            ollama_installed=bool(shutil.which("ollama") or shutil.which("ollama.exe")),
            ollama_running=True,
        )

        gpu_util = (hardware.get("gpu") or {}).get("average_utilization_pct")
        gpu_headroom_pct: float | None = None
        if gpu_util is not None:
            try:
                gpu_headroom_pct = max(0.0, 100.0 - float(gpu_util))
            except Exception:
                gpu_headroom_pct = None

        if not settings.get("enabled") and not force:
            return self._finish(
                ok=False,
                reason="engine_disabled",
                skip_reason="disabled_in_settings",
                settings=settings,
                plan=plan,
                hardware=hardware,
                tasks=[],
                gpu_headroom_pct=gpu_headroom_pct,
                elapsed_ms=started,
            )

        if str(plan.get("recommended_mode") or "").strip().lower() == "cloud_only" and not force:
            return self._finish(
                ok=False,
                reason="cloud_only_recommended",
                skip_reason="cloud_only_device",
                settings=settings,
                plan=plan,
                hardware=hardware,
                tasks=[],
                gpu_headroom_pct=gpu_headroom_pct,
                elapsed_ms=started,
            )

        if (
            gpu_headroom_pct is not None
            and gpu_headroom_pct < float(settings.get("min_gpu_headroom_pct") or _DEFAULT_MIN_GPU_HEADROOM_PCT)
            and not force
        ):
            return self._finish(
                ok=False,
                reason="gpu_busy",
                skip_reason="gpu_headroom_low",
                settings=settings,
                plan=plan,
                hardware=hardware,
                tasks=[],
                gpu_headroom_pct=gpu_headroom_pct,
                elapsed_ms=started,
            )

        tasks = self._run_background_tasks(plan=plan, hardware=hardware)
        ok = all(bool(row.get("ok")) for row in tasks)
        report = self._finish(
            ok=ok,
            reason=str(reason or "manual"),
            skip_reason="",
            settings=settings,
            plan=plan,
            hardware=hardware,
            tasks=tasks,
            gpu_headroom_pct=gpu_headroom_pct,
            elapsed_ms=started,
        )
        if self._notify_fn is not None:
            try:
                mode = str((report.get("plan") or {}).get("recommended_mode") or "unknown")
                self._notify_fn(f"[LocalAgentEngine] cycle {report.get('cycle')}: mode={mode} tasks={len(tasks)}")
            except Exception:
                pass
        return report

    def _run_background_tasks(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fn in (
            self._task_memory_digest_refresh,
            self._task_memory_signal_quality,
            self._task_local_model_readiness,
            self._task_local_model_backlog,
            self._task_goal_backlog_triage,
            self._task_workspace_queue_index,
            self._task_toolchain_preflight,
        ):
            try:
                rows.append(fn(plan=plan, hardware=hardware))
            except Exception as exc:
                rows.append(
                    {
                        "ok": False,
                        "id": getattr(fn, "__name__", "unknown"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return rows

    def _task_memory_digest_refresh(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        persistence = get_persistence()
        open_goals = list(persistence.open_goals())
        recent_turns = list(persistence.recent_turns(n=60))

        topic_counts: dict[str, int] = {}
        for turn in recent_turns:
            content = f"{getattr(turn, 'user_msg', '')} {getattr(turn, 'assistant_msg', '')}"
            for token in extract_topic_tokens(content):
                topic_counts[token] = topic_counts.get(token, 0) + 1
        top_topics = [k for k, _v in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:12]]

        digest = {
            "updated_at": now_iso(),
            "open_goal_count": len(open_goals),
            "open_goal_ids": [str(goal.get("id") or "") for goal in open_goals[:12] if isinstance(goal, dict)],
            "recent_turn_count": len(recent_turns),
            "top_topics": top_topics,
            "recommended_mode": str(plan.get("recommended_mode") or ""),
            "device_tier": str(hardware.get("device_tier") or ""),
        }
        persistence.set_fact("local_agent.memory_digest", digest)
        return {
            "ok": True,
            "id": "memory_digest_refresh",
            "open_goal_count": len(open_goals),
            "recent_turn_count": len(recent_turns),
            "top_topics": top_topics[:6],
        }

    def _list_ollama_models(self) -> list[str]:
        url = "http://127.0.0.1:11434/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=2.5) as resp:
                if int(getattr(resp, "status", 0) or 0) != 200:
                    return []
                # Cap the read so a local MITM / misbehaving endpoint can't OOM us.
                payload = json.loads(resp.read(4 * 1024 * 1024).decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, ValueError):
            return []
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []
        rows = payload.get("models")
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    def _task_local_model_readiness(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        recommended_ids = [
            str(row.get("id") or "").strip()
            for row in list(plan.get("recommended_models") or [])
            if isinstance(row, dict)
        ]
        recommended_ids = [model_id for model_id in recommended_ids if model_id]
        installed = self._list_ollama_models()
        installed_set = set(installed)
        missing = [model_id for model_id in recommended_ids if model_id not in installed_set]
        readiness = {
            "updated_at": now_iso(),
            "recommended_models": recommended_ids,
            "installed_models": installed,
            "missing_models": missing,
            "healthy": len(missing) == 0,
        }
        get_persistence().set_fact("local_agent.model_readiness", readiness)
        return {
            "ok": True,
            "id": "local_model_readiness",
            "recommended_count": len(recommended_ids),
            "installed_count": len(installed),
            "missing_count": len(missing),
            "healthy": len(missing) == 0,
        }

    def _task_local_model_backlog(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        recommended = [dict(row) for row in list(plan.get("recommended_models") or []) if isinstance(row, dict)]
        installed_set = set(self._list_ollama_models())
        backlog: list[dict[str, Any]] = []
        for row in recommended:
            model_id = str(row.get("id") or "").strip()
            if not model_id or model_id in installed_set:
                continue
            role = str(row.get("role") or "local_agent").strip().lower()
            priority = "high" if ("primary" in role or "reasoning" in role) else "normal"
            backlog.append(
                {
                    "model_id": model_id,
                    "role": role or "local_agent",
                    "priority": priority,
                    "action": "pull_and_probe",
                }
            )

        snapshot = {
            "updated_at": now_iso(),
            "device_tier": str(hardware.get("device_tier") or ""),
            "recommended_mode": str(plan.get("recommended_mode") or ""),
            "queue_size": len(backlog),
            "queue": backlog,
        }
        get_persistence().set_fact("local_agent.model_backlog", snapshot)
        return {
            "ok": True,
            "id": "local_model_backlog",
            "queue_size": len(backlog),
            "high_priority": sum(1 for row in backlog if row.get("priority") == "high"),
        }

    def _task_goal_backlog_triage(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        persistence = get_persistence()
        open_goals = list(persistence.open_goals())
        now = datetime.now(timezone.utc)

        stale_goal_ids: list[str] = []
        urgent_goal_ids: list[str] = []
        for row in open_goals:
            if not isinstance(row, dict):
                continue
            goal_id = str(row.get("id") or "").strip()
            text = str(row.get("text") or "").strip().lower()
            created_dt = parse_iso_utc(row.get("created"))
            if created_dt is not None:
                age_hours = (now - created_dt).total_seconds() / 3600.0
                if age_hours >= 72.0 and goal_id:
                    stale_goal_ids.append(goal_id)
            if re.search(r"\b(urgent|critical|broken|failing|incident|security)\b", text):
                if goal_id:
                    urgent_goal_ids.append(goal_id)

        triage = {
            "updated_at": now_iso(),
            "open_goal_count": len(open_goals),
            "stale_goal_ids": stale_goal_ids[:40],
            "urgent_goal_ids": urgent_goal_ids[:40],
            "recommended_mode": str(plan.get("recommended_mode") or ""),
        }
        persistence.set_fact("local_agent.goal_backlog", triage)
        return {
            "ok": True,
            "id": "goal_backlog_triage",
            "open_goal_count": len(open_goals),
            "stale_goal_count": len(stale_goal_ids),
            "urgent_goal_count": len(urgent_goal_ids),
        }

    def _task_memory_signal_quality(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        turns = list(get_persistence().recent_turns(n=120))
        if not turns:
            snapshot = {
                "updated_at": now_iso(),
                "turn_count": 0,
                "signal_score": 100,
                "weak_signals": {"assistant_empty": 0, "unanswered_questions": 0, "long_user_turns": 0},
            }
            get_persistence().set_fact("local_agent.memory_signal_quality", snapshot)
            return {"ok": True, "id": "memory_signal_quality", "turn_count": 0, "signal_score": 100}

        assistant_empty = 0
        unanswered_questions = 0
        long_user_turns = 0
        for turn in turns:
            user_msg = str(getattr(turn, "user_msg", "") or "")
            assistant_msg = str(getattr(turn, "assistant_msg", "") or "")
            if len(user_msg) >= 500:
                long_user_turns += 1
            if not assistant_msg.strip():
                assistant_empty += 1
            if "?" in user_msg and len(assistant_msg.strip()) < 16:
                unanswered_questions += 1

        penalty = (assistant_empty * 12) + (unanswered_questions * 9) + (max(0, long_user_turns - 6) * 2)
        signal_score = max(0, min(100, 100 - penalty))
        snapshot = {
            "updated_at": now_iso(),
            "turn_count": len(turns),
            "signal_score": signal_score,
            "weak_signals": {
                "assistant_empty": assistant_empty,
                "unanswered_questions": unanswered_questions,
                "long_user_turns": long_user_turns,
            },
        }
        get_persistence().set_fact("local_agent.memory_signal_quality", snapshot)
        return {
            "ok": True,
            "id": "memory_signal_quality",
            "turn_count": len(turns),
            "signal_score": signal_score,
        }

    def _task_workspace_queue_index(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
        except Exception as exc:
            return {
                "ok": False,
                "id": "workspace_queue_index",
                "error": f"{type(exc).__name__}: {exc}",
            }
        if int(proc.returncode or 0) != 0:
            return {
                "ok": False,
                "id": "workspace_queue_index",
                "error": str(proc.stderr or proc.stdout or "git status failed").strip(),
            }
        lines = [line.rstrip() for line in str(proc.stdout or "").splitlines() if line.strip()]
        staged = 0
        unstaged = 0
        untracked = 0
        for line in lines:
            if line.startswith("??"):
                untracked += 1
                continue
            prefix = line[:2]
            if len(prefix) == 2:
                if prefix[0] != " ":
                    staged += 1
                if prefix[1] != " ":
                    unstaged += 1

        snapshot = {
            "updated_at": now_iso(),
            "total_changes": len(lines),
            "staged_changes": staged,
            "unstaged_changes": unstaged,
            "untracked_files": untracked,
        }
        get_persistence().set_fact("local_agent.workspace_queue", snapshot)
        return {
            "ok": True,
            "id": "workspace_queue_index",
            "total_changes": len(lines),
            "staged_changes": staged,
            "unstaged_changes": unstaged,
            "untracked_files": untracked,
        }

    def _task_toolchain_preflight(self, *, plan: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
        checks = {
            "python": bool(shutil.which("python") or shutil.which("python.exe")),
            "git": bool(shutil.which("git") or shutil.which("git.exe")),
            "ollama": bool(shutil.which("ollama") or shutil.which("ollama.exe")),
        }
        get_persistence().set_fact(
            "local_agent.toolchain_preflight",
            {
                "updated_at": now_iso(),
                "checks": checks,
            },
        )
        return {
            "ok": True,
            "id": "toolchain_preflight",
            "checks": checks,
        }

    def _finish(
        self,
        *,
        ok: bool,
        reason: str,
        skip_reason: str,
        settings: dict[str, Any],
        plan: dict[str, Any],
        hardware: dict[str, Any],
        tasks: list[dict[str, Any]],
        gpu_headroom_pct: float | None,
        elapsed_ms: float,
    ) -> dict[str, Any]:
        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)

        report = {
            "ok": bool(ok),
            "cycle": cycle_id,
            "reason": str(reason or "manual"),
            "skip_reason": str(skip_reason or ""),
            "timestamp": now_iso(),
            "settings": settings,
            "plan": plan,
            "hardware": hardware,
            "tasks": tasks,
            "gpu_headroom_pct": round(float(gpu_headroom_pct), 1) if gpu_headroom_pct is not None else None,
            "elapsed_ms": round((time.monotonic() - elapsed_ms) * 1000.0, 1),
        }
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = dict(report)
        return report

    def _write_cycle_log(self, report: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug("LocalAgentEngine failed to write log: %s", exc)

    def _read_cycle_reports(self, *, limit: int = 20) -> list[dict[str, Any]]:
        max_items = max(1, min(int(limit), 500))
        if not self._log_path.exists():
            return []
        tail: deque[str] = deque(maxlen=max_items)
        try:
            with self._log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = str(line or "").strip()
                    if line:
                        tail.append(line)
        except Exception as exc:
            log.debug("LocalAgentEngine failed reading cycle logs: %s", exc)
            return []

        rows: list[dict[str, Any]] = []
        for raw in tail:
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows


_engine: LocalAgentEngine | None = None
_engine_lock = threading.Lock()


def get_local_agent_engine() -> LocalAgentEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = LocalAgentEngine()
    return _engine
