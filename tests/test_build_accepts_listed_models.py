"""Build runs a Claude model Anthropic listed, even one its pattern has never seen."""

from __future__ import annotations

import pytest

from thomas.core import listed_models
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError


@pytest.fixture(autouse=True)
def _clean_registry():
    listed_models.publish("anthropic", [])
    yield
    listed_models.publish("anthropic", [])


def test_a_new_claude_family_runs_once_anthropic_lists_it() -> None:
    listed_models.publish("anthropic", ["claude-nova-5"])
    settings = ForgeCodeSettings.from_payload({"model": "claude-nova-5", "model_id": "claude-nova-5"})
    assert settings.runs_requested_model()


def test_an_unlisted_unknown_name_is_still_refused() -> None:
    listed_models.publish("anthropic", ["claude-nova-5"])
    with pytest.raises(ForgeCodeSettingsError, match="claude-nova-6"):
        ForgeCodeSettings.from_payload({"model": "claude-nova-6", "model_id": "claude-nova-6"})


def test_gpt_6_runs_through_the_chatgpt_sign_in() -> None:
    settings = ForgeCodeSettings.from_payload({"model": "gpt-6-astra", "model_id": "gpt-6-astra"})
    assert settings.model_id == "gpt-6-astra"
