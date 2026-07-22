"""Tests for the in-sandbox browser/desktop control port (CAP-061).

Acceptance line: "Drive a GUI/browser inside a sandbox and stream observations/
actions back, scoped to that sandbox."

These are hermetic: they use the in-memory :class:`FakeDisplay`, no network, no
wall-clock, and an injected deterministic seq clock. The live CDP transport is
NOT exercised (it needs a real sandboxed display) -- only its pure command
mapping is asserted.
"""

from __future__ import annotations

import pytest

from thomas.tools.sandbox_control import (
    ACTION_CLICK,
    ACTION_NAVIGATE,
    ACTION_SCREENSHOT,
    ACTION_TYPE,
    CdpDisplayTransport,
    ControlAction,
    FakeDisplay,
    LiveDisplayUnavailable,
    SandboxControlSession,
    SandboxScopeError,
    UnknownActionError,
    UnknownSandboxError,
    cdp_command_for,
    command_method,
    open_session,
)


def _display(*sandbox_ids: str) -> FakeDisplay:
    return FakeDisplay(list(sandbox_ids))


# ---------------------------------------------------------------------------
# Acceptance: navigate -> click -> type returns observations reflecting actions
# ---------------------------------------------------------------------------


def test_action_sequence_returns_observations_reflecting_actions() -> None:
    display = _display("sbx-1")
    session = open_session("sbx-1", display)

    nav = session.navigate("https://example.test/login")
    assert nav.action_kind == ACTION_NAVIGATE
    assert nav.url == "https://example.test/login"
    assert nav.sandbox_id == "sbx-1"

    clicked = session.click("#search")
    assert clicked.action_kind == ACTION_CLICK
    assert clicked.focused == "#search"
    assert clicked.element is not None
    assert clicked.element["selector"] == "#search"
    assert clicked.element["focused"] is True

    typed = session.type_text("hello world")
    assert typed.action_kind == ACTION_TYPE
    # The observation reflects the typed text landing in the focused element.
    assert typed.element is not None
    assert typed.element["selector"] == "#search"
    assert typed.element["value"] == "hello world"

    # Appending more text accumulates on the same element.
    typed2 = session.type_text("!", selector="#search")
    assert typed2.element is not None
    assert typed2.element["value"] == "hello world!"


# ---------------------------------------------------------------------------
# Acceptance: screenshot returns a frame descriptor
# ---------------------------------------------------------------------------


def test_screenshot_returns_frame_descriptor() -> None:
    display = _display("sbx-1")
    session = open_session("sbx-1", display)
    session.navigate("https://example.test/")

    shot = session.screenshot()
    assert shot.action_kind == ACTION_SCREENSHOT
    assert shot.frame is not None
    frame = shot.frame
    assert frame["kind"] == "frame"
    assert frame["width"] > 0 and frame["height"] > 0
    assert frame["url"] == "https://example.test/"
    assert frame["frame_index"] == 1
    # Content hash is a stable, deterministic digest of the display state.
    assert isinstance(frame["content_hash"], str) and len(frame["content_hash"]) == 64


# ---------------------------------------------------------------------------
# Acceptance: cross-sandbox action is rejected (isolation)
# ---------------------------------------------------------------------------


def test_cross_sandbox_action_is_rejected() -> None:
    display = _display("sbx-1", "sbx-2")
    session = open_session("sbx-1", display)

    # An action explicitly addressed to a different sandbox is refused before
    # it can reach any display.
    hostile = ControlAction(kind=ACTION_NAVIGATE, sandbox_id="sbx-2", target="https://evil.test")
    with pytest.raises(SandboxScopeError):
        session.dispatch(hostile)

    # And nothing leaked into the other sandbox's display: sbx-2 is untouched.
    other = open_session("sbx-2", display)
    shot = other.screenshot()
    assert shot.frame is not None
    assert shot.frame["url"] == "about:blank"

    # The rejected action is not recorded in the originating session's trace.
    assert session.trace == ()


def test_session_requires_registered_sandbox() -> None:
    display = _display("sbx-1")
    with pytest.raises(UnknownSandboxError):
        SandboxControlSession("sbx-missing", display)


# ---------------------------------------------------------------------------
# Acceptance: the action/observation trace is ordered
# ---------------------------------------------------------------------------


