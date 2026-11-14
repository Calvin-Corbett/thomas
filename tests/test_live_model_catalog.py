"""The catalog is the one list every picker reads."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from thomas.core import listed_models
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.models import catalog
from thomas.models.sources import ListedModel, SourceAnswer

ASTRA = ListedModel(id="gpt-6-astra", display_name="GPT-6-Astra", order=1)
SOL = ListedModel(id="gpt-6-sol", order=2)
RESERVE = ListedModel(id="gpt-reserve", order=3, hidden=True)
RETIRING = ListedModel(id="gpt-5.5", order=12, retires_at="2026-10-14T19:00:00Z", replacement="gpt-5.6-sol")
OK_CHATGPT = SourceAnswer(ok=True, source="chatgpt", models=(SOL, RESERVE, RETIRING), etag='W/"a"')
OK_ANTHROPIC = SourceAnswer(ok=True, source="provider", models=(ListedModel(id="claude-nova-5"),))


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        models={
            "chatgpt": ModelConfig(name="chatgpt", provider="openai_codex", model="gpt-5.6-sol"),
            "anthropic": ModelConfig(
                name="anthropic", provider="anthropic", api_key="k", model="claude-sonnet-4-5-20250929"
            ),
        },
        default_model="chatgpt",
        memory=MemoryConfig(root=str(tmp_path)),
    )


def _refresh(cfg: AppConfig, monkeypatch, answers: dict[str, SourceAnswer]) -> dict:
    async def fake(profile, _cfg, **_kw):  # noqa: ANN001
        return answers[profile]

    monkeypatch.setattr(catalog, "list_profile_models", fake)
    return asyncio.run(catalog.build_model_catalog_async(cfg, refresh=True))


def _ids(payload: dict, profile: str) -> list[str]:
    return [r["id"] for r in payload["models"] if r["profile"] == profile and r["source"] == "live"]


def test_the_providers_order_hidden_flags_and_retirements_survive(tmp_path, monkeypatch) -> None:
    payload = _refresh(_config(tmp_path), monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC})
    assert _ids(payload, "chatgpt") == ["gpt-6-sol", "gpt-reserve", "gpt-5.5"]
    rows = {r["id"]: r for r in payload["models"]}
    assert rows["gpt-reserve"]["hidden"] is True
    assert rows["gpt-5.5"]["replacement"] == "gpt-5.6-sol"
    assert payload["providers"]["chatgpt"]["etag"] == 'W/"a"'


def test_the_first_check_marks_nothing_new_and_a_later_arrival_is_new(tmp_path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    first = catalog.catalog_view(_refresh(cfg, monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC}))
    assert not any(r["is_new"] for r in first["models"])
    grown = SourceAnswer(ok=True, source="chatgpt", models=(ASTRA, SOL, RESERVE, RETIRING))
    second = catalog.catalog_view(_refresh(cfg, monkeypatch, {"chatgpt": grown, "anthropic": OK_ANTHROPIC}))
    assert [r["id"] for r in second["models"] if r["is_new"]] == ["gpt-6-astra"]
    later = catalog.catalog_view(second, now=datetime.now(timezone.utc) + timedelta(days=8))
    assert not any(r["is_new"] for r in later["models"])


def test_a_failed_check_keeps_the_last_good_list_and_says_why(tmp_path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    good = _refresh(cfg, monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC})
    failed = SourceAnswer(ok=False, source="chatgpt", error="the ChatGPT sign-in answered HTTP 503")
    after = _refresh(cfg, monkeypatch, {"chatgpt": failed, "anthropic": OK_ANTHROPIC})
    assert _ids(after, "chatgpt") == _ids(good, "chatgpt")
    assert after["providers"]["chatgpt"]["error"] == "the ChatGPT sign-in answered HTTP 503"
    assert after["providers"]["chatgpt"]["checked_at"] == good["providers"]["chatgpt"]["checked_at"]


def test_not_modified_keeps_the_rows(tmp_path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    good = _refresh(cfg, monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC})
    same = SourceAnswer(ok=True, source="chatgpt", etag='W/"a"', not_modified=True)
    after = _refresh(cfg, monkeypatch, {"chatgpt": same, "anthropic": OK_ANTHROPIC})
    assert _ids(after, "chatgpt") == _ids(good, "chatgpt")


def test_the_hand_list_stands_in_only_until_the_sign_in_answers(tmp_path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    before = asyncio.run(catalog.build_model_catalog_async(cfg, refresh=False))
    assert any(r["source"] == "curated" for r in before["models"])
    after = _refresh(cfg, monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC})
    assert not any(r["source"] == "curated" for r in after["models"])


def test_anthropics_list_is_published_for_build(tmp_path, monkeypatch) -> None:
    _refresh(_config(tmp_path), monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": OK_ANTHROPIC})
    assert "claude-nova-5" in listed_models.listed("anthropic")


def test_claude_cli_names_are_offered_to_chat_as_well_as_build(tmp_path, monkeypatch) -> None:
    """They were marked ``build_only`` while Chat could not run them. Chat can now
    (thomas/core/llm_streaming_claude_cli.py), so the row carries no such mark and the
    Chat picker has nothing to filter on."""
    cli = SourceAnswer(ok=True, source="claude-cli", models=(ListedModel(id="opus"),))
    payload = _refresh(_config(tmp_path), monkeypatch, {"chatgpt": OK_CHATGPT, "anthropic": cli})
    row = next(r for r in payload["models"] if r["id"] == "opus")
    assert "build_only" not in row and row["available"] is True


def test_one_profiles_reader_raising_does_not_abort_the_others(tmp_path, monkeypatch) -> None:
    cfg = _config(tmp_path)

    async def fake(profile, _cfg, **_kw):  # noqa: ANN001
        if profile == "chatgpt":
            raise UnicodeEncodeError("utf-8", "x", 0, 1, "boom")
        return OK_ANTHROPIC

    monkeypatch.setattr(catalog, "list_profile_models", fake)
    payload = asyncio.run(catalog.build_model_catalog_async(cfg, refresh=True))
    assert _ids(payload, "anthropic") == ["claude-nova-5"]
    assert "UnicodeEncodeError" in payload["providers"]["chatgpt"]["error"]
    assert payload["providers"]["chatgpt"]["error"].startswith("chatgpt:")


def test_profiles_are_asked_concurrently_not_one_after_another(tmp_path, monkeypatch) -> None:
    cfg = AppConfig(
        models={
            "a": ModelConfig(name="a", provider="anthropic", api_key="k", model="claude-a"),
            "b": ModelConfig(name="b", provider="anthropic", api_key="k", model="claude-b"),
            "c": ModelConfig(name="c", provider="anthropic", api_key="k", model="claude-c"),
        },
        default_model="a",
        memory=MemoryConfig(root=str(tmp_path)),
    )

    async def slow(profile, _cfg, **_kw):  # noqa: ANN001
        await asyncio.sleep(0.3)
        return SourceAnswer(ok=True, source="provider", models=(ListedModel(id=f"{profile}-model"),))

    monkeypatch.setattr(catalog, "list_profile_models", slow)
    start = time.monotonic()
    asyncio.run(catalog.build_model_catalog_async(cfg, refresh=True))
    elapsed = time.monotonic() - start
    assert elapsed < 0.9


def test_the_hand_list_never_duplicates_a_live_openai_answer(tmp_path, monkeypatch) -> None:
    # An OpenAI-family profile that is not openai_codex (as in tests/test_model_catalog.py)
    # never flips `signed_in`, so the curated fallback is always considered here. Its ids
    # must not duplicate a live row this profile already answered with.
    cfg = AppConfig(
        models={"codex": ModelConfig(name="codex", provider="codex", model="gpt-5.4")},
        default_model="codex",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    live = SourceAnswer(
        ok=True,
        source="provider",
        models=(ListedModel(id="gpt-5.5", order=0), ListedModel(id="gpt-5.4", order=1)),
    )

    async def fake(profile, _cfg, **_kw):  # noqa: ANN001
        return live

    monkeypatch.setattr(catalog, "list_profile_models", fake)
    payload = asyncio.run(catalog.build_model_catalog_async(cfg, refresh=True))

    openai_ids = [r["id"] for r in payload["models"] if r["family"] == "openai"]
    assert len(openai_ids) == len(set(openai_ids))
    gpt55 = [r for r in payload["models"] if r["id"] == "gpt-5.5"]
    assert len(gpt55) == 1
    assert gpt55[0]["source"] == "live"
