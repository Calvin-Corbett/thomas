from __future__ import annotations

from pathlib import Path

import pytest

from thomas.cli.repl import ThomasREPL
from thomas.cli.repl_settings import ReplRuntimeSettings, save_repl_runtime_settings
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ToolsConfig


class _DummyTools:
    def list_categories(self) -> list[str]:
        return []

    def list_tools(self, _category: str | None = None) -> list[object]:
        return []


def _build_config(tmp_path: Path) -> AppConfig:
    runtime_root = (tmp_path / "runtime").resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        default_model="codex",
        models={
            "codex": ModelConfig(name="codex", provider="codex", model="gpt-5"),
            "local": ModelConfig(name="local", provider="local", model="qwen2.5-coder:7b"),
        },
        memory=MemoryConfig(root=str(runtime_root)),
        tools=ToolsConfig(sandbox_root=str(tmp_path.resolve())),
    )


def test_repl_restores_runtime_settings_on_startup(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    state_path = cfg.memory.root_path / ".thomas" / "cli" / "repl_runtime_state.json"
    save_repl_runtime_settings(
        state_path,
        ReplRuntimeSettings(
            autonomy_level=4,
            tools_policy="never",
            show_system_logs=True,
            activity_verbosity="debug",
        ),
    )

    repl = ThomasREPL(cfg, _DummyTools())
    assert repl._autonomy_level == 4
    assert repl._tools_policy == "never"
    assert repl._show_system_logs is True
    assert repl._activity_verbosity == "debug"


def test_repl_persists_runtime_settings_for_next_session(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)

    repl = ThomasREPL(cfg, _DummyTools())
    repl._autonomy_level = 2
    repl._tools_policy = "always"
    repl._show_system_logs = True
    repl._activity_verbosity = "minimal"
    repl._persist_runtime_settings()

    next_repl = ThomasREPL(cfg, _DummyTools())
    assert next_repl._autonomy_level == 2
    assert next_repl._tools_policy == "always"
    assert next_repl._show_system_logs is True
    assert next_repl._activity_verbosity == "minimal"


def test_repl_respects_chat_auto_failover_disabled_for_chat_llm(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    cfg.failover.enabled = True
    cfg.failover.chat_auto_failover = False

    repl = ThomasREPL(cfg, _DummyTools())
    llm = repl._get_llm()

    assert llm._failover_enabled is False


def test_repl_enables_failover_when_chat_auto_failover_enabled(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    cfg.failover.enabled = True
    cfg.failover.chat_auto_failover = True

    repl = ThomasREPL(cfg, _DummyTools())
    llm = repl._get_llm()

    assert llm._failover_enabled is True


@pytest.mark.asyncio
async def test_repl_clear_rotates_chat_memory_scope(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)

    repl = ThomasREPL(cfg, _DummyTools())
    before_session = repl._repl_session_id
    before_thread = repl._chat_thread_id
    repl._conversation = [{"role": "user", "content": "test"}]

    should_exit, handled = await repl._handle_slash("/clear")

    assert should_exit is False
    assert handled is True
    assert repl._conversation == []
    assert repl._repl_session_id != before_session
    assert repl._chat_thread_id != before_thread
    assert repl._chat_thread_id.startswith(repl._repl_session_id)


@pytest.mark.asyncio
async def test_repl_memory_command_rotates_thread_without_clearing_conversation(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)

    repl = ThomasREPL(cfg, _DummyTools())
    repl._conversation = [{"role": "user", "content": "keep this"}]
    before_session = repl._repl_session_id
    before_thread = repl._chat_thread_id

    async def _passthrough_arg(_command: str, incoming: str):
        return incoming

    repl._pick_slash_argument = _passthrough_arg  # type: ignore[assignment]

    should_exit, handled = await repl._handle_slash("/memory new")

    assert should_exit is False
    assert handled is True
    assert len(repl._conversation) == 1
    assert repl._repl_session_id != before_session
    assert repl._chat_thread_id != before_thread


@pytest.mark.asyncio
async def test_repl_memory_command_query_without_text_shows_usage(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    repl = ThomasREPL(cfg, _DummyTools())

    async def _passthrough_arg(_command: str, incoming: str):
        return incoming

    repl._pick_slash_argument = _passthrough_arg  # type: ignore[assignment]

    should_exit, handled = await repl._handle_slash("/memory query")

    assert should_exit is False
    assert handled is True


@pytest.mark.asyncio
async def test_repl_session_new_resets_conversation_and_scope(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    repl = ThomasREPL(cfg, _DummyTools())
    repl._conversation = [{"role": "user", "content": "old"}]
    repl._session_turns = 3
    before_session = repl._repl_session_id
    before_thread = repl._chat_thread_id

    async def _passthrough_arg(_command: str, incoming: str):
        return incoming

    repl._pick_slash_argument = _passthrough_arg  # type: ignore[assignment]

    should_exit, handled = await repl._handle_slash("/session new")

    assert should_exit is False
    assert handled is True
    assert repl._conversation == []
    assert repl._session_turns == 0
    assert repl._repl_session_id != before_session
    assert repl._chat_thread_id != before_thread


@pytest.mark.asyncio
async def test_repl_session_save_and_load_roundtrip(tmp_path: Path, monkeypatch) -> None:
    import thomas.cli.repl as repl_mod

    monkeypatch.setattr(repl_mod, "_HAS_MEMORY", False)
    monkeypatch.setattr(ThomasREPL, "_build_session", lambda self: object())
    cfg = _build_config(tmp_path)
    repl = ThomasREPL(cfg, _DummyTools())

    async def _passthrough_arg(_command: str, incoming: str):
        return incoming

    repl._pick_slash_argument = _passthrough_arg  # type: ignore[assignment]

    repl._conversation = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    repl._current_model = "local"
    repl._autonomy_level = 4
    repl._tools_policy = "never"
    repl._show_system_logs = True
    repl._activity_verbosity = "debug"
    save_exit, save_handled = await repl._handle_slash("/session save lane-a")

    repl._conversation = [{"role": "user", "content": "different"}]
    repl._current_model = "codex"
    repl._autonomy_level = 2
    repl._tools_policy = "auto"
    repl._show_system_logs = False
    repl._activity_verbosity = "minimal"
    before_load_session = repl._repl_session_id
    before_load_thread = repl._chat_thread_id
    load_exit, load_handled = await repl._handle_slash("/session load lane-a")

    assert save_exit is False
    assert save_handled is True
    assert load_exit is False
    assert load_handled is True
    assert repl._current_model == "local"
    assert repl._autonomy_level == 4
    assert repl._tools_policy == "never"
    assert repl._show_system_logs is True
    assert repl._activity_verbosity == "debug"
    assert repl._conversation == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    assert repl._session_turns == 1
    assert repl._repl_session_id != before_load_session
    assert repl._chat_thread_id != before_load_thread
