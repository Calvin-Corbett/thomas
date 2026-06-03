"""Regressions for high-risk skill approval logic (praxis-unbypassable R5).

The bypass: an explicit mention of a high-risk skill (e.g. `$cloudflare-deploy`)
was treated as approval even when the same prompt explicitly DECLINED risky
skills. These tests pin the negation-aware decision helpers.
"""

from __future__ import annotations

from thomas.agent.skills_policy import has_skill_approval_phrase, prompt_negates_risky_approval


def test_codex_exact_bypass_prompt_is_detected_as_negation() -> None:
    prompt = "Use $cloudflare-deploy for context, but I do not approve risky skills or deployment actions"
    assert prompt_negates_risky_approval(prompt) is True


def test_plain_explicit_invocation_is_not_a_negation() -> None:
    # A genuine explicit invocation must still be allowed to approve.
    assert prompt_negates_risky_approval("please use $deploy-prod now") is False
    assert prompt_negates_risky_approval("ship the release now") is False


def test_various_risky_refusals_are_detected() -> None:
    for prompt in (
        "do not approve risky skills",
        "don't deploy anything",
        "never allow risky skills",
        "no risky deployments please",
        "I refuse any dangerous skills",
    ):
        assert prompt_negates_risky_approval(prompt) is True, prompt


def test_approval_phrase_rejects_negated_approval() -> None:
    assert has_skill_approval_phrase("do not approve cloudflare-deploy", "cloudflare-deploy") is False
    assert has_skill_approval_phrase("never allow deploy-prod", "deploy-prod") is False


def test_approval_phrase_accepts_affirmative_approval() -> None:
    assert has_skill_approval_phrase("I approve cloudflare-deploy for this task", "cloudflare-deploy") is True
    # hyphen/space normalization: prompt uses a space, skill name uses a hyphen
    assert has_skill_approval_phrase("you may allow cloudflare deploy", "cloudflare-deploy") is True


def test_global_approval_rejects_negated_prompt_R5() -> None:
    from thomas.agent.skills_policy import is_globally_approved

    # The literal substring "approve risky skills" appears inside the negation.
    assert is_globally_approved("Use $deploy but I do not approve risky skills") is False
    assert is_globally_approved("do not approve risky skills or deployment actions") is False
    # A genuine global approval still works.
    assert is_globally_approved("I approve risky skills for this session") is True
