"""The Agent choice does what it says, end to end.

An independent check of bc982119 found the choice unfinished where you would
meet it: Chat's hand-off refused every Claude Code pick, the refusal sent you to
a Settings key Thomas's loop never read, ``ANTHROPIC_BASE_URL`` in its usual
form made Anthropic answer 404, and a key in the environment quietly moved every
unpicked Claude conversation off Claude Code. Each test here holds one of those
closed. The picker's own half is tests/web_node/coding_agent_picker.mjs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.core.coding_agents import (
    ANTHROPIC_KEY_MISSING_MSG,
    anthropic_api_key,
    anthropic_api_root,
    builtin_registry,
    read_stored_anthropic_key_with,
    resolve,
)
from thomas.forge.anvil import agent_passes, forge_code_runner
from thomas.forge.anvil.agent_continuity import agent_that_ran, keep_conversation_agent
from thomas.forge.anvil.dispatch_claude_cli import CliDispatchResult
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server.app_keys import APP_SECRETS
from thomas.server.praxis.intake import DEFAULT_DELEGATION_MODEL_ID, build_choice, delegation_model_id
from thomas.server.routes import evolve_agent_http_support
from thomas.server.routes.evolve_agent_agents_routes import saved_anthropic_key
from thomas.server.secrets import SecretStore

CLAUDE_MODEL = "claude-sonnet-4-5"


@pytest.fixture(autouse=True)
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("ANTHROPIC_API_KEY", "THOMAS_ANTHROPIC_API_KEY", "THOMAS_MODELS_FORGECODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))


def _app_with_saved_key(tmp_path: Path, key: str = "sk-ant-saved", profile: str = "anthropic") -> web.Application:
    app = web.Application()
    store = SecretStore(tmp_path / "secrets")
    store.set(profile, key, persist=False)
    app[APP_SECRETS] = store
    return app


# -- Point 4: Chat's hand-off sends a model the picked agent runs ---------------


def test_a_claude_code_hand_off_is_not_sent_gpt() -> None:
    """Before: every hand-off ran gpt-5.6-sol, so a Claude Code pick was refused with HTTP 400."""
    picked = build_choice({"build_agent": "claude_code"})
    assert delegation_model_id(picked) == "sonnet"
    ForgeCodeSettings.from_payload({"model_id": delegation_model_id(picked), "agent": "claude_code"})
    chip = build_choice({"build_agent": "claude_code", "build_model_id": CLAUDE_MODEL})
    assert delegation_model_id(chip) == CLAUDE_MODEL
    assert delegation_model_id(build_choice({})) == DEFAULT_DELEGATION_MODEL_ID  # no pick: as before


# -- Point 6: a key saved in the app is a key Thomas's loop uses ----------------


def test_the_key_saved_in_the_app_reaches_thomas(tmp_path: Path) -> None:
    app = _app_with_saved_key(tmp_path)
    assert saved_anthropic_key(app) == "sk-ant-saved"
    assert anthropic_api_key() == ""  # nothing has told core where the app keeps keys yet
    read_stored_anthropic_key_with(lambda: saved_anthropic_key(app))
    assert anthropic_api_key() == "sk-ant-saved"
    selection = resolve(builtin_registry(), model_id=CLAUDE_MODEL, requested="thomas")
    assert selection.spec.reaches_family("claude")


def test_only_the_anthropic_profile_key_is_sent_to_anthropic(tmp_path: Path) -> None:
    """Another profile on the anthropic provider may be a different service; its key stays home."""
    assert saved_anthropic_key(_app_with_saved_key(tmp_path, profile="minimax")) == ""


def test_settings_anthropic_configuration_is_read_too(tmp_path: Path) -> None:
    from thomas.preferences.store import PreferencesStore, get_db_path

    PreferencesStore(get_db_path()).set_api_key("default", "anthropic", "sk-ant-from-settings")
    app = web.Application()
    assert saved_anthropic_key(app) == "sk-ant-from-settings"


def test_with_no_key_the_picker_says_why_thomas_cannot_reach_claude() -> None:
    thomas = next(a for a in builtin_registry().to_dict(model_id=CLAUDE_MODEL)["agents"] if a["id"] == "thomas")
    assert thomas["reaches_selected_model"] is False
    assert thomas["unreachable"] == ANTHROPIC_KEY_MISSING_MSG
    # It names places the key is actually read from, not an environment variable in Settings.
    assert "model menu" in ANTHROPIC_KEY_MISSING_MSG and "Anthropic Configuration" in ANTHROPIC_KEY_MISSING_MSG


def test_the_saved_key_rides_the_start_pipe_not_the_environment(tmp_path: Path) -> None:
    app = _app_with_saved_key(tmp_path)
    read_stored_anthropic_key_with(lambda: saved_anthropic_key(app))
    prepare = evolve_agent_http_support.prepare_code_oauth_credential
    assert asyncio.run(prepare(app, "claude", agent="thomas")) == ("sk-ant-saved", None)
    assert asyncio.run(prepare(app, "claude", agent="claude_code")) == ("", None)
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": "thomas"})
    assert "THOMAS_MODELS_FORGECODE_API_KEY" not in settings.child_environment({})


def test_the_runner_hands_the_pipe_key_to_thomas_on_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _loop(goal: str, **kwargs: Any) -> CliDispatchResult:
        captured.update(kwargs)
        return CliDispatchResult(True, "ok", "prompt", returncode=0)

    monkeypatch.setattr(agent_passes, "dispatch_via_agent_loop", _loop)
    monkeypatch.setattr(forge_code_runner, "_default_emit", lambda _event: None)
    argv = ["build it", "--project-root", str(tmp_path), "--family", "claude", "--agent", "thomas"]
    args = forge_code_runner.build_parser().parse_args([*argv, "--model", CLAUDE_MODEL, "--memory", "off"])
    assert forge_code_runner.run_configured_turn(args, oauth_access_token="sk-ant-saved") == 0
    assert captured["oauth_access_token"] == "sk-ant-saved"  # set on the profile in-process
    assert captured["token_check"]() is True


# -- Point 7: ANTHROPIC_BASE_URL in the SDK's form ------------------------------


@pytest.mark.parametrize(
    ("sdk_value", "root"),
    [
        ("", "https://api.anthropic.com/v1"),
        ("https://api.anthropic.com", "https://api.anthropic.com/v1"),
        ("https://api.anthropic.com/", "https://api.anthropic.com/v1"),
        ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1"),
        ("https://proxy.example/anthropic", "https://proxy.example/anthropic/v1"),
    ],
)
def test_the_sdk_base_url_becomes_the_api_root(sdk_value: str, root: str) -> None:
    assert anthropic_api_root(sdk_value) == root


def test_the_child_profile_gets_the_api_root() -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": "thomas"})
    env = settings.child_environment({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
    assert env["THOMAS_MODELS_FORGECODE_BASE_URL"] == "https://api.anthropic.com/v1"


# -- Point 8: a key does not quietly move a conversation ------------------------


def _conversation(*turns: dict[str, Any]) -> dict[str, Any]:
    return {"id": "c1", "turns": [{"role": "user", "text": "hi"}, *turns]}


def test_an_unpicked_claude_code_conversation_stays_on_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL})
    assert settings.agent == "thomas"  # the default a new conversation gets, which the picker names
    before_the_picker = _conversation({"role": "agent", "model": f"claude:{CLAUDE_MODEL}"})
    for conversation in (before_the_picker, _conversation({"role": "agent", "agent": "claude_code"})):
        kept = keep_conversation_agent(settings, conversation)
        assert (kept.agent, kept.agent_picked) == ("claude_code", False)
        assert kept.recorded_model() == f"claude:{CLAUDE_MODEL}"  # the prefix stays true
        assert "THOMAS_MODELS_FORGECODE_PROVIDER" not in kept.child_environment({"ANTHROPIC_API_KEY": "sk-ant-env"})
        report = kept.capability_report()["support"]["agent"]
        assert report["status"] == "resolved" and "stayed on Claude Code" in report["reason"]


def test_a_pick_or_a_new_conversation_is_not_held_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    ran_on_claude_code = _conversation({"role": "agent", "agent": "claude_code"})
    picked = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL, "agent": "thomas"})
    assert keep_conversation_agent(picked, ran_on_claude_code).agent == "thomas"
    unpicked = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL})
    assert keep_conversation_agent(unpicked, _conversation()).agent == "thomas"
    assert keep_conversation_agent(unpicked, None).agent == "thomas"


def test_a_thomas_conversation_with_no_key_left_is_not_kept_on_a_dead_end() -> None:
    settings = ForgeCodeSettings.from_payload({"model_id": CLAUDE_MODEL})
    assert settings.agent == "claude_code"
    kept = keep_conversation_agent(settings, _conversation({"role": "agent", "agent": "thomas"}))
    assert kept.agent == "claude_code"


def test_the_agent_that_ran_is_read_from_the_latest_agent_turn() -> None:
    assert agent_that_ran(None) == ""
    assert agent_that_ran(_conversation()) == ""
    assert agent_that_ran(_conversation({"role": "agent", "model": "gpt-5.6-sol"})) == "thomas"
    turns = ({"role": "agent", "agent": "thomas"}, {"role": "agent", "model": "claude:sonnet"})
    assert agent_that_ran(_conversation(*turns)) == "claude_code"
