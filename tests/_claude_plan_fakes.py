"""Shared fakes for the two suites about your Claude plan and a usage limit.

Split out of ``tests/test_chat_runs_on_your_claude_plan.py`` when it reached the
repo's 800-line limit (``scripts/forge/gates/monolith_guard.py``): the transport
and the menu are proved there, the limit's wording in
``tests/test_a_usage_limit_tells_you_the_truth.py``, and both drive the same fake
process.

Nothing here stubs Thomas. The CLI lines are Claude Code's own
``--output-format stream-json`` protocol (2.1.278), copied from the shapes Build's
translator already reads, and ``chatgpt_plan_limit`` is the exact string
``thomas/core/llm_streaming.py`` raises on your plan's usage-limit body. Only the
process is fake, the same way ``dispatch_via_claude_cli``'s ``runner`` is faked in
``test_a_claude_limit_pauses_autopilot``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest

from thomas.core.config import ModelConfig
from thomas.core.llm import LLMClient
from thomas.core.llm_streaming_claude_cli import stream_claude_cli

SEND_TASK = {
    "type": "function",
    "function": {
        "name": "send_task",
        "description": "Hand actionable work to the task manager.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
    },
}
SESSION_LIMIT = "You've hit your session limit · resets 12:20pm (America/Chicago)"
THROTTLED = "API Error: Server is temporarily limiting requests (not your usage limit) · Rate limited"
# The limit you met was 41.5 hours from its refusal ("resets_at": 1790427721, Saturday 08:02).
# Counted from now instead of pinned to that date, so these tests say the same thing next month.
AHEAD_S = 36 * 3600


def chatgpt_plan_limit(resets_at: int) -> str:
    """The error ``thomas/core/llm_streaming.py`` raises on the ChatGPT plan's usage-limit body."""
    error = {"type": "usage_limit_reached", "message": "The usage limit has been reached", "plan_type": "pro",
             "resets_at": resets_at, "eligible_promo": None, "resets_in_seconds": AHEAD_S}  # fmt: skip
    body = json.dumps({"error": error}, separators=(",", ":"))
    return f"ChatGPT/Codex HTTP 429 rate limited. {body[:240]}"


def reasoning_failed(error: str) -> str:
    """As the chat turn records a failed model call (thomas/marketplace/specialists/reasoning.py)."""
    return f"Reasoning failed: {error}"


@pytest.fixture(autouse=True)
def no_refusals_between_tests() -> Iterator[None]:
    """Both memories a refusal leaves behind are process-wide.

    The park registry (``llm_client._PROVIDER_COOLDOWNS``) and the Claude CLI
    sign-in the transport remembers (``claude_plan._no_signin``) outlive the test
    that filled them, and in the next one they read as a connection that cannot
    answer — which is the thing several of these tests assert about. Cleared on
    both sides, so test order cannot matter. Autouse in whichever module imports it.
    """
    from thomas.core import claude_plan, llm_client

    def forget() -> None:
        llm_client._PROVIDER_COOLDOWNS.clear()
        claude_plan._no_signin.clear()

    forget()
    yield
    forget()


# --- the CLI, as a process that is not really there -----------------------------


def text_line(text: str) -> str:
    message = {"model": "claude-sonnet-4-5", "role": "assistant", "content": [{"type": "text", "text": text}]}
    return json.dumps({"type": "assistant", "message": message})


def delta_line(text: str) -> str:
    event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
    return json.dumps({"type": "stream_event", "event": event})


def result_line(text: str, *, is_error: bool = False, status: int | None = None, usage: dict | None = None) -> str:
    result: dict[str, Any] = {"type": "result", "subtype": "success", "is_error": is_error, "result": text}
    if status is not None:
        result["api_error_status"] = status
    if usage is not None:
        result["usage"] = usage
    return json.dumps(result, ensure_ascii=False)


def limit_event(resets_at: int) -> str:
    info = {"status": "rejected", "resetsAt": resets_at, "rateLimitType": "five_hour", "overageStatus": "rejected"}
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": info})


class _Stdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [f"{line}\n".encode() for line in lines]

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class _Stdin:
    def __init__(self) -> None:
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class Proc:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _Stdout(lines)
        self.stdin = _Stdin()
        self.returncode: int | None = None
        self.killed = False

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def spawner(lines: list[str], seen: dict[str, Any]) -> Any:
    async def spawn(command: list[str], *, cwd: str) -> Proc:
        seen["command"], seen["cwd"] = command, cwd
        seen["proc"] = Proc(lines)
        return seen["proc"]

    return spawn


def plan_profile(**over: Any) -> ModelConfig:
    """The profile the model menu offers as your Claude plan: Anthropic, no key."""
    fields: dict[str, Any] = {"name": "anthropic", "provider": "anthropic", "api_key": "",
                              "base_url": "https://api.anthropic.com/v1", "model": "sonnet", "timeout_s": 30.0}  # fmt: skip
    return ModelConfig(**{**fields, **over})


def run_cli(lines: list[str], *, tools: list[dict] | None = None, seen: dict | None = None) -> list[Any]:
    """One chat turn on your Claude plan, against those CLI lines."""
    llm = LLMClient(plan_profile())
    watched = seen if seen is not None else {}

    async def go() -> list[Any]:
        collected = []
        stream = stream_claude_cli(
            llm,
            [{"role": "system", "content": "You are Thomas."}, {"role": "user", "content": "a meal-prep plan?"}],
            tools,
            spawn=spawner(lines, watched),
            cli_path="claude.cmd",
        )
        async for event in stream:
            collected.append(event)
        return collected

    return asyncio.run(go())
