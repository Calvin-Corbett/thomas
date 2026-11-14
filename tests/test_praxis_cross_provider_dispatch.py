"""One Build task can route its children across configured providers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from thomas.forge.anvil import forge_code_roles
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server.praxis import launch


@pytest.mark.asyncio
async def test_gpt_lead_can_choose_claude_cli_or_anthropic_api_child(tmp_path, monkeypatch):
    calls = []

    def cli(_project, *, model_id):
        async def run(*_args):
            calls.append(("cli", model_id))
            yield {"type": "done", "model_used": "claude-sonnet"}

        return run

    def worker(_app, _project, *, model_id, run_id, profile):
        async def run(_id, _kind, _title, _brief, choice=None):
            calls.append(("worker", profile, model_id, choice))
            yield {"type": "done", "model_used": model_id}

        return run

    monkeypatch.setattr(launch, "build_claude_read_child_runner", cli)
    monkeypatch.setattr(launch, "build_read_child_runner", worker)
    settings = SimpleNamespace(
        family="gpt", model_id="gpt-5.6-sol", reviewer_model="gpt-5.6-luna", dispatch_model="codex:gpt"
    )
    run = launch.build_dispatching_child_runner({}, tmp_path, settings, "run")
    assert [event async for event in run("a", "review", "A", "Inspect")][-1]["model_used"] == "gpt-5.6-luna"
    assert [
        event
        async for event in run("b", "review", "B", "Inspect", {"profile": "anthropic", "model_id": "claude-sonnet-4-5"})
    ][-1]["model_used"] == "claude-sonnet-4-5"
    assert [
        event async for event in run("c", "review", "C", "Inspect", {"profile": "claude_cli", "model_id": "sonnet"})
    ][-1]["model_used"] == "claude-sonnet"
    assert calls == [
        ("worker", "openai_codex", "gpt-5.6-luna", None),
        ("worker", "anthropic", "claude-sonnet-4-5", {"profile": "anthropic", "model_id": "claude-sonnet-4-5"}),
        ("cli", "sonnet"),
    ]


@pytest.mark.asyncio
async def test_claude_lead_defaults_to_cli_but_saved_gpt_reviewer_can_override(tmp_path, monkeypatch):
    calls = []

    def cli(_project, *, model_id):
        async def run(*_args):
            calls.append(("cli", model_id))
            yield {"type": "done"}

        return run

    def worker(_app, _project, *, model_id, run_id, profile):
        async def run(*_args):
            calls.append(("worker", profile, model_id))
            yield {"type": "done"}

        return run

    monkeypatch.setattr(launch, "build_claude_read_child_runner", cli)
    monkeypatch.setattr(launch, "build_read_child_runner", worker)
    settings = SimpleNamespace(family="claude", dispatch_model="claude:sonnet")
    run = launch.build_dispatching_child_runner({}, tmp_path, settings, "run")
    assert [event async for event in run("a", "review", "A", "Inspect")] == [{"type": "done"}]
    assert [event async for event in run("b", "review", "B", "Inspect", {"model_id": "gpt-5.6-luna"})] == [
        {"type": "error", "error": "Explicit Build child model choice needs a provider profile", "retryable": False}
    ]
    assert calls == [("cli", "claude:sonnet")]

    monkeypatch.setattr(
        forge_code_roles,
        "read_user_model_role_preferences",
        lambda *, user_id, role: ("openai_codex", "gpt-5.6-luna") if role == "build_reviewer" else ("", ""),
    )
    saved = ForgeCodeSettings.from_payload({"model": "claude:sonnet"})
    assert saved.praxis_reviewer_profile == "openai_codex"
    run = launch.build_dispatching_child_runner({}, tmp_path, saved, "run-2")
    assert [event async for event in run("c", "review", "C", "Inspect")] == [{"type": "done"}]
    assert calls[-1] == ("worker", "openai_codex", "gpt-5.6-luna")
