"""Benchmark task runners: raw model, embedded Thomas, and API-based Thomas."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

try:
    import httpx
except ImportError:
    pass  # type: ignore[assignment]

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.demo.agentic_benchmark_core import (
    _ensure_usage_telemetry,
    _extract_reported_first_token_ms,
    _normalize_usage,
    _select_elapsed_seconds,
    _select_optional_elapsed_seconds,
)
from thomas.demo.agentic_benchmark_helpers import (
    _chat_json_lane,
    _extract_revised_code,
    _merge_usage_rows,
    _parse_reviewer_verdict,
    _pass_budget_for_mode,
    _pipeline_topology,
    _review_decision_for_candidate,
    _should_use_coding_pipeline,
    _watch_line,
    _watch_text,
)
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools

DEFAULT_SYSTEM_PROMPT = (
    "You are a baseline assistant. Do not claim to have executed tools unless you actually can. "
    "Respond concisely and truthfully."
)


def _build_tools(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    register_ssh_tools(registry)
    return registry


async def _run_raw_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    started = time.monotonic()
    text = ""
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    error = ""
    try:
        _watch_line(watch, f"{watch_prefix} raw model request started")
        response = await llm.chat(
            [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": str(prompt or "")},
            ],
            tools=None,
        )
        text = str(response.get("text") or "")
        usage = _ensure_usage_telemetry(
            response.get("usage"),
            prompt_text=str(prompt or ""),
            response_text=text,
        )
        _watch_line(watch, f"{watch_prefix} raw model request completed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"{watch_prefix} raw model error: {error}")
    finally:
        await llm.close()
    elapsed = max(0.0, time.monotonic() - started)
    return {
        "ok": not bool(error),
        "text": text,
        "error": error,
        "usage": usage,
        "tool_calls": 0,
        "elapsed_seconds": round(elapsed, 3),
    }


def _resolve_via_modules(symbol: str, default):
    """Look up ``symbol`` via sys.modules so test monkeypatches intercept it.

    The public ``thomas.demo.agentic_benchmark`` module re-exports several
    helpers — tests patch them on that public surface. The implementation
    runners need to call through the re-export so the patched version wins.
    """
    import sys

    for mod_name in ("thomas.demo.agentic_benchmark", "thomas.demo.agentic_benchmark_runners"):
        module = sys.modules.get(mod_name)
        if module is not None:
            candidate = getattr(module, symbol, None)
            if candidate is not None and candidate is not _resolve_via_modules:
                return candidate
    return default


def _resolve_single_agent_lane():
    return _resolve_via_modules("_run_single_agent_lane", _run_single_agent_lane)


def _resolve_chat_json_lane():
    from thomas.demo.agentic_benchmark_helpers import _chat_json_lane

    return _resolve_via_modules("_chat_json_lane", _chat_json_lane)


async def _run_single_agent_lane(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str,
    job_type: str,
    watch: bool,
    watch_prefix: str,
    text_delta_hook: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    tools = _build_tools(config)
    agent = AgentLoop(
        config,
        llm,
        tools,
        conversation=[],
        memory=None,
        thread_id=f"bench-{int(time.time() * 1000)}",
    )
    started = time.monotonic()
    text_parts: list[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    token_report: dict[str, Any] = {}
    error = ""
    try:
        run_kwargs: dict[str, Any] = {
            "mode": str(mode),
            "tools_policy": str(tools_policy or "auto"),
            "token_economy": str(token_economy),
            "job_type": str(job_type or "coding"),
        }
        if max_iterations is not None:
            run_kwargs["max_iterations"] = int(max_iterations)

        async for event in agent.run(str(prompt or ""), **run_kwargs):
            et = str(getattr(event.type, "value", ""))
            if et == "text_delta":
                chunk = str(event.data.get("text") or "")
                text_parts.append(chunk)
                _watch_text(watch, chunk)
                if text_delta_hook is not None and chunk:
                    maybe = text_delta_hook(chunk)
                    if inspect.isawaitable(maybe):
                        await maybe  # type: ignore[arg-type]
            elif et == "tool_call_start":
                _watch_line(
                    watch,
                    f"\n{watch_prefix} tool_start: {event.data.get('tool_name', '')}",
                )
            elif et == "tool_result":
                _watch_line(
                    watch,
                    f"\n{watch_prefix} tool_result: {event.data.get('tool_name', '')} ok={bool(event.data.get('ok', False))}",
                )
            elif et == "agent_error":
                error = str(event.data.get("error") or "unknown error")
                _watch_line(watch, f"\n{watch_prefix} agent_error: {error}")
            elif et == "agent_done":
                final_text = str(event.data.get("text") or "")
                usage = _normalize_usage(event.data.get("usage"))
                tool_calls = int(event.data.get("tool_calls") or 0)
                token_report = dict(event.data.get("token_report") or {})
                _watch_line(
                    watch,
                    f"\n{watch_prefix} done: iterations={event.data.get('iterations')} tools={tool_calls}",
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"\n{watch_prefix} runner_exception: {error}")
    finally:
        await llm.close()

    if not final_text:
        final_text = "".join(text_parts).strip("\n")
    usage = _ensure_usage_telemetry(
        usage,
        prompt_text=str(prompt or ""),
        response_text=final_text,
        token_report=token_report,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }


async def _run_thomas_embedded_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str = "auto",
    job_type: str = "coding",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    if mode == "swarm":
        raise ValueError("Embedded runner does not support mode=swarm. Use --thomas-runner api.")
    started = time.monotonic()
    topology = _pipeline_topology(token_economy)
    pass_budget = _pass_budget_for_mode(mode)
    coding_pipeline_enabled = _should_use_coding_pipeline(
        job_type=str(job_type or ""),
        prompt=str(prompt or ""),
    )
    if not coding_pipeline_enabled:
        coder_only = await _resolve_single_agent_lane()(
            config,
            profile=profile,
            prompt=prompt,
            mode=mode,
            token_economy=token_economy,
            max_iterations=max_iterations,
            tools_policy=tools_policy,
            job_type=job_type,
            watch=watch,
            watch_prefix=watch_prefix,
        )
        token_report = dict(coder_only.get("token_report") or {})
        token_report["pipeline"] = {
            "enabled": False,
            "reason": "non_coding_task",
            "topology": "single_agent",
        }
        coder_only["token_report"] = token_report
        coder_only["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 3)
        return coder_only

    lane_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    lane_errors: list[str] = []
    stream_meta: dict[str, Any] = {
        "enabled": bool(topology == "coder_reviewer_parallel_conditional_fixer"),
        "chunks": 0,
        "chars": 0,
        "lines": 0,
    }
    streamed_text_parts: list[str] = []
    stream_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _stream_consumer() -> None:
        while True:
            item = await stream_queue.get()
            if item is None:
                break
            chunk = str(item or "")
            if not chunk:
                continue
            streamed_text_parts.append(chunk)
            stream_meta["chunks"] = int(stream_meta.get("chunks", 0) or 0) + 1
            stream_meta["chars"] = int(stream_meta.get("chars", 0) or 0) + len(chunk)
            stream_meta["lines"] = int(stream_meta.get("lines", 0) or 0) + chunk.count("\n")

    consumer_task: asyncio.Task | None = None
    text_hook: Callable[[str], Awaitable[None]] | None = None
    if topology == "coder_reviewer_parallel_conditional_fixer":
        consumer_task = asyncio.create_task(_stream_consumer())

        async def _enqueue_chunk(chunk: str) -> None:
            await stream_queue.put(str(chunk or ""))

        text_hook = _enqueue_chunk

    coder = await _resolve_single_agent_lane()(
        config,
        profile=profile,
        prompt=prompt,
        mode=mode,
        token_economy=token_economy,
        max_iterations=max_iterations,
        tools_policy=tools_policy,
        job_type=job_type,
        watch=watch,
        watch_prefix=watch_prefix,
        text_delta_hook=text_hook,
    )
    lane_rows.append(
        {
            "lane": "coder",
            "ok": bool(coder.get("ok")),
            "elapsed_seconds": float(coder.get("elapsed_seconds") or 0.0),
            "tool_calls": int(coder.get("tool_calls") or 0),
        }
    )
    if str(coder.get("error") or "").strip():
        lane_errors.append(str(coder.get("error") or "").strip())

    if consumer_task is not None:
        await stream_queue.put(None)
        await consumer_task

    current_text = str(coder.get("text") or "")
    if streamed_text_parts:
        streamed_text = "".join(streamed_text_parts).strip("\n")
        if streamed_text:
            current_text = streamed_text
    usage_rows = [dict(coder.get("usage") or {})]
    tool_calls = int(coder.get("tool_calls") or 0)
    token_report: dict[str, Any] = dict(coder.get("token_report") or {})
    review_decision: dict[str, Any] = {
        "required": False,
        "reason": "topology_coder_only" if topology == "coder_only" else "review_not_requested",
    }
    if not bool(coder.get("ok")) or not str(current_text or "").strip():
        review_decision = {"required": False, "reason": "coder_failure_or_empty"}
        token_report["pipeline"] = {
            "enabled": True,
            "topology": topology,
            "pass_budget": int(pass_budget),
            "review_triggered": False,
            "review_trigger_reason": str(review_decision.get("reason") or ""),
            "review_rounds": review_rows,
            "lane_rows": lane_rows,
            "lane_errors": lane_errors,
            "stream": stream_meta,
            "early_exit": "coder_failure_or_empty",
        }
        usage = _ensure_usage_telemetry(
            _merge_usage_rows(usage_rows),
            prompt_text=str(prompt or ""),
            response_text=str(current_text or ""),
            token_report=token_report,
        )
        return {
            "ok": bool(coder.get("ok")) and bool(str(current_text or "").strip()),
            "text": str(current_text or ""),
            "error": str(coder.get("error") or ""),
            "usage": usage,
            "tool_calls": int(tool_calls),
            "token_report": token_report,
            "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        }

    if topology != "coder_only":
        review_decision = _review_decision_for_candidate(
            candidate_text=str(current_text or ""),
            prompt=str(prompt or ""),
            mode=str(mode or ""),
            token_economy=str(token_economy or ""),
        )
    if topology != "coder_only" and bool(review_decision.get("required")):
        for review_round in range(1, int(pass_budget) + 1):
            review_prompt = (
                "Review this candidate code for correctness relative to the task.\n"
                "Return JSON with keys: pass (bool), issues (array of short strings), summary (string).\n"
                "Be strict about edge cases and wrong complexity.\n\n"
                f"Task:\n{prompt}\n\nCandidate code:\n{current_text}\n"
            )
            reviewer_lane = await _resolve_chat_json_lane()(
                config,
                profile=profile,
                system_prompt=(
                    "You are a strict code reviewer. Output only compact JSON: "
                    '{"pass": <bool>, "issues": [..], "summary": "..."}.'
                ),
                user_prompt=review_prompt,
                watch=watch,
                watch_prefix=f"{watch_prefix} reviewer[{review_round}]",
            )
            usage_rows.append(dict(reviewer_lane.get("usage") or {}))
            verdict = _parse_reviewer_verdict(str(reviewer_lane.get("text") or ""))
            reviewer_ok = bool(reviewer_lane.get("ok"))
            passed = bool(verdict.get("pass")) if reviewer_ok else True
            issues = list(verdict.get("issues") or [])
            summary = str(verdict.get("summary") or "")
            if str(reviewer_lane.get("error") or "").strip():
                lane_errors.append(str(reviewer_lane.get("error") or "").strip())
            review_row = {
                "round": int(review_round),
                "passed": bool(passed),
                "issues": issues,
                "summary": summary,
                "reviewer_ok": reviewer_ok,
                "reviewer_elapsed_seconds": float(reviewer_lane.get("elapsed_seconds") or 0.0),
            }
            review_rows.append(review_row)
            lane_rows.append(
                {
                    "lane": f"reviewer_{review_round}",
                    "ok": reviewer_ok,
                    "elapsed_seconds": float(reviewer_lane.get("elapsed_seconds") or 0.0),
                    "tool_calls": 0,
                }
            )
            if passed or review_round >= int(pass_budget):
                break

            fix_prompt = (
                "Revise the candidate code to resolve the reviewer issues.\n"
                "Return JSON with keys: revised_code (string), change_summary (string).\n\n"
                f"Task:\n{prompt}\n\nCurrent code:\n{current_text}\n\nIssues:\n{issues}\n"
            )
            fixer_lane = await _chat_json_lane(
                config,
                profile=profile,
                system_prompt=(
                    "You are a coding fixer. Output only compact JSON: "
                    '{"revised_code": "...", "change_summary": "..."}.'
                ),
                user_prompt=fix_prompt,
                watch=watch,
                watch_prefix=f"{watch_prefix} fixer[{review_round}]",
            )
            usage_rows.append(dict(fixer_lane.get("usage") or {}))
            lane_rows.append(
                {
                    "lane": f"fixer_{review_round}",
                    "ok": bool(fixer_lane.get("ok")),
                    "elapsed_seconds": float(fixer_lane.get("elapsed_seconds") or 0.0),
                    "tool_calls": 0,
                }
            )
            if str(fixer_lane.get("error") or "").strip():
                lane_errors.append(str(fixer_lane.get("error") or "").strip())
            revised_code = _extract_revised_code(str(fixer_lane.get("text") or ""))
            if revised_code.strip():
                current_text = revised_code
                review_row["fix_applied"] = True
            else:
                review_row["fix_applied"] = False

    token_report["pipeline"] = {
        "enabled": True,
        "topology": topology,
        "pass_budget": int(pass_budget),
        "review_triggered": bool(review_decision.get("required")),
        "review_trigger_reason": str(review_decision.get("reason") or ""),
        "review_rounds": review_rows,
        "lane_rows": lane_rows,
        "lane_errors": lane_errors,
        "stream": stream_meta,
        "final_text_chars": len(str(current_text or "")),
    }
    usage = _ensure_usage_telemetry(
        _merge_usage_rows(usage_rows),
        prompt_text=str(prompt or ""),
        response_text=str(current_text or ""),
        token_report=token_report,
    )
    return {
        "ok": bool(str(current_text or "").strip()),
        "text": str(current_text or ""),
        "error": "; ".join([e for e in lane_errors if e]).strip(),
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }


async def _run_thomas_api_task(
    *,
    api_base: str,
    api_token: str,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str = "auto",
    job_type: str = "coding",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    base = str(api_base or "").rstrip("/")
    if not base:
        raise ValueError("thomas api base URL is empty")
    headers: dict[str, str] = {}
    token = str(api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = time.monotonic()
    chat_started = started
    reported_elapsed_ms: float | None = None
    reported_first_token_ms: float | None = None
    first_stream_event_elapsed_seconds: float | None = None
    first_text_delta_elapsed_seconds: float | None = None
    stream_event_count = 0
    text_event_count = 0
    text_parts: list[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    token_report: dict[str, Any] = {}
    error = ""

    timeout = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        session_resp = await client.post(f"{base}/api/session/new", headers=headers)
        session_resp.raise_for_status()
        sid = str((session_resp.json() or {}).get("session_id") or "").strip()
        if not sid:
            raise ValueError("thomas api did not return session_id")
        chat_started = time.monotonic()

        payload: dict[str, Any] = {
            "session_id": sid,
            "profile": profile,
            "mode": mode,
            "text": str(prompt or ""),
            "token_economy": token_economy,
            "tools_policy": str(tools_policy or "auto"),
            "job_type": str(job_type or "coding"),
        }
        if max_iterations is not None:
            payload["max_iterations"] = int(max_iterations)
        _watch_line(watch, f"{watch_prefix} api session: {sid}")
        _watch_line(watch, f"{watch_prefix} started mode={mode} economy={token_economy}")

        async with client.stream("POST", f"{base}/api/chat", headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = str(raw_line or "").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stream_event_count += 1
                if first_stream_event_elapsed_seconds is None:
                    first_stream_event_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                et = str(evt.get("type") or "")
                if et == "text":
                    chunk = str(evt.get("text") or "")
                    text_parts.append(chunk)
                    text_event_count += 1
                    if chunk and first_text_delta_elapsed_seconds is None:
                        first_text_delta_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                    _watch_text(watch, chunk)
                elif et == "tool_start":
                    _watch_line(watch, f"\n{watch_prefix} tool_start: {evt.get('name', '')}")
                elif et == "tool_result":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} tool_result: {evt.get('name', '')} ok={bool(evt.get('ok', False))}",
                    )
                elif et == "iteration":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} iteration={evt.get('iteration')} token_estimate={evt.get('token_estimate')}",
                    )
                elif et == "error":
                    error = str(evt.get("error") or "unknown error")
                    _watch_line(watch, f"\n{watch_prefix} error: {error}")
                elif et == "done":
                    final_text = str(evt.get("response") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    from thomas.demo.agentic_benchmark_core import _safe_float

                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} done tools={tool_calls}")
                elif et == "swarm_done":
                    final_text = str(evt.get("final") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    from thomas.demo.agentic_benchmark_core import _safe_float

                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} swarm_done tools={tool_calls}")

    elapsed = _select_elapsed_seconds(
        reported_elapsed_ms=reported_elapsed_ms,
        fallback_elapsed_seconds=max(0.0, time.monotonic() - chat_started),
    )
    if not final_text:
        final_text = "".join(text_parts).strip("\n")
    usage = _ensure_usage_telemetry(
        usage,
        prompt_text=str(prompt or ""),
        response_text=final_text,
        token_report=token_report,
    )
    first_token_fallback = (
        first_text_delta_elapsed_seconds
        if first_text_delta_elapsed_seconds is not None
        else first_stream_event_elapsed_seconds
    )
    first_token_seconds = _select_optional_elapsed_seconds(
        reported_elapsed_ms=reported_first_token_ms,
        fallback_elapsed_seconds=first_token_fallback,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": float(elapsed),
        "setup_elapsed_seconds": round(max(0.0, chat_started - started), 3),
        "reported_elapsed_ms": (round(float(reported_elapsed_ms), 3) if reported_elapsed_ms is not None else None),
        "first_token_seconds": first_token_seconds,
        "first_text_delta_seconds": (
            round(float(first_text_delta_elapsed_seconds), 3) if first_text_delta_elapsed_seconds is not None else None
        ),
        "first_stream_event_seconds": (
            round(float(first_stream_event_elapsed_seconds), 3)
            if first_stream_event_elapsed_seconds is not None
            else None
        ),
        "reported_first_token_ms": (
            round(float(reported_first_token_ms), 3) if reported_first_token_ms is not None else None
        ),
        "stream_event_count": int(stream_event_count),
        "text_event_count": int(text_event_count),
    }


__all__ = [
    "_build_tools",
    "_run_raw_task",
    "_run_single_agent_lane",
    "_run_thomas_api_task",
    "_run_thomas_embedded_task",
]
