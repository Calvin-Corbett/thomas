"""Blue-owned spend governor for Thomas evolve loops.

The mutable evolve loop may ask this module whether it can start more work, but
the decision is derived from a repo-root config and the spend ledger. The green
candidate tree is not trusted for either input.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # nosec
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import tomllib

DEFAULT_CONFIG_FILE = "evolve_governor.toml"
DEFAULT_LEDGER_FILE = "thomas_spend.jsonl"
DEFAULT_WATCHDOG_INTERVAL_SECONDS = 5.0
WATCHDOG_RETURN_CODE = 125


@dataclass(frozen=True)
class SpendGovernorVerdict:
    ok: bool
    enabled: bool
    code: str
    message: str
    daily_usd: float = 0.0
    total_usd: float = 0.0
    daily_usd_cap: float = 0.0
    total_usd_cap: float = 0.0
    reserved_usd: float = 0.0
    ledger_path: str = ""
    config_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "enabled": bool(self.enabled),
            "code": self.code,
            "message": self.message,
            "daily_usd": float(self.daily_usd),
            "total_usd": float(self.total_usd),
            "daily_usd_cap": float(self.daily_usd_cap),
            "total_usd_cap": float(self.total_usd_cap),
            "reserved_usd": float(self.reserved_usd),
            "ledger_path": self.ledger_path,
            "config_path": self.config_path,
        }


@dataclass(frozen=True)
class SpendGuardedProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    watchdog_triggered: bool = False
    watchdog_verdict: SpendGovernorVerdict | None = None


@dataclass(frozen=True)
class SpendLedgerWriteResult:
    ok: bool
    enabled: bool
    code: str
    message: str
    usd_total: float = 0.0
    ledger_path: str = ""
    config_path: str = ""
    entry: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "enabled": bool(self.enabled),
            "code": self.code,
            "message": self.message,
            "usd_total": float(self.usd_total),
            "ledger_path": self.ledger_path,
            "config_path": self.config_path,
            "entry": dict(self.entry or {}),
        }


def _as_float(value: Any, *, field: str) -> float:
    try:
        out = float(value or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if out < 0:
        raise ValueError(f"{field} must be >= 0")
    return out


def _resolve_child(root: Path, raw: str, *, field: str) -> Path:
    value = str(raw or "").strip() or DEFAULT_LEDGER_FILE
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{field} must be a repo-relative path")
    return (root / candidate).resolve()


def _recorded_day(obj: dict[str, Any], *, line_no: int) -> str:
    raw_recorded_at = str(obj.get("recorded_at") or "").strip()
    if raw_recorded_at:
        try:
            return datetime.fromisoformat(raw_recorded_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError as exc:
            raise ValueError(f"spend ledger line {line_no} has invalid recorded_at") from exc
    if str(obj.get("source") or "") == "blue_evolve_child_reserve":
        raise ValueError(f"spend ledger line {line_no} is missing recorded_at")
    return str(obj.get("day") or "").strip()


def _read_spend_ledger(path: Path, *, today: str) -> tuple[float, float]:
    if not path.exists():
        return 0.0, 0.0
    daily = 0.0
    total = 0.0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"spend ledger is unreadable: {exc}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"spend ledger has invalid JSON on line {line_no}: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"spend ledger line {line_no} is not an object")
        try:
            usd = max(0.0, float(obj.get("usd_total", 0.0) or 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"spend ledger line {line_no} has invalid usd_total") from exc
        total += usd
        if _recorded_day(obj, line_no=line_no) == today:
            daily += usd
    return daily, total


def evaluate_spend_governor(
    repo_root: Path,
    *,
    config_path: Path | None = None,
    today: str | None = None,
) -> SpendGovernorVerdict:
    root = Path(repo_root).resolve()
    cfg_path = Path(config_path).resolve() if config_path is not None else (root / DEFAULT_CONFIG_FILE)
    if not cfg_path.exists():
        return SpendGovernorVerdict(
            ok=True,
            enabled=False,
            code="config_missing",
            message="spend governor config missing; governor disabled",
            config_path=str(cfg_path),
        )
    try:
        payload = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="config_invalid",
            message=f"spend governor config is invalid: {exc}",
            config_path=str(cfg_path),
        )

    section = payload.get("spend_governor") if isinstance(payload, dict) else None
    if not isinstance(section, dict) or not bool(section.get("enabled", False)):
        return SpendGovernorVerdict(
            ok=True,
            enabled=False,
            code="disabled",
            message="spend governor disabled",
            config_path=str(cfg_path),
        )

    try:
        daily_cap = _as_float(section.get("daily_usd_cap"), field="daily_usd_cap")
        total_cap = _as_float(section.get("total_usd_cap"), field="total_usd_cap")
        reserved = _as_float(section.get("per_iteration_usd_reserve"), field="per_iteration_usd_reserve")
        ledger_path = _resolve_child(root, str(section.get("ledger_path") or DEFAULT_LEDGER_FILE), field="ledger_path")
    except ValueError as exc:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="config_invalid",
            message=str(exc),
            config_path=str(cfg_path),
        )

    if daily_cap <= 0 and total_cap <= 0:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="cap_missing",
            message="spend governor is enabled but has no positive cap",
            config_path=str(cfg_path),
        )
    if reserved <= 0:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="reserve_missing",
            message="spend governor is enabled but per_iteration_usd_reserve is not positive",
            daily_usd_cap=daily_cap,
            total_usd_cap=total_cap,
            reserved_usd=reserved,
            ledger_path=str(ledger_path),
            config_path=str(cfg_path),
        )

    day_key = str(today or datetime.now(timezone.utc).date().isoformat())
    try:
        daily, total = _read_spend_ledger(ledger_path, today=day_key)
    except ValueError as exc:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="ledger_invalid",
            message=str(exc),
            daily_usd_cap=daily_cap,
            total_usd_cap=total_cap,
            reserved_usd=reserved,
            ledger_path=str(ledger_path),
            config_path=str(cfg_path),
        )

    projected_daily = daily + reserved
    projected_total = total + reserved
    if daily_cap > 0 and projected_daily > daily_cap:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="daily_cap_exceeded",
            message="daily evolve spend cap would be exceeded",
            daily_usd=daily,
            total_usd=total,
            daily_usd_cap=daily_cap,
            total_usd_cap=total_cap,
            reserved_usd=reserved,
            ledger_path=str(ledger_path),
            config_path=str(cfg_path),
        )
    if total_cap > 0 and projected_total > total_cap:
        return SpendGovernorVerdict(
            ok=False,
            enabled=True,
            code="total_cap_exceeded",
            message="total evolve spend cap would be exceeded",
            daily_usd=daily,
            total_usd=total,
            daily_usd_cap=daily_cap,
            total_usd_cap=total_cap,
            reserved_usd=reserved,
            ledger_path=str(ledger_path),
            config_path=str(cfg_path),
        )
    return SpendGovernorVerdict(
        ok=True,
        enabled=True,
        code="within_budget",
        message="spend governor permits another evolve iteration",
        daily_usd=daily,
        total_usd=total,
        daily_usd_cap=daily_cap,
        total_usd_cap=total_cap,
        reserved_usd=reserved,
        ledger_path=str(ledger_path),
        config_path=str(cfg_path),
    )


def record_evolve_child_spend(
    repo_root: Path,
    child_result: dict[str, Any],
    *,
    session_id: str,
    phase: str,
    pass_index: int | None = None,
    config_path: Path | None = None,
    today: str | None = None,
) -> SpendLedgerWriteResult:
    """Append a blue-owned reserve entry for one green child attempt."""
    verdict = evaluate_spend_governor(repo_root, config_path=config_path, today=today)
    if not verdict.enabled:
        return SpendLedgerWriteResult(
            ok=True,
            enabled=False,
            code=verdict.code,
            message=verdict.message,
            config_path=verdict.config_path,
        )
    if not verdict.ok:
        return SpendLedgerWriteResult(
            ok=False,
            enabled=True,
            code=verdict.code,
            message=f"spend ledger write refused: {verdict.message}",
            usd_total=verdict.reserved_usd,
            ledger_path=verdict.ledger_path,
            config_path=verdict.config_path,
        )

    if today:
        day_key = str(today)
        recorded_at = f"{day_key}T00:00:00+00:00"
    else:
        now = datetime.now(timezone.utc)
        day_key = now.date().isoformat()
        recorded_at = now.isoformat()
    entry: dict[str, Any] = {
        "source": "blue_evolve_child_reserve",
        "day": day_key,
        "recorded_at": recorded_at,
        "session_id": str(session_id),
        "phase": str(phase or "unknown"),
        "pass_index": int(pass_index) if pass_index is not None else None,
        "returncode": int(child_result.get("returncode") or 0),
        "timed_out": bool(child_result.get("timed_out")),
        "spend_watchdog_triggered": bool(child_result.get("spend_watchdog_triggered")),
        "usd_total": float(verdict.reserved_usd),
    }
    ledger_path = Path(verdict.ledger_path)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        return SpendLedgerWriteResult(
            ok=False,
            enabled=True,
            code="ledger_write_failed",
            message=f"spend ledger write failed: {exc}",
            usd_total=verdict.reserved_usd,
            ledger_path=str(ledger_path),
            config_path=verdict.config_path,
            entry=entry,
        )

    return SpendLedgerWriteResult(
        ok=True,
        enabled=True,
        code="ledger_appended",
        message="blue evolve child spend reserve appended",
        usd_total=verdict.reserved_usd,
        ledger_path=str(ledger_path),
        config_path=verdict.config_path,
        entry=entry,
    )


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _timeout_stdout(exc: subprocess.TimeoutExpired) -> str:
    return _coerce_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))


def _timeout_stderr(exc: subprocess.TimeoutExpired) -> str:
    return _coerce_text(getattr(exc, "stderr", None))


def _process_still_running(process: Any) -> bool:
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return False
    try:
        return poll() is None
    except OSError:
        return False


def _kill_process(process: Any) -> None:
    kill = getattr(process, "kill", None)
    if callable(kill):
        try:
            kill()
        except OSError:
            return


def _process_tree_popen_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) or 0)
        return {"creationflags": flags} if flags else {}
    return {"start_new_session": True}


def terminate_process_tree(process: Any) -> None:
    """Terminate a process and its children without building shell commands."""
    pid = int(getattr(process, "pid", 0) or 0)
    if pid <= 0:
        _kill_process(process)
        return

    if os.name == "nt":
        subprocess.run(  # nosec - fixed executable/args; pid is converted to an int above.
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            os.kill(pid, signal.SIGTERM)

    if _process_still_running(process):
        _kill_process(process)


def _collect_after_termination(process: Any, timeout_exc: subprocess.TimeoutExpired | None = None) -> tuple[str, str]:
    stdout = _timeout_stdout(timeout_exc) if timeout_exc is not None else ""
    stderr = _timeout_stderr(timeout_exc) if timeout_exc is not None else ""
    communicate = getattr(process, "communicate", None)
    if not callable(communicate):
        return stdout, stderr
    try:
        out, err = communicate(timeout=5)
    except subprocess.TimeoutExpired as exc:
        _kill_process(process)
        stdout = stdout or _timeout_stdout(exc)
        stderr = stderr or _timeout_stderr(exc)
        try:
            out, err = communicate(timeout=5)
        except subprocess.TimeoutExpired as final_exc:
            return stdout or _timeout_stdout(final_exc), stderr or _timeout_stderr(final_exc)
    return _coerce_text(out) or stdout, _coerce_text(err) or stderr


def _append_stderr(stderr: str, message: str) -> str:
    if not stderr:
        return message
    return stderr.rstrip() + "\n" + message


def monitor_process_with_spend_watchdog(
    process: Any,
    *,
    repo_root: Path,
    timeout_seconds: int,
    interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
    terminator: Callable[[Any], None] | None = None,
    evaluator: Callable[[Path], SpendGovernorVerdict] = evaluate_spend_governor,
) -> SpendGuardedProcessResult:
    """Watch a running child process and terminate it if spend caps are breached."""
    terminate = terminator or terminate_process_tree
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    interval = max(0.05, float(interval_seconds or DEFAULT_WATCHDOG_INTERVAL_SECONDS))
    root = Path(repo_root)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate(process)
            stdout, stderr = _collect_after_termination(process)
            return SpendGuardedProcessResult(returncode=124, stdout=stdout, stderr=stderr, timed_out=True)

        try:
            stdout, stderr = process.communicate(timeout=min(interval, remaining))
            return SpendGuardedProcessResult(
                returncode=int(getattr(process, "returncode", 0) or 0),
                stdout=_coerce_text(stdout),
                stderr=_coerce_text(stderr),
            )
        except subprocess.TimeoutExpired as exc:
            try:
                verdict = evaluator(root)
            except Exception as check_exc:  # noqa: BLE001 - watchdog failures must fail closed.
                verdict = SpendGovernorVerdict(
                    ok=False,
                    enabled=True,
                    code="watchdog_error",
                    message=f"spend watchdog check failed: {check_exc}",
                    config_path=str(root / DEFAULT_CONFIG_FILE),
                )
            if verdict.ok:
                continue

            terminate(process)
            stdout, stderr = _collect_after_termination(process, exc)
            stderr = _append_stderr(stderr, f"spend watchdog terminated process: {verdict.message}")
            return SpendGuardedProcessResult(
                returncode=WATCHDOG_RETURN_CODE,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                watchdog_triggered=True,
                watchdog_verdict=verdict,
            )


def run_process_with_spend_watchdog(
    command: str | list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    repo_root: Path,
    shell: bool = False,
    interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
) -> SpendGuardedProcessResult:
    """Run a subprocess under the blue-side spend watchdog."""
    process = subprocess.Popen(  # nosec
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=shell,
        **_process_tree_popen_kwargs(),
    )
    return monitor_process_with_spend_watchdog(
        process,
        repo_root=repo_root,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )
