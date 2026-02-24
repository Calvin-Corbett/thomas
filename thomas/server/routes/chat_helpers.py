"""Shared helpers for the aiohttp chat route."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from aiohttp import web

from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.server.app_keys import APP_CONFIG

log = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


_CHAT_AUTOPILOT_INTENT_RE = re.compile(
    r"\b(24\/?7|24x7|continuous|continuously|always on|autopilot|run forever|keep running|keep working|keep monitoring)\b",
    re.IGNORECASE,
)
_CHAT_AUTOPILOT_ACTION_RE = re.compile(
    r"\b(build|ship|fix|monitor|manage|orchestrate|maintain|improve|optimize|triage|track|watch|automate)\b",
    re.IGNORECASE,
)
_CHAT_AUTOPILOT_MIN_COOLDOWN_S = 15 * 60
_CHAT_AUTOPILOT_MAX_TRACKED_GOALS = 512


def _chat_autopilot_should_auto_start(text_raw: Any) -> bool:
    text = str(text_raw or "").strip()
    if len(text) < 12:
        return False
    if not _CHAT_AUTOPILOT_INTENT_RE.search(text):
        return False
    if not _CHAT_AUTOPILOT_ACTION_RE.search(text):
        return False
    return True


def _chat_autopilot_goal_from_prompt(text_raw: Any) -> str:
    text = str(text_raw or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)[:320].strip()


def _chat_autopilot_goal_key(goal_raw: Any) -> str:
    return re.sub(r"\s+", " ", str(goal_raw or "").strip().lower())[:220]


def _chat_autopilot_parse_epoch(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return float(dt.timestamp())
    except Exception:
        return None


def _chat_autopilot_recent_goal_exists(
    store: Any,
    *,
    goal_key: str,
    now_s: float,
    cooldown_s: int,
) -> bool:
    if not goal_key:
        return False
    try:
        jobs = list(store.list_jobs(limit=320) or [])
    except Exception:
        return False
    for job in jobs:
        payload = getattr(job, "payload", None)
        if not isinstance(payload, dict):
            continue
        auto = payload.get("autopilot")
        if not isinstance(auto, dict):
            continue
        if auto.get("enabled") is False:
            continue
        existing_goal = (
            str(payload.get("goal") or "").strip()
            or str(payload.get("prompt") or "").strip()
            or str(payload.get("task") or "").strip()
        )
        if _chat_autopilot_goal_key(existing_goal) != goal_key:
            continue
        created_s = (
            _chat_autopilot_parse_epoch(auto.get("created_at"))
            or _chat_autopilot_parse_epoch(getattr(job, "created_at", None))
            or _chat_autopilot_parse_epoch(getattr(job, "updated_at", None))
        )
        if created_s is None:
            return True
        if (now_s - created_s) <= float(max(1, cooldown_s)):
            return True
    return False


def _chat_autopilot_prune_goal_cache(cache: Dict[str, float], *, now_s: float) -> None:
    stale_cutoff = now_s - 86400.0
    stale_keys = [k for k, ts in cache.items() if float(ts or 0.0) < stale_cutoff]
    for key in stale_keys:
        cache.pop(key, None)
    overflow = len(cache) - _CHAT_AUTOPILOT_MAX_TRACKED_GOALS
    if overflow > 0:
        oldest = sorted(cache.items(), key=lambda item: float(item[1] or 0.0))
        for key, _ts in oldest[:overflow]:
            cache.pop(key, None)


async def maybe_auto_start_autopilot_from_chat(
    request: web.Request,
    *,
    text: str,
    session_id: str,
    profile: str,
    model_id: Optional[str],
    autonomy_level: int,
) -> None:
    if not _env_flag("THOMAS_CHAT_AUTOPILOT_AUTO_START", True):
        return
    if not _chat_autopilot_should_auto_start(text):
        return

    goal = _chat_autopilot_goal_from_prompt(text)
    goal_key = _chat_autopilot_goal_key(goal)
    if not goal or not goal_key:
        return

    now_s = float(time.time())
    cooldown_s = int(_CHAT_AUTOPILOT_MIN_COOLDOWN_S)
    cache_raw = request.app.get("_chat_autopilot_last_by_goal")
    cache: Dict[str, float] = cache_raw if isinstance(cache_raw, dict) else {}

    try:
        last_s = float(cache.get(goal_key) or 0.0)
    except Exception:
        last_s = 0.0
    if last_s > 0.0 and (now_s - last_s) < float(cooldown_s):
        return

    store = request.app.get("autonomy_store")
    if store is not None and _chat_autopilot_recent_goal_exists(
        store,
        goal_key=goal_key,
        now_s=now_s,
        cooldown_s=cooldown_s,
    ):
        cache[goal_key] = now_s
        _chat_autopilot_prune_goal_cache(cache, now_s=now_s)
        return

    body: Dict[str, Any] = {
        "goal": goal,
        "cadence": "continuous",
        "every_seconds": 900,
        "start_immediately": True,
        "kind": "workflow_task",
        "workflow": "orchestrator_worker",
        "worker_count": 3,
        "autonomy_level": max(1, min(4, int(autonomy_level or 4))),
        "risk_class": "low",
        "session_id": str(session_id or "").strip() or None,
    }
    if str(profile or "").strip():
        body["profile"] = str(profile).strip()
    if str(model_id or "").strip():
        body["model_id"] = str(model_id).strip()

    base_candidates: List[str] = []
    transport = request.transport
    if transport is not None:
        sock = transport.get_extra_info("sockname")
        if isinstance(sock, tuple) and len(sock) >= 2:
            with contextlib.suppress(Exception):
                local_port = int(sock[1])
                if 0 < local_port <= 65535:
                    base_candidates.append(f"http://127.0.0.1:{local_port}")
                    base_candidates.append(f"http://localhost:{local_port}")
    with contextlib.suppress(Exception):
        origin = str(request.url.origin() or "").strip()
        if origin:
            base_candidates.append(origin.rstrip("/"))

    endpoints: List[str] = []
    seen: set[str] = set()
    for base in base_candidates:
        normalized = str(base or "").strip().rstrip("/")
        if not normalized:
            continue
        endpoint = f"{normalized}/api/mission/autopilot/objectives"
        if endpoint in seen:
            continue
        seen.add(endpoint)
        endpoints.append(endpoint)
    if not endpoints:
        return

    cfg_local: AppConfig = request.app[APP_CONFIG]
    headers = {"Content-Type": "application/json"}
    api_token = str(getattr(getattr(cfg_local, "server", None), "api_token", "") or "").strip()
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    timeout = httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=2.0)
    for endpoint in endpoints:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
            if resp.status_code < 400:
                cache[goal_key] = now_s
                _chat_autopilot_prune_goal_cache(cache, now_s=now_s)
                return
        except Exception as exc:
            log.debug("chat autopilot auto-start request failed (%s): %s", endpoint, exc)


def _normalize_usage_payload(payload: Any) -> Dict[str, int]:
    """Normalize usage object/dict to {prompt_tokens, completion_tokens, total_tokens}."""
    if isinstance(payload, dict):
        prompt_raw = payload.get("prompt_tokens", 0)
        completion_raw = payload.get("completion_tokens", 0)
        total_raw = payload.get("total_tokens", 0)
    else:
        prompt_raw = getattr(payload, "prompt_tokens", 0)
        completion_raw = getattr(payload, "completion_tokens", 0)
        total_raw = getattr(payload, "total_tokens", 0)

    try:
        prompt = max(0, int(prompt_raw or 0))
    except Exception:
        prompt = 0
    try:
        completion = max(0, int(completion_raw or 0))
    except Exception:
        completion = 0
    try:
        total = max(0, int(total_raw or 0))
    except Exception:
        total = 0
    total = max(total, prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _swarm_tool_mutates_fs(name: str, _args: Dict[str, Any]) -> bool:
    n = (name or "").lower()
    return any(
        k in n
        for k in (
            "fs.",
            "diff.",
            "git.",
            "shell",
            "write",
            "edit",
            "delete",
            "remove",
            "rename",
            "mkdir",
            "rmdir",
            "move",
            "copy",
            "apply",
            "patch",
        )
    )


class _LLMSwarmSubagent:
    """Basic LLM-backed Swarm subagent for planner/coder/tester/reviewer roles."""

    def __init__(
        self,
        agent_id: str,
        model_cfg: Any,
        system_hint: str,
        *,
        fallback_cfgs: Optional[List[Any]] = None,
        failover_enabled: bool = False,
        failover_cooldown_s: int = 300,
        failover_on_auth_error: bool = False,
    ):
        self.agent_id = agent_id
        self._model_cfg = model_cfg
        self._system_hint = system_hint
        self._fallback_cfgs = list(fallback_cfgs or [])
        self._failover_enabled = bool(failover_enabled)
        self._failover_cooldown_s = int(failover_cooldown_s)
        self._failover_on_auth_error = bool(failover_on_auth_error)

    async def run_task(
        self,
        *,
        task: Any,
        graph: Any,
        prior_results: Any,
        emit_text: Any,
        call_tool: Any,
        cancel_event: Any,
    ):
        from thomas.agent.swarm import TaskResult

        llm = LLMClient(
            self._model_cfg,
            fallback_configs=self._fallback_cfgs,
            failover_enabled=self._failover_enabled,
            failover_cooldown_s=self._failover_cooldown_s,
            failover_on_auth_error=self._failover_on_auth_error,
        )
        chunks: List[str] = []
        try:
            prior_bits: List[str] = []
            for tid, tr in (prior_results or {}).items():
                txt = (getattr(tr, "output", "") or "").strip()
                if not txt:
                    continue
                prior_bits.append(f"[{tid}] {txt[:500]}")
            prior_blob = "\n".join(prior_bits[:10]).strip()

            user_prompt = (
                f"Task ID: {task.id}\n"
                f"Task title: {task.title}\n"
                f"Task prompt:\n{task.prompt}\n\n"
            )
            if getattr(task, "acceptance", None):
                user_prompt += "Acceptance:\n" + "\n".join(f"- {x}" for x in task.acceptance) + "\n\n"
            if prior_blob:
                user_prompt += "Prior task outputs:\n" + prior_blob + "\n"

            messages = [
                {"role": "system", "content": self._system_hint},
                {"role": "user", "content": user_prompt},
            ]

            async for ev in llm.stream_chat(messages, tools=None):
                if cancel_event.is_set():
                    return TaskResult(ok=False, error="cancelled", output="".join(chunks))
                if ev.type == "token":
                    token = str(ev.data.get("text", ""))
                    if token:
                        chunks.append(token)
                        await emit_text(token)
                elif ev.type == "error":
                    return TaskResult(ok=False, error=str(ev.data.get("error") or "llm error"), output="".join(chunks))

            return TaskResult(ok=True, output="".join(chunks).strip())
        except Exception as exc:
            return TaskResult(ok=False, error=f"{type(exc).__name__}: {exc}", output="".join(chunks))
        finally:
            try:
                await llm.close()
            except Exception as llm_close_err:
                log.warning("LLM client close failed: %s", llm_close_err)
