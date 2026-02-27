"""aiohttp route registration for setup, diagnostics, and local model pull."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]
from aiohttp import web

from thomas.core.config import AppConfig
from thomas.models.local_recommendations import (
    build_local_runtime_plan,
    detect_local_hardware_profile,
    local_background_task_catalog,
)
from thomas.preferences.store import (
    AdvancedPatch,
    AdvancedRuntimePatch,
    PreferencesPatch,
    PreferencesStore,
    get_db_path,
)
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.routes.setup_local_sync import (
    build_local_sync_payload,
    fetch_ollama_model_ids,
)
from thomas.server.secrets import SecretStore

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

log = logging.getLogger(__name__)


# ── small pure helpers (duplicated from app.py to avoid import cycle) ──


def _join_url(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = path or ""
    if not p.startswith("/"):
        p = "/" + p
    return b + p


def _is_loopback_host(host: str) -> bool:
    if not host:
        return False
    if host.lower() in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ollama_base_url(app: web.Application, profile: str = "local") -> str:
    from urllib.parse import urlparse

    cfg: AppConfig = app[APP_CONFIG]
    if profile not in cfg.models:
        raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
    base = str(cfg.models[profile].base_url or "").strip()
    if not base:
        raise web.HTTPBadRequest(text=f"models.{profile}.base_url is empty")
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    u = urlparse(base)
    if u.scheme not in ("http", "https"):
        raise web.HTTPBadRequest(text="local model base_url must be http(s)")
    if not _is_loopback_host(u.hostname or ""):
        raise web.HTTPBadRequest(text="local model base_url must be loopback (localhost/127.0.0.1)")
    return base


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _clamp_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(int(min_value), min(int(max_value), int(parsed)))


def register_setup_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    require_loopback: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    async def api_setup_bootstrap(request: web.Request) -> web.Response:
        """Return machine readiness data for first-run onboarding."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        secrets_store: SecretStore = request.app[APP_SECRETS]

        def _first_command(names: list[str]) -> str:
            for name in names:
                found = shutil.which(name)
                if found:
                    return str(found)
            return ""

        codex_cmd = _first_command(["codex", "codex.cmd", "codex.exe"])
        node_cmd = _first_command(["node", "node.exe"])
        npm_cmd = _first_command(["npm", "npm.cmd", "npm.exe"])
        ollama_cmd = _first_command(["ollama", "ollama.exe"])

        local_profile_exists = "local" in cfg.models
        ollama_base = "http://127.0.0.1:11434"
        if local_profile_exists:
            try:
                ollama_base = _ollama_base_url(request.app, "local")
            except Exception:
                ollama_base = "http://127.0.0.1:11434"
        ollama_check_url = _join_url(ollama_base, "/api/tags")

        ollama_running = False
        ollama_error = ""
        if ollama_cmd:
            try:
                timeout = httpx.Timeout(connect=0.8, read=1.2, write=1.2, pool=1.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(ollama_check_url)
                    if int(resp.status_code) < 500:
                        ollama_running = True
                    else:
                        ollama_error = f"http {int(resp.status_code)}"
            except Exception as e:
                ollama_error = f"{type(e).__name__}: {e}"

        profile_rows: list[dict[str, Any]] = []
        cloud_key_count = 0
        for name, m in cfg.models.items():
            has_key = m.provider == "codex" or bool(secrets_store.get(name) or m.api_key)
            provider = str(m.provider or "")
            if provider not in {"ollama", "local", "codex"} and has_key:
                cloud_key_count += 1
            profile_rows.append(
                {
                    "name": str(name),
                    "provider": provider,
                    "has_key": bool(has_key),
                }
            )

        hardware = detect_local_hardware_profile()
        local_plan = build_local_runtime_plan(
            hardware=hardware,
            local_profile_exists=bool(local_profile_exists),
            ollama_installed=bool(ollama_cmd),
            ollama_running=bool(ollama_running),
        )

        if codex_cmd:
            recommended_path = "codex"
            reason = "Codex CLI is installed on this machine."
        else:
            local_recommendation = str(local_plan.get("recommended_connection_path") or "cloud").strip().lower()
            if local_recommendation == "local" and local_profile_exists and (ollama_running or ollama_cmd):
                recommended_path = "local"
                reason = str(local_plan.get("reason") or "Local execution is recommended for this device.")
            elif cloud_key_count > 0:
                recommended_path = "cloud"
                reason = "At least one cloud API key is already configured."
            else:
                recommended_path = "cloud"
                reason = str(
                    local_plan.get("reason") or "Cloud setup is the fastest path when local tools are not installed."
                )

        return web.json_response(
            {
                "system": {
                    "platform": str(sys.platform),
                    "python_version": str(sys.version.split()[0]),
                },
                "tools": {
                    "codex": {
                        "installed": bool(codex_cmd),
                        "command": codex_cmd,
                        "install_hint": "npm i -g @openai/codex",
                        "install_url": "https://developers.openai.com/codex",
                    },
                    "node": {
                        "installed": bool(node_cmd),
                        "command": node_cmd,
                        "install_url": "https://nodejs.org/en/download",
                    },
                    "npm": {
                        "installed": bool(npm_cmd),
                        "command": npm_cmd,
                        "install_url": "https://nodejs.org/en/download",
                    },
                    "ollama": {
                        "installed": bool(ollama_cmd),
                        "running": bool(ollama_running),
                        "command": ollama_cmd,
                        "base_url": ollama_base,
                        "check_url": ollama_check_url,
                        "last_error": ollama_error,
                        "install_url": "https://ollama.com/download",
                    },
                },
                "profiles": {
                    "default": str(cfg.default_model or ""),
                    "rows": profile_rows,
                    "cloud_key_count": int(cloud_key_count),
                },
                "hardware": hardware,
                "local_plan": local_plan,
                "quick_start": {
                    "recommended_path": recommended_path,
                    "reason": reason,
                },
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_setup_repair(request: web.Request) -> web.Response:
        """Run one-click setup repair for local desktop installs."""
        require_api_access(request)
        require_loopback(request)
        if request.method.upper() != "POST":
            raise web.HTTPMethodNotAllowed(method=request.method, allowed_methods=["POST"])

        payload: dict[str, Any] = {}
        if request.can_read_body:
            try:
                payload_raw = await read_json(request)
                if isinstance(payload_raw, dict):
                    payload = payload_raw
            except web.HTTPUnsupportedMediaType:
                payload = {}
            except web.HTTPBadRequest:
                payload = {}

        auto_install = _as_bool(payload.get("auto_install_tools"), True)
        skip_install = _as_bool(payload.get("skip_install"), False)
        skip_doctor = _as_bool(payload.get("skip_doctor"), False)

        root_dir = Path(__file__).resolve().parents[3]
        repair_script = root_dir / "scripts" / "repair.ps1"
        if not repair_script.exists():
            raise web.HTTPNotFound(text=f"repair script not found: {repair_script}")

        cmd: list[str] = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repair_script),
            "-NoPrompt",
        ]
        if skip_install:
            cmd.append("-SkipInstall")
        if skip_doctor:
            cmd.append("-SkipDoctor")
        if not auto_install:
            cmd.append("-NoAutoInstallTools")

        def _run_repair() -> dict[str, Any]:
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(root_dir),
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                stdout = str(completed.stdout or "")
                stderr = str(completed.stderr or "")
                report_path = ""
                for line in stdout.splitlines():
                    if "Repair report:" in line:
                        report_path = line.split("Repair report:", 1)[1].strip()
                return {
                    "ok": int(completed.returncode) == 0,
                    "exit_code": int(completed.returncode),
                    "stdout": stdout,
                    "stderr": stderr,
                    "report_path": report_path,
                }
            except subprocess.TimeoutExpired as e:
                return {
                    "ok": False,
                    "exit_code": 124,
                    "stdout": str(
                        (e.stdout or b"").decode("utf-8", errors="replace")
                        if isinstance(e.stdout, bytes)
                        else (e.stdout or "")
                    ),
                    "stderr": str(
                        (e.stderr or b"").decode("utf-8", errors="replace")
                        if isinstance(e.stderr, bytes)
                        else (e.stderr or "")
                    ),
                    "report_path": "",
                    "error": "repair timed out",
                }
            except Exception as e:
                return {
                    "ok": False,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "",
                    "report_path": "",
                    "error": f"{type(e).__name__}: {e}",
                }

        result = await asyncio.to_thread(_run_repair)
        stdout_tail = "\n".join(str(result.get("stdout", "")).splitlines()[-40:])
        stderr_tail = "\n".join(str(result.get("stderr", "")).splitlines()[-40:])

        status = 200 if bool(result.get("ok")) else 500
        return web.json_response(
            {
                "ok": bool(result.get("ok")),
                "exit_code": int(result.get("exit_code", 1)),
                "report_path": str(result.get("report_path") or ""),
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "error": str(result.get("error") or ""),
                "options": {
                    "auto_install_tools": bool(auto_install),
                    "skip_install": bool(skip_install),
                    "skip_doctor": bool(skip_doctor),
                },
            },
            status=status,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_setup_diagnostics(request: web.Request) -> web.Response:
        """Return setup diagnostics for troubleshooting."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]
        try:
            from thomas.system.config_validator import build_report_for_config

            config_report = build_report_for_config(
                cfg,
                config_path=getattr(cfg, "config_path", None),
            )
        except Exception as exc:
            config_report = {
                "ok": False,
                "errors": [
                    {
                        "code": "config.validator_unavailable",
                        "message": str(exc),
                        "remediation": "Fix the validator import/runtime error and retry diagnostics.",
                    }
                ],
                "warnings": [],
                "summary": {"error_count": 1, "warning_count": 0},
            }

        next_actions: list[str] = []
        seen_actions: set[str] = set()
        for finding in list(config_report.get("errors") or []) + list(config_report.get("warnings") or []):
            remediation = str(finding.get("remediation") or "").strip()
            if remediation and remediation not in seen_actions:
                next_actions.append(remediation)
                seen_actions.add(remediation)

        codes = {
            str(item.get("code") or "")
            for item in list(config_report.get("errors") or []) + list(config_report.get("warnings") or [])
        }
        if "server.remote.webhook_signatures_disabled" in codes:
            action = "Re-enable webhook signature enforcement before exposing remote mode."
            if action not in seen_actions:
                next_actions.append(action)

        return web.json_response(
            {
                "ok": bool(config_report.get("ok", False)),
                "config": config_report,
                "runtime": {
                    "python_version": sys.version,
                    "data_dir": str(cfg.memory.root_path),
                    "access_mode": str(cfg.server.access_mode or "local"),
                },
                "next_actions": next_actions,
            }
        )

    async def api_local_recommendations(request: web.Request) -> web.Response:
        """Return hardware-aware local model/runtime recommendations."""
        require_api_access(request)
        cfg: AppConfig = request.app[APP_CONFIG]

        profile = str(request.query.get("profile") or "local").strip() or "local"
        local_profile_exists = profile in cfg.models

        ollama_base = "http://127.0.0.1:11434"
        ollama_error = ""
        if local_profile_exists:
            try:
                ollama_base = _ollama_base_url(request.app, profile)
            except Exception as exc:
                ollama_error = f"{type(exc).__name__}: {exc}"

        ollama_cmd = shutil.which("ollama") or shutil.which("ollama.exe") or shutil.which("ollama.cmd") or ""
        installed_models: list[str] = []
        tags_error = ""
        if not ollama_error:
            installed_models, tags_error = await fetch_ollama_model_ids(ollama_base)

        hardware = detect_local_hardware_profile()
        local_plan = build_local_runtime_plan(
            hardware=hardware,
            local_profile_exists=bool(local_profile_exists),
            ollama_installed=bool(ollama_cmd),
            ollama_running=bool(not tags_error and not ollama_error),
        )
        recommended_models = [
            str(row.get("id") or "").strip()
            for row in list(local_plan.get("recommended_models") or [])
            if isinstance(row, dict)
        ]
        recommended_models = [model_id for model_id in recommended_models if model_id]
        installed_set = set(installed_models)
        missing_recommended_models = [model_id for model_id in recommended_models if model_id not in installed_set]

        return web.json_response(
            {
                "ok": True,
                "profile": profile,
                "hardware": hardware,
                "local_plan": local_plan,
                "readiness": {
                    "recommended_models": recommended_models,
                    "missing_recommended_models": missing_recommended_models,
                    "healthy": len(missing_recommended_models) == 0,
                },
                "ollama": {
                    "base_url": ollama_base,
                    "installed": bool(ollama_cmd),
                    "running": bool(not tags_error and not ollama_error),
                    "error": str(ollama_error or tags_error or ""),
                    "installed_models": installed_models,
                },
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_local_sync(request: web.Request) -> web.Response:
        """Pull/verify a local model set and report per-model verification status."""
        require_api_access(request)
        payload: dict[str, Any] = {}
        if request.can_read_body:
            try:
                incoming = await read_json(request)
                if isinstance(incoming, dict):
                    payload = incoming
            except Exception:
                payload = {}

        cfg: AppConfig = request.app[APP_CONFIG]
        profile = str(payload.get("profile") or "local").strip() or "local"
        base = _ollama_base_url(request.app, profile)
        result = await build_local_sync_payload(
            payload=payload,
            cfg=cfg,
            profile=profile,
            base_url=base,
        )
        healthy = bool(result.get("ok", False))
        return web.json_response(
            result,
            status=(200 if healthy else 207),
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_local_background_status(request: web.Request) -> web.Response:
        """Return local background-agent status, health, and recent cycle reports."""
        require_api_access(request)
        limit = _clamp_int(request.query.get("limit"), 20, min_value=1, max_value=200)
        from thomas.core.local_agent_engine import get_local_agent_engine

        engine = get_local_agent_engine()
        prefs = PreferencesStore(get_db_path()).get(user_id="default")
        runtime = getattr(getattr(prefs, "advanced", None), "runtime", None)
        return web.json_response(
            {
                "ok": True,
                "status": engine.status_snapshot(),
                "health": engine.health_snapshot(history_limit=limit),
                "recent_reports": engine.recent_reports(limit=limit),
                "settings": {
                    "local_background_agents_enabled": bool(getattr(runtime, "local_background_agents_enabled", False)),
                    "local_background_min_gpu_headroom_pct": int(
                        getattr(runtime, "local_background_min_gpu_headroom_pct", 35) or 35
                    ),
                },
                "task_catalog": local_background_task_catalog(),
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_local_background_control(request: web.Request) -> web.Response:
        """Update local background runtime settings and optionally run a cycle."""
        require_api_access(request)
        payload: dict[str, Any] = {}
        if request.can_read_body:
            try:
                incoming = await read_json(request)
                if isinstance(incoming, dict):
                    payload = incoming
            except Exception:
                payload = {}

        runtime_patch: dict[str, Any] = {}
        if "enabled" in payload:
            runtime_patch["local_background_agents_enabled"] = bool(payload.get("enabled"))
        if "min_gpu_headroom_pct" in payload:
            runtime_patch["local_background_min_gpu_headroom_pct"] = _clamp_int(
                payload.get("min_gpu_headroom_pct"),
                35,
                min_value=5,
                max_value=95,
            )

        updated_settings: dict[str, Any] = {}
        if runtime_patch:
            updated = PreferencesStore(get_db_path()).patch(
                PreferencesPatch(
                    advanced=AdvancedPatch(
                        runtime=AdvancedRuntimePatch(**runtime_patch),
                    )
                ),
                user_id="default",
            )
            updated_settings = {
                "local_background_agents_enabled": bool(updated.advanced.runtime.local_background_agents_enabled),
                "local_background_min_gpu_headroom_pct": int(
                    updated.advanced.runtime.local_background_min_gpu_headroom_pct
                ),
            }

        run_once = _as_bool(payload.get("run_once"), False)
        force = _as_bool(payload.get("force"), False)
        reason = str(payload.get("reason") or "manual").strip() or "manual"
        report_limit = _clamp_int(payload.get("history_limit"), 20, min_value=1, max_value=200)
        cycle_result: dict[str, Any] | None = None
        from thomas.core.local_agent_engine import get_local_agent_engine

        engine = get_local_agent_engine()
        if run_once:
            cycle_result = await asyncio.to_thread(
                engine.run_cycle_once,
                reason=reason,
                force=force,
            )

        status_code = 200
        if isinstance(cycle_result, dict) and not bool(cycle_result.get("ok", True)):
            reason_code = str(cycle_result.get("reason") or "").strip().lower()
            if reason_code in {"busy", "not_idle"}:
                status_code = 409
            elif reason_code in {"engine_disabled"}:
                status_code = 503
            else:
                status_code = 400

        return web.json_response(
            {
                "ok": not isinstance(cycle_result, dict) or bool(cycle_result.get("ok", False)),
                "updated_settings": updated_settings,
                "cycle_result": cycle_result,
                "status": engine.status_snapshot(),
                "health": engine.health_snapshot(history_limit=report_limit),
                "recent_reports": engine.recent_reports(limit=report_limit),
            },
            status=status_code,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_local_pull(request: web.Request) -> web.StreamResponse:
        """Pull a local model via Ollama's HTTP API.

        Note: restricted by server access policy and loopback local-model endpoints.
        """
        require_api_access(request)
        payload = await read_json(request)
        model_id = str(payload.get("model_id") or payload.get("name") or "").strip()
        if not model_id:
            raise web.HTTPBadRequest(text="missing model_id")

        profile = str(payload.get("profile") or "local").strip() or "local"
        base = _ollama_base_url(request.app, profile)
        url = _join_url(base, "/api/pull")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/x-ndjson; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )
        await resp.prepare(request)

        async def send(obj: dict[str, Any]) -> None:
            line = json.dumps(obj, ensure_ascii=False)
            await resp.write(line.encode("utf-8") + b"\n")

        ok = True
        try:
            # Keep streaming pulls unbounded for read time, but bound connect/write/pool.
            timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json={"name": model_id}) as r:
                    if r.status_code != 200:
                        text = (await r.aread()).decode("utf-8", errors="replace")
                        await send({"type": "error", "error": f"Ollama {r.status_code}: {text.strip()}"})
                        ok = False
                        await send({"type": "done", "ok": ok})
                        return resp

                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            j = json.loads(line)
                            if isinstance(j, dict) and j.get("error"):
                                ok = False
                                await send({"type": "error", "error": str(j.get("error"))})
                            else:
                                await send({"type": "progress", "data": j})
                        except Exception:
                            await send({"type": "progress", "data": {"raw": line}})

            await send({"type": "done", "ok": ok})
        except Exception as e:
            try:
                ok = False
                await send({"type": "error", "error": f"{type(e).__name__}: {e}"})
                await send({"type": "done", "ok": ok})
            except Exception as send_err:
                log.debug("Failed to stream local pull error payload: %s", send_err)
        finally:
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.debug("Failed to close local pull stream cleanly: %s", eof_err)

        return resp

    app.router.add_get("/api/setup/bootstrap", api_setup_bootstrap)
    app.router.add_post("/api/setup/repair", api_setup_repair)
    app.router.add_get("/api/setup/diagnostics", api_setup_diagnostics)
    app.router.add_get("/api/local/recommendations", api_local_recommendations)
    app.router.add_post("/api/local/sync", api_local_sync)
    app.router.add_get("/api/local/background", api_local_background_status)
    app.router.add_post("/api/local/background", api_local_background_control)
    app.router.add_post("/api/local/pull", api_local_pull)
