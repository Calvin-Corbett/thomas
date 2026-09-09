"""In-sandbox browser/desktop control port (CAP-061).

Drive a GUI/browser that lives *inside a sandbox* and stream observations and
actions back, strictly scoped to that one sandbox. This module is the hermetic
**core** of the capability -- the control SPI, the session lifecycle, the
sandbox-scoping policy, and the action/observation trace. The only thing it
does *not* contain is the physical display: that edge sits behind an injectable
:class:`DisplayTransport`.

Two transports ship here:

- :class:`FakeDisplay` -- a deterministic, in-memory display server used by the
  tests. It models one browser-ish surface per sandbox id (current URL, a small
  DOM of addressable elements, focus, typed text, click log, frame counter) and
  is completely hermetic: no network, no clock, no filesystem.
- :class:`CdpDisplayTransport` -- the **live lane**. It maps control actions to
  real Chrome DevTools Protocol commands (``Page.navigate``,
  ``Input.dispatchMouseEvent``, ``Input.insertText``, ``Page.captureScreenshot``)
  and ships them to a CDP/VNC-style debugging endpoint over a stdlib-only
  WebSocket (``socket`` + the RFC-6455 handshake, no third-party deps). It is
  NEVER exercised by the test-suite because it requires a real sandboxed display
  (a browser started with ``--remote-debugging-port`` inside the sandbox, or a
  VNC/CDP bridge) plus that endpoint's URL. The CDP *command mapping* is a pure
  function (:func:`cdp_command_for`) and IS tested; only the socket send is
  gated behind the live endpoint.

Sandbox scoping is the security-relevant invariant: a
:class:`SandboxControlSession` is bound to exactly one sandbox id at
construction, and every action it dispatches must carry that same id. An action
addressed to a different sandbox is rejected with :class:`SandboxScopeError`
*before* it can reach any display -- so one sandbox's session can never drive
another sandbox's GUI.

Layering: tools tier, standard library only (no imports from agent/server/cli).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Action kinds understood by the control port.
ACTION_NAVIGATE = "navigate"
ACTION_CLICK = "click"
ACTION_TYPE = "type"
ACTION_SCREENSHOT = "screenshot"

ACTION_KINDS = frozenset({ACTION_NAVIGATE, ACTION_CLICK, ACTION_TYPE, ACTION_SCREENSHOT})

_DEFAULT_FRAME_WIDTH = 1280
_DEFAULT_FRAME_HEIGHT = 800


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SandboxControlError(Exception):
    """Base class for control-port failures."""


class SandboxScopeError(SandboxControlError):
    """Raised when an action would cross the session's sandbox boundary."""


class UnknownSandboxError(SandboxControlError):
    """Raised when a transport has no display for the requested sandbox id."""


class UnknownActionError(SandboxControlError):
    """Raised for an action whose kind is not a known control verb."""


class LiveDisplayUnavailable(SandboxControlError):
    """Raised by the live CDP transport when no display endpoint is reachable."""


# ---------------------------------------------------------------------------
# Action / observation value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlAction:
    """A single GUI action addressed to one sandbox's display.

    ``sandbox_id`` is load-bearing: the session verifies it matches its own
    bound sandbox before dispatch, which is what enforces isolation.
    """

    kind: str
    sandbox_id: str
    target: str | None = None
    value: str | None = None
    seq: int = 0

    def with_seq(self, seq: int) -> ControlAction:
        return ControlAction(
            kind=self.kind,
            sandbox_id=self.sandbox_id,
            target=self.target,
            value=self.value,
            seq=seq,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "sandbox_id": self.sandbox_id,
            "target": self.target,
            "value": self.value,
            "seq": self.seq,
        }


@dataclass(frozen=True)
class Observation:
    """What the display reports back after applying one action.

    ``element`` carries element state for click/type; ``frame`` carries a frame
    descriptor for screenshots. Both are plain, JSON-serializable dicts so the
    observation can be streamed straight back to the caller.
    """

    action_kind: str
    sandbox_id: str
    seq: int
    url: str
    focused: str | None
    detail: str
    element: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_kind": self.action_kind,
            "sandbox_id": self.sandbox_id,
            "seq": self.seq,
            "url": self.url,
            "focused": self.focused,
            "detail": self.detail,
            "element": self.element,
            "frame": self.frame,
        }


