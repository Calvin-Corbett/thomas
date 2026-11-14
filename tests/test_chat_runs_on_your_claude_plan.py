"""Chat answers on your Claude plan, through the same CLI Build uses.

You asked for this on 2026-09-24, with your ChatGPT plan out of allowance until
Saturday morning: "Make your Chat able to run on my Claude plan too when I pick it,
the same way Build does, and prove a Chat conversation works on it." A conversation
on the plan is proved here, along with who serves the profile and what the model
menu says about it.

The other half of what you asked — "Tell me the truth when that happens: which
limit, when it resets, and what I can use instead" — is proved in
``tests/test_a_usage_limit_tells_you_the_truth.py``. Both suites drive the real
stream-json protocol through the fakes in ``tests/_claude_plan_fakes.py``; only the
process is fake. Nothing about the chat turn, the model catalog or the picker's rule
is stubbed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests._claude_plan_fakes import (
    SEND_TASK,
    delta_line,
    no_refusals_between_tests,  # noqa: F401  (autouse: the CLI's 429 parks the profile)
    plan_profile,
    reasoning_failed,
    result_line,
    run_cli,
    spawner,
    text_line,
)
from thomas.core.claude_plan import (
    CLAUDE_PLAN_MODEL_IDS,
    chose_claude_plan,
    claude_plan_ready,
    runs_on_claude_plan,
)
from thomas.core.config import AppConfig, MemoryConfig
from thomas.core.llm import LLMClient
from thomas.core.llm_shared import LLMError, StreamEvent
from thomas.core.llm_streaming_claude_cli import (
    DENIED_CLI_TOOLS,
    cli_command,
    render_prompt,
    stream_claude_cli,
)
from thomas.marketplace.orchestrator.response_failures import _chat_failure_message
from thomas.models.sources.claude_cli import claude_cli_aliases

# --- a Chat conversation on the Claude plan -------------------------------------


def test_a_chat_conversation_answers_on_your_claude_plan() -> None:
    """The proof you asked for: a question in, the model's own answer out, on the plan."""
    seen: dict[str, Any] = {}
    events = run_cli(
        [
            json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-4-5"}),
            delta_line("Here is a three-day "),
            delta_line("meal-prep plan."),
            text_line("Here is a three-day meal-prep plan."),
            result_line("Here is a three-day meal-prep plan.", usage={"input_tokens": 120, "output_tokens": 30}),
        ],
        seen=seen,
    )

    assert [e.type for e in events] == ["token", "token", "usage", "done"]
    assert "".join(e.data["text"] for e in events if e.type == "token") == "Here is a three-day meal-prep plan."
    assert events[2].data["usage"].total_tokens == 150
    # The question, and Thomas's instructions, really reached the model.
    sent = json.loads(seen["proc"].stdin.written.decode())
    assert "a meal-prep plan?" in sent["message"]["content"]
    assert "You are Thomas." in sent["message"]["content"]


def test_the_answer_is_kept_when_it_arrives_only_in_the_result() -> None:
    events = run_cli([result_line("Two answers are not better than none.")])
    assert [e.type for e in events] == ["token", "done"]
    assert events[0].data["text"] == "Two answers are not better than none."


def test_a_chat_turn_may_not_touch_this_machine() -> None:
    """Thomas's own tool policy governs a chat turn; the CLI's built-in tools are all denied."""
    command = cli_command("claude.cmd", "sonnet")
    denied = command[command.index("--disallowedTools") + 1 : command.index("--strict-mcp-config")]
    assert tuple(denied) == DENIED_CLI_TOOLS
    assert "--allowedTools" not in command
    for tool in ("Bash", "Write", "Edit", "Read"):
        assert tool in denied


def test_the_model_you_picked_is_the_model_that_runs() -> None:
    seen: dict[str, Any] = {}
    llm = LLMClient(plan_profile(model="opus"))

    async def go() -> None:
        async for _ in stream_claude_cli(
            llm, [{"role": "user", "content": "hi"}], None, spawn=spawner([result_line("hello")], seen),
            cli_path="claude.cmd",
        ):  # fmt: skip
            pass

    asyncio.run(go())
    assert seen["command"][seen["command"].index("--model") + 1] == "opus"


