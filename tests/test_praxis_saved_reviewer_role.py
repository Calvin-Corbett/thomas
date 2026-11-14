"""A saved non-GPT read reviewer survives Build settings and launch."""

from __future__ import annotations

import json

import pytest
from aiohttp import web

from thomas.forge.anvil import forge_code_roles
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server.praxis import launch
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


@pytest.mark.asyncio
async def test_saved_anthropic_reviewer_is_frozen_without_changing_gpt_internal_reviewers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        forge_code_roles,
        "read_user_model_role_preferences",
        lambda *, user_id, role: ("anthropic", "claude-sonnet-4-5") if role == "build_reviewer" else ("", ""),
    )
    settings = ForgeCodeSettings.from_payload({"model": "gpt-5.6-sol"})
    assert settings.praxis_reviewer_profile == "anthropic"
    assert settings.praxis_reviewer_model == "claude-sonnet-4-5"
    assert settings.reviewer_model == ""
    assert json.loads(settings.child_environment({})[forge_code_roles.ROLE_ENV])["reviewer"] == ""
    assert settings.requested()["build_roles"]["reviewer"] == {
        "profile": "anthropic",
        "model_id": "claude-sonnet-4-5",
    }
    assert ForgeCodeSettings.from_payload(settings.requested()).praxis_reviewer_profile == "anthropic"
    report = settings.capability_report()["effective"]["build_roles"]
    assert report["reviewer"] == "gpt-5.6-sol"
    assert report["praxis_read_reviewer"] == {"profile": "anthropic", "model_id": "claude-sonnet-4-5"}

    captured = {}

    def fake_runner(_app, _project, **kwargs):
        captured.update(kwargs)

        async def run(*_args):
            yield {"type": "done"}

        return run

    monkeypatch.setattr(launch, "build_read_child_runner", fake_runner)
    monkeypatch.setattr(launch, "user_praxis_root", lambda: tmp_path)
    app = web.Application()
    registry = register_praxis_run_routes(app)
    launch.prepare_launch(app, settings, tmp_path, "run", "request", {}, 8899)
    assert [event async for event in registry._runs["run"]._run_child("child", "review", "Review", "Inspect")] == [
        {"type": "done"}
    ]
    assert captured == {"model_id": "claude-sonnet-4-5", "run_id": "run", "profile": "anthropic"}
    await registry.close("run")
