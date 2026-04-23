from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.demo.agentic_benchmark_core import _ensure_usage_telemetry, _normalize_usage
from thomas.demo.agentic_benchmark_helpers import _merge_usage_rows, _watch_line
from thomas.demo.agentic_benchmark_runners import _build_tools

DEFAULT_TOOL_AGENT_SYSTEM_PROMPT = (
    "You are a benchmark baseline agent with tool access. Use tools directly when needed, keep the work narrow, "
    "and finish the exact task without extra narration. Do not invent tool results."
)


async def _run_tool_agent_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str = "auto",
    token_economy: str = "optimal",
    max_iterations: int | None = None,
    tools_policy: str = "auto",
    job_type: str = "benchmark",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    _ = (mode, token_economy, tools_policy, job_type)
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    tools = _build_tools(config)
    started = time.monotonic()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": DEFAULT_TOOL_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": str(prompt or "")},
    ]
    usage_rows: list[dict[str, int]] = []
    final_text = ""
    error = ""
    total_tool_calls = 0
    max_turns = max(1, int(max_iterations if max_iterations is not None else 8))
    try:
        for turn in range(max_turns):
            _watch_line(watch, f"{watch_prefix} baseline tool-agent turn {turn + 1} started")
            response = await llm.chat(messages, tools=tools.get_openai_specs())
            turn_text = str(response.get("text") or "")
            if turn_text:
                final_text = turn_text
            usage_rows.append(_normalize_usage(response.get("usage")))
            tool_calls = list(response.get("tool_calls") or [])
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": turn_text}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": str(tc.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(tc.get("name") or ""),
                            "arguments": str(tc.get("arguments") or "{}"),
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)
            if not tool_calls:
                _watch_line(watch, f"{watch_prefix} baseline tool-agent completed without further tool calls")
                break
            for tc in tool_calls:
                tc_id = str(tc.get("id") or "")
                tc_name = str(tc.get("name") or "")
                raw_arguments = tc.get("arguments")
                try:
                    parsed_args = (
                        dict(raw_arguments)
                        if isinstance(raw_arguments, dict)
                        else json.loads(str(raw_arguments or "{}"))
                    )
                except json.JSONDecodeError as exc:
                    error = f"Invalid tool arguments for {tc_name}: {exc}"
                    break
                if not isinstance(parsed_args, dict):
                    error = f"Invalid tool arguments for {tc_name}: expected object"
                    break
                _watch_line(watch, f"{watch_prefix} tool_start: {tc_name}")
                tool_result = await tools.execute(tc_name, parsed_args)
                total_tool_calls += 1
                _watch_line(watch, f"{watch_prefix} tool_result: {tc_name} ok={tool_result.ok}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": tc_name,
                        "content": tool_result.to_content(),
                    }
                )
            if error:
                break
        else:
            error = f"Baseline tool-agent hit max turns ({max_turns}) without finishing."
    except (asyncio.TimeoutError, RuntimeError, ValueError, TypeError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"{watch_prefix} baseline tool-agent error: {error}")
    finally:
        await llm.close()
    usage = _ensure_usage_telemetry(
        _merge_usage_rows(usage_rows),
        prompt_text=str(prompt or ""),
        response_text=final_text,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(total_tool_calls),
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }
