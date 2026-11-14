"""A usage limit says which limit, when it resets, and what you can use instead.

You asked for this on 2026-09-24, after Chat answered a meal-prep question with
"The selected model is temporarily rate-limited. Please wait a moment or choose
another model": "The limit lasts until Saturday morning, not a moment, and there
was no other model I could choose. Tell me the truth when that happens: which
limit, when it resets, and what I can use instead."

Every surface that speaks about a limit is held to that here — the chat message,
the park between you and the provider, the task loop, the composer's line and the
sentence that names the way out. Chat answering on your Claude plan at all is
proved in ``tests/test_chat_runs_on_your_claude_plan.py``; the fakes both suites
drive are in ``tests/_claude_plan_fakes.py``. The ChatGPT 429 is the exact string
``llm_streaming.py`` raises, and nothing about the chat turn, the model catalog or
Autopilot's pause is stubbed.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests._claude_plan_fakes import (
    AHEAD_S,
    SESSION_LIMIT,
    THROTTLED,
    chatgpt_plan_limit,
    limit_event,
    no_refusals_between_tests,  # noqa: F401  (autouse: a refusal outlives the test that set it)
    plan_profile,
    reasoning_failed,
    result_line,
    run_cli,
    spawner,
    text_line,
)
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.llm import LLMClient
from thomas.core.llm_shared import LLMError
from thomas.core.provider_limits import read_limit, when_words
from thomas.marketplace.orchestrator.response_failures import _chat_failure_message
from thomas.models import catalog
from thomas.models.ready_elsewhere import models_ready_elsewhere

# --- the limit, told truthfully ---------------------------------------------------


def test_your_chatgpt_plan_limit_names_the_limit_its_reset_and_the_way_round_it() -> None:
    """The message you were given was "temporarily rate-limited ... wait a moment or choose
    another model", on a limit with a day and a half left and no other model to choose."""
    resets_at = int(time.time()) + AHEAD_S
    failed = reasoning_failed(chatgpt_plan_limit(resets_at))

    text = _chat_failure_message(failed, alternatives=("Claude Sonnet (newest)", "Qwen2.5 Coder"))

    when = datetime.fromtimestamp(resets_at)
    assert "Your ChatGPT Pro plan has reached its usage limit" in text
    assert f"it resets {when:%A} {when.day} {when:%B} at {when:%H:%M}" in text
    assert "This is not a wait of moments." in text
    assert "Claude Sonnet (newest) or Qwen2.5 Coder" in text and "model menu" in text
    assert "wait a moment" not in text


def test_with_nothing_else_signed_in_it_says_that_instead_of_offering_a_choice() -> None:
    text = _chat_failure_message(reasoning_failed(chatgpt_plan_limit(int(time.time()) + AHEAD_S)), alternatives=())
    assert "No other model on this machine is ready" in text
    assert "signing in to the Claude CLI" in text


def test_the_next_message_on_the_same_limit_is_told_the_same_truth() -> None:
    """The park between you and the provider must not swallow the limit.

    The first 429 parks the profile (``thomas/core/llm_client.py``), and from then on
    the park refuses the turn before the provider is asked again. It lasts ten minutes
    at most and your plan's limit lasted a day and a half, so every message after the
    first was answered out of a sentence that names no limit and no reset -- "wait a
    moment", the words you were given. The park now repeats what the provider said.
    """
    resets_at = int(time.time()) + AHEAD_S
    profile = plan_profile(name="chatgpt-under-test", provider="openai_codex", api_key="k")
    llm = LLMClient(profile)
    # Exactly what the transport does on the 429 it raises (thomas/core/llm_streaming.py).
    llm._mark_rate_limited(profile, None, chatgpt_plan_limit(resets_at))

    async def go() -> None:
        async for _ in llm.stream_chat([{"role": "user", "content": "a meal-prep plan?"}]):
            pass

    with pytest.raises(LLMError) as raised:
        asyncio.run(go())

    assert "Rate-limit cooldown active" in str(raised.value), "the park refused this turn, not ChatGPT"
    said = _chat_failure_message(reasoning_failed(str(raised.value)), alternatives=("Local",))
    when = datetime.fromtimestamp(resets_at)
    assert "Your ChatGPT Pro plan has reached its usage limit" in said
    assert f"it resets {when:%A} {when.day} {when:%B} at {when:%H:%M}" in said
    assert "I can answer on Local meanwhile" in said
    assert "said nothing about which limit" not in said


