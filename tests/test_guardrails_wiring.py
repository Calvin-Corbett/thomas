"""Guardrails end-to-end wiring: enforcement helpers, persistence, and API."""

from __future__ import annotations

import json

from thomas.server import guardrails_state as gs


def test_reach_deny_set_by_mode():
    # strict denies all external reach; permissive denies nothing; standard denies remote only.
    assert gs.reach_deny_set("permissive") == frozenset()
    assert "remote" in gs.reach_deny_set("standard")
    strict = gs.reach_deny_set("strict")
    for tok in ("web", "http", "browser", "remote"):
        assert tok in strict
    # local coding tools are never in any reach deny set
    for mode in ("strict", "standard", "permissive"):
        assert "shell" not in gs.reach_deny_set(mode)
        assert "git" not in gs.reach_deny_set(mode)
    # unknown mode falls back to standard
    assert gs.reach_deny_set("nonsense") == gs.reach_deny_set("standard")


def test_gatekeeper_no_human_mode():
    assert gs.gatekeeper_no_human_mode("strict", "allow") == "deny"
    assert gs.gatekeeper_no_human_mode("strict", None) == "deny"
    assert gs.gatekeeper_no_human_mode("standard", "allow") == "allow"  # passes base through
    assert gs.gatekeeper_no_human_mode("standard", None) is None
    assert gs.gatekeeper_no_human_mode("permissive", None) == "allow"


def test_build_effective_precedence_modes_over_preset():
    # explicit modes win over preset
    state = gs.build_effective_guardrails("fortress", {"reach": "permissive"})
    assert state.mode_for("reach") == "permissive"


def test_build_effective_from_preset():
    state = gs.build_effective_guardrails("fortress", None)
    assert all(state.mode_for(g) == "strict" for g in gs.GUARDRAIL_GROUPS)
    state = gs.build_effective_guardrails("open", None)
    assert all(state.mode_for(g) == "permissive" for g in gs.GUARDRAIL_GROUPS)


def test_normalize_state_coerces_unknown():
    state = gs.normalize_state({"modes": {"reach": "bogus", "gatekeeper": "strict"}})
    assert state.mode_for("reach") == "standard"  # unknown -> standard
    assert state.mode_for("gatekeeper") == "strict"


def test_policy_store_roundtrip(tmp_path, monkeypatch):
    from thomas.server import guardrails_policy_store as store

    monkeypatch.setattr(store, "_policy_path", lambda: tmp_path / "guardrails_policy.json")
    # default when absent
    assert store.load_guardrails_policy().mode_for("reach") == "standard"
    # save + reload
    saved = store.save_guardrails_policy(gs.from_preset("fortress"))
    assert saved.mode_for("reach") == "strict"
    reloaded = store.load_guardrails_policy()
    assert all(reloaded.mode_for(g) == "strict" for g in gs.GUARDRAIL_GROUPS)
    # file is valid json with the expected shape
    raw = json.loads((tmp_path / "guardrails_policy.json").read_text(encoding="utf-8"))
    assert raw["modes"]["gatekeeper"] == "strict"


def test_build_effective_falls_back_to_saved(tmp_path, monkeypatch):
    from thomas.server import guardrails_policy_store as store

    monkeypatch.setattr(store, "_policy_path", lambda: tmp_path / "guardrails_policy.json")
    store.save_guardrails_policy(gs.from_preset("fortress"))
    # no preset, no modes -> use the persisted policy
    state = gs.build_effective_guardrails("", None)
    assert state.mode_for("reach") == "strict"
