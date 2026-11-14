"""The sessions slot: one store per folder, a store that meets its contract, and both kernels carrying the slots."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from thomas.agent.kernel_wiring import default_kernel
from thomas.chat.conversation import ConversationManager
from thomas.chat.session_slot import Sessions, SessionUnreadable, sessions
from thomas.chat.session_store import SessionStore
from thomas.core.kernel import LLM, RUNS, SEAMS, SESSIONS, Kernel, RunsSeam, SessionsSeam, SessionStoreSeam, require
from thomas.core.llm_slot import models
from thomas.marketplace.observability import run_store
from thomas.server.plugin_startup import (
    APP_SESSION_DISPOSERS,
    dispose_plugin_handles,
    mount_plugin_handles,
    provide_session_services,
)
from thomas.server.routes import chat_v2_registration


def test_the_slot_and_the_store_meet_their_contracts(tmp_path: Path) -> None:
    assert isinstance(sessions(), SessionsSeam)
    assert isinstance(sessions().store(tmp_path), SessionStoreSeam)
    assert isinstance(run_store, RunsSeam)


def test_runs_is_a_named_seam() -> None:
    assert RUNS == "runs" and RUNS in SEAMS
    assert SEAMS.index(SESSIONS) < SEAMS.index(RUNS)


def test_a_store_that_cannot_list_does_not_meet_the_contract() -> None:
    class Half:
        async def load(self, session_id): ...

    assert not isinstance(Half(), SessionStoreSeam)


def test_one_store_per_folder_and_a_folder_for_each_surface(tmp_path: Path) -> None:
    slot = Sessions()
    chat = slot.store(tmp_path)
    assert slot.store(tmp_path) is chat
    assert chat.path_of("x").parent == (tmp_path / ".thomas" / "sessions_v2").resolve()
    telegram = slot.store(tmp_path, surface="telegram")
    assert telegram is not chat
    assert telegram.path_of("x").parent == (tmp_path / ".thomas" / "sessions_telegram").resolve()
    with pytest.raises(ValueError):
        slot.store(tmp_path, surface=" ")


def test_a_folder_that_went_away_is_made_again(tmp_path: Path) -> None:
    slot = Sessions()
    folder = tmp_path / "gone"
    first = slot.store_at(folder)
    folder.rmdir()
    assert slot.store_at(folder) is first
    assert folder.is_dir()


def test_lock_path_of_and_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert store.files() == []
    assert store.lock("a") is store.lock("a")
    assert store.lock("a") is not store.lock("b")

    async def go() -> None:
        await store.save("a", ConversationManager(), force=True)
        await store.save("b", ConversationManager(), force=True)

    asyncio.run(go())
    assert store.path_of("a").is_file()
    assert sorted(store.files()) == sorted([store.path_of("a"), store.path_of("b")])


def test_an_unreadable_session_is_still_not_an_empty_one() -> None:
    assert issubclass(SessionUnreadable, Exception)
    assert inspect.getmodule(SessionUnreadable).__name__ == "thomas.chat.session_store"


def test_chat_has_no_working_directory_fallback(tmp_path: Path) -> None:
    source = inspect.getsource(chat_v2_registration)
    assert 'Path(".thomas")' not in source
    with pytest.raises(RuntimeError):
        chat_v2_registration.register_chat_v2_route_set(
            None,  # type: ignore[arg-type]
            config=None,
            llm=None,
            tools=None,
            chat_handler=lambda request: None,  # type: ignore[arg-type,return-value]
            chat_store_dir=None,
            require_api_access=lambda request: None,
        )


def test_the_services_are_set_and_undone() -> None:
    kernel = Kernel()
    undos = provide_session_services(kernel.root)
    assert require(kernel.root, SESSIONS, SessionsSeam) is sessions()
    assert require(kernel.root, RUNS, RunsSeam) is run_store
    for undo in reversed(undos):
        undo()
    assert not kernel.root.has(SESSIONS) and not kernel.root.has(RUNS)


def test_the_process_kernel_gets_both_at_startup_and_gives_them_back() -> None:
    from thomas.agent.kernel_wiring import get_kernel, set_kernel

    set_kernel(default_kernel())
    try:
        app: dict = {}
        mount_plugin_handles(app)
        try:
            assert len(app[APP_SESSION_DISPOSERS]) == 2
            assert get_kernel().root[SESSIONS] is sessions()
            assert get_kernel().root[RUNS] is run_store
        finally:
            dispose_plugin_handles(app)
        assert not get_kernel().root.has(SESSIONS) and not get_kernel().root.has(RUNS)
    finally:
        set_kernel(None)


def test_a_default_kernel_still_leaves_them_for_the_server() -> None:
    assert default_kernel().root[LLM] is models()
    assert not default_kernel().root.has(SESSIONS)


@pytest.mark.asyncio
async def test_the_servers_own_kernel_carries_llm_sessions_and_runs(tmp_path: Path, monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from tests import plugin_view_fixture as views
    from thomas.server import app_core
    from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(TestServer(app_core.create_app(views.config_in(tmp_path))))
    await client.start_server()
    try:
        root = client.server.app[APP_RUNTIME_PLUGINS].kernel.root
        assert root[LLM] is models()
        assert root[SESSIONS] is sessions()
        assert root[RUNS] is run_store
    finally:
        await client.close()
