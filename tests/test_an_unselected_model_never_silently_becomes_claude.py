"""An EMPTY model must never silently become ``claude:sonnet``.

Measured 2026-08-05, code-network scenario: the model chip read **GPT-5.6
Terra**, OpenAI had 4 ready keys — and the run was dispatched to an
unauthenticated ``claude:sonnet``, dying in 15s with the CLI's raw "Not logged
in — Please run /login" as the user-facing error. Two hands stacked the trap:

* ``unified_code_lifecycle.js`` sent ``model: 'claude:sonnet'`` whenever
  ``modelId`` did not start with ``gpt-`` — INCLUDING when ``modelId`` was
  empty because client model state had been lost;
* ``forge_code_settings.from_payload`` invented ``claude:sonnet`` for a missing
  model, so even a request that honestly said "I have no model" ran Claude.

The fix, pinned here from both sides:

* the client sends NO ``model`` key when it has no model (JSON.stringify drops
  ``undefined``), instead of fabricating a Claude pick;
* the server resolves the actually-configured default — the same resolution
  that feeds the model chip via ``/api/models`` (``resolve_effective_model``) —
  and the capability report says the model came from configuration, not a pick;
* when NOTHING is configured either, the request fails BEFORE dispatch with a
  sentence naming the real situation, not the Claude CLI's login prompt.

Named-but-non-gpt models keep today's routing (a separate, documented design
issue) — asserted below so this change cannot widen past the empty case.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_settings
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_lifecycle.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_request_settings_model.mjs"


def _drive_js() -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(LIFECYCLE_JS)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"node harness failed:\n{result.stderr}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Client half: what actually goes over the wire.
# ---------------------------------------------------------------------------


def test_an_empty_model_id_sends_no_model_at_all() -> None:
    report = _drive_js()
    for case in ("empty", "missing"):
        wire = report[case]
        assert "model" not in wire, (
            f"context {case!r} (no model selected) put model={wire.get('model')!r} on the "
            "wire. A lost client model state must not fabricate a Claude pick — the "
            "server resolves the configured default when no model arrives."
        )


def test_a_named_model_keeps_todays_routing() -> None:
    report = _drive_js()
    assert report["gpt"]["model"] == "gpt-5.6-terra"
    assert report["gpt"]["model_id"] == "gpt-5.6-terra"
    # Known design issue, deliberately unchanged here: a named non-GPT model
    # still rides the claude:sonnet placeholder and the server reports the
    # substitution. Only the EMPTY case changes.
    assert report["qwen"]["model"] == "claude:sonnet"
    assert report["qwen"]["model_id"] == "qwen2.5-coder:7b"


# ---------------------------------------------------------------------------
# Server half: resolution, reporting, and the pre-dispatch refusal.
# ---------------------------------------------------------------------------


def test_an_empty_payload_resolves_the_configured_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forge_code_settings, "_configured_default_model", lambda: "gpt-5.6-terra")

    settings = ForgeCodeSettings.from_payload({})
    assert settings.family == "gpt", (
        "the chip showed a GPT model, yet the empty request still dispatched to "
        f"family {settings.family!r}"
    )
    assert settings.recorded_model() == "gpt-5.6-terra"
    support = settings.capability_report()["support"]["model"]
    assert support["status"] == "configured_default", (
        f"the report says {support['status']!r}; nothing was requested, the server "
        "filled in its configured default and must say so"
    )


def test_an_unresolvable_model_fails_before_dispatch_with_a_real_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forge_code_settings, "_configured_default_model", lambda: "")

    with pytest.raises(ForgeCodeSettingsError) as excinfo:
        ForgeCodeSettings.from_payload({})
    message = str(excinfo.value)
    assert "model" in message.lower() and "pick" in message.lower(), (
        f"the refusal {message!r} does not tell the owner what the situation is or "
        "what to do about it"
    )
    assert "login" not in message.lower() and "claude" not in message.lower(), (
        f"the refusal {message!r} leaks executor internals; the real situation is "
        "'no model selected', not a Claude CLI login problem"
    )


def test_a_defaulted_non_runnable_model_is_reported_as_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured default can itself be a model Code cannot run (local qwen).

    Today's routing sends it to the Claude CLI; the capability report must mark
    the model dial substituted on the empty-model path exactly as it does when
    the model was named explicitly.
    """

    monkeypatch.setattr(forge_code_settings, "_configured_default_model", lambda: "qwen2.5-coder:7b")

    settings = ForgeCodeSettings.from_payload({})
    assert settings.family == "claude"
    support = settings.capability_report()["support"]["model"]
    assert support["status"] == "substituted"
    assert "reason" in support and "Claude" in support["reason"]


def test_a_named_model_never_consults_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolution is for the EMPTY case only; a named model keeps today's path."""

    def _boom() -> str:
        raise AssertionError("_configured_default_model consulted for a named model")

    monkeypatch.setattr(forge_code_settings, "_configured_default_model", _boom)

    assert ForgeCodeSettings.from_payload({"model_id": "gpt-5.6-terra"}).family == "gpt"
    assert (
        ForgeCodeSettings.from_payload({"model": "claude:sonnet", "model_id": "qwen2.5-coder:7b"}).family == "claude"
    )
