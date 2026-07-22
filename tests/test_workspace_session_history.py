from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from thomas.chat.session_store import SessionStore
from thomas.server.app_routes_init import _v2_sessions_as_chats
from thomas.server.routes.chat_surface_namespace import (
    ChatSurfaceNamespace,
    SessionNamespaceBindError,
    bind_chat_surface_session,
)


def _write_session(
    directory: Path, name: str, *, mode: str, context: str, saved_at: float
) -> None:
    path = directory / f"chat_{name}.json"
    path.write_text(
        json.dumps(
            {
                "session_id": name,
                "saved_at": saved_at,
                "meta": {"surface_mode": mode, "context_id": context},
                "conversation": {
                    "messages": [{"role": "user", "content": f"message {name}"}]
                },
            }
        ),
        encoding="utf-8",
    )
    os.utime(path, (saved_at, saved_at))


def test_workspace_history_filters_before_global_three_hundred_limit(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "mission-old",
        mode="workspace",
        context="workspace:mission",
        saved_at=1,
    )
    for index in range(301):
        _write_session(
            tmp_path,
            f"chat-{index}",
            mode="chat",
            context="",
            saved_at=1000 + index,
        )
    rows = _v2_sessions_as_chats(
        tmp_path, surface_mode="workspace", context_id="workspace:mission"
    )
    assert [row["id"] for row in rows] == ["mission-old"]


@pytest.mark.asyncio
async def test_concurrent_workspace_and_chat_first_turns_cannot_share_sid(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    workspace = ChatSurfaceNamespace("workspace", "workspace:mission")
    chat = ChatSurfaceNamespace("chat", "")

    async def _bind(namespace: ChatSurfaceNamespace):
        try:
            return await bind_chat_surface_session(
                store,
                session_id="same-new-sid",
                temporary=False,
                namespace=namespace,
            )
        except SessionNamespaceBindError as exc:
            return exc

    results = await asyncio.gather(_bind(workspace), _bind(chat))
    successes = [row for row in results if isinstance(row, tuple)]
    conflicts = [row for row in results if isinstance(row, SessionNamespaceBindError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status == 409