def test_a_park_that_remembers_nothing_still_claims_nothing() -> None:
    """A profile parked with no refusal kept (a server-failure park, an older process)
    must not invent a limit: the text stays the one the park has always had."""
    profile = plan_profile(name="parked-without-words")
    llm = LLMClient(profile)
    llm._mark_rate_limited(profile, 45.0)
    text = llm._parked_text(profile, 45.0)
    parked = llm._parked_error(profile, 45.0)

    assert text == "Rate-limit cooldown active for profile 'parked-without-words' (45s remaining)."
    assert parked.error_code == "" and parked.quota_hint is False, "a park with no words claims no usage limit"


def test_a_parked_plan_limit_is_not_a_pause_work_resumes_after() -> None:
    """The park must not tell a task that the wait is seconds long.

    A 429 with no quota hint is sat out by the agent loop
    (``thomas/agent/loop_execution.py``), which says "the provider asked Thomas to pause
    for 5.0s; work will resume automatically" and then asks again -- the same "wait a
    moment" you were given, in another voice, on a limit with a day and a half to run.
    The park now hands back the code and reset the provider's refusal carried, so a
    spent allowance is reported instead of slept through. A burst is still slept through
    (the test above: nothing remembered, nothing claimed).
    """
    profile = plan_profile(name="chatgpt-parked-plan", provider="openai_codex", api_key="k")
    llm = LLMClient(profile)
    llm._mark_rate_limited(profile, None, chatgpt_plan_limit(int(time.time()) + AHEAD_S))
    parked = llm._parked_error(profile, 540.0)

    assert parked.status == 429
    assert parked.error_code == "usage_limit_reached"
    assert parked.quota_hint is True, "the loop would have called a day-and-a-half limit a pause of seconds"
    assert read_limit(str(parked), at=time.time()) is not None, "Autopilot's pause reads the park's words too"


def test_a_short_burst_is_still_called_a_short_burst() -> None:
    burst = 'Anthropic HTTP 429 rate limited. Retry after about 20s. {"error":{"type":"rate_limit_error"}}'
    text = _chat_failure_message(reasoning_failed(burst), alternatives=("Local",))
    assert "short burst limit, not a usage limit" in text
    assert "clears in about 20s" in text
    assert "usage limit —" not in text


def test_your_claude_plans_limit_is_read_the_same_way_in_chat() -> None:
    """The CLI's refusal, through the transport, worded so every surface reads one limit."""
    resets_at = int(time.time()) + 3 * 3600
    with pytest.raises(LLMError) as raised:
        run_cli(
            [limit_event(resets_at), text_line(SESSION_LIMIT), result_line(SESSION_LIMIT, is_error=True, status=429)]
        )

    error = raised.value
    assert error.status == 429 and error.retryable is False, "the allowance is spent; retrying cannot pass"
    assert error.error_code == "usage_limit_reached" and error.quota_hint is True
    limit = read_limit(str(error), at=time.time())
    assert limit is not None and limit.account == "Claude" and int(limit.resets_at or 0) == resets_at
    said = _chat_failure_message(reasoning_failed(str(error)), alternatives=("GPT-5.6 Sol",))
    assert "Your Claude plan has reached its usage limit" in said and "GPT-5.6 Sol" in said


