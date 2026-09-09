import asyncio

from thomas.core.config import AppConfig, ModelConfig
from thomas.integrations.telegram import (
    TelegramBridge,
    _TelegramSession,
    load_sessions,
    parse_allowed_chat_ids,
    parse_telegram_command,
    save_sessions,
    split_telegram_text,
)
from thomas.tools.registry import ToolRegistry


def _make_config() -> AppConfig:
    return AppConfig(
        models={
            "local": ModelConfig(name="local"),
            "codex": ModelConfig(name="codex", provider="codex", model="gpt-5.2-codex"),
        },
        default_model="local",
    )


def test_parse_allowed_chat_ids_handles_empty() -> None:
    assert parse_allowed_chat_ids(None) == set()
    assert parse_allowed_chat_ids("") == set()


def test_parse_allowed_chat_ids_ignores_invalid_values() -> None:
    out = parse_allowed_chat_ids("123, 456;bad, -7, nope")
    assert out == {123, 456, -7}


def test_parse_telegram_command_with_bot_suffix() -> None:
    assert parse_telegram_command("/reset@thomas_bot") == ("/reset", "")
    assert parse_telegram_command("/model@thomas_bot codex") == ("/model", "codex")
    assert parse_telegram_command("hello") is None


def test_split_telegram_text_round_trip() -> None:
    text = ("a" * 2000) + "\n" + ("b" * 2000) + "\n" + ("c" * 2000)
    parts = split_telegram_text(text, max_len=4096)
    assert len(parts) == 2
    assert "".join(parts) == text
    assert all(len(p) <= 4096 for p in parts)


def test_split_telegram_text_small_payload() -> None:
    assert split_telegram_text("hello", max_len=4096) == ["hello"]


def test_save_load_sessions_round_trip(tmp_path) -> None:
    path = tmp_path / "telegram_sessions.json"
    sessions = {
        42: _TelegramSession(
            model_name="codex",
            conversation=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
                {"role": "x", "content": "skip"},
            ],
        )
    }
    save_sessions(path, sessions)

    loaded = load_sessions(path, default_model="local")
    assert set(loaded.keys()) == {42}
    assert loaded[42].model_name == "codex"
    assert loaded[42].conversation == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_bridge_thread_mode_switches_between_shared_and_isolated() -> None:
    cfg = _make_config()
    tools = ToolRegistry()

    default_isolated = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
    )
    shared = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
        shared_memory=True,
        shared_memory_thread="telegram:global",
    )
    isolated = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
        shared_memory=False,
    )

    assert default_isolated._thread_id_for_chat(123) == "telegram:123"
    assert default_isolated._memory_retrieval_scope == "thread"
    assert default_isolated._include_global_memory is True
    assert default_isolated._include_profile_memory is True
    assert shared._thread_id_for_chat(123) == "telegram:global"
    assert isolated._thread_id_for_chat(123) == "telegram:123"


def test_bridge_memory_retrieval_scope_coerces_all_to_thread() -> None:
    cfg = _make_config()
    tools = ToolRegistry()
    bridge = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
        memory_retrieval_scope="all",
    )
    assert bridge._memory_retrieval_scope == "thread"


def test_bridge_applies_memory_policy_when_supported() -> None:
    cfg = _make_config()
    tools = ToolRegistry()
    calls: list[dict[str, object]] = []

    class _Mem:
        def set_thread_memory_policy(self, thread_id: str, **kwargs):  # noqa: ANN001
            calls.append({"thread_id": thread_id, **kwargs})

    bridge = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=_Mem(),
        default_model="local",
        include_global_memory=False,
        include_profile_memory=True,
    )
    bridge._apply_thread_memory_policy("telegram:7")

    assert len(calls) == 1
    assert calls[0]["thread_id"] == "telegram:7"
    assert calls[0]["include_global"] is False
    assert calls[0]["include_profile"] is True


def test_bridge_model_command_persists_between_restarts(tmp_path) -> None:
    cfg = _make_config()
    tools = ToolRegistry()
    path = tmp_path / "telegram_sessions.json"

    bridge_a = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
        sessions_path=path,
    )
    reply = asyncio.run(bridge_a.handle_text(chat_id=7, text="/model codex"))
    assert "Switched this chat to model profile: codex" in reply

    bridge_b = TelegramBridge(
        config=cfg,
        tools=tools,
        memory=None,
        default_model="local",
        sessions_path=path,
    )
    status = asyncio.run(bridge_b.handle_text(chat_id=7, text="/model"))
    assert "Current model: codex" in status
