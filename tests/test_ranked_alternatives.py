"""Rank failover choices from supplied catalog, preferences, and Build turns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from thomas.core.config import ModelConfig
from thomas.models.ready_elsewhere import ranked_alternatives


def _config():
    profiles = {
        "gpt": ModelConfig(name="gpt", provider="openai_codex", model="gpt-default"),
        "gpt-second": ModelConfig(name="gpt-second", provider="openai_codex", model="gpt-second-default"),
        "claude": ModelConfig(name="claude", provider="anthropic", model="sonnet"),
        "key": ModelConfig(name="key", provider="anthropic", api_key="metered", model="claude-key"),
        "local": ModelConfig(name="local", provider="ollama", model="qwen"),
        "dead": ModelConfig(name="dead", provider="openrouter", api_key="metered", model="dead-model"),
    }
    return SimpleNamespace(models=profiles)


def _catalog():
    return {
        "providers": {
            name: {"checked_at": "today", "error": ""}
            for name in ("gpt", "gpt-second", "claude", "key", "local", "dead")
        },
        "models": [
            {"profile": "gpt", "id": "gpt-default", "source": "live"},
            {"profile": "gpt-second", "id": "gpt-second-default", "source": "live"},
            {"profile": "claude", "id": "sonnet", "source": "live", "display_name": "Claude Sonnet"},
            {"profile": "claude", "id": "opus", "source": "live", "display_name": "Claude Opus"},
            {"profile": "key", "id": "claude-key", "source": "live"},
            {"profile": "local", "id": "qwen", "source": "live"},
            {"profile": "dead", "id": "dead-model", "source": "live"},
        ],
    }


def _prefs(chain="", local_only=False):
    return SimpleNamespace(
        advanced=SimpleNamespace(
            cost=SimpleNamespace(model_failover_chain=chain),
            privacy=SimpleNamespace(local_only_mode=local_only),
        ),
    )


def _rank(
    current="gpt", surface="chat", chain="", local_only=False, *, catalog=None, turns=(), resting=(), config=None
):
    return ranked_alternatives(
        current,
        surface,
        _prefs(chain, local_only),
        _config() if config is None else config,
        catalog=_catalog() if catalog is None else catalog,
        turns=turns,
        resting_profiles=resting,
    )


def test_dead_signed_out_parked_and_unlisted_models_are_not_offered():
    payload = _catalog()
    payload["providers"]["dead"]["error"] = "timeout"
    payload["models"].append({"profile": "claude", "id": "not-listed", "source": "config"})
    payload["models"].append({"profile": "claude", "id": "hidden", "source": "live", "hidden": True})
    payload["models"].append({"profile": "claude", "id": "unavailable", "source": "live", "available": False})
    assert _rank(catalog=payload, resting=("claude", "local")) == ()
    assert _rank(catalog=payload, resting=("local",)) == (("claude", "sonnet"),)
    payload["providers"]["claude"]["checked_at"] = ""
    assert _rank(catalog=payload, resting=("local",)) == ()


def test_catalog_error_excludes_an_otherwise_ready_plan():
    payload = _catalog()
    assert _rank(catalog=payload, resting=("local",)) == (("claude", "sonnet"),)
    payload["providers"]["claude"]["error"] = "timeout"
    assert _rank(catalog=payload, resting=("local",)) == ()


def test_an_outage_skips_every_profile_of_the_same_provider():
    assert _rank() == (("claude", "sonnet"), ("local", "qwen"))
    assert _rank(current="claude") == (
        ("gpt", "gpt-default"),
        ("gpt-second", "gpt-second-default"),
        ("local", "qwen"),
    )


def test_metered_keys_need_explicit_opt_in_and_then_follow_plan_choices():
    assert ("key", "claude-key") not in _rank()
    assert _rank(chain="key") == (("claude", "sonnet"), ("key", "claude-key"), ("local", "qwen"))


def test_build_can_only_run_on_gpt_or_claude_plans():
    assert _rank(surface="build", chain="key,local") == (("claude", "sonnet"),)
    assert _rank(current="local", surface="build") == (
        ("gpt", "gpt-default"),
        ("gpt-second", "gpt-second-default"),
        ("claude", "sonnet"),
    )


def test_chat_local_only_never_offers_a_network_provider():
    assert _rank(local_only=True, chain="key") == (("local", "qwen"),)
    assert _rank(current="local", local_only=True) == ()


@pytest.mark.parametrize("provider", ["ollama", "lmstudio"])
def test_remote_local_runtime_needs_chain_opt_in_and_is_not_local_only(provider):
    config = _config()
    config.models["local"].provider = provider
    config.models["local"].base_url = "https://ollama.example.com"
    assert ("local", "qwen") not in _rank(config=config)
    assert ("local", "qwen") not in _rank(config=config, local_only=True, chain="local")
    assert ("local", "qwen") in _rank(config=config, chain="local")


def test_owner_chain_orders_surviving_plans_before_metered_keys():
    assert _rank(current="local", chain="claude,gpt-second,key,gpt") == (
        ("claude", "sonnet"),
        ("gpt-second", "gpt-second-default"),
        ("gpt", "gpt-default"),
        ("key", "claude-key"),
    )


def test_latest_build_turn_on_a_plan_selects_its_ready_model():
    turns = [
        {"role": "agent", "model": "claude:opus"},
        {"role": "agent", "model": "claude:sonnet"},
        {"role": "agent", "model": "claude:opus"},
        {"role": "agent", "model": "claude:missing"},
    ]
    assert _rank(turns=turns)[0] == ("claude", "opus")
    assert _rank(turns=[{"role": "agent", "model": "claude:missing"}])[0] == ("claude", "sonnet")


def test_claude_plan_versioned_default_uses_its_live_alias_without_turns():
    config = _config()
    config.models["claude"] = ModelConfig(name="claude", provider="anthropic", model="claude-sonnet-4-5-20250929")
    catalog = _catalog()
    catalog["models"] = [row for row in catalog["models"] if row["profile"] != "claude"]
    catalog["models"].extend(
        [
            {"profile": "claude", "id": "claude-sonnet-4-5-20250929", "source": "config"},
            {"profile": "claude", "id": "opus", "source": "live"},
            {"profile": "claude", "id": "sonnet", "source": "live"},
            {"profile": "claude", "id": "haiku", "source": "live"},
        ]
    )
    assert _rank(config=config, catalog=catalog, turns=()) == (("claude", "sonnet"), ("local", "qwen"))


@pytest.mark.parametrize("surface", ["chat", "build"])
def test_no_catalog_answer_means_no_alternatives(surface):
    assert _rank(surface=surface, catalog={}) == ()
