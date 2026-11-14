"""The sessions slot: where every part of Thomas gets the store for a folder of chat sessions.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md (slots). Any process that may import ``thomas.chat``
can use it (``from thomas.chat.session_slot import sessions``): there is no kernel and no server in the way. The kernels
carry the same object under ``SESSIONS`` for rows that ask for it.

A store keeps its locks and its 500 ms save debounce on the instance, so they guard one process only. That is why the
slot hands out one store per folder per process, and why each surface gets a folder of its own: two processes must never
share a store.

This is the persistence half only. A chat that is running now stays where it is.
"""

from __future__ import annotations

import threading
from pathlib import Path

from thomas.chat.session_store import SessionStore, SessionUnreadable

__all__ = ["SessionUnreadable", "Sessions", "session_files", "sessions"]

#: The folder name for the chat surface. Every other surface is ``sessions_<surface>``.
_CHAT = "sessions_v2"


class Sessions:
    def __init__(self) -> None:
        self._stores: dict[Path, SessionStore] = {}
        self._guard = threading.Lock()

    def store(self, root: Path, *, surface: str = "chat") -> SessionStore:
        """The store for *surface* under *root*: ``<root>/.thomas/sessions_v2`` for chat, ``sessions_<surface>`` otherwise."""
        name = str(surface or "").strip()
        if not name:
            raise ValueError("a session store needs a surface name")
        folder = _CHAT if name == "chat" else f"sessions_{name}"
        return self.store_at(Path(root) / ".thomas" / folder)

    def store_at(self, folder: Path) -> SessionStore:
        """The one store for this folder in this process. The folder is made if it is not there."""
        key = Path(folder).resolve()
        with self._guard:
            found = self._stores.get(key)
            if found is None:
                found = self._stores[key] = SessionStore(key)
            else:
                key.mkdir(parents=True, exist_ok=True)
            return found


def session_files(source: SessionStore | Path) -> list[Path]:
    """Every session file in *source*: the store's ``files()``, or a bare folder's ``chat_*.json`` for a caller without one."""
    if isinstance(source, SessionStore):
        return source.files()
    return sorted(Path(source).glob("chat_*.json"))


_sessions = Sessions()


def sessions() -> Sessions:
    return _sessions
