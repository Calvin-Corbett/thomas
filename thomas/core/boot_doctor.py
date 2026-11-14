"""Deterministic startup repair flow for Thomas."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.boot_ai_summary import SecretLookup, ai_boot_summary, best_model_profile, model_cfg_with_secret
from thomas.core.boot_checks import answers_as_thomas, classify_startup_log, log_tail, run_offline_checks
from thomas.core.boot_process import (
    _bootdoctor_sleep,
    _is_port_listening,
    _is_thomas_cmdline,
    _kill_pid,
    _listening_pids_windows,
    _pid_cmdline,
    _run_cmd,
    _spawn_thomas_server,
    port_owner_note,
    thomas_owns_port,
)
from thomas.core.config import AppConfig

# (action, reason) -> True when the person approved it. The entry point supplies the Windows PIN prompt:
# it lives in thomas.tools, which thomas.core may not import.
Authorizer = Callable[[str, str], bool]


@dataclass
class BootDoctorFinding:
    check: str
    status: str
    detail: str


@dataclass
class BootDoctorResult:
    created_at_utc: str
    reason: str
    port: int
    findings: list[BootDoctorFinding] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    ai_model: str = ""
    ai_summary: str = ""
    offline_fallback_reason: str = ""
    offline_steps: list[str] = field(default_factory=list)

    def add(self, check: str, status: str, detail: str) -> None:
        self.findings.append(BootDoctorFinding(check=check, status=status, detail=detail))


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


BOOT_DOCTOR_RUNTIME_DIRNAME = "runtime/boot_doctor"
BOOT_DOCTOR_STATUS_FILENAME = "rescue_status.json"
BOOT_DOCTOR_NOTICE_FILENAME = "recovery_notice.json"


def boot_doctor_runtime_dir(root: Path) -> Path:
    return (Path(root).resolve() / BOOT_DOCTOR_RUNTIME_DIRNAME).resolve()


def boot_doctor_status_path(root: Path) -> Path:
    return boot_doctor_runtime_dir(root) / BOOT_DOCTOR_STATUS_FILENAME


def boot_doctor_notice_path(root: Path) -> Path:
    return boot_doctor_runtime_dir(root) / BOOT_DOCTOR_NOTICE_FILENAME


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


BOOT_DOCTOR_RECOMMENDED_ACTIONS = {
    "healthy": ["view_report", "dismiss_notice"],
    "degraded": ["view_report", "retry_repair", "restart", "open_rescue", "dismiss_notice"],
    "fatal": ["view_report", "retry_repair", "restart", "open_rescue"],
}

BOOT_DOCTOR_PROBE_SPECS = (
    {"id": "root", "path": "/", "class": "core"},
    {"id": "health", "path": "/api/health", "class": "core"},
    {"id": "models", "path": "/api/models", "class": "important"},
    {"id": "recovery_notice", "path": "/api/bootdoctor/recovery_notice", "class": "important"},
)


def _normalize_bootdoctor_severity(severity: str | None) -> str:
    value = str(severity or "").strip().lower()
    if value in {"healthy", "degraded", "fatal"}:
        return value
    return "degraded"


def _default_bootdoctor_actions(severity: str | None, *, report_available: bool = False) -> list[str]:
    normalized = _normalize_bootdoctor_severity(severity)
    actions = list(BOOT_DOCTOR_RECOMMENDED_ACTIONS.get(normalized, BOOT_DOCTOR_RECOMMENDED_ACTIONS["degraded"]))
    if not report_available:
        actions = [item for item in actions if item != "view_report"]
    return actions


def _bootdoctor_status_message(*, severity: str, recovered: bool) -> str:
    if severity == "healthy":
        return "Boot Doctor verified a healthy startup state."
    if severity == "fatal":
        return "Boot Doctor finished, but Thomas still has a fatal startup issue."
    if recovered:
        return "Thomas launched in a degraded state while Boot Doctor investigates."
    return "Boot Doctor detected a degraded startup state."


def _bootdoctor_notice_message(
    *,
    reason: str,
    repairs: list[str],
    recovered: bool,
    severity: str,
    ai_summary: str,
    report_path: str,
) -> str:
    if severity == "fatal":
        opening = "Boot Doctor found a startup issue that still blocks a fully healthy Thomas launch."
    elif recovered:
        opening = "Boot Doctor kept Thomas available in a degraded state while it investigates startup issues."
    else:
        opening = "Boot Doctor found a startup issue and is still investigating."

    lines = [opening, f"Failure: {str(reason or '').strip() or 'startup failure'}."]
    trimmed_repairs = [str(item).strip() for item in repairs if str(item).strip()][:4]
    if trimmed_repairs:
        lines.append("Changes made: " + "; ".join(trimmed_repairs) + ".")
    else:
        lines.append("Changes made: diagnostics only; no safe automatic repair was available.")
    compact = str(ai_summary or "").strip().replace("\r", " ").replace("\n", " ")
    if compact:
        lines.append(f"Boot Doctor summary: {compact}")
    if report_path:
        lines.append(f"Report: {report_path}")
    return "\n\n".join(lines)


def write_boot_doctor_status(
    root: Path,
    *,
    status: str,
    phase: str,
    message: str,
    reason: str = "",
    port: int | None = None,
    attempts: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    severity: str | None = None,
    recovered: bool | None = None,
    blocking: bool | None = None,
    report_path: str | Path | None = None,
    repairs: list[str] | None = None,
    ai_summary: str = "",
    recommended_actions: list[str] | None = None,
    probe_results: list[dict[str, Any]] | None = None,
) -> Path:
    normalized_severity = _normalize_bootdoctor_severity(severity)
    report_value = str(report_path).strip() if report_path else ""
    payload: dict[str, Any] = {
        "status": str(status or "unknown").strip() or "unknown",
        "phase": str(phase or "unknown").strip() or "unknown",
        "message": str(message or "").strip(),
        "reason": str(reason or "").strip(),
        "severity": normalized_severity,
        "recovered": bool(recovered) if recovered is not None else normalized_severity != "fatal",
        "blocking": bool(blocking) if blocking is not None else normalized_severity == "fatal",
        "repairs": [str(item).strip() for item in list(repairs or []) if str(item).strip()],
        "ai_summary": str(ai_summary or "").strip(),
        "recommended_actions": list(
            recommended_actions or _default_bootdoctor_actions(normalized_severity, report_available=bool(report_value))
        ),
        "probe_results": list(probe_results or []),
        "updated_at_utc": _now_utc_iso(),
    }
    if port is not None:
        payload["port"] = int(port)
    if report_value:
        payload["report_path"] = report_value
    if attempts:
        payload["attempts"] = dict(attempts)
    if extra:
        payload.update(dict(extra))
    return _write_json_atomic(boot_doctor_status_path(root), payload)


def read_boot_doctor_status(root: Path, *, consume: bool = False) -> dict[str, Any] | None:
    path = boot_doctor_status_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if consume:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    return payload if isinstance(payload, dict) else None


def clear_boot_doctor_status(root: Path) -> None:
    try:
        boot_doctor_status_path(root).unlink(missing_ok=True)
    except Exception:
        pass


def write_boot_recovery_notice(
    root: Path,
    *,
    reason: str,
    report_path: Path | str,
    repairs: list[str],
    recovered: bool,
    offline_fallback_reason: str = "",
    ai_summary: str = "",
    severity: str | None = None,
    blocking: bool | None = None,
    phase: str = "report_complete",
    recommended_actions: list[str] | None = None,
    probe_results: list[dict[str, Any]] | None = None,
) -> Path:
    normalized_severity = _normalize_bootdoctor_severity(severity)
    report_value = str(report_path).strip() if report_path else ""
    attention = str(offline_fallback_reason or "").strip()
    payload = {
        "message": _bootdoctor_notice_message(
            reason=str(reason or "").strip(),
            repairs=list(repairs or []),
            recovered=bool(recovered),
            severity=normalized_severity,
            ai_summary=ai_summary or attention,
            report_path=report_value,
        ),
        "reason": str(reason or "").strip(),
        "recovered": bool(recovered),
        "severity": normalized_severity,
        "blocking": bool(blocking) if blocking is not None else normalized_severity == "fatal",
        "phase": str(phase or "report_complete").strip() or "report_complete",
        "repairs": [str(item).strip() for item in list(repairs or []) if str(item).strip()][:4],
        "needs_attention": attention,
        "report_path": report_value,
        "ai_summary": str(ai_summary or "").strip(),
        "recommended_actions": list(
            recommended_actions or _default_bootdoctor_actions(normalized_severity, report_available=bool(report_value))
        ),
        "probe_results": list(probe_results or []),
        "updated_at_utc": _now_utc_iso(),
    }
    return _write_json_atomic(boot_doctor_notice_path(root), payload)


def read_boot_recovery_notice(root: Path, *, consume: bool = False) -> dict[str, Any] | None:
    path = boot_doctor_notice_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if consume:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    if isinstance(payload, dict):
        return payload
    return None


def clear_boot_recovery_notice(root: Path) -> None:
    try:
        boot_doctor_notice_path(root).unlink(missing_ok=True)
    except Exception:
        pass


def reconcile_boot_doctor_runtime_state(
    root: Path,
    *,
    port: int,
    host: str = "127.0.0.1",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    root = Path(root).resolve()
    status_payload = read_boot_doctor_status(root, consume=False)
    notice_payload = read_boot_recovery_notice(root, consume=False)
    if not status_payload and not notice_payload:
        return None, None

    runtime_state = probe_boot_runtime(int(port), host=str(host or "127.0.0.1"))
    severity = str(runtime_state.get("severity") or "fatal")
    if severity == "fatal":
        return status_payload, notice_payload

    existing = status_payload or notice_payload or {}
    existing_port = int(existing.get("port") or port)
    existing_severity = str(existing.get("severity") or "").strip().lower()
    existing_phase = str(existing.get("phase") or "").strip().lower()
    if (
        status_payload
        and existing_port == int(port)
        and existing_severity == severity
        and existing_phase == "runtime_reconciled"
        and not bool(status_payload.get("blocking", False))
    ):
        return status_payload, notice_payload

    report_path = str(
        (status_payload or {}).get("report_path") or (notice_payload or {}).get("report_path") or ""
    ).strip()
    repairs = list((status_payload or {}).get("repairs") or (notice_payload or {}).get("repairs") or [])
    reason = str(
        (status_payload or {}).get("reason") or (notice_payload or {}).get("reason") or "Boot Doctor recovered startup."
    ).strip()
    ai_summary = str(
        (status_payload or {}).get("ai_summary")
        or (notice_payload or {}).get("ai_summary")
        or (notice_payload or {}).get("needs_attention")
        or ""
    ).strip()
    actions = _default_bootdoctor_actions(severity, report_available=bool(report_path))
    message = (
        "Thomas is healthy again."
        if severity == "healthy"
        else "Thomas is available again, but some startup checks are still degraded."
    )

    write_boot_doctor_status(
        root,
        status="recovered",
        phase="runtime_reconciled",
        message=message,
        reason=reason,
        port=int(port),
        severity=severity,
        recovered=True,
        blocking=False,
        report_path=report_path,
        repairs=repairs,
        ai_summary=ai_summary,
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    write_boot_recovery_notice(
        root,
        reason=reason,
        report_path=report_path,
        repairs=repairs,
        recovered=True,
        ai_summary=ai_summary,
        severity=severity,
        blocking=False,
        phase="runtime_reconciled",
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    return read_boot_doctor_status(root, consume=False), read_boot_recovery_notice(root, consume=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


class BootDoctorPathGate:
    """Scope-limited file gate with explicit auth escalation for extra paths."""

    def __init__(self, root: Path, authorize: Authorizer | None = None):
        self._root = root.resolve()
        self._authorize = authorize
        self._allowed_roots: list[Path] = [
            self._root,
            (self._root / "runtime").resolve(),
            (self._root / ".venv").resolve(),
            (self._root / "scripts").resolve(),
            (self._root / "thomas").resolve(),
        ]

    def allow_with_auth(self, path: Path, *, purpose: str) -> Path:
        resolved = path.resolve()
        if self._is_allowed(resolved):
            return resolved

        action = f"Boot Doctor path access: {resolved}"
        reason = (
            "Boot Doctor needs temporary filesystem access outside the Thomas root.\n\n"
            f"Path: {resolved}\n"
            f"Purpose: {purpose}\n\n"
            "Enter your Windows PIN/password to approve or Cancel to deny."
        )
        # With no way to ask, the answer is no.
        if self._authorize is None or not self._authorize(action, reason):
            raise PermissionError(f"Boot Doctor path access denied for: {resolved}")

        self._allowed_roots.append(resolved if resolved.is_dir() else resolved.parent)
        return resolved

    def _is_allowed(self, path: Path) -> bool:
        return any(_is_within(path, root) for root in self._allowed_roots)


def _resolve_python(root: Path) -> Path:
    if os.name == "nt":
        cand = root / ".venv" / "Scripts" / "python.exe"
    else:
        cand = root / ".venv" / "bin" / "python"
    if cand.exists():
        return cand
    return Path(sys.executable).resolve()


def _http_probe_result(
    host: str, port: int, *, probe_id: str, path: str, probe_class: str, timeout: float = 1.5
) -> dict[str, Any]:
    url = f"http://{host}:{int(port)}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 0) or 0)
        ok = 200 <= status < 400
        detail = f"HTTP {status} at {path}"
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        ok = status not in {0, 500, 502, 503, 504}
        detail = f"HTTP {status} at {path}"
    except Exception as exc:
        status = 0
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "id": probe_id,
        "class": probe_class,
        "path": path,
        "ok": bool(ok),
        "status": int(status),
        "detail": detail,
    }


def probe_boot_runtime(port: int, host: str = "127.0.0.1") -> dict[str, Any]:
    listening = _is_port_listening(host, int(port))
    probe_results: list[dict[str, Any]] = []
    if listening:
        for spec in BOOT_DOCTOR_PROBE_SPECS:
            probe_results.append(
                _http_probe_result(
                    host,
                    int(port),
                    probe_id=str(spec["id"]),
                    path=str(spec["path"]),
                    probe_class=str(spec["class"]),
                )
            )
    else:
        for spec in BOOT_DOCTOR_PROBE_SPECS:
            probe_results.append(
                {
                    "id": str(spec["id"]),
                    "class": str(spec["class"]),
                    "path": str(spec["path"]),
                    "ok": False,
                    "status": 0,
                    "detail": "port not listening",
                }
            )

    fatal = (not listening) or any((not item.get("ok")) and item.get("class") == "core" for item in probe_results)
    degraded = any((not item.get("ok")) and item.get("class") != "core" for item in probe_results)
    severity = "fatal" if fatal else "degraded" if degraded else "healthy"
    return {
        "ready": severity != "fatal",
        "severity": severity,
        "listening": bool(listening),
        "probe_results": probe_results,
    }


def _thomas_http_healthy(port: int) -> bool:
    return bool(probe_boot_runtime(int(port)).get("ready"))


def _thomas_serving(port: int, foreign: bool) -> bool:
    """The probes pass and, once another program was seen on the port, Thomas's own /api/health payload does too."""
    return _thomas_http_healthy(port) and (not foreign or answers_as_thomas("127.0.0.1", int(port)))