@dataclass(frozen=True)
class TraceEntry:
    """One ordered (action, observation) pair recorded by a session."""

    action: ControlAction
    observation: Observation

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action.to_dict(), "observation": self.observation.to_dict()}


# ---------------------------------------------------------------------------
# Transport SPI
# ---------------------------------------------------------------------------


@runtime_checkable
class DisplayTransport(Protocol):
    """The injectable display edge.

    Implementations turn a :class:`ControlAction` into an :class:`Observation`
    by driving some display bound to ``action.sandbox_id``. Real transports talk
    to a live sandboxed browser/desktop; the hermetic fake models one in memory.
    """

    def has_sandbox(self, sandbox_id: str) -> bool: ...

    def apply(self, action: ControlAction) -> Observation: ...


# ---------------------------------------------------------------------------
# Hermetic fake display (used by tests)
# ---------------------------------------------------------------------------


def _default_elements() -> dict[str, dict[str, str]]:
    """A tiny, deterministic DOM every fake page starts with."""
    return {
        "#search": {"tag": "input", "text": ""},
        "#submit": {"tag": "button", "text": "Go"},
        "#link-home": {"tag": "a", "text": "Home"},
    }


@dataclass
class _DisplayState:
    """In-memory state of one sandbox's display surface."""

    url: str = "about:blank"
    title: str = ""
    focused: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    clicks: list[str] = field(default_factory=list)
    elements: dict[str, dict[str, str]] = field(default_factory=_default_elements)
    frames: int = 0

    def snapshot(self) -> dict[str, Any]:
        """Canonical, order-stable view used for deterministic hashing."""
        return {
            "url": self.url,
            "title": self.title,
            "focused": self.focused,
            "values": {k: self.values[k] for k in sorted(self.values)},
            "clicks": list(self.clicks),
            "elements": {k: self.elements[k] for k in sorted(self.elements)},
            "frames": self.frames,
        }


def _title_for(url: str) -> str:
    """Derive a deterministic page title from a URL (no network)."""
    trimmed = url.split("://", 1)[-1].rstrip("/")
    if not trimmed:
        return "blank"
    tail = trimmed.rsplit("/", 1)[-1]
    return tail or trimmed


