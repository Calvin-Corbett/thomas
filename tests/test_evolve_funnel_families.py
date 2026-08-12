"""Model-family identity + independent-evaluator selection."""

from __future__ import annotations

from thomas.forge.anvil.evolve_funnel_families import (
    family_of,
    lane_families,
    select_independent_evaluator,
)


def test_family_of_classifies_known_providers():
    assert family_of("anthropic", "claude-sonnet-4-5") == "anthropic"
    assert family_of("openai_codex", "gpt-5.5") == "openai"
    assert family_of("google", "gemini-2.0") == "google"
    assert family_of("mistral", "mistral-large") == "mistral"


_INFO = {
    "openai_codex": ("openai_codex", "gpt-5.5"),
    "anthropic": ("anthropic", "claude-sonnet-4-5"),
    "gemini": ("google", "gemini-2.0-flash"),
}


def _info(profile):
    return _INFO[profile]


def test_lane_families_collects_used_families():
    assert lane_families(["openai_codex"], _info) == {"openai"}


def test_select_independent_evaluator_picks_disjoint_family():
    profile, fam, degraded = select_independent_evaluator(
        ["anthropic", "gemini"], used_families={"openai"}, model_info=_info
    )
    assert profile == "anthropic"
    assert fam == "anthropic"
    assert degraded is False


def test_select_independent_evaluator_skips_same_family():
    # lanes already use anthropic -> evaluator must skip anthropic, pick gemini
    profile, fam, degraded = select_independent_evaluator(
        ["anthropic", "gemini"], used_families={"anthropic"}, model_info=_info
    )
    assert profile == "gemini"
    assert fam == "google"
    assert degraded is False


def test_select_independent_evaluator_degrades_when_no_disjoint_family():
    # every candidate shares the lanes' family -> degraded
    profile, fam, degraded = select_independent_evaluator(["anthropic"], used_families={"anthropic"}, model_info=_info)
    assert profile is None
    assert degraded is True