def test_trace_is_ordered() -> None:
    display = _display("sbx-1")
    # Inject a deterministic clock so seq assignment is fully specified.
    counter = {"n": 0}

    def clock() -> int:
        value = counter["n"]
        counter["n"] += 1
        return value

    session = open_session("sbx-1", display, clock=clock)
    session.navigate("https://example.test/")
    session.click("#submit")
    session.type_text("abc", selector="#search")
    session.screenshot()

    trace = session.trace
    assert [e.action.kind for e in trace] == [
        ACTION_NAVIGATE,
        ACTION_CLICK,
        ACTION_TYPE,
        ACTION_SCREENSHOT,
    ]
    # Sequence numbers are strictly increasing and match dispatch order.
    seqs = [e.action.seq for e in trace]
    assert seqs == [0, 1, 2, 3]
    obs_seqs = [e.observation.seq for e in trace]
    assert obs_seqs == seqs
    # Observations line up with their actions positionally.
    assert [o.action_kind for o in session.observations()] == [
        ACTION_NAVIGATE,
        ACTION_CLICK,
        ACTION_TYPE,
        ACTION_SCREENSHOT,
    ]


# ---------------------------------------------------------------------------
# Acceptance: determinism
# ---------------------------------------------------------------------------


def _run_scenario() -> list[dict]:
    display = _display("sbx-1")
    session = open_session("sbx-1", display)
    session.navigate("https://example.test/app")
    session.click("#search")
    session.type_text("query")
    session.screenshot()
    return session.trace_dicts()


def test_determinism_identical_streams_identical_traces() -> None:
    first = _run_scenario()
    second = _run_scenario()
    assert first == second
    # And the frame content hash is stable across runs.
    assert first[-1]["observation"]["frame"]["content_hash"] == (second[-1]["observation"]["frame"]["content_hash"])


def test_type_without_focus_is_rejected() -> None:
    display = _display("sbx-1")
    session = open_session("sbx-1", display)
    session.navigate("https://example.test/")  # navigate clears focus
    with pytest.raises(UnknownActionError):
        session.type_text("no target")


def test_unknown_action_kind_rejected() -> None:
    display = _display("sbx-1")
    session = open_session("sbx-1", display)
    with pytest.raises(UnknownActionError):
        session.dispatch(ControlAction(kind="drag", sandbox_id="sbx-1"))


# ---------------------------------------------------------------------------
# Live-lane CDP transport: pure command mapping is real & tested; the socket
# path is NOT exercised (needs a real sandboxed display).
# ---------------------------------------------------------------------------


def test_cdp_command_mapping() -> None:
    nav = cdp_command_for(ControlAction(kind=ACTION_NAVIGATE, sandbox_id="s", target="https://x.test"))
    assert nav == {"method": "Page.navigate", "params": {"url": "https://x.test"}}

    typ = cdp_command_for(ControlAction(kind=ACTION_TYPE, sandbox_id="s", value="hi"))
    assert typ == {"method": "Input.insertText", "params": {"text": "hi"}}

    shot = cdp_command_for(ControlAction(kind=ACTION_SCREENSHOT, sandbox_id="s"))
    assert shot["method"] == "Page.captureScreenshot"

    assert command_method(ControlAction(kind=ACTION_CLICK, sandbox_id="s", target="#a")) == ("Runtime.evaluate")


def test_cdp_transport_uses_injected_sender_and_stays_scoped() -> None:
    # Inject a fake sender so no socket is opened; this proves the mapping +
    # observation assembly without touching a live display.
    sent: list = []

    def sender(endpoint: str, command: dict) -> dict:
        sent.append((endpoint, command))
        if command["method"] == "Page.captureScreenshot":
            return {"result": {"data": "QUJD"}}
        return {"result": {}}

    transport = CdpDisplayTransport({"sbx-1": "ws://127.0.0.1:9222/devtools/page/A"}, sender=sender)
    session = open_session("sbx-1", transport)

    session.navigate("https://example.test/")
    shot = session.screenshot()
    assert shot.frame is not None
    assert shot.frame["format"] == "png-base64"
    assert shot.frame["data"] == "QUJD"
    assert sent[0][0] == "ws://127.0.0.1:9222/devtools/page/A"

    # A sandbox with no configured CDP endpoint cannot be reached.
    assert transport.has_sandbox("sbx-2") is False
    with pytest.raises(UnknownSandboxError):
        transport.apply(ControlAction(kind=ACTION_NAVIGATE, sandbox_id="sbx-2", target="x"))


def test_cdp_live_send_unreachable_endpoint_raises_clean_error() -> None:
    # Port 1 is not listening; the live path must surface LiveDisplayUnavailable
    # rather than a raw socket error. This still opens no real display.
    transport = CdpDisplayTransport({"sbx-1": "ws://127.0.0.1:1/devtools/page/A"}, connect_timeout=0.25)
    with pytest.raises(LiveDisplayUnavailable):
        transport.apply(ControlAction(kind=ACTION_NAVIGATE, sandbox_id="sbx-1", target="x"))