class FakeDisplay:
    """Deterministic, hermetic multi-sandbox display server for tests.

    Holds one :class:`_DisplayState` per sandbox id. Applying an action mutates
    only that sandbox's state and returns an observation reflecting it. No
    network, no wall-clock, no randomness -- identical action streams always
    produce identical observations.
    """

    def __init__(self, sandbox_ids: list[str] | None = None) -> None:
        self._states: dict[str, _DisplayState] = {}
        for sid in sandbox_ids or []:
            self._states[sid] = _DisplayState()

    def register(self, sandbox_id: str) -> None:
        """Provision a fresh display for ``sandbox_id`` if absent."""
        self._states.setdefault(sandbox_id, _DisplayState())

    def has_sandbox(self, sandbox_id: str) -> bool:
        return sandbox_id in self._states

    def _state(self, sandbox_id: str) -> _DisplayState:
        state = self._states.get(sandbox_id)
        if state is None:
            raise UnknownSandboxError(f"no display registered for sandbox {sandbox_id!r}")
        return state

    def _element_state(self, state: _DisplayState, selector: str | None) -> dict[str, Any]:
        if selector is None:
            return {"selector": None, "tag": None, "focused": False, "value": "", "text": ""}
        meta = state.elements.get(selector, {"tag": "unknown", "text": ""})
        return {
            "selector": selector,
            "tag": meta.get("tag", "unknown"),
            "focused": state.focused == selector,
            "value": state.values.get(selector, ""),
            "text": meta.get("text", ""),
        }

    def _frame_descriptor(self, state: _DisplayState) -> dict[str, Any]:
        payload = json.dumps(state.snapshot(), sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {
            "kind": "frame",
            "format": "fake-rgba",
            "width": _DEFAULT_FRAME_WIDTH,
            "height": _DEFAULT_FRAME_HEIGHT,
            "url": state.url,
            "title": state.title,
            "focused": state.focused,
            "element_count": len(state.elements),
            "frame_index": state.frames,
            "content_hash": content_hash,
        }

    def apply(self, action: ControlAction) -> Observation:
        state = self._state(action.sandbox_id)
        kind = action.kind

        if kind == ACTION_NAVIGATE:
            url = action.target or "about:blank"
            state.url = url
            state.title = _title_for(url)
            state.focused = None
            detail = f"navigated to {url}"
            return Observation(
                action_kind=kind,
                sandbox_id=action.sandbox_id,
                seq=action.seq,
                url=state.url,
                focused=state.focused,
                detail=detail,
                element=None,
                frame=None,
            )

        if kind == ACTION_CLICK:
            selector = action.target or ""
            state.focused = selector or None
            state.clicks.append(selector)
            detail = f"clicked {selector}"
            return Observation(
                action_kind=kind,
                sandbox_id=action.sandbox_id,
                seq=action.seq,
                url=state.url,
                focused=state.focused,
                detail=detail,
                element=self._element_state(state, selector or None),
                frame=None,
            )

        if kind == ACTION_TYPE:
            selector = action.target or state.focused
            text = action.value or ""
            if selector is None:
                raise UnknownActionError("type action has no target and no focused element")
            state.values[selector] = state.values.get(selector, "") + text
            state.focused = selector
            detail = f"typed {len(text)} chars into {selector}"
            return Observation(
                action_kind=kind,
                sandbox_id=action.sandbox_id,
                seq=action.seq,
                url=state.url,
                focused=state.focused,
                detail=detail,
                element=self._element_state(state, selector),
                frame=None,
            )

        if kind == ACTION_SCREENSHOT:
            state.frames += 1
            frame = self._frame_descriptor(state)
            detail = f"captured frame {state.frames}"
            return Observation(
                action_kind=kind,
                sandbox_id=action.sandbox_id,
                seq=action.seq,
                url=state.url,
                focused=state.focused,
                detail=detail,
                element=None,
                frame=frame,
            )

        raise UnknownActionError(f"unknown action kind: {kind!r}")


# ---------------------------------------------------------------------------
# Control session -- lifecycle + scoping + trace
# ---------------------------------------------------------------------------


SeqClock = Callable[[], int]


class SandboxControlSession:
    """A control session bound to exactly one sandbox id.

    Every dispatched action must carry the session's sandbox id; an action for
    any other sandbox is rejected with :class:`SandboxScopeError` before the
    display is touched. The session assigns a monotonic sequence number to each
    action so the recorded trace is strictly ordered and deterministic.
    """

    def __init__(
        self,
        sandbox_id: str,
        transport: DisplayTransport,
        *,
        clock: SeqClock | None = None,
    ) -> None:
        if not sandbox_id:
            raise ValueError("sandbox_id must be a non-empty string")
        if not transport.has_sandbox(sandbox_id):
            raise UnknownSandboxError(f"transport has no display for sandbox {sandbox_id!r}")
        self.sandbox_id = sandbox_id
        self._transport = transport
        self._trace: list[TraceEntry] = []
        self._counter = 0
        self._clock = clock

    # -- sequence -----------------------------------------------------------

    def _next_seq(self) -> int:
        if self._clock is not None:
            return int(self._clock())
        seq = self._counter
        self._counter += 1
        return seq

    # -- core dispatch ------------------------------------------------------

    def dispatch(self, action: ControlAction) -> Observation:
        """Validate scope, apply the action, and record it in the trace."""
        if action.kind not in ACTION_KINDS:
            raise UnknownActionError(f"unknown action kind: {action.kind!r}")
        if action.sandbox_id != self.sandbox_id:
            raise SandboxScopeError(
                f"session bound to sandbox {self.sandbox_id!r} cannot dispatch "
                f"action targeting sandbox {action.sandbox_id!r}"
            )
        stamped = action.with_seq(self._next_seq())
        observation = self._transport.apply(stamped)
        self._trace.append(TraceEntry(action=stamped, observation=observation))
        return observation

    # -- convenience verbs (stamp the session's sandbox id) -----------------

    def navigate(self, url: str) -> Observation:
        return self.dispatch(ControlAction(kind=ACTION_NAVIGATE, sandbox_id=self.sandbox_id, target=url))

    def click(self, selector: str) -> Observation:
        return self.dispatch(ControlAction(kind=ACTION_CLICK, sandbox_id=self.sandbox_id, target=selector))

    def type_text(self, text: str, selector: str | None = None) -> Observation:
        return self.dispatch(
            ControlAction(
                kind=ACTION_TYPE,
                sandbox_id=self.sandbox_id,
                target=selector,
                value=text,
            )
        )

    def screenshot(self) -> Observation:
        return self.dispatch(ControlAction(kind=ACTION_SCREENSHOT, sandbox_id=self.sandbox_id))

    # -- trace --------------------------------------------------------------

    @property
    def trace(self) -> tuple[TraceEntry, ...]:
        return tuple(self._trace)

    def observations(self) -> tuple[Observation, ...]:
        return tuple(entry.observation for entry in self._trace)

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._trace]


