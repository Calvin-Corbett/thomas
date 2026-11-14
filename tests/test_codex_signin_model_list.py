# tests/test_codex_signin_model_list.py
"""The ChatGPT sign-in's own list is what the picker shows for that connection.

On 2026-09-23 it offered GPT-6-Astra, GPT-6-Sol and GPT-6-Luna, and Thomas's
hand-typed list offered none of them.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from thomas.models.sources.codex_signin import list_codex_models, parse_codex_models, read_app_cache

FIXTURE = Path(__file__).parent / "fixtures" / "codex_models_2026-09-23.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _transport(status: int, payload: dict | None = None, etag: str = 'W/"1"') -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.url.path.endswith("/backend-api/codex/models")
        assert request.url.params.get("client_version")
        if status == 304:
            return httpx.Response(304)
        return httpx.Response(status, json=payload or {}, headers={"etag": etag})

    return httpx.MockTransport(handler)


async def _token(_profile: str) -> str:
    return "tok"


def _app_copy(home: Path, *, age: timedelta) -> None:
    fetched = (datetime.now(timezone.utc) - age).isoformat()
    home.joinpath("models_cache.json").write_text(
        json.dumps({"fetched_at": fetched, "client_version": "0.155.0", **_payload()}), encoding="utf-8"
    )


def test_the_real_list_keeps_the_providers_order_hidden_flags_and_retirements() -> None:
    models = parse_codex_models(_payload())
    visible = [m.id for m in models if not m.hidden]
    assert visible[:3] == ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"]
    assert {m.id for m in models if m.hidden} == {"gpt-reserve", "codex-auto-review"}
    retiring = next(m for m in models if m.id == "gpt-5.5")
    assert retiring.retires_at.startswith("2026-10-14")
    assert retiring.replacement == "gpt-5.6-sol"
    assert models[0].display_name == "GPT-6-Astra"


def test_a_live_answer_is_used_and_its_etag_kept(tmp_path: Path) -> None:
    answer = asyncio.run(
        list_codex_models("chatgpt", codex_token=_token, transport=_transport(200, _payload()), home=tmp_path)
    )
    assert answer.ok and answer.source == "chatgpt" and answer.etag == 'W/"1"'
    assert answer.models[0].id == "gpt-6-astra"


def test_an_unchanged_list_answers_not_modified(tmp_path: Path) -> None:
    answer = asyncio.run(
        list_codex_models("chatgpt", codex_token=_token, etag='W/"1"', transport=_transport(304), home=tmp_path)
    )
    assert answer.ok and answer.not_modified and answer.models == ()


def test_a_failed_call_falls_back_to_the_codex_apps_copy(tmp_path: Path) -> None:
    _app_copy(tmp_path, age=timedelta(hours=2))
    answer = asyncio.run(list_codex_models("chatgpt", codex_token=_token, transport=_transport(500), home=tmp_path))
    assert answer.ok and answer.source == "codex-app"
    assert answer.models[0].id == "gpt-6-astra"


def test_a_week_old_copy_is_not_trusted_and_both_failures_are_named(tmp_path: Path) -> None:
    _app_copy(tmp_path, age=timedelta(days=10))
    answer = asyncio.run(list_codex_models("chatgpt", codex_token=_token, transport=_transport(500), home=tmp_path))
    assert not answer.ok
    assert "HTTP 500" in answer.error and "10 days old" in answer.error


def test_without_a_sign_in_the_apps_fresh_copy_answers(tmp_path: Path) -> None:
    _app_copy(tmp_path, age=timedelta(minutes=5))
    assert read_app_cache(tmp_path).ok
    answer = asyncio.run(list_codex_models("chatgpt", codex_token=None, home=tmp_path))
    assert answer.ok and answer.source == "codex-app"
