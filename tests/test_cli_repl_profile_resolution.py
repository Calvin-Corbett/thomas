from __future__ import annotations

from types import SimpleNamespace

import thomas.cli.main as cli_main
from thomas.core.config import AppConfig, ModelConfig


def _base_config() -> AppConfig:
    return AppConfig(
        default_model="local",
        models={
            "local": ModelConfig(name="local", provider="local", model="local-model"),
            "codex": ModelConfig(name="codex", provider="codex", model="codex-model"),
        },
    )


def _install_fake_preferences(monkeypatch, active_profile: str = "", model_id: str = "") -> None:
    class _FakeStore:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def get(self, user_id: str = "default", thread_id: str | None = None) -> object:
            return SimpleNamespace(
                advanced=SimpleNamespace(
                    model=SimpleNamespace(
                        active_profile=active_profile,
                        model_id=model_id,
                    )
                )
            )

    monkeypatch.setattr("thomas.preferences.store.PreferencesStore", _FakeStore)


def test_repl_profile_resolution_prefers_ui_profile(monkeypatch) -> None:
    cfg = _base_config()
    _install_fake_preferences(monkeypatch, active_profile="codex", model_id="codex-1")
    profile, model_id = cli_main._resolve_repl_profile_from_prefs(cfg)

    assert profile == "codex"
    assert model_id == "codex-1"


def test_repl_profile_resolution_ignores_missing_ui_profile(monkeypatch) -> None:
    cfg = _base_config()
    _install_fake_preferences(monkeypatch, active_profile="missing", model_id="codex-1")
    profile, model_id = cli_main._resolve_repl_profile_from_prefs(cfg)

    assert profile == "local"
    assert model_id == ""


def test_repl_profile_resolution_falls_back_on_store_failure(monkeypatch) -> None:
    cfg = _base_config()

    class _FailingStore:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def get(self, user_id: str = "default", thread_id: str | None = None) -> object:
            raise RuntimeError("prefs down")

    monkeypatch.setattr("thomas.preferences.store.PreferencesStore", _FailingStore)
    monkeypatch.setattr("thomas.preferences.store.get_db_path", lambda: "test")

    profile, model_id = cli_main._resolve_repl_profile_from_prefs(cfg)

    assert profile == "local"
    assert model_id == ""


def test_resolve_repl_profile_name_is_case_insensitive() -> None:
    cfg = _base_config()
    cfg.models["Codex"] = cfg.models.pop("codex")
    cfg.models["Codex"].name = "Codex"

    resolved = cli_main._resolve_model_profile_name(cfg, "cOdEx")
    assert resolved == "Codex"


def test_repl_needs_codex_when_failover_chain_includes_codex() -> None:
    cfg = _base_config()
    cfg.failover.enabled = True

    assert cli_main._repl_needs_codex_event_loop(cfg, "local") is True


def test_repl_does_not_need_codex_for_local_only_runtime() -> None:
    cfg = _base_config()
    cfg.models["codex"].provider = "openai"
    cfg.failover.enabled = False

    assert cli_main._repl_needs_codex_event_loop(cfg, "local") is False