# ---------------------------------------------------------------------------
# Live lane: real CDP display transport (stdlib only, NOT run in tests)
# ---------------------------------------------------------------------------


def cdp_command_for(action: ControlAction) -> dict[str, Any]:
    """Map a control action to a Chrome DevTools Protocol command.

    Pure function -- no I/O -- so it is unit-tested hermetically. This is the
    real protocol surface the live transport ships over the wire.
    """
    if action.kind == ACTION_NAVIGATE:
        return {"method": "Page.navigate", "params": {"url": action.target or "about:blank"}}
    if action.kind == ACTION_CLICK:
        return {
            "method": "Runtime.evaluate",
            "params": {
                "expression": f"document.querySelector({json.dumps(action.target or '')}).click()",
                "awaitPromise": True,
            },
        }
    if action.kind == ACTION_TYPE:
        return {"method": "Input.insertText", "params": {"text": action.value or ""}}
    if action.kind == ACTION_SCREENSHOT:
        return {"method": "Page.captureScreenshot", "params": {"format": "png"}}
    raise UnknownActionError(f"no CDP mapping for action kind {action.kind!r}")


# Concrete socket faults we translate into a clean LiveDisplayUnavailable.
_WIRE_FAULTS = (OSError, socket.timeout, ConnectionError, TimeoutError)


