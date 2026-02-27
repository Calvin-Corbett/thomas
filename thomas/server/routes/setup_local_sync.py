"""Shared local-sync helpers for setup routes."""

from __future__ import annotations

import json
import logging
import re
import shutil
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
)
from thomas.preferences.store import (
    AdvancedPatch,
    AdvancedRuntimePatch,
    PreferencesPatch,
    PreferencesStore,
    get_db_path,
)

log = logging.getLogger(__name__)


def _join_url(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = path or ""
    if not p.startswith("/"):
        p = "/" + p
    return b + p


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


def _extract_tool_readiness_flag(text: str) -> tuple[bool, bool]:
    """Return (json_like, tool_ready_signal)."""
    src = str(text or "").strip()
    if not src:
        return False, False
    json_like = False
    tool_ready = False
    try:
        payload = json.loads(src)
        if isinstance(payload, dict):
            json_like = True
            if bool(payload.get("tool_ready", False)):
                tool_ready = True
    except Exception:
        # best-effort fallback when model prepends/appends chatter
        match = re.search(r"\{[\s\S]{0,600}\}", src)
        if match:
            try:
                payload = json.loads(match.group(0))
                if isinstance(payload, dict):
                    json_like = True
                    if bool(payload.get("tool_ready", False)):
                        tool_ready = True
            except Exception:
                pass
    if not tool_ready:
        lower = src.lower()
        if '"tool_ready"' in lower and "true" in lower:
            tool_ready = True
    return json_like, tool_ready


def _extract_model_ids_from_tags(payload: Any) -> list[str]:
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
        model_id = str(row.get("name") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        out.append(model_id)
    return out


def _dedupe_model_ids(rows: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in rows:
        model_id = str(raw or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        out.append(model_id)
    return out


async def fetch_ollama_model_ids(base_url: str) -> tuple[list[str], str]:
    url = _join_url(base_url, "/api/tags")
    timeout = httpx.Timeout(connect=1.5, read=2.5, write=2.0, pool=2.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if int(resp.status_code) != 200:
        body = str(resp.text or "").strip()
        tail = body[:200] if body else f"http {int(resp.status_code)}"
        return [], tail
    try:
        payload = resp.json()
    except Exception as exc:
        return [], f"Invalid JSON from /api/tags: {type(exc).__name__}: {exc}"
    return _extract_model_ids_from_tags(payload), ""


async def pull_ollama_model(base_url: str, model_id: str) -> tuple[bool, str, list[str]]:
    url = _join_url(base_url, "/api/pull")
    timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=10.0)
    tail: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json={"name": model_id}) as resp:
                if int(resp.status_code) != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace").strip()
                    return False, f"Ollama {int(resp.status_code)}: {body}", tail

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    snippet = str(line).strip()
                    if len(snippet) > 280:
                        snippet = snippet[:280] + "..."
                    tail.append(snippet)
                    if len(tail) > 8:
                        tail = tail[-8:]
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict) and parsed.get("error"):
                        return False, str(parsed.get("error")), tail
        return True, "", tail
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", tail


async def probe_ollama_model(
    base_url: str,
    model_id: str,
    *,
    require_tool_signal: bool,
) -> dict[str, Any]:
    """Run a deterministic readiness probe for one local model."""
    url = _join_url(base_url, "/api/generate")
    timeout = httpx.Timeout(connect=3.0, read=45.0, write=20.0, pool=10.0)
    prompt = (
        "Reply with JSON only and no prose: " '{"tool_ready": true, "probe": "ok", "model": "' + str(model_id) + '"}'
    )
    payload = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    out: dict[str, Any] = {
        "ok": False,
        "model_id": str(model_id),
        "responded": False,
        "json_like": False,
        "tool_signal": False,
        "status_code": 0,
        "error": "",
        "response_preview": "",
        "require_tool_signal": bool(require_tool_signal),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["status_code"] = int(resp.status_code or 0)
    if int(resp.status_code or 0) != 200:
        body = str(resp.text or "").strip()
        out["error"] = body[:240] if body else f"http {int(resp.status_code)}"
        return out
    try:
        data = resp.json()
    except Exception as exc:
        out["error"] = f"Invalid JSON from /api/generate: {type(exc).__name__}: {exc}"
        return out
    if not isinstance(data, dict):
        out["error"] = "unexpected /api/generate payload"
        return out
    response_text = str(data.get("response") or "").strip()
    out["responded"] = bool(response_text)
    out["response_preview"] = response_text[:220]
    json_like, tool_signal = _extract_tool_readiness_flag(response_text)
    out["json_like"] = bool(json_like)
    out["tool_signal"] = bool(tool_signal)
    if not out["responded"]:
        out["error"] = "empty generation response"
        return out
    out["ok"] = bool(out["responded"] and (tool_signal if require_tool_signal else True))
    if not out["ok"] and not out["error"]:
        if require_tool_signal:
            out["error"] = "tool_readiness_signal_missing"
        else:
            out["error"] = "probe_failed"
    return out


async def build_local_sync_payload(
    *,
    payload: dict[str, Any],
    cfg: AppConfig,
    profile: str,
    base_url: str,
) -> dict[str, Any]:
    verify_only = _as_bool(payload.get("verify_only"), False)
    pull_missing_only = _as_bool(payload.get("pull_missing_only"), True)
    verify_inference = _as_bool(payload.get("verify_inference"), True)
    verify_tooling = _as_bool(payload.get("verify_tooling"), True)
    auto_repair_failed_probes = _as_bool(payload.get("auto_repair_failed_probes"), True)

    incoming_models_raw = payload.get("model_ids")
    if incoming_models_raw is None:
        incoming_models_raw = payload.get("models")
    incoming_models: list[str] = []
    if isinstance(incoming_models_raw, str):
        incoming_models = [part.strip() for part in incoming_models_raw.split(",")]
    elif isinstance(incoming_models_raw, list):
        incoming_models = [str(v or "").strip() for v in incoming_models_raw]

    use_recommended = _as_bool(payload.get("use_recommended"), True)
    ollama_cmd = shutil.which("ollama") or shutil.which("ollama.exe") or shutil.which("ollama.cmd") or ""
    hardware = detect_local_hardware_profile()
    local_plan = build_local_runtime_plan(
        hardware=hardware,
        local_profile_exists=bool(profile in cfg.models),
        ollama_installed=bool(ollama_cmd),
        ollama_running=True,
    )
    recommended_model_ids = [
        str(row.get("id") or "").strip()
        for row in list(local_plan.get("recommended_models") or [])
        if isinstance(row, dict)
    ]
    recommended_model_ids = [model_id for model_id in recommended_model_ids if model_id]
    if not incoming_models and use_recommended:
        incoming_models = list(recommended_model_ids)

    model_ids = _dedupe_model_ids(incoming_models)
    if not model_ids:
        raise web.HTTPBadRequest(text="No model_ids requested and no recommended local models for this hardware tier.")

    installed_before, tags_error_before = await fetch_ollama_model_ids(base_url)
    installed_before_set = set(installed_before)

    results: list[dict[str, Any]] = []
    for model_id in model_ids:
        row: dict[str, Any] = {
            "model_id": model_id,
            "already_installed": bool(model_id in installed_before_set),
            "pulled": False,
            "verified": False,
            "probe_ok": False,
            "probe": {},
            "ok": False,
            "error": "",
            "events_tail": [],
            "repair_attempted": False,
            "repair_events_tail": [],
            "repair_error": "",
        }
        if not verify_only:
            if row["already_installed"] and pull_missing_only:
                row["pulled"] = False
            else:
                pulled_ok, pull_error, events_tail = await pull_ollama_model(base_url, model_id)
                row["pulled"] = bool(pulled_ok)
                row["events_tail"] = list(events_tail)
                row["error"] = str(pull_error or "")
        results.append(row)

    installed_after_pull, tags_error_after_pull = await fetch_ollama_model_ids(base_url)
    installed_after_set = set(installed_after_pull)

    for row in results:
        model_id = str(row.get("model_id") or "")
        row["verified"] = bool(model_id in installed_after_set)
        if bool(row["verified"]) and bool(verify_inference):
            probe = await probe_ollama_model(
                base_url,
                model_id,
                require_tool_signal=bool(verify_tooling),
            )
            row["probe"] = probe
            row["probe_ok"] = bool(probe.get("ok", False))
            if not row["probe_ok"] and not row.get("error"):
                row["error"] = str(probe.get("error") or "probe_failed")
        elif not verify_inference and bool(row["verified"]):
            row["probe_ok"] = True
        row["ok"] = bool(row["verified"] and not row.get("error") and row.get("probe_ok", False))

    if bool(auto_repair_failed_probes) and bool(verify_inference) and not bool(verify_only):
        for row in results:
            if bool(row.get("ok", False)):
                continue
            if not bool(row.get("verified", False)):
                continue
            model_id = str(row.get("model_id") or "")
            if not model_id:
                continue
            row["repair_attempted"] = True
            pulled_ok, pull_error, events_tail = await pull_ollama_model(base_url, model_id)
            row["repair_events_tail"] = list(events_tail)
            if not pulled_ok:
                row["repair_error"] = str(pull_error or "repair_pull_failed")
            installed_after_repair, _tags_error_after_repair = await fetch_ollama_model_ids(base_url)
            installed_after_set = set(installed_after_repair)
            row["verified"] = bool(model_id in installed_after_set)
            if bool(row["verified"]):
                probe = await probe_ollama_model(
                    base_url,
                    model_id,
                    require_tool_signal=bool(verify_tooling),
                )
                row["probe"] = probe
                row["probe_ok"] = bool(probe.get("ok", False))
                if bool(row["probe_ok"]):
                    row["error"] = ""
                elif not row.get("error"):
                    row["error"] = str(probe.get("error") or "probe_failed_after_repair")
            row["ok"] = bool(row["verified"] and not row.get("error") and row.get("probe_ok", False))

    installed_final, tags_error_final = await fetch_ollama_model_ids(base_url)
    installed_final_set = set(installed_final)
    missing_recommended = [model_id for model_id in recommended_model_ids if model_id not in installed_final_set]

    apply_recommended_settings_default = bool(
        use_recommended
        and not (
            (isinstance(incoming_models_raw, str) and incoming_models_raw.strip())
            or (isinstance(incoming_models_raw, list) and len(incoming_models_raw) > 0)
        )
    )
    apply_recommended_settings = _as_bool(
        payload.get("apply_recommended_settings"),
        apply_recommended_settings_default,
    )
    settings_applied: dict[str, Any] = {}
    settings_apply_error = ""
    if apply_recommended_settings:
        defaults = dict(local_plan.get("settings_defaults") or {})
        runtime_patch = AdvancedRuntimePatch(
            local_background_agents_enabled=bool(defaults.get("local_background_agents_enabled", False)),
            local_background_min_gpu_headroom_pct=_clamp_int(
                defaults.get("local_background_min_gpu_headroom_pct"),
                35,
                min_value=5,
                max_value=95,
            ),
        )
        try:
            updated = PreferencesStore(get_db_path()).patch(
                PreferencesPatch(
                    advanced=AdvancedPatch(
                        runtime=runtime_patch,
                    )
                ),
                user_id="default",
            )
            settings_applied = {
                "local_background_agents_enabled": bool(updated.advanced.runtime.local_background_agents_enabled),
                "local_background_min_gpu_headroom_pct": int(
                    updated.advanced.runtime.local_background_min_gpu_headroom_pct
                ),
            }
        except Exception as exc:
            settings_apply_error = f"{type(exc).__name__}: {exc}"

    all_ok = bool(results) and all(bool(row.get("ok")) for row in results)
    healthy = bool(all_ok and len(missing_recommended) == 0 and not tags_error_final)
    return {
        "ok": bool(healthy),
        "profile": profile,
        "base_url": base_url,
        "verify_only": bool(verify_only),
        "pull_missing_only": bool(pull_missing_only),
        "verify_inference": bool(verify_inference),
        "verify_tooling": bool(verify_tooling),
        "auto_repair_failed_probes": bool(auto_repair_failed_probes),
        "requested_models": model_ids,
        "installed_before": installed_before,
        "installed_after_pull": installed_after_pull,
        "installed_after": installed_final,
        "results": results,
        "readiness": {
            "healthy": bool(healthy),
            "recommended_models": recommended_model_ids,
            "missing_recommended_models": missing_recommended,
            "requested_models_ok": bool(all_ok),
        },
        "local_plan": local_plan,
        "hardware": hardware,
        "settings_applied": settings_applied,
        "settings_apply_error": settings_apply_error,
        "errors": {
            "before_tags": str(tags_error_before or ""),
            "after_pull_tags": str(tags_error_after_pull or ""),
            "after_tags": str(tags_error_final or ""),
        },
    }
