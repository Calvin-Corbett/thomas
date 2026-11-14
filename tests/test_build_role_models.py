"""Role defaults must affect real helper clients, persistence and exact receipts."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from thomas.core.events import AgentEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil.forge_code_roles import ROLE_ENV, role_configs
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError
from thomas.preferences.model_prefs import persist_user_model_role_preference
from thomas.server.routes.evolve_agent_runtime import _code_action_hash
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


def choice(model, profile="openai_codex"):
    return {"profile": profile, "model_id": model}


def test_personal_defaults_are_frozen_and_reported_before_dispatch(runtime, monkeypatch):
    persist_user_model_role_preference(
        user_id="default", role="build_builder", profile="openai_codex", model_id="gpt-5.6-luna"
    )
    settings = ForgeCodeSettings.from_payload({"model": "gpt-5.6-sol"})
    persist_user_model_role_preference(
        user_id="default", role="build_builder", profile="openai_codex", model_id="gpt-5.6-terra"
    )
    assert settings.builder_model == "gpt-5.6-luna"
    assert ForgeCodeSettings.from_payload(settings.requested()).builder_model == "gpt-5.6-luna"
    assert json.loads(settings.child_environment({ROLE_ENV: "stale"})[ROLE_ENV]) == {
        "builder": "gpt-5.6-luna",
        "reviewer": "",
    }
    assert settings.capability_report()["effective"]["build_roles"] == {
        "manager": "gpt-5.6-sol",
        "builder": "gpt-5.6-luna",
        "reviewer": "gpt-5.6-sol",
    }
    assert ForgeCodeSettings.from_payload({"model": "gpt-5.6-sol"}).builder_model == "gpt-5.6-terra"
    inherited = ForgeCodeSettings.from_payload({"model": "gpt-5.6-sol", "build_roles": {"builder": None}})
    assert inherited.builder_model == ""
    assert ROLE_ENV not in ForgeCodeSettings.from_payload({"model": "claude:sonnet"}).child_environment(
        {ROLE_ENV: "stale"}
    )


@pytest.mark.parametrize(
    "roles",
    [
        [],
        {"manager": "gpt-5.6-sol"},
        {"builder": "gpt-5.6-luna"},
        {"builder": {"profile": False, "model_id": []}},
        {"builder": {"profile": None, "model_id": ""}},
        {"builder": {"profile": "", "model_id": 0}},
        {"builder": choice("claude-sonnet")},
        {"builder": choice("gpt-5.6-luna", "another_account")},
        {"builder": choice("gpt-5.6-luna", "openai")},
        {"builder": choice("gpt-5.6-luna\n")},
        {"builder": {"profile": "openai_codex", "model_id": "gpt-5.6-luna", "api_key": "refused"}},
    ],
)
def test_bad_roles_refuse_before_any_dispatch(runtime, roles):
    with pytest.raises(ForgeCodeSettingsError):
        ForgeCodeSettings.from_payload({"model": "gpt-5.6-sol", "build_roles": roles})


def test_explicit_role_changes_are_different_actions():
    original = {"model": "gpt-5.6-sol", "build_roles": {"builder": choice("gpt-5.6-luna")}}
    other = {**original, "build_roles": {"builder": choice("gpt-5.6-terra")}}
    assert _code_action_hash("Build", original) != _code_action_hash("Build", other)


def test_role_configs_never_move_credentials_to_a_different_provider(runtime):
    manager = runtime.models["selected"]
    manager.provider = "openai"
    with pytest.raises(ValueError, match="connected ChatGPT"):
        role_configs(manager, json.dumps({"builder": "gpt-5.6-luna"}))


@pytest.mark.asyncio
async def test_real_registration_uses_luna_builder_sol_reviewer_and_honest_receipts(runtime, monkeypatch, tmp_path):
    manager = runtime.models["selected"]
    manager.model = "gpt-5.6-sol"
    manager.api_key = "offline-fixture"
    monkeypatch.setenv(ROLE_ENV, json.dumps({"builder": "gpt-5.6-luna", "reviewer": "gpt-5.6-sol"}))
    events, models = [], []

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.config, self.llm, self.tools = config, llm, tools

        async def run(self, prompt, **kwargs):
            models.append(self.llm.config.model)
            assert self.tools.get("shell.exec") is None and self.tools.get("task.spawn") is None
            assert self.llm.config.api_key == "offline-fixture"
            assert self.llm.config._openai_codex_token_ready
            if self.tools.get("fs.write_file"):
                assert self.llm.config.model == "gpt-5.6-luna"
                result = await self.tools.execute("fs.write_file", {"path": "block.txt", "content": "grass"})
                assert result.ok
            else:
                assert self.llm.config.model == "gpt-5.6-sol"
            yield AgentEvent.text_delta("Working")
            yield AgentEvent.agent_done("Verified assigned work", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=manager,
        emit=events.append,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="balanced",
        protected_paths=[],
        can_write=True,
    )
    # A later preference/env change cannot mutate this already registered team.
    monkeypatch.setenv(ROLE_ENV, json.dumps({"builder": "gpt-5.6-terra"}))
    built, reviewed = await asyncio.gather(
        registry.execute(
            "task.team", {"assignments": [{"title": "Grass", "path": "block.txt", "instructions": "Write grass"}]}
        ),
        registry.execute("task.spawn", {"title": "Review", "instructions": "Inspect the project"}),
    )
    assert built.ok and reviewed.ok
    assert sorted(models) == ["gpt-5.6-luna", "gpt-5.6-sol"]
    assert manager.model == "gpt-5.6-sol"
    assert (tmp_path / "block.txt").read_text() == "grass"
    ledger = json.loads(next(tmp_path.glob(".thomas/evolve/agent/team/team_*/team.json")).read_text())
    assert ledger["model"] == "gpt-5.6-luna" and ledger["state"] == "completed"
    children = [event for event in events if event.get("agent_id")]
    assert {event["model"] for event in children if event["agent_mode"] == "builder"} == {"gpt-5.6-luna"}
    assert {event["model"] for event in children if event["agent_mode"] == "read_only"} == {"gpt-5.6-sol"}
    assert all(client.closed and client.options["failover_enabled"] is False for client in OfflineClient.instances)
