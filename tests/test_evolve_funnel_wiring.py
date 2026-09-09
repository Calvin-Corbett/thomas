"""Wiring: the funnel mode is selectable, additive, and config-driven.
Proven with injected fakes (no heavy engine, no model calls)."""

from __future__ import annotations

from thomas.forge.anvil.evolve_funnel import run_funnel_session
from thomas.forge.anvil.evolve_funnel_config import FunnelConfig, load_funnel_config
from thomas.forge.anvil.evolve_loop_actions import bind_real_collaborators


def _fake_promoter(*args, **kwargs):
    return {"ok": True}


def test_funnel_mode_selects_funnel_session_runner():
    _p, session_runner, _pr = bind_real_collaborators(None, None, _fake_promoter, mode="funnel")
    assert session_runner is run_funnel_session


def test_classic_mode_selects_classic_session_runner():
    from thomas.forge.anvil.evolve import run_evolve_session

    _p, session_runner, _pr = bind_real_collaborators(None, None, _fake_promoter, mode="classic")
    assert session_runner is run_evolve_session


def test_default_mode_is_classic():
    from thomas.forge.anvil.evolve import run_evolve_session

    _p, session_runner, _pr = bind_real_collaborators(None, None, _fake_promoter)
    assert session_runner is run_evolve_session


def test_injected_session_runner_wins_over_mode():
    sentinel = lambda *a, **k: {"session": {}}  # noqa: E731
    _p, session_runner, _pr = bind_real_collaborators(None, sentinel, _fake_promoter, mode="funnel")
    assert session_runner is sentinel


def test_funnel_config_defaults_safe_and_off():
    cfg = FunnelConfig()
    assert cfg.enabled is False
    assert cfg.lanes == 5
    assert cfg.survivors == 3
    assert cfg.evaluator_candidates == ["anthropic", "gemini"]


def test_funnel_config_from_dict_overrides():
    cfg = FunnelConfig.from_dict({"enabled": True, "lanes": 3, "evaluator_candidates": ["gemini"]})
    assert cfg.enabled is True
    assert cfg.lanes == 3
    assert cfg.evaluator_candidates == ["gemini"]


def test_funnel_config_env_override(monkeypatch):
    monkeypatch.setenv("FUNNEL_LANES", "2")
    monkeypatch.setenv("FUNNEL_ENABLED", "1")
    cfg = FunnelConfig().with_env_overrides()
    assert cfg.lanes == 2
    assert cfg.enabled is True


def test_load_funnel_config_reads_repo_toml():
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = load_funnel_config(here)
    assert isinstance(cfg, FunnelConfig)
    assert cfg.enabled is False
    assert cfg.lanes == 5