def test_a_tool_call_written_as_json_becomes_a_real_tool_call() -> None:
    """The CLI has no function-calling wire, so one JSON object is read back as the call it is."""
    call = json.dumps({"name": "send_task", "arguments": {"title": "Plan the week's meals"}})
    events = run_cli([delta_line(call), result_line(call)], tools=[SEND_TASK])

    kinds = [e.type for e in events]
    assert kinds == ["tool_call_start", "tool_call_delta", "tool_call_end", "done"], kinds
    assert events[-2].data["name"] == "send_task"
    assert "Plan the week's meals" in events[-2].data["arguments"]


def test_prose_is_not_held_back_waiting_to_see_if_it_was_a_call() -> None:
    events = run_cli([delta_line("Sure — "), delta_line("here goes."), result_line("Sure — here goes.")],
                     tools=[SEND_TASK])  # fmt: skip
    assert [e.type for e in events] == ["token", "token", "done"]
    assert events[0].data["text"] == "Sure — "


def test_an_unoffered_tool_name_stays_text() -> None:
    """A model that answers with JSON about something else has not called anything."""
    text = json.dumps({"name": "rm_rf", "arguments": {}})
    events = run_cli([delta_line(text), result_line(text)], tools=[SEND_TASK])
    assert [e.type for e in events] == ["token", "done"]
    assert events[0].data["text"] == text


def test_the_prompt_names_an_image_it_cannot_send() -> None:
    prompt = render_prompt(
        [{"role": "user", "content": [{"type": "text", "text": "what is this?"}, {"type": "image_url"}]}]
    )
    assert "what is this?" in prompt and "an image you attached" in prompt


def _spawn_raises(error: BaseException) -> Any:
    async def spawn(_command: list[str], *, cwd: str) -> Any:
        raise error

    return spawn


def _refused_spawn(error: BaseException) -> LLMError:
    llm = LLMClient(plan_profile())

    async def go() -> None:
        async for _ in stream_claude_cli(
            llm, [{"role": "user", "content": "hi"}], None, spawn=_spawn_raises(error), cli_path="claude.cmd"
        ):
            pass

    with pytest.raises(LLMError) as raised:
        asyncio.run(go())
    return raised.value


def test_a_loop_that_cannot_spawn_says_so_instead_of_failing_namelessly() -> None:
    """A Windows selector loop (the terminal REPL's) raises NotImplementedError on spawn."""
    error = _refused_spawn(NotImplementedError())
    assert "event loop does not support subprocesses" in str(error)
    assert error.retryable is False
    # And the sentence reaches the person whole, rather than becoming "no answer".
    assert _chat_failure_message(reasoning_failed(str(error))) == str(error)


def test_a_cli_that_will_not_start_is_reported_as_that() -> None:
    error = _refused_spawn(FileNotFoundError(2, "No such file"))
    assert "The Claude CLI would not start" in str(error)
    assert error.retryable is True


def test_without_the_cli_chat_says_what_to_do_about_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.core import llm_streaming_claude_cli

    monkeypatch.setattr(llm_streaming_claude_cli, "claude_cli_path", lambda **_kw: "")
    llm = LLMClient(plan_profile())

    async def go() -> None:
        async for _ in stream_claude_cli(llm, [{"role": "user", "content": "hi"}], None):
            pass

    with pytest.raises(LLMError, match="Claude CLI, and it is not installed"):
        asyncio.run(go())


# --- who serves the profile ------------------------------------------------------


def test_the_anthropic_profile_without_a_key_is_your_claude_plan() -> None:
    assert runs_on_claude_plan("anthropic", "") is True
    assert claude_plan_ready("anthropic", "", which=lambda _n: "C:/claude.cmd") is True
    assert claude_plan_ready("anthropic", "", which=lambda _n: None) is False, "nothing is offered that cannot run"


def test_a_key_sends_the_same_profile_back_to_anthropics_api() -> None:
    assert runs_on_claude_plan("anthropic", "sk-ant-1") is False
    assert runs_on_claude_plan("openai_codex", "") is False