def _record_probe_failure(result: BootDoctorResult, probe_log: Path) -> None:
    """Put the real cause of a failed start in the report, not only a log path."""
    try:
        text = probe_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for cause in classify_startup_log(text):
        result.add("startup_probe_cause", "warn", cause)
    tail = log_tail(text)
    if tail:
        result.add("startup_probe_log_tail", "warn", "last lines of the probe log:\n    " + "\n    ".join(tail))


def _offline_steps(port: int) -> list[str]:
    return [
        f"Run `run-ui.cmd -NoTray -Port {int(port)}` to start without the tray manager.",
        "Run `python -m thomas.bootdoctor check` to test thomas.toml, the data folders and every database; "
        "add `--quarantine` to move a damaged database aside so Thomas can start fresh.",
        f"Run `python -m thomas doctor --port {int(port)} --full` to validate config and provider keys.",
        "If cloud auth fails, verify API keys and billing/credits for the active model profile.",
        "If offline, switch to a local profile in `thomas.toml` and make sure Ollama is running.",
        "If startup still fails, restart the machine to clear orphaned listeners, then retry.",
    ]


def _write_report(path: Path, result: BootDoctorResult) -> None:
    lines: list[str] = []
    lines.append("Thomas Boot Doctor Report")
    lines.append(f"Generated (UTC): {result.created_at_utc}")
    lines.append(f"Reason: {result.reason}")
    lines.append(f"Port: {int(result.port)}")
    lines.append("")
    lines.append("Findings:")
    if result.findings:
        for row in result.findings:
            lines.append(f"- [{row.status}] {row.check}: {row.detail}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Repairs Attempted:")
    if result.repairs:
        for row in result.repairs:
            lines.append(f"- {row}")
    else:
        lines.append("- none")
    lines.append("")
    if result.ai_model:
        lines.append(f"AI Summary Model: {result.ai_model}")
    if result.ai_summary:
        lines.append("AI Summary:")
        lines.append(result.ai_summary.strip())
        lines.append("")
    if result.offline_fallback_reason:
        lines.append(f"AI Fallback Reason: {result.offline_fallback_reason}")
    lines.append("Offline Recovery Steps:")
    for row in result.offline_steps:
        lines.append(f"- {row}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_boot_doctor(
    *,
    config: AppConfig,
    root: Path,
    port: int,
    reason: str,
    report_path: Path | None = None,
    allow_paths: list[Path] | None = None,
    auto_repair: bool = True,
    allow_ai: bool = True,
    relaunch: bool = False,
    relaunch_host: str = "127.0.0.1",
    config_path: Path | None = None,
    authorize: Authorizer | None = None,
    secret_lookup: SecretLookup | None = None,
) -> Path:
    root = root.resolve()
    gate = BootDoctorPathGate(root, authorize)
    for extra in allow_paths or []:
        gate.allow_with_auth(Path(extra), purpose="user-approved boot diagnostics scope extension")

    report_dir = gate.allow_with_auth(root / "runtime" / "boot_doctor", purpose="write boot report")
    # allow_with_auth only resolves the path. A fresh install has no such folder
    # yet, so the probe log below failed with FileNotFoundError before any check ran.
    report_dir.mkdir(parents=True, exist_ok=True)
    if report_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"boot_doctor_{stamp}.txt"
    else:
        report_path = gate.allow_with_auth(Path(report_path), purpose="write boot report")

    result = BootDoctorResult(
        created_at_utc=_now_utc_iso(),
        reason=str(reason or "").strip() or "startup failure",
        port=int(port),
        offline_steps=_offline_steps(int(port)),
    )

    py_exe = _resolve_python(root)
    result.add("python_executable", "ok" if py_exe.exists() else "warn", str(py_exe))

    # The probe below only asks whether the port answers. These look at the
    # config file, the state folders and the databases, which stop a start
    # while leaving the port free.
    offline_rows, _corrupt = run_offline_checks(root, memory_root=config.memory.root_path, config_path=config_path)
    for check, status, detail in offline_rows:
        result.add(check, status, detail)

    port_in_use = _is_port_listening("127.0.0.1", int(port))
    foreign = False
    if port_in_use:
        healthy = _thomas_http_healthy(int(port))
        is_thomas = healthy and answers_as_thomas("127.0.0.1", int(port))
        # Any web server passes the probes, and a busy Thomas can miss the health deadline: only a port no Thomas
        # process holds is another program's.
        foreign = not is_thomas and not thomas_owns_port(int(port))
        if is_thomas:
            detail = f"Port {int(port)} is listening (healthy Thomas endpoint)"
        elif healthy and foreign:
            detail = f"Port {int(port)} answers HTTP but not as Thomas; {port_owner_note(int(port))}"
        else:
            detail = f"Port {int(port)} is listening (endpoint not healthy); {port_owner_note(int(port))}"
        result.add("port_probe", "ok" if is_thomas else "fail" if foreign else "warn", detail)
    else:
        result.add("port_probe", "ok", f"Port {int(port)} is currently free")

    if auto_repair and port_in_use and not _thomas_http_healthy(int(port)):
        if os.name == "nt":
            pids = _listening_pids_windows(int(port))
        else:
            pids = []
        if not pids:
            result.repairs.append("No owning PID discovered for busy port.")
        else:
            killed: list[int] = []
            skipped: list[int] = []
            for pid in pids:
                cmdline = _pid_cmdline(pid)
                if _is_thomas_cmdline(cmdline):
                    if _kill_pid(pid):
                        killed.append(pid)
                    else:
                        skipped.append(pid)
                else:
                    skipped.append(pid)
            if killed:
                result.repairs.append(f"Stopped stale Thomas listener PID(s): {', '.join(str(x) for x in killed)}")
            if skipped:
                result.repairs.append("Skipped non-Thomas or protected PID(s): " + ", ".join(str(x) for x in skipped))
            _bootdoctor_sleep(0.7)

    dep_ok, dep_detail = _run_cmd([str(py_exe), "-c", "import aiohttp, httpx"], cwd=root, timeout_s=20.0)
    result.add("server_deps", "ok" if dep_ok else "warn", dep_detail)
    if auto_repair and not dep_ok:
        install_ok, install_detail = _run_cmd(
            [str(py_exe), "-m", "pip", "install", "-e", ".[server]"],
            cwd=root,
            timeout_s=180.0,
        )
        result.repairs.append("Dependency repair: " + ("succeeded" if install_ok else f"failed ({install_detail})"))

    healthy_after = _thomas_serving(int(port), foreign)
    if not healthy_after and auto_repair and foreign:
        # A second Thomas could not bind the port, and starting one boots the whole engine stack to find that out. The
        # port_probe row above already names the taken port and the program that holds it. Past tense: the holder can
        # answer as Thomas by the time the report ends (the status then reads healthy).
        result.repairs.append(
            f"Startup probe skipped: what holds port {int(port)} did not answer as Thomas when it was checked, so no "
            "second server was started."
        )
    elif not healthy_after and auto_repair:
        probe_log = report_dir / f"probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with probe_log.open("w", encoding="utf-8") as fh:
            proc = _spawn_thomas_server(
                py_exe=py_exe,
                root=root,
                host=str(relaunch_host),
                port=int(port),
                stdout=fh,
            )
            started = False
            keep_running = False
            deadline = time.monotonic() + (8.0 if relaunch else 70.0)
            while time.monotonic() < deadline:
                if _thomas_http_healthy(int(port)):
                    started = True
                    if relaunch and proc.poll() is None:
                        keep_running = True
                    break
                if proc.poll() is not None:
                    break
                _bootdoctor_sleep(0.25)

            if started and keep_running:
                result.repairs.append(f"Startup recovery launch: server left running on {relaunch_host}:{int(port)}.")
            elif started:
                result.repairs.append("Startup probe: server became healthy in diagnostic launch.")
                if proc.poll() is None:
                    _kill_pid(proc.pid)
            elif relaunch and proc.poll() is None:
                result.repairs.append(
                    f"Startup recovery launch is still initializing on {relaunch_host}:{int(port)}; leaving the server it started running for continued startup."
                )
            else:
                if proc.poll() is None:
                    _kill_pid(proc.pid)
                exit_code = proc.poll()
                result.repairs.append(
                    f"Startup probe failed (exit={exit_code if exit_code is not None else 'running'}). Log: {probe_log}"
                )
                _record_probe_failure(result, probe_log)

    profile = best_model_profile(config) if allow_ai else None
    if profile:
        ai_cfg = model_cfg_with_secret(config, profile, secret_lookup)
        result.ai_model = f"{profile}/{ai_cfg.model}"
        try:
            result.ai_summary = asyncio.run(
                ai_boot_summary(
                    model_cfg=ai_cfg,
                    reason=result.reason,
                    findings=result.findings,
                    repairs=result.repairs,
                )
            )
            result.add("ai_diagnosis", "ok", f"Summary generated with {result.ai_model}")
        except Exception as e:
            result.offline_fallback_reason = f"{type(e).__name__}: {e}"
            result.add("ai_diagnosis", "warn", result.offline_fallback_reason)
    else:
        result.offline_fallback_reason = "No suitable model profile configured for AI diagnosis."
        result.add("ai_diagnosis", "warn", result.offline_fallback_reason)

    report_path = Path(report_path)
    _write_report(report_path, result)
    # Carry what the offline checks found into the status and notice. Without it
    # they read only "diagnostics only" and, with no AI, "No suitable model profile".
    problems = "; ".join(f"{row.check}: {row.detail}" for row in result.findings if row.status == "fail")
    host = str(relaunch_host or "127.0.0.1")
    runtime_state = probe_boot_runtime(int(port), host=host)
    severity = str(runtime_state.get("severity") or "fatal")
    if foreign and not answers_as_thomas(host, int(port)):
        # The other program's 404 passes every probe, so the taken port has to be said here, not left as "healthy".
        severity = "fatal"
    recovered = severity != "fatal"
    actions = _default_bootdoctor_actions(severity, report_available=True)
    write_boot_doctor_status(
        root,
        status=("recovered" if recovered else "attention"),
        phase="report_complete",
        message=_bootdoctor_status_message(severity=severity, recovered=recovered),
        reason=result.reason,
        port=int(port),
        severity=severity,
        recovered=recovered,
        blocking=severity == "fatal",
        report_path=report_path,
        repairs=result.repairs,
        ai_summary=result.ai_summary or problems or result.offline_fallback_reason,
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    write_boot_recovery_notice(
        root,
        reason=result.reason,
        report_path=report_path,
        repairs=result.repairs,
        recovered=recovered,
        offline_fallback_reason=problems or result.offline_fallback_reason,
        ai_summary=result.ai_summary,
        severity=severity,
        blocking=severity == "fatal",
        phase="report_complete",
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    return report_path
