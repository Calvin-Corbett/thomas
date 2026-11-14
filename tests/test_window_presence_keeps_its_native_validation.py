"""Presence validation and WTS binding coverage survive retirement of the Express landing lane."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest
from scripts.cage.referee import presence, presence_win
from scripts.cage.referee.authstate import StateError


@pytest.mark.parametrize(
    "reading",
    [
        SimpleNamespace(locked=False, idle_seconds=-1, logon_session="a"),
        SimpleNamespace(locked=False, idle_seconds=float("nan"), logon_session="a"),
        SimpleNamespace(locked=False, idle_seconds=float("inf"), logon_session="a"),
        SimpleNamespace(locked=False, idle_seconds=True, logon_session="a"),
        SimpleNamespace(locked=False, idle_seconds="1", logon_session="a"),
        SimpleNamespace(locked="no", idle_seconds=1, logon_session="a"),
        SimpleNamespace(locked=False, idle_seconds=1, logon_session=""),
        SimpleNamespace(locked=False, idle_seconds=1, logon_session=None),
        SimpleNamespace(idle_seconds=1, logon_session="a"),
    ],
)
def test_invalid_presence_is_unavailable(reading: object) -> None:
    with pytest.raises(StateError) as error:
        presence.read_presence(SimpleNamespace(state=lambda: reading))
    assert error.value.code == "presence_unreadable"


@pytest.mark.parametrize("error", [OSError("WTS failed"), RuntimeError("reader failed"), AttributeError("missing")])
def test_a_failed_presence_reader_fails_closed(error: Exception) -> None:
    def fail() -> None:
        raise error

    with pytest.raises(StateError, match="presence_unreadable"):
        presence.read_presence(SimpleNamespace(state=fail))


def test_away_and_recent_touch_keep_their_exact_boundaries() -> None:
    assert presence.touched_recently(presence.Presence(False, 60, "a"))
    assert not presence.touched_recently(presence.Presence(False, 60.5, "a"))
    assert not presence.away(presence.Presence(False, 900, "a"), 15)
    assert presence.away(presence.Presence(False, 900.5, "a"), 15)
    assert presence.away(presence.Presence(True, 0, "a"), 15)


class FakeWts:
    def __init__(self, session: int = 2, **values: int) -> None:
        self.session = session
        self.info = presence_win.SessionInfo(
            **{
                "flags": 1,
                "logon_time": 5 * presence_win.TICKS,
                "last_input": 0,
                "current": 65 * presence_win.TICKS,
                **values,
            }
        )

    def active_session(self) -> int:
        return self.session

    def session_info(self, session_id: int) -> presence_win.SessionInfo:
        assert session_id == self.session
        return self.info


def test_windows_presence_preserves_lock_idle_and_logon_identity() -> None:
    seen = presence_win.WindowsPresence(FakeWts(last_input=50 * presence_win.TICKS)).state()
    assert seen == presence.Presence(False, 15.0, f"2:{5 * presence_win.TICKS}")
    assert presence_win.WindowsPresence(FakeWts(flags=0)).state().locked
    assert presence_win.WindowsPresence(FakeWts()).state().idle_seconds == 60
    assert (
        presence_win.WindowsPresence(FakeWts(logon_time=9 * presence_win.TICKS)).state().logon_session
        != seen.logon_session
    )


@pytest.mark.parametrize("reader", [FakeWts(presence_win.NO_SESSION), FakeWts(flags=0xFFFFFFFF), FakeWts(flags=7)])
def test_unknown_windows_sessions_never_count_as_presence(reader: FakeWts) -> None:
    with pytest.raises(OSError):
        presence_win.WindowsPresence(reader).state()
    with pytest.raises(StateError):
        presence.read_presence(presence_win.WindowsPresence(reader))


class NativeFunction:
    def __init__(self, function) -> None:
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch):
    freed: list[int | None] = []
    query = NativeFunction(lambda *_args: False)
    active = NativeFunction(lambda: 2)
    free = NativeFunction(lambda pointer: freed.append(pointer.value))
    kernel = SimpleNamespace(WTSGetActiveConsoleSessionId=active)
    wts = SimpleNamespace(WTSQuerySessionInformationW=query, WTSFreeMemory=free)
    monkeypatch.setattr(presence_win.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_kw: kernel if name == "kernel32" else wts, raising=False)
    reader = presence_win.NativeWts()
    return reader, query, free, freed


def test_native_prototypes_preserve_pointer_width(native) -> None:
    reader, query, free, _freed = native
    assert reader.active_session() == 2
    assert len(query.argtypes) == 5
    assert query.argtypes[-2]._type_ is ctypes.c_void_p
    assert free.argtypes == [ctypes.c_void_p] and free.restype is None


def test_native_query_failure_is_unavailable_without_freeing_an_unreturned_buffer(
    native, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, _query, _free, freed = native
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(OSError, match=r"WTSQuerySessionInformationW failed \(5\)"):
        reader.session_info(2)
    assert freed == []


@pytest.mark.parametrize("bad", ["", "short", "null"])
def test_native_session_buffers_are_read_and_always_freed(native, bad: str) -> None:
    from ctypes import wintypes

    reader, query, _free, freed = native
    info = reader._type()
    info.Data.SessionFlags = 1
    info.Data.LogonTime, info.Data.LastInputTime, info.Data.CurrentTime = 5, 8, 13

    def answer(_server, session, kind, buffer, size):
        assert session == 2 and kind == presence_win.WTS_SESSION_INFO_EX
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0] = None if bad == "null" else ctypes.addressof(info)
        ctypes.cast(size, ctypes.POINTER(wintypes.DWORD))[0] = 1 if bad == "short" else ctypes.sizeof(info)
        return True

    query.function = answer
    if bad:
        with pytest.raises(OSError, match="shorter than expected"):
            reader.session_info(2)
    else:
        assert reader.session_info(2) == presence_win.SessionInfo(1, 5, 8, 13)
    assert freed == [None if bad == "null" else ctypes.addressof(info)]


def test_native_binding_refuses_other_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(presence_win.sys, "platform", "not-windows")
    with pytest.raises(OSError, match="only runs on Windows"):
        presence_win.NativeWts()