@pytest.mark.parametrize(
    ("where", "on_plan"),
    [("a key saved in Settings, which the chat turn never receives", True), ("a key on the profile itself", False)],
)
def test_the_model_menu_answers_from_the_key_the_turn_will_run_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, on_plan: bool
) -> None:
    """``/api/models`` and the transport must name one engine for one profile.

    A key saved in Settings goes to the secret store, and ``_model_cfg_with_secrets``
    -- the one resolver the chat stream and the catalog both use -- does not put it on
    the profile, so the Claude CLI serves that turn. Reading the store directly here
    called the same profile Anthropic's API, and the menu then named an engine that
    was not the one answering.
    """
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from thomas.core import claude_plan
    from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
    from thomas.server.routes.models_aiohttp import register_models_routes
    from thomas.server.secrets import SecretStore

    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "prefs.db"))  # never the real preferences
    monkeypatch.setattr(claude_plan, "claude_cli_path", lambda **_kw: "C:/claude.cmd")
    key = "" if on_plan else "sk-ant-on-the-profile"
    cfg = AppConfig(models={"anthropic": plan_profile(api_key=key)}, default_model="anthropic",
                    memory=MemoryConfig(root=str(tmp_path)))  # fmt: skip
    secrets = SecretStore(tmp_path)
    secrets.set("anthropic", "sk-ant-in-settings", persist=False)  # in memory: no real store is touched

    async def flag() -> bool:
        app = web.Application()
        app[APP_CONFIG], app[APP_SECRETS] = cfg, secrets
        register_models_routes(app, require_api_access=lambda _r: None,
                               model_cfg_with_secrets=lambda name: cfg.models[name])  # fmt: skip
        async with TestClient(TestServer(app)) as client:
            body = await (await client.get("/api/models")).json()
        return bool(next(p for p in body["profiles"] if p["name"] == "anthropic")["claude_plan"])

    runtime = cfg.models["anthropic"]
    assert runs_on_claude_plan(runtime.provider, runtime.api_key) is on_plan, where
    assert asyncio.run(flag()) is on_plan, "the menu's flag has drifted from the transport's rule"


def test_a_chat_turn_on_that_profile_is_dispatched_to_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """The routing itself, through the dispatcher every provider goes through."""
    from thomas.core import llm_transport_pool

    calls: list[str] = []

    async def fake(owner, messages, tools=None):  # noqa: ANN001
        calls.append(str(owner.config.model))

        async def stream() -> Any:
            yield StreamEvent(type="done")

        return stream()

    async def go() -> None:
        llm = LLMClient(plan_profile())
        async for _ in llm_transport_pool.stream_current_provider(llm, [{"role": "user", "content": "hi"}]):
            pass

    monkeypatch.setattr(llm_transport_pool, "stream_claude_cli", fake)
    asyncio.run(go())
    assert calls == ["sonnet"], "the Anthropic profile with no key must not be sent to Anthropic's API"


@pytest.mark.parametrize(
    ("model", "engine"),
    [("sonnet", "the Claude CLI"), ("claude-sonnet-4-5-20250929", "Anthropic's API")],
)
def test_only_a_model_the_plan_offers_starts_the_claude_program(
    monkeypatch: pytest.MonkeyPatch, model: str, engine: str
) -> None:
    """A missing key is not by itself a request for the Claude program.

    Routing on "Anthropic, no key" alone caught every keyless Anthropic profile,
    whatever model it named -- including Anthropic's own versioned ids, which the
    plan does not answer to. A turn that asked for an HTTP call then started a
    program on this machine instead, which is a different request than the one
    made (it took test_llm_budget_transport's HTTP transport test with it).
    """
    from thomas.core import llm_transport_pool

    took: list[str] = []

    async def cli(owner, messages, tools=None):  # noqa: ANN001, ARG001
        took.append("the Claude CLI")

        async def stream() -> Any:
            yield StreamEvent(type="done")

        return stream()

    async def api(messages, tools=None):  # noqa: ANN001, ARG001
        took.append("Anthropic's API")
        yield StreamEvent(type="done")

    llm = LLMClient(plan_profile(model=model))
    monkeypatch.setattr(llm_transport_pool, "stream_claude_cli", cli)
    monkeypatch.setattr(llm, "_stream_anthropic", api)

    async def go() -> None:
        async for _ in llm_transport_pool.stream_current_provider(llm, [{"role": "user", "content": "hi"}]):
            pass

    asyncio.run(go())
    assert took == [engine], f"{model} must be answered by {engine}"


