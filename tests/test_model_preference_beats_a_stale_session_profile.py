"""The model you picked applies to chats you started before you picked it."""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core.config import AppConfig, ModelConfig, ToolsConfig
from thomas.preferences.store import PreferencesPatch, PreferencesStore
from thomas.server.chat_runtime_policy import resolve_chat_runtime_policy


class _SessionMeta:
    """The fields chat_runtime_policy reads off a stored session row."""

    def __init__(self, profile: str = "", model_id: str | None = None) -> None:
        self.profile = profile
        self.model_id = model_id
        self.autonomy_level = 2
        self.system_prompt = None
        self.reasoning_effort = None
        self.memory_enabled = True


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={
            "local": ModelConfig(
                name="local",
                provider="openai_compat",
                base_url="http://127.0.0.1:11434/v1",
                model="qwen2.5-coder:7b",
            ),
            "openai_codex": ModelConfig(
                name="openai_codex",
                provider="openai_codex",
                base_url="https://chatgpt.com/backend-api/codex",
                model="gpt-5.6-terra",
            ),
        },
        default_model="local",
        tools=ToolsConfig(sandbox_root=str(tmp_path)),
    )


def _prefer_codex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "preferences.sqlite"
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    PreferencesStore(str(db_path)).patch(
        PreferencesPatch.model_validate(
            {"advanced": {"model": {"active_profile": "openai_codex", "model_id": "gpt-5.6-terra"}}}
        ),
        user_id="default",
    )


def _resolve(config: AppConfig, saved_meta: _SessionMeta | None, payload: dict | None = None):
    meta = saved_meta if saved_meta is not None else _SessionMeta()
    return resolve_chat_runtime_policy(
        payload=payload or {},
        session_meta=meta,
        saved_meta=saved_meta,
        config=config,
        session_id="session-1",
        user_id="default",
    )


def test_a_chat_started_before_you_picked_a_model_still_uses_the_model_you_picked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: AppConfig
) -> None:
    """PATCH advanced.model, then take a turn on a chat that predates it.

    Measured on the same session meta, payload ``{}``, before and after the
    precedence change in ``chat_runtime_policy``::

        before: ('local', '')                      <- the reported revert
        after:  ('openai_codex', 'gpt-5.6-terra')

    ``local`` renders as "Local" in the shell, and the empty model_id is the
    half that breaks Code: an unspecified model becomes ``claude:sonnet`` in
    ``ForgeCodeSettings.from_payload``, so every run goes to the Claude CLI.

    The stored preference was never wrong -- it round-trips and survives boot
    unchanged. What outranked it was the session's own ``profile`` snapshot,
    which sessions are BORN with (``sessions_aiohttp`` creates rows with
    ``profile=<current default>``) and which ``chat_v2`` rewrites from this
    function's own answer on every turn, so it re-armed itself forever.
    """
    _prefer_codex(monkeypatch, tmp_path)
    stale = _SessionMeta(profile="local", model_id=None)

    policy = _resolve(config, stale)
    assert (policy.profile, policy.model_id) == ("openai_codex", "gpt-5.6-terra")

    # chat_v2 writes the resolved profile back onto the session, so the next
    # turn must stay fixed rather than flip back.
    stale.profile = policy.profile
    stale.model_id = policy.model_id or None
    again = _resolve(config, stale)
    assert (again.profile, again.model_id) == ("openai_codex", "gpt-5.6-terra")


def test_a_fresh_chat_uses_the_model_you_picked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: AppConfig
) -> None:
    """CONTROL: the same assertion on a session with no saved meta.

    This passed before the fix too. It is here so the test above cannot be
    read as "the preference never applies anywhere" -- the preference always
    worked for new chats, which is why the revert looked intermittent.
    """
    _prefer_codex(monkeypatch, tmp_path)
    policy = _resolve(config, None)
    assert (policy.profile, policy.model_id) == ("openai_codex", "gpt-5.6-terra")


def test_a_profile_sent_with_the_turn_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: AppConfig
) -> None:
    """An explicit per-turn profile outranks the preference, as before."""
    _prefer_codex(monkeypatch, tmp_path)
    policy = _resolve(config, _SessionMeta(profile="local"), payload={"profile": "local"})
    assert policy.profile == "local"


def test_a_preference_naming_an_unknown_profile_leaves_the_session_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config: AppConfig
) -> None:
    """A stale preference name must not strand a chat on a working profile.

    The preferences API has historically stored display-cased names such as
    "Local", which match no key in ``config.models``. Those must keep losing to
    the session, so promoting the preference cannot make a bad name worse.
    """
    db_path = tmp_path / "preferences.sqlite"
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    PreferencesStore(str(db_path)).patch(
        PreferencesPatch.model_validate({"advanced": {"model": {"active_profile": "Local"}}}),
        user_id="default",
    )
    policy = _resolve(config, _SessionMeta(profile="openai_codex", model_id="gpt-5.6-terra"))
    assert (policy.profile, policy.model_id) == ("openai_codex", "gpt-5.6-terra")
