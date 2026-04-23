"""Agent runtime lifecycle helpers for persistent CLI operation."""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from thomas.cli.parity_gateway_support import (
    active_gateway_target as _active_gateway_target,
    clear_gateway_state as _clear_gateway_state,
    gateway_spawn as _gateway_spawn,
    is_pid_running as _is_pid_running,
    kill_pid as _kill_pid,
    probe_gateway as _probe_gateway,
    resolve_bind_port as _resolve_bind_port,
    save_gateway_state as _save_gateway_state,
)
from thomas.cli.parity_support import (
    gateway_log_file as _gateway_log_file,
    gateway_state_file as _gateway_state_file,
    load_gateway_state as _load_gateway_state,
    utc_iso as _utc_iso,
)
from thomas.core.config import AppConfig


def engine_snapshot() -> dict[str, Any]:
    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        payload = manager.status()
        if isinstance(payload, dict):
            return payload
        return {"running": False, "error": "invalid engine status payload", "engines": {}}
    except Exception as e:
        return {"running": False, "error": f"{type(e).__name__}: {e}", "engines": {}}


def gateway_detached_status(
    config: AppConfig,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> dict[str, Any]:
    use_host, use_port, state = _active_gateway_target(config, host, port)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    process_running = bool(pid > 0 and _is_pid_running(pid))
    probe = _probe_gateway(use_host, use_port, token=config.server.api_token)
    engines_probe = probe.get("engines")
    runtime: dict[str, Any] = {}
    if isinstance(engines_probe, dict):
        payload = engines_probe.get("payload")
        if isinstance(payload, dict):
            runtime = payload
    healthy = bool(probe.get("healthy", False))
    running = bool(process_running or healthy or bool(runtime.get("running", False)))
    return {
        "running": running,
        "pid": pid,
        "process_running": process_running,
        "host": use_host,
        "port": int(use_port),
        "url": f"http://{use_host}:{int(use_port)}/",
        "state_file": str(_gateway_state_file(config)),
        "log_file": str(state.get("log_file") or _gateway_log_file(config)),
        "probe": probe,
        "healthy": healthy,
        "runtime": runtime,
    }


def status_payload(
    config: AppConfig,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> dict[str, Any]:
    local_payload = engine_snapshot()
    detached_payload = gateway_detached_status(config, host=host, port=port)
    source = "gateway_detached" if bool(detached_payload.get("running", False)) else "local_process"
    runtime_payload = detached_payload.get("runtime")
    if source == "gateway_detached" and isinstance(runtime_payload, dict):
        engines_payload = runtime_payload.get("engines")
        engines = engines_payload if isinstance(engines_payload, dict) else {}
        running = bool(runtime_payload.get("running", detached_payload.get("running", False)))
    else:
        engines_payload = local_payload.get("engines")
        engines = engines_payload if isinstance(engines_payload, dict) else {}
        running = bool(local_payload.get("running", False))
    return {
        "running": running,
        "engines": engines,
        "source": source,
        "gateway_detached": detached_payload,
        "local_process": local_payload,
    }


def start_payload(
    config: AppConfig,
    *,
    config_path: str = "",
    detach: bool,
    host: str,
    port: int,
    auto_port: bool,
) -> dict[str, Any]:
    if detach:
        target_port = int(port)
        existing_probe = _probe_gateway(host, target_port, token=config.server.api_token)
        if bool(existing_probe.get("healthy", False)):
            return {
                "ok": True,
                "mode": "gateway_detached",
                "already_running": True,
                "pid": 0,
                "host": host,
                "port": target_port,
                "url": f"http://{host}:{target_port}/",
                "state_file": str(_gateway_state_file(config)),
                "external_runtime": True,
                "healthy": True,
            }

        selected_port = _resolve_bind_port(host, target_port, bool(auto_port))
        state = _load_gateway_state(config)
        prior_pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
        if prior_pid > 0 and _is_pid_running(prior_pid):
            return {
                "ok": True,
                "mode": "gateway_detached",
                "already_running": True,
                "pid": prior_pid,
                "host": str(state.get("host") or host),
                "port": int(state.get("port") or selected_port),
                "url": f"http://{state.get('host', host)}:{int(state.get('port', selected_port))}/",
                "state_file": str(_gateway_state_file(config)),
            }
        cfg_path = str(config_path or "").strip() or str(os.environ.get("THOMAS_CONFIG") or "").strip()
        log_path = _gateway_log_file(config)
        proc = _gateway_spawn(config_path=cfg_path, host=host, port=selected_port, log_path=log_path)
        time.sleep(1.2)
        running = _is_pid_running(int(proc.pid))
        probe = _probe_gateway(host, selected_port, token=config.server.api_token)
        payload = {
            "ok": bool(running),
            "mode": "gateway_detached",
            "pid": int(proc.pid),
            "host": host,
            "port": int(selected_port),
            "url": f"http://{host}:{int(selected_port)}/",
            "log_file": str(log_path),
            "state_file": str(_gateway_state_file(config)),
            "healthy": bool(probe.get("healthy", False)),
        }
        if running:
            _save_gateway_state(
                config,
                {
                    "pid": int(proc.pid),
                    "host": host,
                    "port": int(selected_port),
                    "started_at": _utc_iso(),
                    "log_file": str(log_path),
                },
            )
        return payload

    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        result = manager.start_all()
        return {"ok": True, "mode": "in_process", "started": result, "status": manager.status()}
    except Exception as e:
        return {"ok": False, "mode": "in_process", "error": f"{type(e).__name__}: {e}"}


def stop_payload(config: AppConfig, *, detach: bool) -> dict[str, Any]:
    if detach:
        state = _load_gateway_state(config)
        pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
        if pid <= 0:
            host, port, _state = _active_gateway_target(config, None, None)
            probe = _probe_gateway(host, int(port), token=config.server.api_token)
            if bool(probe.get("healthy", False)):
                return {
                    "ok": False,
                    "mode": "gateway_detached",
                    "error": "detached runtime is external/untracked; no pid available for safe stop",
                    "host": host,
                    "port": int(port),
                    "url": f"http://{host}:{int(port)}/",
                    "state_file": str(_gateway_state_file(config)),
                }
            return {
                "ok": False,
                "mode": "gateway_detached",
                "error": "no gateway pid in state",
                "state_file": str(_gateway_state_file(config)),
            }
        running = _is_pid_running(pid)
        killed = False
        if running:
            killed = _kill_pid(pid)
            if not killed and not _is_pid_running(pid):
                killed = True
        _clear_gateway_state(config)
        return {
            "ok": bool((not _is_pid_running(pid)) and ((not running) or killed)),
            "mode": "gateway_detached",
            "pid": pid,
            "was_running": running,
            "killed": killed,
        }

    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        manager.stop_all()
        return {"ok": True, "mode": "in_process", "status": manager.status()}
    except Exception as e:
        return {"ok": False, "mode": "in_process", "error": f"{type(e).__name__}: {e}"}
