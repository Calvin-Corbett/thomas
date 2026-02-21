from thomas.models.switching import (
    infer_profile_candidates,
    is_model_switch_request,
    resolve_model_switch_request,
)


def test_is_model_switch_request_requires_explicit_switch_intent() -> None:
    assert is_model_switch_request("switch to grok 4.2 api")
    assert is_model_switch_request("Please change model to opus 4.6")
    assert is_model_switch_request("could you switch to grok 4.2 api")
    assert not is_model_switch_request("I want 4.6 opus")
    assert not is_model_switch_request("i wnat grok 4.2 api")
    assert not is_model_switch_request("Please tell me how to switch to opus 4.6")
    assert not is_model_switch_request("how can I use grok 4.2 without auto switch")
    assert not is_model_switch_request("Summarize this file please")


def test_infer_profile_candidates_prefers_anthropic_for_claude_hints() -> None:
    profiles = infer_profile_candidates(
        "switch to opus 4.6",
        current_profile="openai",
        available_profiles=["local", "openai", "anthropic"],
    )
    assert profiles[0] == "anthropic"


def test_resolve_model_switch_request_maps_opus_46() -> None:
    res = resolve_model_switch_request(
        "switch to 4.6 opus",
        current_profile="anthropic",
        default_models={
            "anthropic": "claude-sonnet-4-5-20250929",
            "openai": "gpt-4o-mini",
        },
        discovered_models={
            "anthropic": [
                "claude-sonnet-4-6",
                "claude-opus-4-6",
                "claude-sonnet-4-5-20250929",
            ],
        },
    )
    assert res is not None
    assert res.profile == "anthropic"
    assert res.matched_model == "claude-opus-4-6"
    assert res.model_id == "claude-opus-4-6"


def test_resolve_model_switch_request_can_select_specific_model_id() -> None:
    res = resolve_model_switch_request(
        "use claude-sonnet-4-6",
        current_profile="anthropic",
        default_models={
            "anthropic": "claude-sonnet-4-5-20250929",
        },
        discovered_models={
            "anthropic": ["claude-sonnet-4-6"],
        },
    )
    assert res is not None
    assert res.profile == "anthropic"
    assert res.matched_model == "claude-sonnet-4-6"


def test_resolve_model_switch_request_maps_grok_request_to_xai_profile() -> None:
    res = resolve_model_switch_request(
        "please switch to grok 4.2 api",
        current_profile="openai",
        default_models={
            "xai": "grok-4-1-fast-reasoning",
            "openai": "gpt-4o-mini",
        },
        discovered_models={
            "xai": [
                "grok-4",
                "grok-4-1",
                "grok-4-1-fast-reasoning",
            ],
        },
    )
    assert res is not None
    assert res.profile == "xai"
    assert res.matched_model.startswith("grok-4")


def test_resolve_model_switch_request_ignores_conversational_mentions() -> None:
    res = resolve_model_switch_request(
        "i want to use 4.2 how can i do that so it does not auto switch",
        current_profile="openai",
        default_models={
            "xai": "grok-4-1-fast-reasoning",
            "openai": "gpt-4o-mini",
        },
        discovered_models={
            "xai": [
                "grok-4",
                "grok-4-1",
                "grok-4-1-fast-reasoning",
            ],
        },
    )
    assert res is None
