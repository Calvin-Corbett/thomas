from __future__ import annotations

import dataclasses

import pytest

from thomas.agent.verification_contract import LEVELS, apply_verification_plan, normalize_level, plan_for

BOOL_FIELDS = [f.name for f in dataclasses.fields(plan_for("max")) if f.type == "bool"]


def test_ladder_is_monotone_each_level_is_a_superset_of_the_one_below() -> None:
    plans = [plan_for(level) for level in LEVELS]
    for lower, higher in zip(plans, plans[1:]):
        for name in BOOL_FIELDS:
            assert getattr(higher, name) >= getattr(lower, name), (name, lower.level, higher.level)
        assert higher.retry_budget >= lower.retry_budget


def test_max_runs_everything_and_none_runs_nothing() -> None:
    top, bottom = plan_for("max"), plan_for("none")
    assert all(getattr(top, name) for name in BOOL_FIELDS)
    assert top.reasoning_sandwich == ("max", "high", "max")
    assert not any(getattr(bottom, name) for name in BOOL_FIELDS)
    assert bottom.retry_budget == 0


@pytest.mark.parametrize("raw", ["", None, "  ", "turbo", "MAX "])
def test_blank_or_unknown_slider_verifies_as_medium_and_case_is_ignored(raw) -> None:
    expected = "max" if str(raw or "").strip().lower() == "max" else "medium"
    assert normalize_level(raw) == expected


def test_plan_folds_into_the_completion_gate_knobs() -> None:
    assert apply_verification_plan(plan_for("none"), quality_max_retries=1, gate_active=False) == (1, False)
    assert apply_verification_plan(plan_for("medium"), quality_max_retries=0, gate_active=False) == (1, True)
    assert apply_verification_plan(plan_for("max"), quality_max_retries=1, gate_active=False) == (4, True)
    assert apply_verification_plan(plan_for("low"), quality_max_retries=3, gate_active=True) == (3, True)


def test_payload_is_json_shaped() -> None:
    payload = plan_for("xhigh").to_payload()
    assert payload["level"] == "xhigh" and payload["separate_evaluator"] is True and payload["reasoning_sandwich"] is None
