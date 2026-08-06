"""A Code turn must name the engine that actually produced it.

Code has exactly two executors. `forge_code_settings.from_payload`::

    gpt = id.startswith("gpt-") or model.startswith(("gpt-", "codex", ...))
    if gpt:  family "gpt"    -> in-process ChatGPT via openai_codex
    else:    family "claude" -> the claude CLI subprocess

and the shell feeds it (`unified_code_lifecycle.js`)::

    model:    modelId.startsWith('gpt-') ? modelId : 'claude:sonnet',
    model_id: modelId,

so picking a local qwen, a Gemini or a Mistral in the Code model menu runs the
Claude CLI. That is a real product limit and this test does not argue with it.

What it pins is the REPORT. Both turn-recording call sites in
``evolve_agent_routes`` passed ``settings.model_id or settings.dispatch_model``
-- the owner's pick winning over the executor -- and ``capability_report``
reported the same value with ``status: "applied"``. Observed live on this
machine: active profile ``Local``, ``model_id`` empty, a turn labelled
``qwen2.5-coder:7b``, and a transcript ending ``claude exited 1`` because the
Claude CLI is not logged in here. A model that had no part in the run was named
as its author, and the failure was attributed to it.

The module docstring says it "preserves every requested dial while separately
reporting which values the current executor applies, fixes to a safe value, or
cannot honor". For the model dial it did the opposite.

Nothing about what RUNS changes here -- only what Thomas says ran. The other
half of the trap, inventing ``claude:sonnet`` when the caller sent no model at
all, was closed 2026-08-05 after it bit live (chip on GPT-5.6 Terra, dispatch
to an unauthenticated Claude CLI): an empty request now resolves the server's
configured default, or fails before dispatch. That path is pinned in
``test_an_unselected_model_never_silently_becomes_claude.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_settings
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings

ROOT = Path(__file__).resolve().parents[1]

# The live drift state, reproduced exactly: the shell sends its `claude:sonnet`
# placeholder for anything non-GPT, and the owner's actual pick in `model_id`.
DRIFTED = {"model": "claude:sonnet", "model_id": "qwen2.5-coder:7b"}


def test_a_rerouted_request_is_not_labelled_with_the_model_it_did_not_use() -> None:
    settings = ForgeCodeSettings.from_payload(DRIFTED)

    assert settings.family == "claude", "precondition: a non-GPT model routes to the Claude CLI"
    recorded = settings.recorded_model()
    assert recorded != "qwen2.5-coder:7b", (
        "the turn is still labelled with the model the owner picked rather than "
        "the executor that ran. That model had no part in the run, and any "
        "failure in it gets attributed to a model that never executed."
    )
    assert recorded.startswith("claude"), (
        f"the recorded model {recorded!r} does not name the executor that ran"
    )


def test_the_report_says_the_model_was_substituted_not_applied() -> None:
    support = ForgeCodeSettings.from_payload(DRIFTED).capability_report()["support"]["model"]

    assert support["status"] == "substituted", (
        f"the model dial reports {support['status']!r}. 'applied' asserts the "
        "requested model was honoured; the Claude CLI ran instead."
    )
    assert support.get("requested") == "qwen2.5-coder:7b", (
        "the report no longer preserves what was actually asked for, so the "
        "owner cannot see that a substitution happened"
    )
    assert "reason" in support and "Claude" in support["reason"], (
        "a substituted model is reported without saying why or what ran instead"
    )


def test_a_genuine_claude_request_is_still_applied() -> None:
    """The opposite failure: marking every Claude run a substitution.

    Someone who asks for Claude gets Claude. Nothing was substituted and the
    report must not imply it was.
    """

    for payload in ({"model": "claude:opus"}, {"model": "claude:sonnet", "model_id": "sonnet"}):
        report = ForgeCodeSettings.from_payload(payload).capability_report()
        assert report["support"]["model"]["status"] == "applied", (
            f"{payload} is a genuine Claude request but reports "
            f"{report['support']['model']['status']!r}"
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
        assert "Claude" not in str(support), (
            f"{name!r} names the Claude CLI, which had no part in this request"
        )


def test_gpt_keeps_its_exact_model() -> None:
    """The forgecode profile really is pinned to that model, so it may claim it."""

    settings = ForgeCodeSettings.from_payload({"model_id": "gpt-5.6-terra"})
    assert settings.family == "gpt"
    assert settings.recorded_model() == "gpt-5.6-terra"
    assert settings.capability_report()["support"]["model"]["status"] == "applied"


def test_a_model_merely_containing_a_claude_name_is_not_treated_as_claude() -> None:
    """`octopus-7b` contains "opus". A substring test would clear it wrongly."""

    settings = ForgeCodeSettings.from_payload({"model": "claude:sonnet", "model_id": "octopus-7b"})
    assert settings.capability_report()["support"]["model"]["status"] == "substituted"


def test_both_turn_recorders_use_the_honest_accessor() -> None:
    """The label is written in two places, and they must not drift apart.

    One is the normal path and one is the cancellation/error path; fixing only
    the first would leave every interrupted run mislabelled.
    """

    source = (ROOT / "thomas" / "server" / "routes" / "evolve_agent_routes.py").read_text(
        encoding="utf-8"
    )
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