class CdpDisplayTransport:
    """Live-lane transport that drives a real sandboxed browser over CDP.

    LIVE LANE -- requires a real sandboxed display and is therefore never
    exercised by the hermetic test-suite. To run it for real you need, *inside
    the sandbox*:

    - a browser launched with ``--remote-debugging-port`` (Chrome/Chromium) or a
      VNC/CDP bridge exposing that port, and
    - the per-sandbox WebSocket debugger URL (``ws://host:port/devtools/page/ID``),
      supplied via ``endpoints[sandbox_id]``.

    The WebSocket client is stdlib-only (``socket`` + the RFC-6455 upgrade
    handshake + a minimal text-frame codec) so it adds no pip dependency. The
    CDP *command mapping* (:func:`cdp_command_for`) is real and tested; only the
    physical socket send is gated behind the live endpoint. This class makes no
    claim of a live run having happened -- callers must provide a reachable
    endpoint.
    """

    def __init__(
        self,
        endpoints: dict[str, str],
        *,
        connect_timeout: float = 5.0,
        sender: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        # endpoints maps sandbox_id -> ws:// debugger URL, keeping the transport
        # itself scoped: it can only reach sandboxes it was given a URL for.
        self._endpoints = dict(endpoints)
        self._connect_timeout = connect_timeout
        # `sender` is injectable purely so the wire path can be swapped in an
        # integration harness; the default performs a genuine CDP round-trip.
        self._sender = sender or self._live_send
        self._msg_id = 0

    def has_sandbox(self, sandbox_id: str) -> bool:
        return sandbox_id in self._endpoints

    def apply(self, action: ControlAction) -> Observation:
        endpoint = self._endpoints.get(action.sandbox_id)
        if endpoint is None:
            raise UnknownSandboxError(f"no CDP endpoint configured for sandbox {action.sandbox_id!r}")
        command = cdp_command_for(action)
        reply = self._sender(endpoint, command)
        return self._observation_from_reply(action, reply)

    def _observation_from_reply(self, action: ControlAction, reply: dict[str, Any]) -> Observation:
        result = reply.get("result", {}) if isinstance(reply, dict) else {}
        frame: dict[str, Any] | None = None
        if action.kind == ACTION_SCREENSHOT:
            data = result.get("data") if isinstance(result, dict) else None
            frame = {
                "kind": "frame",
                "format": "png-base64",
                "data": data,
                "url": action.target,
            }
        return Observation(
            action_kind=action.kind,
            sandbox_id=action.sandbox_id,
            seq=action.seq,
            url=action.target or "",
            focused=action.target if action.kind in (ACTION_CLICK, ACTION_TYPE) else None,
            detail=f"cdp:{command_method(action)}",
            element=None,
            frame=frame,
        )

    # -- stdlib WebSocket client (LIVE LANE ONLY) ---------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _live_send(self, endpoint: str, command: dict[str, Any]) -> dict[str, Any]:
        """Open a CDP WebSocket, send one command, read one reply.

        Only reached when a real endpoint is configured. Wire faults are logged
        and re-raised as :class:`LiveDisplayUnavailable` so the control port has
        a single, honest failure type for "no live display".
        """
        host, port, path = _parse_ws_url(endpoint)
        payload = {"id": self._next_id(), **command}
        try:
            with socket.create_connection((host, port), timeout=self._connect_timeout) as sock:
                sock.settimeout(self._connect_timeout)
                _ws_handshake(sock, host, port, path)
                _ws_send_text(sock, json.dumps(payload))
                raw = _ws_recv_text(sock)
        except _WIRE_FAULTS as exc:
            logger.warning("CDP live send to %s failed: %s", endpoint, exc)
            raise LiveDisplayUnavailable(f"no reachable CDP display at {endpoint!r}: {exc}") from exc
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning("CDP reply from %s was not JSON: %s", endpoint, exc)
            raise LiveDisplayUnavailable(f"malformed CDP reply from {endpoint!r}: {exc}") from exc


def command_method(action: ControlAction) -> str:
    """Return just the CDP method name for an action (for trace details)."""
    return str(cdp_command_for(action).get("method", "unknown"))


def _parse_ws_url(url: str) -> tuple[str, int, str]:
    """Split a ``ws://host:port/path`` URL with no third-party parser."""
    rest = url.split("://", 1)[-1]
    netloc, _, path = rest.partition("/")
    host, _, port_str = netloc.partition(":")
    port = int(port_str) if port_str else 9222
    return host, port, "/" + path


def _ws_handshake(sock: socket.socket, host: str, port: int, path: str) -> None:
    """Perform the RFC-6455 client upgrade handshake."""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(1024)
        if not chunk:
            raise ConnectionError("CDP endpoint closed during handshake")
        response += chunk
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        raise ConnectionError(f"CDP endpoint refused upgrade: {response[:64]!r}")


def _ws_send_text(sock: socket.socket, text: str) -> None:
    """Send a single masked text frame (client frames must be masked)."""
    data = text.encode("utf-8")
    header = bytearray([0x81])  # FIN + text opcode
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += length.to_bytes(2, "big")
    else:
        header.append(0x80 | 127)
        header += length.to_bytes(8, "big")
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + masked)


def _ws_recv_exact(sock: socket.socket, count: int) -> bytes:
    buf = b""
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("CDP endpoint closed during frame read")
        buf += chunk
    return buf


def _ws_recv_text(sock: socket.socket) -> str:
    """Read a single (server, unmasked) text frame payload."""
    first = _ws_recv_exact(sock, 2)
    length = first[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_ws_recv_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_ws_recv_exact(sock, 8), "big")
    payload = _ws_recv_exact(sock, length)
    return payload.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def open_session(
    sandbox_id: str,
    transport: DisplayTransport,
    *,
    clock: SeqClock | None = None,
) -> SandboxControlSession:
    """Open a control session scoped to ``sandbox_id`` over ``transport``."""
    return SandboxControlSession(sandbox_id, transport, clock=clock)
