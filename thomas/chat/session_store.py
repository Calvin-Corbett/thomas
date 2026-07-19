"""Persistent session storage with automatic save.

CRITICAL FIX for Bug #2: conversations were only saved to disk when the
frontend explicitly called ``PUT /api/chat/{id}``.  Server crash = total loss.

New behaviour: ``SessionStore.save()`` is called by the orchestrator after
every completed turn.  Writes are **atomic** (temp-file + rename) to prevent
corruption on crash.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.core.autonomy import DEFAULT_AUTONOMY_LEVEL

log = logging.getLogger(__name__)


@dataclass
class SessionMeta:
    """Metadata about a chat session."""

    session_id: str
    surface_mode: str = "chat"
    context_id: str | None = None
    profile: str = ""
    model_id: str | None = None
    autonomy_level: int = DEFAULT_AUTONOMY_LEVEL  # L2 Assist — ask before acting (Calvin law)
    system_prompt: str | None = None
    reasoning_effort: str | None = None
    memory_enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    total_turns: int = 0
    token_spend: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "surface_mode": self.surface_mode,
            "context_id": self.context_id,
            "profile": self.profile,
            "model_id": self.model_id,
            "autonomy_level": self.autonomy_level,
            "system_prompt": self.system_prompt,
            "reasoning_effort": self.reasoning_effort,
            "memory_enabled": self.memory_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_turns": self.total_turns,
            "token_spend": self.token_spend,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMeta:
        return cls(
            session_id=data.get("session_id", ""),
            surface_mode=str(data.get("surface_mode") or "chat"),
            context_id=(str(data.get("context_id")) if data.get("context_id") else None),
            profile=data.get("profile", ""),
            model_id=data.get("model_id"),
            autonomy_level=data.get("autonomy_level", DEFAULT_AUTONOMY_LEVEL),
            system_prompt=data.get("system_prompt"),
            reasoning_effort=data.get("reasoning_effort"),
            memory_enabled=bool(data.get("memory_enabled", True)),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            total_turns=data.get("total_turns", 0),
            token_spend=data.get("token_spend", 0),
        )


class SessionStore:
    """Persistent session store with atomic auto-save.

    Sessions are stored as JSON files in ``store_dir``.  Every call to
    ``save()`` writes to a temporary file first, then renames atomically.
    This prevents half-written files from corrupting sessions on crash.

    Parameters
    ----------
    store_dir:
        Directory for session JSON files.  Created if it doesn't exist.
    auto_save_debounce_ms:
        Minimum interval between disk writes for the same session (prevents
        thrashing during rapid tool loops).  Default 500 ms.
    """

    _locks_guard = threading.Lock()

    def __init__(
        self,
        store_dir: Path,
        *,
        auto_save_debounce_ms: int = 500,
    ) -> None:
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._debounce_ms = auto_save_debounce_ms
        self._last_save: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._dirty: dict[str, bool] = {}
        log.info("SessionStore initialised at %s", self._store_dir)

    # ── file layout ──────────────────────────────────────────────

    def _session_path(self, session_id: str) -> Path:
        """Deterministic file path for a session (SHA-256 prefix for safety)."""
        safe = hashlib.sha256(session_id.encode()).hexdigest()[:16]
        return self._store_dir / f"chat_{safe}.json"

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        with self._locks_guard:
            if session_id not in self._locks:
                self._locks[session_id] = asyncio.Lock()
            return self._locks[session_id]

    # ── save ─────────────────────────────────────────────────────

    async def save(
        self,
        session_id: str,
        conversation: ConversationManager,
        meta: SessionMeta | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """Atomically persist a session to disk.

        Returns ``True`` if actually written, ``False`` if debounced.
        """
        now = time.monotonic()
        last = self._last_save.get(session_id, 0.0)
        if not force and (now - last) * 1000 < self._debounce_ms:
            self._dirty[session_id] = True
            return False

        lock = self._lock_for(session_id)
        async with lock:
            return await self._write_atomic(session_id, conversation, meta)

    async def _write_atomic(
        self,
        session_id: str,
        conversation: ConversationManager,
        meta: SessionMeta | None,
    ) -> bool:
        """Write JSON via temp file + atomic rename."""
        target = self._session_path(session_id)
        payload: dict[str, Any] = {
            "session_id": session_id,
            "saved_at": time.time(),
            "conversation": conversation.to_dict(),
        }
        if meta:
            payload["meta"] = meta.to_dict()

        try:
            data = json.dumps(payload, default=str, ensure_ascii=False)
            # Write to temp file in same directory (same filesystem → rename is atomic)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._store_dir),
                prefix=".tmp_session_",
                suffix=".json",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp_path, str(target))
            except OSError:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            self._last_save[session_id] = time.monotonic()
            self._dirty.pop(session_id, None)
            log.debug(
                "Session %s saved (%d messages, v%d)",
                session_id[:12],
                conversation.length,
                conversation.version,
            )
            return True

        except Exception:
            # Broad catch: auto-save is best-effort and must not crash an active chat turn.
            log.exception("Failed to save session %s", session_id[:12])
            return False

    async def flush_dirty(
        self, session_id: str, conversation: ConversationManager, meta: SessionMeta | None = None
    ) -> bool:
        """Force-save if there's a pending debounced write."""
        if self._dirty.get(session_id):
            return await self.save(session_id, conversation, meta, force=True)
        return False

    # ── load ─────────────────────────────────────────────────────

    async def load(
        self,
        session_id: str,
    ) -> ConversationManager | None:
        """Load a conversation from disk.  Returns ``None`` if not found."""
        target = self._session_path(session_id)
        if not target.exists():
            return None

        lock = self._lock_for(session_id)
        async with lock:
            try:
                raw = await asyncio.to_thread(target.read_text, "utf-8")
                data = json.loads(raw)
                conv_data = data.get("conversation", {})
                return ConversationManager.from_dict(conv_data)
            except Exception:
                # Broad catch: corrupt or incompatible session files should not block chat startup.
                log.exception("Failed to load session %s", session_id[:12])
                return None

    async def load_meta(self, session_id: str) -> SessionMeta | None:
        """Load session metadata only."""
        target = self._session_path(session_id)
        if not target.exists():
            return None
        try:
            raw = await asyncio.to_thread(target.read_text, "utf-8")
            data = json.loads(raw)
            meta_data = data.get("meta")
            if meta_data:
                return SessionMeta.from_dict(meta_data)
            return None
        except Exception:
            # Broad catch: metadata is optional and malformed files should not block recovery.
            log.exception("Failed to load meta for %s", session_id[:12])
            return None

    # ── list / cleanup ───────────────────────────────────────────

    async def list_sessions(self) -> list[str]:
        """Return session IDs of all persisted sessions."""
        sessions = []
        for p in self._store_dir.glob("chat_*.json"):
            try:
                raw = await asyncio.to_thread(p.read_text, "utf-8")
                data = json.loads(raw)
                sid = data.get("session_id", "")
                if sid:
                    sessions.append(sid)
            except Exception:
                # Broad catch: skip unreadable or malformed session files while listing sessions.
                log.exception("Skipping unreadable session file %s", p)
                continue
        return sessions

    async def delete(self, session_id: str) -> bool:
        """Remove a session from disk."""
        target = self._session_path(session_id)
        if target.exists():
            try:
                os.unlink(str(target))
                self._dirty.pop(session_id, None)
                self._last_save.pop(session_id, None)
                return True
            except OSError as exc:
                log.error("Failed to delete session %s: %s", session_id[:12], exc)
        return False

    async def vacuum(self, older_than_hours: int = 72) -> int:
        """Remove sessions older than the given threshold.  Returns count."""
        cutoff = time.time() - (older_than_hours * 3600)
        removed = 0
        for p in self._store_dir.glob("chat_*.json"):
            try:
                raw = await asyncio.to_thread(p.read_text, "utf-8")
                data = json.loads(raw)
                saved_at = data.get("saved_at", 0)
                if saved_at < cutoff:
                    os.unlink(str(p))
                    removed += 1
            except Exception:
                # Broad catch: vacuum should continue past corrupt or concurrently removed files.
                log.exception("Skipping session file during vacuum: %s", p)
                continue
        if removed:
            log.info("Vacuumed %d stale sessions (older than %dh)", removed, older_than_hours)
        return removed