def test_the_other_half_of_that_routing_is_not_blamed_on_your_chatgpt_signin() -> None:
    """The API refusal above has to read as itself.

    A keyless Anthropic profile on a versioned model reaches Anthropic's API and is
    refused there for want of a key -- "Anthropic HTTP 401: ...". Chat answered every
    401 with "Your ChatGPT sign-in has expired ... Run `codex login`", which names a
    different product and a command that cannot touch this. A 401 that names nobody
    must not be attributed to a specific login without checking the live login.
    """
    body = '{"type":"error","error":{"type":"authentication_error","message":"x-api-key header is required"}}'
    text = _chat_failure_message(reasoning_failed(f"Anthropic HTTP 401: {body}"))

    assert "Anthropic's API refused this request as unauthorized" in text
    assert "codex login` cannot fix it" in text and "ChatGPT sign-in has expired" not in text
    assert "switch to your Claude plan (Claude Opus, Sonnet or Haiku in the model menu)" in text
    assert "codex login" not in _chat_failure_message(reasoning_failed("HTTP 401 Unauthorized"))


def test_an_anthropic_key_refusal_does_not_make_health_report_your_chatgpt_signin() -> None:
    """The same mistake as above, one surface over.

    An Anthropic 401 and an unattributed access-token 401 do not establish a
    rejection of the live Codex login. A refresh-token 401 does.
    """
    from thomas.core.model_auth_health import model_auth_health, record_auth_success

    rejected = "Your ChatGPT sign-in was rejected"
    body = '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}'
    try:
        record_auth_success()
        _chat_failure_message(reasoning_failed(f"Anthropic HTTP 401: {body}"))
        assert rejected not in str(model_auth_health(None).get("reason") or "")

        _chat_failure_message(reasoning_failed("ChatGPT/Codex HTTP 401: The stored token was revoked"))
        health = model_auth_health(None)
        assert rejected not in str(health.get("reason") or "")

        _chat_failure_message(reasoning_failed("Token refresh failed with HTTP 401"))
        assert model_auth_health(None)["ok"] is False
        record_auth_success()

        _chat_failure_message(
            reasoning_failed("ChatGPT/Codex HTTP 401: The live Codex login was revoked or invalidated")
        )
        health = model_auth_health(None)
        assert health["ok"] is False
        assert health["reason"] == f"{rejected}, so no model can be reached."
        assert health["remedy"] == "Run `codex login` in a terminal to sign in again."
    finally:
        record_auth_success()


def test_the_plan_offers_exactly_the_models_it_will_run() -> None:
    """What the menu lists for this profile and what the transport accepts are one list."""
    assert tuple(alias.id for alias in claude_cli_aliases()) == CLAUDE_PLAN_MODEL_IDS
    assert all(chose_claude_plan("anthropic", "", name) for name in CLAUDE_PLAN_MODEL_IDS)
    assert chose_claude_plan("anthropic", "sk-ant-1", "sonnet") is False, "a key means Anthropic's API"
    assert chose_claude_plan("anthropic", "", "claude-sonnet-4-5-20250929") is False


def test_no_test_can_start_the_real_claude_program() -> None:
    """The default spawn is replaced for the whole run (tests/conftest.py).

    A test of this path drives the protocol through an injected ``spawn``; one
    that reaches the default would sign in as you, spend your plan's allowance
    and wait on a real model. It fails instead, naming what to do.
    """
    llm = LLMClient(plan_profile())

    async def go() -> None:
        async for _ in stream_claude_cli(llm, [{"role": "user", "content": "hi"}], None, cli_path="claude.cmd"):
            pass

    with pytest.raises(AssertionError, match="tried to start the real Claude CLI"):
        asyncio.run(go())
