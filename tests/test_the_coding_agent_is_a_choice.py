"""Which coding agent runs a Build is a choice next to the model, not its consequence.

You asked for "an Agent choice next to the model choice, in Build and in Chat's
delegation: Thomas ... and Claude Code first, and a shape that lets Codex CLI,
Gemini CLI or OpenCode be added later without touching the rest", with Thomas's
own loop the default and able to run Claude through an API key. These tests hold
each of those, and end with the proof you named: the same small task run once
with each agent from the picker, each turn recording which agent and which model
ran it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thomas.core.coding_agents import (
    ANTHROPIC_KEY_MISSING_MSG,
    BUILTIN_AGENT_IDS,
    DEFAULT_AGENT_ID,
    AgentAvailability,
    AgentCannotRunModel,
    AgentLaunchPlan,
    AgentRunRequest,
    CodingAgentSpec,
    UnknownAgent,
    builtin_registry,
    resolve,
)
from thomas.forge.anvil import agent_passes, forge_code_runner, forge_code_store
from thomas.forge.anvil.dispatch_claude_cli import CliDispatchResult
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError

CLAUDE_MODEL = "claude-sonnet-4-5"
GPT_MODEL = "gpt-5.6-sol"


@pytest.fixture(autouse=True)
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "THOMAS_ANTHROPIC_API_KEY", "THOMAS_MODELS_FORGECODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _claude_code_ready(monkeypatch: pytest.MonkeyPatch, ready: bool = True) -> None:
    from thomas.core import claude_plan

    monkeypatch.setattr(claude_plan, "claude_cli_path", lambda *a, **k: "C:/bin/claude.exe" if ready else "")
    monkeypatch.setattr(claude_plan, "profiles_without_a_signin", lambda: set())


def test_thomas_and_claude_code_are_in_the_picker_and_thomas_is_the_default() -> None:
    picker = builtin_registry().to_dict(model_id=CLAUDE_MODEL)
    ids = [agent["id"] for agent in picker["agents"]]
    assert ids[:2] == ["thomas", "claude_code"]
    assert picker["default"] == DEFAULT_AGENT_ID == "thomas"
    assert all(agent["runs_selected_model"] for agent in picker["agents"])


def test_an_agent_that_cannot_run_the_model_is_listed_with_the_reason() -> None:
    picker = builtin_registry().to_dict(model_id=GPT_MODEL)
    claude_code = next(agent for agent in picker["agents"] if agent["id"] == "claude_code")
    assert claude_code["runs_selected_model"] is False
    assert "Claude models only" in claude_code["mismatch"]


def test_a_later_gpt_agent_is_one_spec_in_the_registry() -> None:
    """In the registry a later agent is one spec; builtins.py says what else a new agent needs."""
    registry = builtin_registry()
    assert set(BUILTIN_AGENT_IDS) <= set(registry.ids())

    later = CodingAgentSpec(
        id="codex_cli",
        label="Codex CLI",
        summary="A later agent, added without touching the rest.",
        dispatch="thomas.forge.anvil.agent_passes:run_thomas_pass",
        model_families=("gpt",),
        availability=lambda: AgentAvailability(installed=False, signed_in=False, detail="not installed"),
        planner=lambda model: AgentLaunchPlan(agent_id="codex_cli", model=model),
        priority=20,
    )
    registry.register(later)
    assert "codex_cli" in registry.ids()
    offered = {agent["id"]: agent for agent in registry.to_dict(model_id=GPT_MODEL)["agents"]}
    assert offered["codex_cli"]["runs_selected_model"] is True
    registry.unregister("codex_cli")
    assert "codex_cli" not in registry.ids()


def test_gpt_with_no_pick_runs_on_thomas() -> None:
    assert resolve(builtin_registry(), model_id=GPT_MODEL).spec.id == "thomas"


def test_claude_with_no_pick_and_no_key_stays_on_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unpicked Claude without a key goes where it went before the picker existed."""
    for ready in (True, False):
        _claude_code_ready(monkeypatch, ready)
        assert resolve(builtin_registry(), model_id=CLAUDE_MODEL).spec.id == "claude_code"


