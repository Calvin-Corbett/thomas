from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.forge.anvil import forge_code_runner
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.dispatch_claude_cli import CliDispatchResult
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, ForgeCodeSettingsError


def test_runner_start_gate_requires_the_unique_parent_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_CODE_START_GATE", "pipe")
    monkeypatch.setenv("THOMAS_CODE_START_TOKEN", "unique-run-token")

    assert forge_code_runner.start_gate_released(io.BytesIO(b"")) is False
    assert forge_code_runner.start_gate_released(io.BytesIO(b"not-json\n")) is False
    wrong = json.dumps({"gate_token": "wrong", "oauth_access_token": "must-not-pass"}).encode() + b"\n"
    assert forge_code_runner.start_gate_released(io.BytesIO(wrong)) is False
    valid = (
        json.dumps(
            {"gate_token": "unique-run-token", "oauth_access_token": "secret-token", "goal": "build safely"}
        ).encode()
        + b"\n"
    )
    gate = forge_code_runner.read_start_gate(io.BytesIO(valid))
    assert gate.released is True
    assert gate.oauth_access_token == "secret-token"
    assert gate.goal == "build safely"

    monkeypatch.delenv("THOMAS_CODE_START_GATE")
    assert forge_code_runner.start_gate_released(io.BytesIO(b"")) is True


def test_exact_gpt_settings_apply_model_and_reasoning_without_overclaiming() -> None:
    settings = ForgeCodeSettings.from_payload(
        {
            "model": "codex:gpt",
            "model_id": "gpt-5.6-codex",
            "reasoning_effort": "xhigh",
            "autonomy_level": 4,
            "file_access": "pc",
            "memory": False,
            "guardrails": "open",
            "token_economy": "cheap",
        }
    )

    assert settings.family == "gpt"
    assert settings.gpt_profile == "forgecode"
    env = settings.child_environment({"PRESERVE": "yes"})
    assert env["PRESERVE"] == "yes"
    assert env["THOMAS_MODELS_FORGECODE_MODEL"] == "gpt-5.6-codex"
    assert env["THOMAS_MODELS_FORGECODE_REASONING_EFFORT"] == "xhigh"
    assert env["THOMAS_MODELS_FORGECODE_CONTEXT_WINDOW"] == "200000"
    assert env["THOMAS_MODELS_FORGECODE_MAX_TOKENS"] == "16384"

    report = settings.capability_report()
    assert report["effective"]["model"] == "gpt-5.6-codex"
    assert report["support"]["reasoning_effort"]["status"] == "applied"
    assert report["support"]["file_access"] == {
        "status": "applied",
        "effective": "pc",
        "level": 3,
        "label": "Your PC",
        "reason": "writes may reach the selected project and the user's home folders",
    }
    assert report["support"]["autonomy_level"] == {
        "status": "applied",
        "effective": "edit_and_verify",
    }
    assert report["support"]["memory"] == {"status": "applied", "effective": "off"}
    assert report["support"]["guardrails"]["terminal"] == "enabled_in_selected_project"
    # cd0203a7 removed pass rationing: every economy reports the same generous
    # runaway ceiling, so the dial no longer decides how many passes exist.
    assert report["support"]["token_economy"]["max_fix_iters"] == 20


def test_read_only_low_autonomy_enforces_plan_only_without_history() -> None:
    settings = ForgeCodeSettings.from_payload(
        {
            "model_id": "gpt-5.6-sol",
            "autonomy_level": 2,
            "file_access": "read_only",
            "memory": False,
            "guardrails": "open",
            "token_economy": "max",
        }
    )

    assert settings.execution_policy() == {
        "live_edit": False,
        "history_enabled": False,
        "allow_shell": False,
        "timeout": 3600,
        "max_fix_iters": 20,
        "sandbox_root": "selected_project",
        "file_access": "read_only",
        "file_access_level": 0,
        "guardrails": "open",
        "guardrail_mode": "permissive",
    }
    report = settings.capability_report()
    assert report["effective"]["file_access"] == "read_only"
    assert report["support"]["autonomy_level"]["effective"] == "plan_only"


@pytest.mark.parametrize(
    ("value", "level"),
    [("read_only", 0), ("workspace", 1), ("project", 2), ("pc", 3), ("full", 4)],
)
def test_file_access_levels_remain_distinct_in_effective_policy(value: str, level: int) -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": "gpt-5.6-sol", "file_access": value})

    report = settings.capability_report()
    assert report["effective"]["file_access"] == value
    assert report["effective"]["file_access_level"] == level
    assert report["support"]["file_access"]["effective"] == value
    assert report["support"]["file_access"]["level"] == level


@pytest.mark.parametrize(
    ("value", "mode", "shell"),
    [("open", "permissive", True), ("guarded", "standard", False), ("fortress", "strict", False)],
)
def test_guardrail_presets_remain_distinct_in_effective_policy(value: str, mode: str, shell: bool) -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": "gpt-5.6-sol", "guardrails": value, "autonomy_level": 4})

    policy = settings.execution_policy()
    report = settings.capability_report()
    assert policy["guardrails"] == value
    assert policy["guardrail_mode"] == mode
    assert policy["allow_shell"] is shell
    assert report["support"]["guardrails"]["effective"] == value
    assert report["support"]["guardrails"]["mode"] == mode


