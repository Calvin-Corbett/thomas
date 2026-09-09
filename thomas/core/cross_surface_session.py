"""One server-side session identity shared across CLI, web, and companion.

A :class:`CrossSurfaceSessionRegistry` mints a single canonical
``session_id`` per user session and a shared state container. Every surface
(``cli``, ``web``, ``companion``) attaches to the *same* identity and reads the
*same* state. When one surface advances the shared state, the others see the
update on their next attach or refresh -- automatic handoff -- and the registry
records which surface last touched it.

The registry is backed by a durable JSON store (path overridable via the
``THOMAS_CROSS_SURFACE_SESSION_STORE`` environment variable) so the identity and
its state survive a process restart: a fresh registry pointed at the same store
resolves the same session and shared state.

This module is core-clean: it imports only from the standard library and does
not reach into ``agent``/``server``/``tools`` layers.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

_STORE_VERSION = 1
_SURFACES = ("cli", "web", "companion")
_VALID_SURFACES = frozenset(_SURFACES)

# JSON decode / filesystem errors that mean "no usable store yet". These are
# recovered from by starting from an empty document; anything else propagates.
_LOAD_ERRORS = (FileNotFoundError, json.JSONDecodeError, ValueError, OSError)


class CrossSurfaceSessionError(RuntimeError):
    """Base error for the cross-surface session registry."""


class UnknownSessionError(CrossSurfaceSessionError):
    """Raised when a surface references a session id that does not exist."""


class UnknownSurfaceError(CrossSurfaceSessionError):
    """Raised when a surface name is not one of cli/web/companion."""


def _default_store_path() -> Path:
    """Resolve the durable store path, honoring the env override."""
    override = str(os.environ.get("THOMAS_CROSS_SURFACE_SESSION_STORE") or "").strip()
    if override:
        return Path(override)
    try:
        from thomas.core.config import resolve_thomas_data_dir

        root = resolve_thomas_data_dir()
    except (ImportError, OSError, ValueError):
        root = Path.home() / ".thomas"
    return Path(root) / "cross_surface_sessions.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_surface(surface: str) -> str:
    name = str(surface or "").strip().lower()
    if name not in _VALID_SURFACES:
        raise UnknownSurfaceError(f"Unknown surface {surface!r}; expected one of {', '.join(_SURFACES)}.")
    return name


@dataclass(frozen=True)
class SessionView:
    """Immutable snapshot returned to a surface on attach/refresh/update.

    ``state`` is a defensive copy of the shared container: mutating it never
    changes stored state (updates go through :meth:`CrossSurfaceSessionRegistry.update_state`).
    """

    session_id: str
    user: str
    surface: str
    state: dict[str, Any] = field(default_factory=dict)
    last_surface: str = ""
    surfaces: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""


class CrossSurfaceSessionRegistry:
    """Server-side registry giving every surface one shared session identity."""

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store_path = Path(store_path) if store_path is not None else _default_store_path()
        self._clock = clock or _utcnow
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._lock = threading.RLock()

    # -- public API ------------------------------------------------------
    @property
    def store_path(self) -> Path:
        return self._store_path

    def create_session(self, user: str) -> SessionView:
        """Mint one canonical session identity with an empty shared state."""
        now = self._timestamp()
        session_id = str(self._id_factory()).strip()
        if not session_id:
            raise CrossSurfaceSessionError("id_factory produced an empty session id.")
        record = {
            "session_id": session_id,
            "user": str(user or ""),
            "created_at": now,
            "updated_at": now,
            "last_surface": "",
            "surfaces": {},
            "state": {},
        }
        with self._lock:
            doc = self._load()
            sessions = doc["sessions"]
            if session_id in sessions:
                raise CrossSurfaceSessionError(f"Session id {session_id!r} already exists.")
            sessions[session_id] = record
            self._save(doc)
        return self._view(record, surface="")

    def attach(self, session_id: str, surface: str) -> SessionView:
        """Register ``surface`` to the existing session and return shared state.

        All of cli/web/companion resolve to the one identity and one state.
        """
        name = _normalize_surface(surface)
        now = self._timestamp()
        with self._lock:
            doc = self._load()
            record = self._require(doc, session_id)
            surfaces = record.setdefault("surfaces", {})
            entry = surfaces.get(name)
            if isinstance(entry, Mapping):
                merged = dict(entry)
                merged["last_seen"] = now
                surfaces[name] = merged
            else:
                surfaces[name] = {"attached_at": now, "last_seen": now}
            self._save(doc)
            return self._view(record, surface=name)

    def refresh(self, session_id: str, surface: str) -> SessionView:
        """Re-read the shared state for ``surface`` (sees others' updates)."""
        name = _normalize_surface(surface)
        now = self._timestamp()
        with self._lock:
            doc = self._load()
            record = self._require(doc, session_id)
            surfaces = record.setdefault("surfaces", {})
            entry = surfaces.get(name)
            if isinstance(entry, Mapping):
                merged = dict(entry)
                merged["last_seen"] = now
                surfaces[name] = merged
                self._save(doc)
            return self._view(record, surface=name)

    def update_state(
        self,
        session_id: str,
        surface: str,
        updates: Mapping[str, Any],
    ) -> SessionView:
        """Merge ``updates`` into the shared state and record the handoff.

        The updating surface becomes ``last_surface``; every other surface sees
        the merged state on its next attach/refresh without a new session.
        """
        name = _normalize_surface(surface)
        if not isinstance(updates, Mapping):
            raise CrossSurfaceSessionError("updates must be a mapping of state changes.")
        now = self._timestamp()
        with self._lock:
            doc = self._load()
            record = self._require(doc, session_id)
            state = record.setdefault("state", {})
            state.update({str(key): value for key, value in updates.items()})
            record["last_surface"] = name
            record["updated_at"] = now
            surfaces = record.setdefault("surfaces", {})
            entry = surfaces.get(name)
            if isinstance(entry, Mapping):
                merged = dict(entry)
                merged["last_seen"] = now
                surfaces[name] = merged
            else:
                surfaces[name] = {"attached_at": now, "last_seen": now}
            self._save(doc)
            return self._view(record, surface=name)

    def get(self, session_id: str) -> SessionView:
        """Return the current shared session view without touching a surface."""
        with self._lock:
            doc = self._load()
            record = self._require(doc, session_id)
            return self._view(record, surface="")

    # -- internals -------------------------------------------------------
    def _timestamp(self) -> str:
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()

    def _require(self, doc: dict[str, Any], session_id: str) -> dict[str, Any]:
        record = doc["sessions"].get(str(session_id or ""))
        if not isinstance(record, dict):
            raise UnknownSessionError(f"No cross-surface session for id {session_id!r}.")
        return record

    def _view(self, record: Mapping[str, Any], *, surface: str) -> SessionView:
        state = record.get("state")
        surfaces = record.get("surfaces")
        return SessionView(
            session_id=str(record.get("session_id") or ""),
            user=str(record.get("user") or ""),
            surface=surface,
            state=dict(state) if isinstance(state, Mapping) else {},
            last_surface=str(record.get("last_surface") or ""),
            surfaces=tuple(sorted(surfaces)) if isinstance(surfaces, Mapping) else (),
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
        )

    def _load(self) -> dict[str, Any]:
        try:
            raw = self._store_path.read_text(encoding="utf-8")
        except _LOAD_ERRORS:
            return {"version": _STORE_VERSION, "sessions": {}}
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return {"version": _STORE_VERSION, "sessions": {}}
        if not isinstance(doc, dict):
            return {"version": _STORE_VERSION, "sessions": {}}
        sessions = doc.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        return {"version": _STORE_VERSION, "sessions": sessions}

    def _save(self, doc: Mapping[str, Any]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dict(doc), sort_keys=True, ensure_ascii=False, indent=2)
        tmp = self._store_path.with_name(self._store_path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._store_path)


__all__ = [
    "CrossSurfaceSessionError",
    "CrossSurfaceSessionRegistry",
    "SessionView",
    "UnknownSessionError",
    "UnknownSurfaceError",
]