def test_claude_with_no_pick_and_a_key_runs_on_thomas(monkeypatch: pytest.MonkeyPatch) -> None:
    _claude_code_ready(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    selection = resolve(builtin_registry(), model_id=CLAUDE_MODEL)
    assert (selection.spec.id, selection.picked) == ("thomas", False)


def test_a_pick_is_obeyed_or_refused_never_swapped() -> None:
    registry = builtin_registry()
    assert resolve(registry, model_id=CLAUDE_MODEL, requested="thomas").spec.id == "thomas"
    with pytest.raises(AgentCannotRunModel, match="Claude Code cannot run gpt-5.6-sol"):
        resolve(registry, model_id=GPT_MODEL, requested="claude_code")
    with pytest.raises(UnknownAgent):
        resolve(registry, model_id=GPT_MODEL, requested="nobody")
    with pytest.raises(ForgeCodeSettingsError, match="Claude Code cannot run"):
        ForgeCodeSettings.from_payload({"model_id": GPT_MODEL, "agent": "claude_code"})


def test_thomas_on_claude_reaches_it_through_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": "thomas"})
    assert (settings.agent, settings.family) == ("thomas", "claude")
    env = settings.child_environment({"ANTHROPIC_API_KEY": "sk-ant-test"})
    assert env["THOMAS_MODELS_FORGECODE_PROVIDER"] == "anthropic"
    assert env["THOMAS_MODELS_FORGECODE_MODEL"] == CLAUDE_MODEL
    assert env["THOMAS_MODELS_FORGECODE_API_KEY"] == "sk-ant-test"
    report = settings.capability_report()
    assert report["effective"]["agent"] == "thomas"
    assert report["support"]["agent"]["status"] == "applied"
    # No `claude:` prefix: that would name Claude Code, which had no part in the run.
    assert settings.recorded_model() == CLAUDE_MODEL


def test_claude_code_pins_nothing_it_carries_its_own_sign_in() -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": "claude_code"})
    env = settings.child_environment({"ANTHROPIC_API_KEY": "sk-ant-test"})
    assert "THOMAS_MODELS_FORGECODE_PROVIDER" not in env
    assert settings.recorded_model().startswith("claude:")


def _args(tmp_path: Path, family: str, agent: str, model: str) -> Any:
    argv = ["build it", "--project-root", str(tmp_path), "--family", family, "--agent", agent]
    return forge_code_runner.build_parser().parse_args([*argv, "--model", model, "--memory", "off"])


def test_thomas_on_claude_without_a_key_is_refused_with_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def _loop(goal: str, **kwargs: Any) -> CliDispatchResult:
        captured.update(kwargs)
        return CliDispatchResult(True, "ok", "prompt", returncode=0)

    monkeypatch.setattr(agent_passes, "dispatch_via_agent_loop", _loop)
    monkeypatch.setattr(forge_code_runner, "_default_emit", lambda _event: None)
    assert forge_code_runner.run_configured_turn(_args(tmp_path, "claude", "thomas", CLAUDE_MODEL)) == 0
    assert captured["profile"] == "forgecode"
    assert captured["oauth_access_token"] == ""
    assert captured["token_check"]() is False
    assert captured["not_connected_msg"] == ANTHROPIC_KEY_MISSING_MSG
    monkeypatch.setenv("THOMAS_MODELS_FORGECODE_API_KEY", "sk-ant-test")
    assert captured["token_check"]() is True


def test_every_pass_carries_thomas_rules_from_the_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bound self-edit's history waiver and the run's fence reach whichever agent was picked."""
    seen: dict[str, dict[str, Any]] = {}

    def _capture(name: str) -> Any:
        def _dispatch(goal: str, **kwargs: Any) -> CliDispatchResult:
            seen[name] = kwargs
            return CliDispatchResult(True, "ok", "prompt", returncode=0)

        return _dispatch

    monkeypatch.setattr(agent_passes, "dispatch_via_agent_loop", _capture("thomas"))
    monkeypatch.setattr(agent_passes, "dispatch_via_claude_cli", _capture("claude_code"))
    for spec in builtin_registry():
        agent_passes.pass_for(spec)(
            AgentRunRequest(
                goal="build it",
                cwd=tmp_path,
                plan=spec.plan(CLAUDE_MODEL),
                protected_paths=["secrets.toml"],
                allow_without_history=True,
            )
        )
    for name in BUILTIN_AGENT_IDS:
        assert seen[name]["allow_without_history"] is True, name
        assert seen[name]["protected_paths"] == ["secrets.toml"], name


def test_the_same_task_with_each_agent_records_which_agent_and_model_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proof you named: one small task, once per agent in the picker."""
    ran: list[str] = []

    def _loop(goal: str, **kwargs: Any) -> CliDispatchResult:
        ran.append("thomas")
        return CliDispatchResult(True, "ok", "prompt", returncode=0)

    def _claude(goal: str, **kwargs: Any) -> CliDispatchResult:
        ran.append("claude_code")
        return CliDispatchResult(True, "ok", "prompt", returncode=0)

    monkeypatch.setattr(agent_passes, "dispatch_via_agent_loop", _loop)
    monkeypatch.setattr(agent_passes, "dispatch_via_claude_cli", _claude)
    monkeypatch.setattr(forge_code_runner, "_default_emit", lambda _event: None)
    conversation = forge_code_store.new_conversation(tmp_path)

    picker = builtin_registry().to_dict(model_id=CLAUDE_MODEL)
    for agent in picker["agents"]:
        settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": agent["id"]})
        args = _args(tmp_path, settings.family, settings.agent, settings.dispatch_model.split(":", 1)[-1])
        assert forge_code_runner.run_configured_turn(args) == 0
        forge_code_store.append_agent_turn(
            tmp_path,
            conversation["id"],
            model=settings.recorded_model(),
            agent=settings.capability_report()["effective"]["agent"],
            transcript="",
            changed_files=["hello.txt"],
            returncode=0,
            ok=True,
            noop=False,
            reason="ok",
        )

    assert ran == ["thomas", "claude_code"]
    recorded = forge_code_store.load_conversation(tmp_path, conversation["id"])["turns"]
    turns = [turn for turn in recorded if turn["role"] == "agent"]
    assert [(t["agent"], t["model"]) for t in turns] == [
        ("thomas", CLAUDE_MODEL),
        ("claude_code", f"claude:{CLAUDE_MODEL}"),
    ]
