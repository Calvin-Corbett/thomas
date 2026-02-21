"""Deterministic startup repair flow for Thomas."""

from __future__ import annotations

import asyncio
import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
    except OSError:
        return False


def _thomas_http_healthy(port: int) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/api/models", timeout=2.0) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            return 200 <= status < 500
    except Exception:
        return False


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
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" "
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


def _best_model_profile(config: AppConfig) -> Optional[str]:
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
        findings_text = "\n".join(
            f"- [{row.status}] {row.check}: {row.detail}" for row in findings
        ) or "- none"
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
        async for event in llm.stream_chat(messages, tools=None):
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
    report_path: Optional[Path] = None,
    allow_paths: Optional[list[Path]] = None,
    auto_repair: bool = True,
    allow_ai: bool = True,
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
                result.repairs.append(
                    f"Stopped stale Thomas listener PID(s): {', '.join(str(x) for x in killed)}"
                )
            if skipped:
                result.repairs.append(
                    "Skipped non-Thomas or protected PID(s): " + ", ".join(str(x) for x in skipped)
                )
            time.sleep(0.7)

    dep_ok, dep_detail = _run_cmd([str(py_exe), "-c", "import aiohttp, httpx"], cwd=root, timeout_s=20.0)
    result.add("server_deps", "ok" if dep_ok else "warn", dep_detail)
    if auto_repair and not dep_ok:
        install_ok, install_detail = _run_cmd(
            [str(py_exe), "-m", "pip", "install", "-e", ".[server]"],
            cwd=root,
            timeout_s=180.0,
        )
        result.repairs.append(
            "Dependency repair: " + ("succeeded" if install_ok else f"failed ({install_detail})")
        )

    healthy_after = _thomas_http_healthy(int(port))
    if not healthy_after and auto_repair:
        probe_log = report_dir / f"probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with probe_log.open("w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                [str(py_exe), "-m", "thomas.server", "--host", "127.0.0.1", "--port", str(int(port))],
                cwd=str(root),
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
            )
            started = False
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if _thomas_http_healthy(int(port)):
                    started = True
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.25)

            if proc.poll() is None:
                _kill_pid(proc.pid)
            if started:
                result.repairs.append("Startup probe: server became healthy in diagnostic launch.")
            else:
                exit_code = proc.poll()
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

    _write_report(Path(report_path), result)
    return Path(report_path)

