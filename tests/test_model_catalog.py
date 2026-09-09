from __future__ import annotations

from types import SimpleNamespace

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.models.catalog import build_model_catalog, load_cached_model_catalog, model_catalog_path


def _config(tmp_path):
    return AppConfig(
        models={
            "codex": ModelConfig(name="codex", provider="codex", model="gpt-5.4"),
            "local": ModelConfig(name="local", provider="ollama", model="qwen2.5-coder:7b"),
        },
        default_model="codex",
        memory=MemoryConfig(root=str(tmp_path)),
    )


def test_model_catalog_refresh_merges_live_models_and_latest_alias(tmp_path, monkeypatch) -> None:
    async def _fake_handshake(cfg, *, timeout_s=2.0, max_results=200):  # noqa: ANN001
        _ = timeout_s
        _ = max_results
        if cfg.provider == "codex":
            return SimpleNamespace(
                ok=True,
                models=["gpt-5.5", "gpt-5.4", "gpt-5.3-codex"],
                to_dict=lambda: {"ok": True, "status": "ok", "models": ["gpt-5.5", "gpt-5.4", "gpt-5.3-codex"]},
            )
        return SimpleNamespace(ok=False, models=[], to_dict=lambda: {"ok": False, "status": "offline", "models": []})

    monkeypatch.setattr("thomas.models.catalog.handshake_models_async", _fake_handshake)

    cfg = _config(tmp_path)
    payload = build_model_catalog(cfg, refresh=True, timeout_s=0.5)

    assert payload["aliases"]["latest.openai.frontier"] == "gpt-5.6-sol"
    assert payload["aliases"]["latest.openai.codex"] == "gpt-5.3-codex"
    assert payload["aliases"]["best.tools"] == "gpt-5.6-sol"
    assert any(row["id"] == "gpt-5.5" and row["source"] == "live" for row in payload["models"])
    assert model_catalog_path(cfg).exists()
    assert load_cached_model_catalog(cfg)["aliases"]["latest.openai.frontier"] == "gpt-5.6-sol"


def test_model_catalog_without_refresh_still_supports_curated_new_gpt_models(tmp_path) -> None:
    payload = build_model_catalog(_config(tmp_path), refresh=False)

    ids = {row["id"] for row in payload["models"]}
    assert "gpt-5.5" in ids
    assert {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}.issubset(ids)
    assert payload["aliases"]["latest.openai.frontier"] == "gpt-5.6-sol"
    assert payload["aliases"]["best.tools"] == "gpt-5.6-sol"
    sol = next(row for row in payload["models"] if row["id"] == "gpt-5.6-sol")
    assert sol["capabilities"]["reasoning_efforts"] == ["none", "low", "medium", "high", "xhigh", "max"]
