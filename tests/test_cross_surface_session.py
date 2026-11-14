"""CAP-018: one server-side session identity across CLI, web, and companion.

Acceptance: "Use one server-side session identity across CLI, web, and
companion with automatic handoff."

Every test is hermetic: a temp-dir JSON store, an injected monotonic clock, and
an injected deterministic id factory. No network, no live model, no wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from thomas.core.cross_surface_session import (
    CrossSurfaceSessionRegistry,
    SessionView,
    UnknownSessionError,
    UnknownSurfaceError,
)


class _Clock:
    """Deterministic, monotonically advancing clock."""

    def __init__(self) -> None:
        self._t = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self._t += timedelta(seconds=1)
        return self._t


def _registry(tmp_path, *, session_id="sess-canonical-1"):
    return CrossSurfaceSessionRegistry(
        tmp_path / "sessions.json",
        clock=_Clock(),
        id_factory=lambda: session_id,
    )


def test_three_surfaces_resolve_to_one_identity_and_state(tmp_path):
    reg = _registry(tmp_path)
    created = reg.create_session("calvin")
    assert created.session_id == "sess-canonical-1"

    cli = reg.attach(created.session_id, "cli")
    web = reg.attach(created.session_id, "web")
    companion = reg.attach(created.session_id, "companion")

    # One identity across all three surfaces.
    assert cli.session_id == web.session_id == companion.session_id == created.session_id
    # One shared state container -- all three see the same (empty) state.
    assert cli.state == web.state == companion.state == {}
    # All three surfaces are registered against the single session.
    assert companion.surfaces == ("cli", "companion", "web")


def test_web_update_hands_off_to_cli_and_companion_on_refresh(tmp_path):
    reg = _registry(tmp_path)
    session = reg.create_session("calvin")
    reg.attach(session.session_id, "cli")
    reg.attach(session.session_id, "web")
    reg.attach(session.session_id, "companion")

    # Web advances the conversation.
    reg.update_state(session.session_id, "web", {"turn": 3, "topic": "handoff"})

    # Automatic handoff: cli and companion see the update on refresh, no new
    # session, and the registry records web as the last surface to touch it.
    cli_view = reg.refresh(session.session_id, "cli")
    companion_view = reg.refresh(session.session_id, "companion")

    assert cli_view.session_id == session.session_id
    assert companion_view.session_id == session.session_id
    assert cli_view.state == {"turn": 3, "topic": "handoff"}
    assert companion_view.state == {"turn": 3, "topic": "handoff"}
    assert cli_view.last_surface == "web"
    assert companion_view.last_surface == "web"


def test_handoff_is_bidirectional_and_merges(tmp_path):
    reg = _registry(tmp_path)
    session = reg.create_session("calvin")

    reg.update_state(session.session_id, "web", {"turn": 1})
    reg.update_state(session.session_id, "cli", {"turn": 2, "note": "cli-added"})

    web_view = reg.refresh(session.session_id, "web")
    assert web_view.state == {"turn": 2, "note": "cli-added"}
    assert web_view.last_surface == "cli"


def test_identity_and_state_survive_process_restart(tmp_path):
    store = tmp_path / "sessions.json"
    reg1 = CrossSurfaceSessionRegistry(store, clock=_Clock(), id_factory=lambda: "sess-durable")
    session = reg1.create_session("calvin")
    reg1.attach(session.session_id, "web")
    reg1.update_state(session.session_id, "web", {"draft": "hello"})

    # Simulated restart: a brand-new registry over the SAME store.
    reg2 = CrossSurfaceSessionRegistry(store, clock=_Clock())
    resumed = reg2.attach("sess-durable", "cli")

    assert resumed.session_id == session.session_id
    assert resumed.state == {"draft": "hello"}
    assert resumed.last_surface == "web"


def test_attach_unknown_session_signals_cleanly(tmp_path):
    reg = _registry(tmp_path)
    with pytest.raises(UnknownSessionError):
        reg.attach("does-not-exist", "cli")


def test_unknown_surface_rejected(tmp_path):
    reg = _registry(tmp_path)
    session = reg.create_session("calvin")
    with pytest.raises(UnknownSurfaceError):
        reg.attach(session.session_id, "watch")


def test_returned_state_is_a_defensive_copy(tmp_path):
    reg = _registry(tmp_path)
    session = reg.create_session("calvin")
    reg.update_state(session.session_id, "web", {"count": 1})

    view = reg.attach(session.session_id, "cli")
    view.state["count"] = 999  # mutate the returned snapshot
    fresh = reg.refresh(session.session_id, "web")
    assert fresh.state == {"count": 1}  # stored state is untouched


def test_env_var_overrides_store_path(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "custom_store.json"
    monkeypatch.setenv("THOMAS_CROSS_SURFACE_SESSION_STORE", str(target))
    reg = CrossSurfaceSessionRegistry(clock=_Clock(), id_factory=lambda: "sess-env")
    reg.create_session("calvin")
    assert reg.store_path == target
    assert target.exists()


def test_create_returns_session_view(tmp_path):
    reg = _registry(tmp_path)
    view = reg.create_session("calvin")
    assert isinstance(view, SessionView)
    assert view.user == "calvin"
    assert view.state == {}
    assert view.last_surface == ""
