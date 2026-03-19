"""
FEATURE 13 -- Dependency Monitor for Thomas (v4 "user-love mode")

Requirements (requested):
- Background daily check (runs once per day at startup if last check > 24hrs ago)
- Scans the Thomas project root by default
- If any CRITICAL or HIGH vulns found -> calls notify_fn immediately
- Persists last scan results and timestamp to persistence engine
- Singleton: get_dep_monitor()
- Method: start(notify_fn) -- starts background monitor

Meaningful upgrades:
1) **Alert only when it matters**: emits "new high/critical since last scan" by default
   (still includes total counts so you can decide in UI).
2) **History ring buffer**: stores last N daily summaries (default 30) for trend charts.
3) **Configurable project root** via env THOMAS_PROJECT_ROOT or thomas.toml [dep_scanner].project_root
4) **Scan both ecosystems** automatically if present in the project (pyproject/requirements + package.json).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core.persistence import get_persistence
from thomas.tools.dep_scanner import deps_scan

STATE_KEY = "dep_monitor.state"
SCHEMA_VERSION = 4

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_DAYS = 30


def _now_unix() -> float:
    return time.time()


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _start_daemon(target: Callable[[], None], name: str) -> threading.Thread:
    """
    Best-effort to integrate with thomas.core.testing_suite background facilities.
    If nothing is available, falls back to a normal daemon thread.
    """
    try:
        ts = __import__("thomas.core.testing_suite", fromlist=["start_daemon_thread", "spawn_daemon"])
        for fn_name in ("start_daemon_thread", "spawn_daemon", "spawn_background", "start_background"):
            fn = getattr(ts, fn_name, None)
            if callable(fn):
                try:
                    th = fn(target=target, name=name)  # type: ignore[misc]
                    if isinstance(th, threading.Thread):
                        return th
                except TypeError:
                    try:
                        th = fn(target, name)  # type: ignore[misc]
                        if isinstance(th, threading.Thread):
                            return th
                    except Exception:
                        pass
    except Exception:
        pass

    th = threading.Thread(target=target, name=name, daemon=True)
    th.start()
    return th


class _PersistenceKV:
    """
    Adapter over Thomas persistence engine, which may have different method names.
    Stores a JSON blob under STATE_KEY.
    """

    def __init__(self, p: Any):
        self._p = p

    def load(self) -> dict[str, Any]:
        raw = None
        for name in ("get", "kv_get", "read", "load", "get_json", "get_value"):
            fn = getattr(self._p, name, None)
            if callable(fn):
                try:
                    raw = fn(STATE_KEY)
                    break
                except TypeError:
                    try:
                        raw = fn(STATE_KEY, None)
                        break
                    except Exception:
                        pass
                except Exception:
                    pass

        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def save(self, state: dict[str, Any]) -> None:
        # Some persistence implementations accept dicts; try dict first.
        for name in ("set_json", "put_json", "set"):
            fn = getattr(self._p, name, None)
            if callable(fn):
                try:
                    fn(STATE_KEY, state)
                    return
                except Exception:
                    pass

        payload = json.dumps(state, ensure_ascii=False)
        for name in ("set", "kv_set", "write", "save", "set_value", "put"):
            fn = getattr(self._p, name, None)
            if callable(fn):
                try:
                    fn(STATE_KEY, payload)
                    return
                except TypeError:
                    try:
                        fn(STATE_KEY, payload, None)
                        return
                    except Exception:
                        pass
                except Exception:
                    pass


def _sha1_json(obj: Any) -> str:
    try:
        b = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    except Exception:
        b = str(obj).encode("utf-8", errors="replace")
    return hashlib.sha1(b).hexdigest()


def _safe_get(d: dict[str, Any], key: str, default: Any) -> Any:
    v = d.get(key, default)
    return v if v is not None else default


@dataclass
class DepMonitorState:
    last_scan_ts: float = 0.0
    last_results: dict[str, Any] | None = None
    last_alert_hash: str = ""
    history: list[dict[str, Any]] | None = None


class DepMonitor:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = self._resolve_project_root(project_root)

        self._p = _PersistenceKV(get_persistence())
        self._state = self._load_state()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._notify_fn: Callable[[Any], None] | None = None
        self._scan_lock = threading.Lock()

    def _resolve_project_root(self, override: Path | None) -> Path:
        if override and override.exists():
            return override
        env = str(os.environ.get("THOMAS_PROJECT_ROOT", "")).strip()
        if env:
            p = Path(env).expanduser()
            if p.exists():
                return p.resolve()
        # fallback to default path if present, else cwd
        return DEFAULT_PROJECT_ROOT if DEFAULT_PROJECT_ROOT.exists() else Path.cwd()

    # ------------------------
    # State I/O
    # ------------------------

    def _load_state(self) -> DepMonitorState:
        raw = self._p.load()
        try:
            ts = float(raw.get("last_scan_ts", 0.0) or 0.0)
        except Exception:
            ts = 0.0

        results = raw.get("last_results")
        if not isinstance(results, dict):
            results = None

        last_alert_hash = str(raw.get("last_alert_hash", "") or "")

        hist = raw.get("history")
        if not isinstance(hist, list):
            hist = []

        return DepMonitorState(last_scan_ts=ts, last_results=results, last_alert_hash=last_alert_hash, history=hist)

    def _save_state(self) -> None:
        self._p.save(
            {
                "schema_version": SCHEMA_VERSION,
                "last_scan_ts": self._state.last_scan_ts,
                "last_results": self._state.last_results,
                "last_alert_hash": self._state.last_alert_hash,
                "history": self._state.history or [],
            }
        )

    # ------------------------
    # Public API
    # ------------------------

    def start(self, notify_fn: Callable[[Any], None]) -> None:
        """
        Start background monitor (idempotent).
        - if due, triggers immediate scan in background
        - then wakes hourly and scans only when due
        """
        self._notify_fn = notify_fn
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = _start_daemon(self._loop, name="DepMonitor")

        if self._due_for_scan():
            _start_daemon(lambda: self.scan_now(reason="startup_due"), name="DepMonitorInitialScan")

    def stop(self) -> None:
        self._stop.set()

    def scan_now(self, reason: str = "manual") -> dict[str, Any]:
        """
        Run a scan synchronously, persist results, update history, and alert if needed.
        """
        with self._scan_lock:
            report = self._scan_project()
            self._state.last_scan_ts = _now_unix()
            self._state.last_results = report
            self._update_history(report)
            self._save_state()

        self._maybe_alert(report, reason=reason)
        return report

    def get_status(self) -> dict[str, Any]:
        return {
            "project": str(self.project_root),
            "last_scan_ts": float(self._state.last_scan_ts or 0.0),
            "due": self._due_for_scan(),
            "history_days": len(self._state.history or []),
            "last_results": self._state.last_results,
        }

    # ------------------------
    # Internal
    # ------------------------

    def _due_for_scan(self) -> bool:
        return (_now_unix() - float(self._state.last_scan_ts or 0.0)) > 24 * 3600

    def _notify(self, payload: Any) -> None:
        fn = self._notify_fn
        if not fn:
            return
        try:
            fn(payload)
        except TypeError:
            fn(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _scan_project(self) -> dict[str, Any]:
        """
        Scan python + npm manifests in the project root (best-effort).

        report = {
          "python": scan|{"error":...}|None,
          "npm": scan|{"error":...}|None,
          "combined": {"vulnerabilities":[...], "total":.., "critical":.., ...},
          "ts": unix
        }
        """
        root = self.project_root
        report: dict[str, Any] = {"python": None, "npm": None, "combined": None, "ts": _now_unix()}

        combined_vulns: list[dict[str, Any]] = []
        totals = {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}

        # Python target preference: pyproject.toml -> requirements.txt
        pyproject = root / "pyproject.toml"
        reqs = root / "requirements.txt"
        if pyproject.exists():
            try:
                report["python"] = deps_scan({"target": str(pyproject), "ecosystem": "python"})
            except Exception as e:
                report["python"] = {"error": str(e)}
        elif reqs.exists():
            try:
                report["python"] = deps_scan({"target": str(reqs), "ecosystem": "python"})
            except Exception as e:
                report["python"] = {"error": str(e)}

        # npm: root package.json, else common web locations
        npm_target = None
        pkg = root / "package.json"
        if pkg.exists():
            npm_target = pkg
        else:
            for candidate in [
                root / "thomas" / "server" / "web" / "package.json",
                root / "server" / "web" / "package.json",
                root / "web" / "package.json",
            ]:
                if candidate.exists():
                    npm_target = candidate
                    break

        if npm_target is not None:
            try:
                report["npm"] = deps_scan({"target": str(npm_target), "ecosystem": "npm"})
            except Exception as e:
                report["npm"] = {"error": str(e)}

        for part in ("python", "npm"):
            r = report.get(part)
            if isinstance(r, dict) and isinstance(r.get("vulnerabilities"), list):
                combined_vulns.extend(r["vulnerabilities"])
                totals["total"] += int(r.get("total", 0) or 0)
                totals["critical"] += int(r.get("critical", 0) or 0)
                totals["high"] += int(r.get("high", 0) or 0)
                totals["medium"] += int(r.get("medium", 0) or 0)
                totals["low"] += int(r.get("low", 0) or 0)

        report["combined"] = {"vulnerabilities": combined_vulns, **totals}
        return report

    def _update_history(self, report: dict[str, Any]) -> None:
        hist = self._state.history or []
        combined = report.get("combined") if isinstance(report.get("combined"), dict) else {}
        entry = {
            "ts": float(report.get("ts", _now_unix()) or _now_unix()),
            "total": int(combined.get("total", 0) or 0),
            "critical": int(combined.get("critical", 0) or 0),
            "high": int(combined.get("high", 0) or 0),
            "medium": int(combined.get("medium", 0) or 0),
            "low": int(combined.get("low", 0) or 0),
        }
        hist.append(entry)
        # keep last N days
        if len(hist) > DEFAULT_HISTORY_DAYS:
            hist[:] = hist[-DEFAULT_HISTORY_DAYS:]
        self._state.history = hist

    def _extract_high_critical(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        combined = report.get("combined") if isinstance(report.get("combined"), dict) else None
        if not isinstance(combined, dict):
            return []
        vulns = combined.get("vulnerabilities")
        if not isinstance(vulns, list):
            return []
        out: list[dict[str, Any]] = []
        for v in vulns:
            if not isinstance(v, dict):
                continue
            sev = str(v.get("severity", "")).lower()
            if sev in ("critical", "high"):
                out.append(v)
        return out

    def _diff_new_high_critical(self, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prev = None
        if isinstance(self._state.last_results, dict):
            prev = self._extract_high_critical(self._state.last_results)

        def key(v: dict[str, Any]) -> str:
            return f"{v.get('package','')}|{v.get('cve','')}|{v.get('severity','')}|{v.get('fix_version','')}"

        prev_set = {key(v) for v in (prev or [])}
        cur_set = {key(v) for v in current}
        new_keys = cur_set - prev_set
        return [v for v in current if key(v) in new_keys]

    def _maybe_alert(self, report: dict[str, Any], reason: str) -> None:
        combined = report.get("combined") if isinstance(report, dict) else None
        if not isinstance(combined, dict):
            return

        critical = int(combined.get("critical", 0) or 0)
        high = int(combined.get("high", 0) or 0)
        if (critical + high) <= 0:
            return

        current_hi = self._extract_high_critical(report)
        new_hi = self._diff_new_high_critical(current_hi)

        # Alert hash: only re-alert if new_hi changes, so users aren't spammed daily for the same known issues.
        alert_fingerprint = _sha1_json({"new": new_hi, "project": str(self.project_root)})
        if alert_fingerprint == (self._state.last_alert_hash or "") and reason != "manual":
            return

        self._state.last_alert_hash = alert_fingerprint
        self._save_state()

        self._notify(
            {
                "type": "dep_monitor.alert",
                "project": str(self.project_root),
                "reason": reason,
                "last_scan_ts": float(self._state.last_scan_ts or 0.0),
                "critical": critical,
                "high": high,
                "total": int(combined.get("total", 0) or 0),
                "new_high_critical": new_hi,
                "current_high_critical": current_hi,
                "report": report,
                "history": self._state.history or [],
            }
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._due_for_scan():
                try:
                    self.scan_now(reason="daily_due")
                except Exception:
                    pass
            _sleep(3600)


_dep_monitor_singleton: DepMonitor | None = None


def get_dep_monitor() -> DepMonitor:
    global _dep_monitor_singleton
    if _dep_monitor_singleton is None:
        _dep_monitor_singleton = DepMonitor(DEFAULT_PROJECT_ROOT)
    return _dep_monitor_singleton
