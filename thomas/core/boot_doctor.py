"""Deterministic startup repair flow for Thomas."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import LLMClient
from thomas.tools.windows_auth import get_auth_gate

try:
    from thomas.server.secrets import SecretStore
except Exception:  # pragma: no cover
    SecretStore = None  # type: ignore[assignment]


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

    def __init__(self, root: Path):
        self._root = root.resolve()
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

        gate = get_auth_gate()
        action = f"Boot Doctor path access: {resolved}"
        reason = (
            "Boot Doctor needs temporary filesystem access outside the Thomas root.\n\n"
            f"Path: {resolved}\n"
            f"Purpose: {purpose}\n\n"
            "Enter your Windows PIN/password to approve or Cancel to deny."
        )
        if not gate.request_authorization(action_description=action, reason=reason):
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


def _is_port_listening(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except KeyboardInterrupt:
        return False
    except OSError:
        return False


def _bootdoctor_sleep(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(seconds or 0.0))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            time.sleep(min(remaining, 0.25))
        except KeyboardInterrupt:
            continue


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


def _listening_pids_windows(port: int) -> list[int]:
    cmd = ["netstat", "-ano", "-p", "tcp"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    pids: list[int] = []
    for raw in str(out.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local, _foreign, state, pid_raw = parts[0], parts[1], parts[2], parts[3], parts[4]
        if proto.upper() != "TCP" or state.upper() != "LISTENING":
            continue
        if not local.endswith(f":{int(port)}"):
            continue
        try:
            pid = int(pid_raw)
        except Exception:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _pid_cmdline(pid: int) -> str:
    try:
        import psutil  # type: ignore

        proc = psutil.Process(int(pid))
        try:
            return " ".join(proc.cmdline()).strip()
        except Exception:
            return str(proc.name() or "").strip()
    except Exception:
        pass

    if os.name == "nt":
        ps_cmd = (
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}" '
            "| Select-Object -ExpandProperty CommandLine)"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(out.stdout or "").strip()
    return ""


def _is_thomas_cmdline(cmdline: str) -> bool:
    s = str(cmdline or "").lower()
    if not s:
        return False
    patterns = (
        r"-m\s+thomas(\.server)?(\s+serve)?\b",
        r"-m\s+thomas\.tray_agent\b",
        r"\bthomas(\.exe)?\s+serve\b",
    )
    return any(re.search(pat, s) for pat in patterns)


def _kill_pid(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            return True
        os.kill(int(pid), signal.SIGTERM)
        return True
    except Exception:
        return False


def _run_cmd(cmd: list[str], *, cwd: Path, timeout_s: float = 60.0) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    ok = int(out.returncode or 0) == 0
    detail = (out.stdout or "") + ("\n" + out.stderr if out.stderr else "")
    detail = detail.strip()
    if not detail:
        detail = f"exit={out.returncode}"
    if len(detail) > 2000:
        detail = detail[:2000] + "\n... (truncated)"
    return ok, detail


class _BootDoctorProcessHandle:
    def __init__(self, pid: int, proc: subprocess.Popen[str] | None = None):
        self.pid = int(pid)
        self._proc = proc

    def poll(self) -> int | None:
        if self._proc is not None:
            return self._proc.poll()
        return None if _pid_is_running(self.pid) else 1


def _pid_is_running(pid: int) -> bool:
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(int(pid))
    except Exception:
        pass

    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = str(out.stdout or "").strip()
        return bool(text) and not text.startswith("INFO:")

    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _spawn_thomas_server(
    *,
    py_exe: Path,
    root: Path,
    host: str,
    port: int,
    stdout: Any,
    detached: bool = False,
) -> _BootDoctorProcessHandle:
    if detached and os.name == "nt":
        stdout_path = Path(getattr(stdout, "name", "")).resolve()
        stderr_path = stdout_path.with_name(stdout_path.stem + ".stderr" + stdout_path.suffix)
        script = (
            "$p = Start-Process "
            f"-FilePath {_ps_single_quote(str(py_exe))} "
            f"-ArgumentList @('-m','thomas.server','--host',{_ps_single_quote(str(host))},'--port',{_ps_single_quote(str(int(port)))}) "
            f"-WorkingDirectory {_ps_single_quote(str(root))} "
            f"-RedirectStandardOutput {_ps_single_quote(str(stdout_path))} "
            f"-RedirectStandardError {_ps_single_quote(str(stderr_path))} "
            "-PassThru; "
            "[Console]::Out.Write($p.Id)"
        )
        launched = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        pid_text = str(launched.stdout or "").strip()
        if int(launched.returncode or 0) == 0 and pid_text.isdigit():
            return _BootDoctorProcessHandle(int(pid_text))

    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "stdout": stdout,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if detached:
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            creationflags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
            if creationflags:
                kwargs["creationflags"] = creationflags
            kwargs["close_fds"] = True
        else:
            kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [str(py_exe), "-m", "thomas.server", "--host", str(host), "--port", str(int(port))],
        **kwargs,
    )
    return _BootDoctorProcessHandle(int(proc.pid), proc=proc)


def _best_model_profile(config: AppConfig) -> str | None:
    if not config.models:
        return None

    def score(name: str, model_cfg: ModelConfig) -> float:
        model_text = f"{name} {model_cfg.model}".lower()
        value = 0.0
        keywords = {
            "gpt-5": 120.0,
            "o3": 110.0,
            "o1": 100.0,
            "gpt-4.1": 95.0,
            "claude-3.7": 100.0,
            "claude-3.5": 90.0,
            "opus": 95.0,
            "sonnet": 85.0,
            "gemini": 85.0,
            "deepseek-r1": 90.0,
        }
        for token, bonus in keywords.items():
            if token in model_text:
                value = max(value, bonus)
        value += min(30.0, float(max(0, int(model_cfg.context_window or 0))) / 4096.0)
        if str(model_cfg.provider or "").strip().lower() not in {"local"}:
            value += 5.0
        if name == config.default_model:
            value += 3.0
        return value

    ranked = sorted(config.models.items(), key=lambda it: score(it[0], it[1]), reverse=True)
    return ranked[0][0] if ranked else None


def _model_cfg_with_secret(config: AppConfig, profile: str) -> ModelConfig:
    model_cfg = config.get_model(profile)
    if str(model_cfg.api_key or "").strip():
        return model_cfg
    if SecretStore is None:
        return model_cfg
    try:
        store = SecretStore(config.memory.root_path / ".thomas")
        key = str(store.get(profile) or "").strip()
        if key:
            return replace(model_cfg, api_key=key)
    except Exception:
        pass
    return model_cfg


async def _ai_boot_summary(
    *,
    model_cfg: ModelConfig,
    reason: str,
    findings: list[BootDoctorFinding],
    repairs: list[str],
) -> str:
    llm = LLMClient(model_cfg, failover_enabled=False)
    try:
        findings_text = "\n".join(f"- [{row.status}] {row.check}: {row.detail}" for row in findings) or "- none"
        repairs_text = "\n".join(f"- {x}" for x in repairs) or "- none"
        prompt = (
            "You are Thomas Boot Doctor analyst.\n"
            "Given startup diagnostics, provide a concise root-cause hypothesis and "
            "next actions.\n\n"
            f"Reason:\n{reason}\n\n"
            f"Findings:\n{findings_text}\n\n"
            f"Repairs attempted:\n{repairs_text}\n\n"
            "Respond with:\n"
            "1) likely_root_cause\n"
            "2) confidence\n"
            "3) next_steps (3 bullets max)\n"
        )
        messages = [
            {"role": "system", "content": "Be precise, short, and operational."},
            {"role": "user", "content": prompt},
        ]
        chunks: list[str] = []
        stream_obj = llm.stream_chat(messages, tools=None)
        if inspect.isawaitable(stream_obj):
            stream_obj = await stream_obj
        if not hasattr(stream_obj, "__aiter__"):
            raise RuntimeError("LLM boot summary stream is not async iterable")

        async for event in stream_obj:
            if event.type == "token":
                chunks.append(str((event.data or {}).get("text") or ""))
            elif event.type == "error":
                raise RuntimeError(str((event.data or {}).get("error") or "LLM error"))
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("empty AI summary")
        return text
    finally:
        await llm.close()


def _offline_steps(port: int) -> list[str]:
    return [
        f"Run `run-ui.cmd -NoTray -Port {int(port)}` to start without the tray manager.",
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
) -> Path:
    root = root.resolve()
    gate = BootDoctorPathGate(root)
    for extra in allow_paths or []:
        gate.allow_with_auth(Path(extra), purpose="user-approved boot diagnostics scope extension")

    report_dir = gate.allow_with_auth(root / "runtime" / "boot_doctor", purpose="write boot report")
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

    port_in_use = _is_port_listening("127.0.0.1", int(port))
    if port_in_use:
        healthy = _thomas_http_healthy(int(port))
        result.add(
            "port_probe",
            "ok" if healthy else "warn",
            f"Port {int(port)} is listening ({'healthy Thomas endpoint' if healthy else 'endpoint not healthy'})",
        )
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

    healthy_after = _thomas_http_healthy(int(port))
    if not healthy_after and auto_repair:
        probe_log = report_dir / f"probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with probe_log.open("w", encoding="utf-8") as fh:
            proc = _spawn_thomas_server(
                py_exe=py_exe,
                root=root,
                host=str(relaunch_host),
                port=int(port),
                stdout=fh,
                detached=False,
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
                    f"Startup recovery launch is still initializing on {relaunch_host}:{int(port)}; leaving the repaired server running for continued startup."
                )
            else:
                if proc.poll() is None:
                    _kill_pid(proc.pid)
                exit_code = proc.poll()
                probe_text = ""
                try:
                    probe_text = probe_log.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    probe_text = ""
                probe_lower = probe_text.lower()
                known_repairs: list[str] = []

                if "unable to locate monolith_source_loader.py" in probe_lower:
                    main_path = (root / "thomas" / "server" / "__main__.py").resolve()
                    main_text = main_path.read_text(encoding="utf-8", errors="replace")
                    main_old = (
                        "        from thomas.server.app import serve\n\n"
                        "        serve(config, host=str(args.host), port=int(args.port))\n"
                    )
                    main_new = (
                        "        from thomas.server.app_lifecycle import serve\n\n"
                        "        serve(config, host=str(args.host), port=int(args.port))\n"
                    )
                    if main_old in main_text:
                        main_path.write_text(main_text.replace(main_old, main_new, 1), encoding="utf-8")
                        known_repairs.append("server_main_import")
                        result.repairs.append(
                            "Known startup repair: patched thomas.server.__main__ to use app_lifecycle.serve."
                        )

                tool_path = (root / "thomas" / "server" / "tool_extensions.py").resolve()
                tool_text = tool_path.read_text(encoding="utf-8", errors="replace")
                tool_old = (
                    "def _try_import(module_path: str, func_name: str):\n"
                    "    try:\n"
                    "        mod = __import__(module_path, fromlist=[func_name])\n"
                    "        return getattr(mod, func_name)\n"
                    "    except (ImportError, ModuleNotFoundError, AttributeError):\n"
                    "        return None\n"
                )
                tool_new = tool_old + (
                    "    except Exception as exc:\n"
                    '        _log.debug("Skipping optional tool module %s.%s: %s", module_path, func_name, exc)\n'
                    "        return None\n"
                )
                if tool_old in tool_text:
                    tool_path.write_text(tool_text.replace(tool_old, tool_new, 1), encoding="utf-8")
                    known_repairs.append("optional_tool_guard")
                    result.repairs.append(
                        "Known startup repair: widened optional tool import fallback to skip broken modules."
                    )

                shim_path = (root / "thomas" / "groupchat" / "__init__.py").resolve()
                shim_text = (
                    '"""Compatibility shim for optional groupchat surface.\n\n'
                    "This package currently has no concrete local implementation. Keep imports safe so\n"
                    "optional tool/module discovery can skip it without crashing startup.\n"
                    '"""\n\n'
                    "from __future__ import annotations\n\n"
                    "__all__: list[str] = []\n"
                )
                current_shim = shim_path.read_text(encoding="utf-8", errors="replace") if shim_path.exists() else ""
                if current_shim != shim_text:
                    shim_path.write_text(shim_text, encoding="utf-8")
                    known_repairs.append("groupchat_shim")
                    result.repairs.append(
                        "Known startup repair: replaced crashing thomas.groupchat re-export with a safe shim."
                    )

                if known_repairs:
                    retry_log = report_dir / f"probe_repaired_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                    with retry_log.open("w", encoding="utf-8") as retry_fh:
                        retry_proc = _spawn_thomas_server(
                            py_exe=py_exe,
                            root=root,
                            host=str(relaunch_host),
                            port=int(port),
                            stdout=retry_fh,
                            detached=bool(relaunch),
                        )
                        retry_started = False
                        retry_keep_running = False
                        retry_deadline = time.monotonic() + (8.0 if relaunch else 70.0)
                        while time.monotonic() < retry_deadline:
                            if _thomas_http_healthy(int(port)):
                                retry_started = True
                                if relaunch and retry_proc.poll() is None:
                                    retry_keep_running = True
                                break
                            if retry_proc.poll() is not None:
                                break
                            _bootdoctor_sleep(0.25)

                        if retry_started and retry_keep_running:
                            result.repairs.append(
                                f"Startup recovery launch after known repair left server running on {relaunch_host}:{int(port)}."
                            )
                        elif retry_started:
                            result.repairs.append("Startup probe became healthy after known startup repair.")
                            if retry_proc.poll() is None:
                                _kill_pid(retry_proc.pid)
                        elif relaunch and retry_proc.poll() is None:
                            result.repairs.append(
                                f"Startup recovery launch after known repair is still initializing on {relaunch_host}:{int(port)}; leaving the repaired server running for continued startup."
                            )
                        else:
                            if retry_proc.poll() is None:
                                _kill_pid(retry_proc.pid)
                            retry_exit = retry_proc.poll()
                            result.repairs.append(
                                f"Startup probe still failed after known startup repair (exit={retry_exit if retry_exit is not None else 'running'}). Log: {retry_log}"
                            )
                else:
                    result.repairs.append(
                        f"Startup probe failed (exit={exit_code if exit_code is not None else 'running'}). Log: {probe_log}"
                    )

    profile = _best_model_profile(config) if allow_ai else None
    if profile:
        ai_cfg = _model_cfg_with_secret(config, profile)
        result.ai_model = f"{profile}/{ai_cfg.model}"
        try:
            result.ai_summary = asyncio.run(
                _ai_boot_summary(
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
    runtime_state = probe_boot_runtime(int(port), host=str(relaunch_host or "127.0.0.1"))
    severity = str(runtime_state.get("severity") or "fatal")
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
        ai_summary=result.ai_summary or result.offline_fallback_reason,
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    write_boot_recovery_notice(
        root,
        reason=result.reason,
        report_path=report_path,
        repairs=result.repairs,
        recovered=recovered,
        offline_fallback_reason=result.offline_fallback_reason,
        ai_summary=result.ai_summary,
        severity=severity,
        blocking=severity == "fatal",
        phase="report_complete",
        recommended_actions=actions,
        probe_results=list(runtime_state.get("probe_results") or []),
    )
    return report_path
