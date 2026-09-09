from __future__ import annotations

from scripts import gate_response_policy as mod


def test_monolith_guard_is_auto_remediate() -> None:
    policy = mod.describe_gate("monolith_guard")

    assert policy.response_class == "auto_remediate"
    assert policy.continue_after_fix is True
    assert policy.stop_immediately is False


def test_protected_files_is_hard_stop() -> None:
    policy = mod.describe_gate("protected_files")

    assert policy.response_class == "hard_stop"
    assert policy.continue_after_fix is False
    assert policy.stop_immediately is True


def test_unknown_gate_defaults_to_manual_review() -> None:
    policy = mod.describe_gate("mystery_gate")

    assert policy.response_class == "manual_review"
    assert policy.continue_after_fix is False
    assert "Inspect the gate output" in policy.next_step
