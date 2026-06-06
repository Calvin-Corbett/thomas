"""Request/response shaping helpers for the ChatGPT/Codex Responses API.

Extracted from ``thomas.core.llm_streaming`` to keep that module under the
architecture size limit. These helpers translate Thomas' internal chat-message
and tool shapes into the OpenAI Responses payload, and pull usage/items back
out of streamed Responses events.
"""

from __future__ import annotations

import json
from typing import Any

from thomas.core.llm_shared import TokenUsage


def _responses_content(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, list)):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _responses_input_from_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        content = _responses_content(msg.get("content", ""))
        if role == "system":
            if content:
                instructions.append(str(content))
            continue
        if role == "tool":
            call_id = str(msg.get("tool_call_id") or "").strip()
            if call_id:
                out.append({"type": "function_call_output", "call_id": call_id, "output": content})
            continue
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if content:
                out.append({"role": "assistant", "content": content})
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    func = tc.get("function")
                    if not isinstance(func, dict):
                        func = {}
                    call_id = str(tc.get("id") or "").strip()
                    name = str(func.get("name") or "").strip()
                    if call_id and name:
                        out.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": str(func.get("arguments") or "{}"),
                            }
                        )
            continue
        if role in {"user", "developer"}:
            out.append({"role": "user", "content": content})
        elif content:
            out.append({"role": role or "user", "content": content})
    return "\n".join(part for part in instructions if part), out


def _responses_tools(owner: Any, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    owner._openai_tool_name_map = {}
    out: list[dict[str, Any]] = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        func = t.get("function")
        if not isinstance(func, dict):
            continue
        original_name = str(func.get("name") or "")
        safe_name = owner._sanitize_tool_name(original_name) if hasattr(owner, "_sanitize_tool_name") else original_name
        if safe_name != original_name:
            owner._openai_tool_name_map[safe_name] = original_name
        out.append(
            {
                "type": "function",
                "name": safe_name,
                "description": str(func.get("description") or ""),
                "parameters": func.get("parameters") or {},
            }
        )
    return out


def _build_openai_codex_request(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    instructions, input_items = _responses_input_from_messages(messages)
    body: dict[str, Any] = {
        "model": owner.config.model,
        "input": input_items,
        "stream": True,
        "store": False,
        "parallel_tool_calls": True,
    }
    if instructions:
        body["instructions"] = instructions
    effort = str(getattr(owner.config, "reasoning_effort", "") or "").strip().lower()
    if effort:
        body["reasoning"] = {"effort": "high" if effort == "xhigh" else effort}
    converted_tools = _responses_tools(owner, tools)
    if converted_tools:
        body["tools"] = converted_tools
        body["tool_choice"] = "auto"
    return body


def _extract_responses_usage(event_data: dict[str, Any]) -> TokenUsage | None:
    usage = event_data.get("usage")
    response = event_data.get("response")
    if not isinstance(usage, dict) and isinstance(response, dict):
        usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    completion_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    total_tokens = usage.get("total_tokens")
    try:
        p = int(prompt_tokens or 0)
        c = int(completion_tokens or 0)
        t = int(total_tokens if total_tokens is not None else p + c)
    except (TypeError, ValueError, OverflowError):
        return None
    return TokenUsage(prompt_tokens=max(0, p), completion_tokens=max(0, c), total_tokens=max(0, t))


def _response_item(event_data: dict[str, Any]) -> dict[str, Any]:
    for key in ("item", "output_item"):
        item = event_data.get(key)
        if isinstance(item, dict):
            return item
    return {}