def test_headless_prompt_carries_exact_file_access_guardrails_and_autonomy() -> None:
    prompt = compose_headless_prompt(
        "Build it",
        file_access="full",
        guardrails="fortress",
        autonomy_level=4,
    )

    assert "File access = full" in prompt
    assert "Guardrails = strict" in prompt
    assert "Autonomy level = 4" in prompt
    assert "progress updates at meaningful milestones" in prompt
    assert "not raw tool output" in prompt


def test_claude_settings_report_reasoning_as_unsupported() -> None:
    settings = ForgeCodeSettings.from_payload({"model": "claude:opus", "reasoning_effort": "high"})

    assert settings.family == "claude"
    assert settings.dispatch_model == "claude:opus"
    assert settings.child_environment({}) == {}
    report = settings.capability_report()
    assert report["support"]["model"]["status"] == "applied"
    assert report["support"]["reasoning_effort"]["status"] == "unsupported"


@pytest.mark.parametrize(
    "payload",
    [
        {"engine": "parallel"},
        {"model_id": "bad model id"},
        {"reasoning_effort": "infinite"},
        {"autonomy_level": 5},
        {"file_access": "internet"},
        {"memory": "sometimes"},
        {"guardrails": "disabled"},
        {"token_economy": "free"},
    ],
)
def test_invalid_settings_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ForgeCodeSettingsError):
        ForgeCodeSettings.from_payload(payload)


def test_configured_runner_reuses_agent_loop_and_propagates_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(forge_code_runner, "history_turns", lambda _root, _cid: [{"role": "user"}])

    def _dispatch(goal: str, **kwargs: object) -> CliDispatchResult:
        captured.update({"goal": goal, **kwargs})
        return CliDispatchResult(True, "finished", "prompt", returncode=0)

    monkeypatch.setattr(forge_code_runner, "dispatch_via_agent_loop", _dispatch)
    args = forge_code_runner.build_parser().parse_args(
        [
            "build it",
            "--project-root",
            str(tmp_path),
            "--conversation-id",
            "conv-1",
            "--family",
            "gpt",
            "--model",
            "gpt",
            "--profile",
            "forgecode",
        ]
    )

    assert forge_code_runner.run_configured_turn(args, oauth_access_token="pipe-token") == 0
    assert captured["goal"] == "build it"
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["profile"] == "forgecode"
    assert captured["token_check"]() is True
    assert captured["oauth_access_token"] == "pipe-token"
    assert captured["history"] == [{"role": "user"}]
    assert captured["file_access"] == "project"
    assert captured["guardrails"] == "guarded"
    assert captured["autonomy_level"] == 3
    assert captured["token_economy"] == "balanced"


def test_configured_runner_applies_every_execution_dial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(forge_code_runner, "history_turns", lambda _root, _cid: [{"role": "user"}])

    def _dispatch(goal: str, **kwargs: object) -> CliDispatchResult:
        captured.update({"goal": goal, **kwargs})
        return CliDispatchResult(False, "dry-run", "prompt", returncode=1)

    monkeypatch.setattr(forge_code_runner, "dispatch_via_agent_loop", _dispatch)
    args = forge_code_runner.build_parser().parse_args(
        [
            "review it",
            "--project-root",
            str(tmp_path),
            "--family",
            "gpt",
            "--model",
            "gpt",
            "--autonomy",
            "2",
            "--file-access",
            "read_only",
            "--memory",
            "off",
            "--guardrails",
            "open",
            "--token-economy",
            "max",
        ]
    )

    assert forge_code_runner.run_configured_turn(args) == 1
    assert captured["dry_run"] is True
    assert captured["history"] == []
    assert captured["allow_shell"] is False
    assert captured["timeout"] == 3600
    assert captured["max_fix_iters"] == 20
    assert captured["file_access"] == "read_only"
    assert captured["guardrails"] == "open"
    assert captured["autonomy_level"] == 2
    assert captured["token_economy"] == "max"


def test_agent_loop_dispatch_forwards_nondefault_effort_to_agent() -> None:
    from thomas.core.events import EventType
    from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator, _translate_agent_stream

    class _CapturingAgent:
        token_economy = ""

        async def run(self, prompt: str, **kwargs: object):
            _ = prompt
            self.token_economy = str(kwargs.get("token_economy") or "")
            yield SimpleNamespace(type=EventType.AGENT_DONE, data={"text": "done"})

    agent = _CapturingAgent()
    translator = _AgentLoopForgeTranslator(lambda _event: None)

    asyncio.run(
        _translate_agent_stream(
            agent,
            "build it",
            timeout=1,
            tools_policy="auto",
            token_economy="max",
            translator=translator,
        )
    )

    assert agent.token_economy == "max"