def test_your_claude_plans_limit_parks_the_plan_the_way_every_other_engine_does(tmp_path: Path) -> None:
    """The park is how every surface but the chat message learns a limit happened.

    The three HTTP transports hand their 429 to the park as well as raising it; the
    Claude CLI was the one engine that did not. So a Claude plan limit left the
    countdown under the composer blank, and left the way-out sentence free to go on
    offering the plan that had just refused the turn. Chat's own text was true and
    nothing else knew anything.
    """
    from thomas.core.provider_cooldowns import active_cooldowns

    resets_at = int(time.time()) + 3 * 3600
    with pytest.raises(LLMError):
        run_cli([limit_event(resets_at), result_line(SESSION_LIMIT, is_error=True, status=429)])

    rows = {str(row["profile"]): row for row in active_cooldowns()}
    assert "anthropic" in rows, "your Claude plan refused a turn and nothing recorded it"
    assert rows["anthropic"]["account"] == "Claude" and rows["anthropic"]["spent"] is True
    assert rows["anthropic"]["resets_words"] == when_words(resets_at), "the composer line names the reset"

    config = AppConfig(
        models={"anthropic": plan_profile(), "local": ModelConfig(name="local", provider="ollama", model="qwen")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    catalog.save_model_catalog(
        config,
        {
            "schema_version": catalog.CATALOG_SCHEMA_VERSION,
            "providers": {"anthropic": {"checked_at": "now"}},
            "models": [{"profile": "anthropic", "id": "sonnet", "display_name": "Claude Sonnet (newest)"}],
        },
    )
    assert models_ready_elsewhere(config, besides="local") == (), "the plan that just refused is not the way out"


def test_claudes_short_lived_throttling_is_not_called_your_plans_limit() -> None:
    with pytest.raises(LLMError) as raised:
        run_cli([text_line(THROTTLED), result_line(THROTTLED, is_error=True, status=429)])
    assert raised.value.retryable is True and raised.value.error_code == ""
    assert "short burst limit" in _chat_failure_message(reasoning_failed(str(raised.value)))


def test_autopilots_pause_reads_the_same_reader_and_is_unchanged() -> None:
    """quota_pause now reads thomas/core/provider_limits.py; its verdict must not have moved."""
    from thomas.server import autopilot_park

    resets_at = int(time.time()) + AHEAD_S
    failed_at = datetime.now(timezone.utc).isoformat()
    turn = {"ok": False, "reason": chatgpt_plan_limit(resets_at), "transcript": "", "ts": failed_at}

    pause = autopilot_park.quota_pause(turn)

    assert pause is not None
    assert (pause.provider, pause.reset_known, pause.estimated) == ("ChatGPT Pro", True, False)
    assert int(pause.retry_at) == resets_at
    assert autopilot_park.paused_text(pause).startswith("Paused: your ChatGPT Pro usage limit is reached. It resets ")


# --- what you can use instead is read from what actually answered -----------------


def test_the_models_offered_instead_are_the_ones_that_answered_last_check(tmp_path: Path) -> None:
    config = AppConfig(
        models={"anthropic": plan_profile(), "local": ModelConfig(name="local", provider="ollama", model="qwen")},
        default_model="anthropic",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    catalog.save_model_catalog(
        config,
        {
            "schema_version": catalog.CATALOG_SCHEMA_VERSION,
            "providers": {"anthropic": {"checked_at": "now"}, "local": {"checked_at": "now"}, "gemini": {"error": "x"}},
            "models": [
                {"profile": "anthropic", "id": "sonnet", "display_name": "Claude Sonnet (newest)"},
                {"profile": "local", "id": "qwen", "display_name": "Qwen"},
                {"profile": "local", "id": "hidden-one", "display_name": "Hidden", "hidden": True},
                {"profile": "gemini", "id": "gemini-3", "display_name": "Gemini 3"},
            ],
        },
    )

    assert models_ready_elsewhere(config, besides="local") == ("Claude Sonnet (newest)",)
    assert models_ready_elsewhere(config, besides="anthropic") == ("Qwen",), "a failed check is not an alternative"


def _two_plan_config(tmp_path: Path, chatgpt: ModelConfig) -> AppConfig:
    """Your Claude plan and your ChatGPT plan, with only ChatGPT's model in the catalog."""
    config = AppConfig(
        models={"anthropic": plan_profile(), "chatgpt": chatgpt},
        default_model="anthropic",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    catalog.save_model_catalog(
        config,
        {
            "schema_version": catalog.CATALOG_SCHEMA_VERSION,
            "providers": {"anthropic": {"checked_at": "now"}, "chatgpt": {"checked_at": "now"}},
            "models": [{"profile": "chatgpt", "id": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol"}],
        },
    )
    return config


def test_a_plan_that_is_out_of_allowance_is_not_offered_as_the_way_out(tmp_path: Path) -> None:
    """The next limit must not send you back to the limit you started from.

    Listing a connection's models costs no allowance, so your ChatGPT plan answers
    the catalog's check all the way through a limit that runs until Saturday. If
    your Claude plan then refuses a turn, the way-out sentence would have named
    ChatGPT: "there was no other model I could choose", one limit later. The park
    the first refusal set is what knows better, and is read here.
    """
    from thomas.core import llm_client

    chatgpt = plan_profile(name="chatgpt", provider="openai_codex", api_key="k", model="gpt-5.6-sol")
    config = _two_plan_config(tmp_path, chatgpt)
    llm = LLMClient(chatgpt)
    llm._mark_rate_limited(chatgpt, None, chatgpt_plan_limit(int(time.time()) + AHEAD_S))

    assert models_ready_elsewhere(config, besides="anthropic") == (), "a spent ChatGPT plan was offered as the way out"

    llm_client._PROVIDER_COOLDOWNS.pop("chatgpt", None)  # the plan answered again, and the park was cleared
    assert models_ready_elsewhere(config, besides="anthropic") == ("GPT-5.6 Sol",), "and is offered again once free"


def test_a_spent_plan_stays_off_the_list_after_its_ten_minute_park_lifts(tmp_path: Path) -> None:
    """The park is the wrong clock for "is this account out of allowance?".

    A rate-limit park is capped at ten minutes (``llm_provider_state.py``) and the
    limit you met ran 41 hours, so read on the park alone the way-out sentence named
    your spent ChatGPT plan again eleven minutes later: "there was no other model I
    could choose", once more. The question is asked with the reset the provider gave
    as its lifetime, and only until then — the park's record outlives the park.
    """
    from thomas.core import llm_client
    from thomas.core.provider_cooldowns import active_cooldowns, spent_allowances

    chatgpt = plan_profile(name="chatgpt", provider="openai_codex", api_key="k", model="gpt-5.6-sol")
    config = _two_plan_config(tmp_path, chatgpt)
    llm = LLMClient(chatgpt)
    llm._mark_rate_limited(chatgpt, None, chatgpt_plan_limit(int(time.time()) + AHEAD_S))
    # Eleven minutes later: the park is over, the allowance has 36 hours left to run.
    llm_client._PROVIDER_COOLDOWNS["chatgpt"].until = time.monotonic() - 1

    assert active_cooldowns() == [], "the park itself has lifted, which is what it is capped to do"
    assert set(spent_allowances()) == {"chatgpt"}
    assert models_ready_elsewhere(config, besides="anthropic") == (), "a spent plan was offered again"

    # Saturday morning: the reset the provider gave has passed, and it is offered again.
    # Written out rather than reusing chatgpt_plan_limit, whose body also carries a
    # relative "resets_in_seconds" that would still be counting 36 hours forward.
    body = {"error": {"type": "usage_limit_reached", "resets_at": int(time.time()) - 30}}
    llm._mark_rate_limited(chatgpt, None, f"ChatGPT/Codex HTTP 429 rate limited. {json.dumps(body)}")
    llm_client._PROVIDER_COOLDOWNS["chatgpt"].until = time.monotonic() - 1
    assert spent_allowances() == {}
    assert models_ready_elsewhere(config, besides="anthropic") == ("GPT-5.6 Sol",)


def test_a_burst_park_is_not_read_as_a_spent_allowance(tmp_path: Path) -> None:
    """A short burst, and a park that remembers nothing, name no reset to wait for.

    Keeping either of them off the list past the park would hide a model that can
    answer — the mirror of the failure above, and just as false a statement about
    what you can use.
    """
    from thomas.core import llm_client
    from thomas.core.provider_cooldowns import spent_allowances

    chatgpt = plan_profile(name="chatgpt", provider="openai_codex", api_key="k", model="gpt-5.6-sol")
    config = _two_plan_config(tmp_path, chatgpt)
    llm = LLMClient(chatgpt)
    burst = 'ChatGPT/Codex HTTP 429 rate limited. Retry after about 20s. {"error":{"type":"rate_limit_error"}}'
    for refusal in (burst, ""):
        llm._mark_rate_limited(chatgpt, None, refusal)
        llm_client._PROVIDER_COOLDOWNS["chatgpt"].until = time.monotonic() - 1
        assert spent_allowances() == {}, refusal or "a park with no words"
        assert models_ready_elsewhere(config, besides="anthropic") == ("GPT-5.6 Sol",)


def test_a_claude_plan_with_no_signin_is_not_offered_as_the_way_out(tmp_path: Path) -> None:
    """The one connection whose catalog check asks it nothing.

    Listing your Claude plan's models is a constant -- opus, sonnet, haiku
    (``thomas/models/sources/claude_cli.py``) -- so the catalog calls it ready
    wherever the CLI is installed, signed in or not, while every other connection's
    check spends its credential and records the refusal. A ChatGPT limit would then
    have answered "I can answer on Claude Sonnet (newest) meanwhile" and sent you to
    a model with no sign-in behind it: "there was no other model I could choose", in
    another provider's name. The CLI's own refusal is what says otherwise, and it is
    forgotten as soon as the plan answers.
    """
    config = AppConfig(
        models={"anthropic": plan_profile(), "local": ModelConfig(name="local", provider="ollama", model="qwen")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    catalog.save_model_catalog(
        config,
        {
            "schema_version": catalog.CATALOG_SCHEMA_VERSION,
            "providers": {"anthropic": {"checked_at": "now"}},
            "models": [{"profile": "anthropic", "id": "sonnet", "display_name": "Claude Sonnet (newest)"}],
        },
    )
    assert models_ready_elsewhere(config, besides="local") == ("Claude Sonnet (newest)",)

    with pytest.raises(LLMError) as raised:
        run_cli([result_line("Invalid API key · Please run /login", is_error=True)])
    assert raised.value.status == 401 and "isn't signed in on this machine" in str(raised.value)
    assert models_ready_elsewhere(config, besides="local") == (), "a plan with no sign-in cannot answer either"

    run_cli([result_line("Signed in now, and here is your answer.")])
    assert models_ready_elsewhere(config, besides="local") == ("Claude Sonnet (newest)",), "a sign-in needs no restart"


def test_a_plan_that_answers_again_stops_being_called_out_of_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reset a refusal named is a claim, and answering is what disproves it.

    A spent allowance is now reported until that reset rather than until the park
    lifts, so something has to end it early when the plan comes back before then --
    and it does come back before then: a reset read from the CLI's words is put an
    hour late on purpose when the zone cannot be read
    (``claude_plan._ZONE_MARGIN_S``), and a provider can lift a limit whenever it
    likes. The park was only ever cleared on the failover loop's success, and one
    plan picked in the model menu has no fallbacks to fail over to, so it went
    through the other branch and nothing cleared it. The composer's line would have
    gone on saying "Claude has reached its usage limit" above the answer it had
    just given, and the way-out sentence would have gone on hiding a model that
    could answer -- the same falsehood as offering one that cannot, facing the
    other way.
    """
    from thomas.core import llm_client, llm_streaming_claude_cli
    from thomas.core.provider_cooldowns import limit_rows, spent_allowances

    config = AppConfig(
        models={"anthropic": plan_profile(), "local": ModelConfig(name="local", provider="ollama", model="qwen")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    catalog.save_model_catalog(
        config,
        {
            "schema_version": catalog.CATALOG_SCHEMA_VERSION,
            "providers": {"anthropic": {"checked_at": "now"}},
            "models": [{"profile": "anthropic", "id": "sonnet", "display_name": "Claude Sonnet (newest)"}],
        },
    )
    with pytest.raises(LLMError):
        run_cli([limit_event(int(time.time()) + 3 * 3600), result_line(SESSION_LIMIT, is_error=True, status=429)])
    assert set(spent_allowances()) == {"anthropic"} and models_ready_elsewhere(config, besides="local") == ()

    # Ten minutes on: the park has lifted and the reset it named is two hours off.
    llm_client._PROVIDER_COOLDOWNS["anthropic"].until = time.monotonic() - 1
    assert [row["profile"] for row in limit_rows()] == ["anthropic"], "the allowance is still claimed to be out"

    # The plan answers, through the whole client rather than the transport alone:
    # LLMClient.stream_chat -> llm_transport_pool -> stream_claude_cli, with only
    # the process faked. This profile has no fallbacks, so it takes the branch that
    # never cleared the park.
    seen: dict[str, Any] = {}
    monkeypatch.setattr(llm_streaming_claude_cli, "claude_cli_path", lambda: "claude.cmd")
    monkeypatch.setattr(
        llm_streaming_claude_cli,
        "_spawn",
        spawner([text_line("Here is a meal-prep plan."), result_line("Here is a meal-prep plan.")], seen),
    )
    llm = LLMClient(plan_profile())

    async def ask() -> None:
        async for _ in llm.stream_chat([{"role": "user", "content": "a meal-prep plan?"}]):
            pass

    asyncio.run(ask())

    assert seen.get("command"), "the turn never reached the CLI, so it proves nothing about answering"
    assert spent_allowances() == {}, "your plan answered and was still called out of allowance"
    assert limit_rows() == [], "the line under the composer would have named a limit that was over"
    assert models_ready_elsewhere(config, besides="local") == ("Claude Sonnet (newest)",)


def test_a_model_the_menu_will_not_show_is_not_offered_either(tmp_path: Path) -> None:
    """Your Claude plan declares one of Anthropic's versioned ids and offers opus,
    sonnet and haiku. The menu lists the three it offered (chat_model_picker.js), so
    naming the declared id would name something you cannot pick — and something that
    would go to Anthropic's API, which has no key here. A connection that listed
    nothing is still named by its declared model, which is what the menu shows then.
    """
    declared = {"profile": "anthropic", "id": "claude-sonnet-4-5-20250929", "display_name": "Claude Sonnet 4 5",
                "source": "config"}  # fmt: skip
    live = {"profile": "anthropic", "id": "sonnet", "display_name": "Claude Sonnet (newest)", "source": "live"}
    config = AppConfig(
        models={"anthropic": plan_profile(model="claude-sonnet-4-5-20250929")},
        default_model="anthropic",
        memory=MemoryConfig(root=str(tmp_path)),
    )

    def _offered(rows: list[dict[str, Any]]) -> tuple[str, ...]:
        catalog.save_model_catalog(
            config,
            {
                "schema_version": catalog.CATALOG_SCHEMA_VERSION,
                "providers": {"anthropic": {"checked_at": "now"}},
                "models": rows,
            },
        )
        return models_ready_elsewhere(config, besides="local")

    assert _offered([declared, live]) == ("Claude Sonnet (newest)",)
    assert _offered([declared]) == ("Claude Sonnet 4 5",)


def test_no_catalog_offers_nothing_rather_than_guessing(tmp_path: Path) -> None:
    config = AppConfig(models={"local": ModelConfig(name="local", provider="ollama", model="qwen")},
                       default_model="local", memory=MemoryConfig(root=str(tmp_path)))  # fmt: skip
    assert models_ready_elsewhere(config, besides="") == ()
