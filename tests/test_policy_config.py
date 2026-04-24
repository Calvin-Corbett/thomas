from __future__ import annotations

from thomas.marketplace.policy.config import load_policy_config


def test_guardrails_are_enabled_for_fresh_runtime_by_default(tmp_path) -> None:
    cfg = load_policy_config(str(tmp_path))

    assert cfg.guardrails.enabled is True


def test_guardrails_can_be_explicitly_disabled_by_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_GUARDRAILS", "0")

    cfg = load_policy_config(str(tmp_path))

    assert cfg.guardrails.enabled is False
