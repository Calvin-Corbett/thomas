"""A Code turn must name the model that actually produced it.

Build now refuses unsupported models before dispatch, including legacy payloads
that pair a Claude placeholder with a foreign model id. The historical reroute
fixture constructs that older settings state directly so attribution remains
covered without requiring the parser to silently substitute models again.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_settings
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError

ROOT = Path(__file__).resolve().parents[1]

DRIFTED = {"model": "claude:sonnet", "model_id": "qwen2.5-coder:7b"}


def _historical_rerouted_settings(model_id: str = DRIFTED["model_id"]) -> ForgeCodeSettings:
    """Construct the old rerouted state without bypassing validation for new runs."""
    settings = ForgeCodeSettings.from_payload({"model": "claude:sonnet", "agent": "claude_code"})
    return replace(settings, model_id=model_id)


def test_a_new_foreign_model_request_is_refused_before_it_can_be_mislabelled() -> None:
    with pytest.raises(ForgeCodeSettingsError, match="qwen2.5-coder:7b.*the selected model"):
        ForgeCodeSettings.from_payload(DRIFTED)


def test_a_rerouted_request_is_not_labelled_with_the_model_it_did_not_use() -> None:
    settings = _historical_rerouted_settings()

    assert settings.family == "claude", "precondition: the historical run used the Claude CLI"
    recorded = settings.recorded_model()
    assert recorded != "qwen2.5-coder:7b", (
        "the turn is still labelled with the model the owner picked rather than "
        "the executor that ran. That model had no part in the run, and any "
        "failure in it gets attributed to a model that never executed."
    )
    assert recorded.startswith("claude"), f"the recorded model {recorded!r} does not name the executor that ran"


@pytest.mark.parametrize("model_id", ["qwen2.5-coder:7b", "octopus-7b"])
def test_a_new_request_cannot_recreate_a_historical_reroute(model_id: str) -> None:
    with pytest.raises(ForgeCodeSettingsError, match=re.escape(model_id)):
        ForgeCodeSettings.from_payload({"model": "claude:sonnet", "model_id": model_id})


def test_the_report_says_the_model_was_substituted_not_applied() -> None:
    settings = _historical_rerouted_settings("qwen2.5-coder:7b")
    report = settings.capability_report()
    support = report["support"]["model"]

    assert support["status"] == "substituted", (
        f"the model dial reports {support['status']!r}. 'applied' asserts the "
        "requested model was honoured; the Claude CLI ran instead."
    )
    assert support.get("requested") == "qwen2.5-coder:7b", (
        "the report no longer preserves what was actually asked for, so the "
        "owner cannot see that a substitution happened"
    )
    assert support["effective"] == report["effective"]["model"] == settings.recorded_model() == "claude:sonnet", (
        "the substitution report must attribute the run to the Claude model that actually ran"
    )
    assert "reason" in support and "Claude" in support["reason"], (
        "a substituted model is reported without saying why or what ran instead"
    )
    assert support["requested"] in support["reason"] and support["effective"] in support["reason"], (
        "the substitution reason must name both the requested model and its replacement"
    )


def test_a_genuine_claude_request_is_still_applied() -> None:
    """The opposite failure: marking every Claude run a substitution.

    Someone who asks for Claude gets Claude. Nothing was substituted and the
    report must not imply it was.
    """

    for payload in ({"model": "claude:opus"}, {"model": "claude:sonnet", "model_id": "sonnet"}):
        report = ForgeCodeSettings.from_payload(payload).capability_report()
        assert report["support"]["model"]["status"] == "applied", (
            f"{payload} is a genuine Claude request but reports {report['support']['model']['status']!r}"
        )


def test_an_unselected_model_is_not_reported_as_a_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    """No choice was made, so no choice was overridden.

    An empty request no longer invents ``claude:sonnet``; it resolves the
    server's configured default. When that default is a model Code really runs
    (Claude here), nothing was substituted -- the report says the model came
    from configuration, and the recorded model names what ran.
    """

    monkeypatch.setattr(forge_code_settings, "_configured_default_model", lambda: "claude:sonnet")
    settings = ForgeCodeSettings.from_payload({})
    assert settings.capability_report()["support"]["model"]["status"] == "configured_default"
    assert settings.recorded_model() == "claude:sonnet"


def test_a_codex_shaped_request_is_not_blamed_on_the_claude_cli() -> None:
    """A regression this file's own first version introduced, found by audit.

    `runs_requested_model` returned `bool(self.model_id)` for the GPT family. But
    `from_payload` also routes `codex`, `chatgpt` and `openai_codex` to that
    family, and none of them start with `gpt-`, so `model_id` is empty and every
    one of them reported::

        status: substituted
        reason: ... 'codex' is neither, so the Claude CLI handled this request.

    The Claude CLI handled nothing -- the in-process ChatGPT path did. The label
    before that change, "configured_default", was true. Replacing a true label
    with a false sentence is precisely what this module is supposed to stop.

    Whether an exact model was pinned is a separate question, and
    `capability_report` already answers it through `exact_gpt`.
    """

    for name in ("codex", "chatgpt", "openai_codex"):
        settings = ForgeCodeSettings.from_payload({"model": name})
        assert settings.family == "gpt", f"{name!r} should route to the GPT executor"
        support = settings.capability_report()["support"]["model"]
        assert support["status"] == "configured_default", (
            f"{name!r} runs on the GPT path but reports {support['status']!r}"
        )
        assert "reason" not in support, (
            f"{name!r} carries a substitution reason: {support.get('reason')!r}. "
            "Nothing was substituted -- a GPT request was handled by the GPT executor."
        )
        assert "Claude" not in str(support), f"{name!r} names the Claude CLI, which had no part in this request"


def test_gpt_keeps_its_exact_model() -> None:
    """The forgecode profile really is pinned to that model, so it may claim it."""

    settings = ForgeCodeSettings.from_payload({"model_id": "gpt-5.6-terra"})
    assert settings.family == "gpt"
    assert settings.recorded_model() == "gpt-5.6-terra"
    assert settings.capability_report()["support"]["model"]["status"] == "applied"


def test_a_model_merely_containing_a_claude_name_is_not_treated_as_claude() -> None:
    """`octopus-7b` contains "opus". A substring test would clear it wrongly."""

    settings = _historical_rerouted_settings("octopus-7b")
    assert settings.capability_report()["support"]["model"]["status"] == "substituted"


def test_both_turn_recorders_use_the_honest_accessor() -> None:
    """The label is written in two places, and they must not drift apart.

    One is the normal path and one is the cancellation/error path; fixing only
    the first would leave every interrupted run mislabelled.
    """

    source = (ROOT / "thomas" / "server" / "routes" / "evolve_agent_routes.py").read_text(encoding="utf-8")
    stale = re.findall(r"settings\.model_id\s+or\s+settings\.dispatch_model", source)
    assert not stale, (
        f"{len(stale)} turn recorder(s) still pass `settings.model_id or "
        "settings.dispatch_model`, which labels the run with the owner's pick "
        "rather than the executor that ran"
    )
    assert source.count("settings.recorded_model()") >= 2, (
        "fewer than two call sites use recorded_model(); the normal path and "
        "the cancellation path both record a turn and both need it"
    )
