"""Thomas Embedding SDK -- transport + public client API.

This module gives third parties a stable, documented way to drive a Thomas
Agent surface from their own host application: create/list/get runs, dispatch
work, stream the event feed, and submit approvals or steer messages.

The network edge is behind an injectable :class:`Transport`:

* :class:`HttpTransport` is the real default. It speaks the exact
  ``/api/runs`` HTTP contract served by ``thomas.server`` using only the
  standard library (:mod:`urllib`) -- no third-party HTTP dependency.
* :class:`FakeTransport` is a hermetic in-memory double that emulates the
  same contract (same paths, methods, query params, and response shapes). It
  lets embedders -- and this repo's tests -- exercise the full client offline
  with no network, no server, and an injected clock.

Because both transports honor one contract, code proven against the fake
behaves identically against a live local server.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "SdkError",
    "TransportError",
    "ApiError",
    "Transport",
    "HttpTransport",
    "FakeTransport",
    "RunSummary",
    "RunDetail",
    "RunEvent",
    "ApprovalRequest",
    "ThomasClient",
]

_log = logging.getLogger(__name__)

# Concrete faults raised by the stdlib HTTP stack. Caught as a wide *specific*
# tuple (never bare Exception) so a broken socket, DNS failure, or malformed
# body surfaces as a typed SDK error instead of leaking urllib internals.
_HTTP_FAULTS: tuple[type[BaseException], ...] = (
    urllib.error.URLError,
    OSError,
    TimeoutError,
    ConnectionError,
    ValueError,
)


class SdkError(Exception):
    """Base class for every error raised by the Thomas embedding SDK."""


class TransportError(SdkError):
    """The request could not be completed (network, socket, or decode fault)."""


class ApiError(SdkError):
    """The server returned a non-2xx status."""

    def __init__(self, status: int, message: str, *, path: str = "") -> None:
        super().__init__(f"HTTP {status} for {path}: {message}" if path else f"HTTP {status}: {message}")
        self.status = int(status)
        self.message = str(message)
        self.path = str(path)


# ---------------------------------------------------------------------------
# Transport contract
# ---------------------------------------------------------------------------


@runtime_checkable
class Transport(Protocol):
    """The single seam between the client and the outside world.

    A transport turns a logical request (method, path, query, json body) into a
    decoded JSON object. Implementations must raise :class:`ApiError` for
    non-2xx responses and :class:`TransportError` for connectivity/decode
    faults.
    """

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one request and return the decoded JSON object."""
        ...


class HttpTransport:
    """Real default transport: stdlib ``urllib`` over HTTP to a local server.

    Talks to a running ``thomas.server`` (default ``http://127.0.0.1:8899``).
    A bearer token is sent when the server runs in remote/authenticated mode.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8899",
        *,
        token: str | None = None,
        timeout: float = 30.0,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.build_opener()

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            clean = {k: v for k, v in query.items() if v not in (None, "")}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean, doseq=True)}"

        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except (OSError, ValueError, AttributeError):
                detail = exc.reason if isinstance(exc.reason, str) else str(exc.reason)
            raise ApiError(exc.code, detail or "request failed", path=path) from exc
        except _HTTP_FAULTS as exc:
            raise TransportError(f"{method.upper()} {url} failed: {exc}") from exc

        if not raw.strip():
            return {}
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise TransportError(f"invalid JSON from {url}: {exc}") from exc
        if not isinstance(decoded, dict):
            return {"data": decoded}
        return decoded


# ---------------------------------------------------------------------------
# Data model -- stable public shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSummary:
    """Lightweight run row as returned by ``list_runs``."""

    run_id: str
    status: str = "unknown"
    session_id: str | None = None
    profile: str | None = None
    mode: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    ok: bool | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, obj: Mapping[str, Any]) -> RunSummary:
        return cls(
            run_id=str(obj.get("run_id") or ""),
            status=str(obj.get("status") or _status_from_ok(obj.get("ok"))),
            session_id=_opt_str(obj.get("session_id")),
            profile=_opt_str(obj.get("profile")),
            mode=_opt_str(obj.get("mode")),
            started_at=_opt_str(obj.get("started_at")),
            ended_at=_opt_str(obj.get("ended_at")),
            ok=_opt_bool(obj.get("ok")),
            raw=dict(obj),
        )


@dataclass(frozen=True)
class RunDetail:
    """Full run record returned by ``dispatch`` / ``get_run``."""

    run_id: str
    status: str = "unknown"
    session_id: str | None = None
    profile: str | None = None
    mode: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    ok: bool | None = None
    error: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, obj: Mapping[str, Any]) -> RunDetail:
        run = obj.get("run") if isinstance(obj.get("run"), Mapping) else obj
        run = dict(run or {})
        return cls(
            run_id=str(run.get("run_id") or ""),
            status=str(run.get("status") or _status_from_ok(run.get("ok"))),
            session_id=_opt_str(run.get("session_id")),
            profile=_opt_str(run.get("profile")),
            mode=_opt_str(run.get("mode")),
            started_at=_opt_str(run.get("started_at")),
            ended_at=_opt_str(run.get("ended_at")),
            ok=_opt_bool(run.get("ok")),
            error=_opt_str(run.get("error")),
            raw=run,
        )


@dataclass(frozen=True)
class RunEvent:
    """One entry in a run's event feed."""

    index: int
    event_type: str
    seq: int = 0
    t_ms: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, obj: Mapping[str, Any]) -> RunEvent:
        return cls(
            index=_int(obj.get("index")),
            event_type=str(obj.get("event_type") or ""),
            seq=_int(obj.get("seq")),
            t_ms=_opt_int(obj.get("t_ms")),
            payload=dict(obj.get("payload") or {}),
        )


@dataclass(frozen=True)
class ApprovalRequest:
    """An approval the agent is blocked on, derived from the event feed."""

    approval_id: str
    prompt: str = ""
    run_id: str = ""
    event_index: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ThomasClient:
    """Stable public client for embedding a Thomas Agent surface.

    Every method is transport-agnostic: point it at :class:`HttpTransport`
    for a live server or :class:`FakeTransport` for offline embedding/tests.
    """

    #: Frozen public method contract. The contract test asserts this matches
    #: the actual callables so the surface cannot drift silently.
    API_METHODS: tuple[str, ...] = (
        "dispatch",
        "list_runs",
        "get_run",
        "get_events",
        "stream_events",
        "submit_approval",
        "submit_steer",
    )

    def __init__(self, transport: Transport) -> None:
        if not hasattr(transport, "request"):
            raise TypeError("transport must implement .request(method, path, ...)")
        self._transport = transport

    # -- runs ---------------------------------------------------------------

    def dispatch(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        profile: str | None = None,
        mode: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RunDetail:
        """Create a new run for ``prompt`` and return its detail record."""
        body: dict[str, Any] = {"prompt": prompt}
        if session_id is not None:
            body["session_id"] = session_id
        if profile is not None:
            body["profile"] = profile
        if mode is not None:
            body["mode"] = mode
        if metadata:
            body["metadata"] = dict(metadata)
        obj = self._transport.request("POST", "/api/runs", body=body)
        return RunDetail.from_payload(obj)

    def list_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        filters: Mapping[str, Any] | None = None,
    ) -> list[RunSummary]:
        """List runs, most-recent first, as :class:`RunSummary` rows."""
        query: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if filters:
            query.update({k: v for k, v in filters.items()})
        obj = self._transport.request("GET", "/api/runs", query=query)
        rows = obj.get("runs") if isinstance(obj.get("runs"), list) else []
        return [RunSummary.from_payload(r) for r in rows if isinstance(r, Mapping)]

    def get_run(self, run_id: str) -> RunDetail:
        """Fetch one run's detail record."""
        obj = self._transport.request("GET", f"/api/runs/{urllib.parse.quote(str(run_id))}")
        return RunDetail.from_payload(obj)

    def get_events(
        self,
        run_id: str,
        *,
        start: int = 0,
        limit: int = 250,
    ) -> tuple[int, list[RunEvent]]:
        """Fetch one page of the event feed; returns ``(total, events)``."""
        obj = self._transport.request(
            "GET",
            f"/api/runs/{urllib.parse.quote(str(run_id))}/events",
            query={"start": int(start), "limit": int(limit)},
        )
        total = _int(obj.get("total"))
        rows = obj.get("events") if isinstance(obj.get("events"), list) else []
        events = [RunEvent.from_payload(e) for e in rows if isinstance(e, Mapping)]
        return total, events

    def stream_events(
        self,
        run_id: str,
        *,
        start: int = 0,
        page_size: int = 250,
    ) -> Iterator[RunEvent]:
        """Yield every event from ``start`` to the current end of the feed.

        This drains one snapshot of the feed by paging until it catches up to
        the server's reported total. Call again with the last index + 1 to pull
        events that arrived since (long-poll style live consumption).
        """
        idx = max(0, int(start))
        while True:
            total, events = self.get_events(run_id, start=idx, limit=page_size)
            if not events:
                break
            yield from events
            idx += len(events)
            if idx >= total:
                break

    # -- actions ------------------------------------------------------------

    def submit_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        approve: bool,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject a pending approval for a run."""
        body: dict[str, Any] = {"approve": bool(approve)}
        if note is not None:
            body["note"] = note
        return self._transport.request(
            "POST",
            f"/api/runs/{urllib.parse.quote(str(run_id))}/approvals/{urllib.parse.quote(str(approval_id))}",
            body=body,
        )

    def submit_steer(self, run_id: str, text: str) -> dict[str, Any]:
        """Send a steering message to an in-flight run."""
        return self._transport.request(
            "POST",
            f"/api/runs/{urllib.parse.quote(str(run_id))}/steer",
            body={"text": str(text)},
        )


# ---------------------------------------------------------------------------
# Hermetic fake transport
# ---------------------------------------------------------------------------


@dataclass
class _FakeRun:
    run_id: str
    session_id: str | None
    profile: str | None
    mode: str | None
    status: str
    prompt: str
    started_at: str
    ended_at: str | None = None
    ok: bool | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: set[str] = field(default_factory=set)


class FakeTransport:
    """In-memory double emulating the ``/api/runs`` HTTP contract.

    Behavioral model (a small deterministic state machine so a host can drive a
    realistic embedded flow offline):

    * ``POST /api/runs`` creates a run, seeds ``run.started`` +
      ``agent.message`` events and one ``approval.requested`` event, and parks
      the run in ``waiting_approval``.
    * ``POST /api/runs/{id}/approvals/{aid}`` resolves the approval, appends
      ``approval.resolved`` + a final ``agent.message`` + ``run.completed``,
      and moves the run to ``completed``.
    * ``POST /api/runs/{id}/steer`` appends a ``steer.received`` event.

    A monotonically increasing injected clock stamps ``t_ms`` so tests are
    deterministic without wall-clock time.
    """

    def __init__(self, *, clock: Callable[[], int] | None = None) -> None:
        self._runs: dict[str, _FakeRun] = {}
        self._counter = 0
        self._tick = 0
        self._clock = clock or self._default_clock

    def _default_clock(self) -> int:
        self._tick += 10
        return self._tick

    # -- transport contract -------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        parts = [p for p in path.split("?", 1)[0].split("/") if p]
        # parts: ["api", "runs", ...]
        if parts[:2] != ["api", "runs"]:
            raise ApiError(404, f"unknown path: {path}", path=path)
        rest = parts[2:]

        if method == "POST" and not rest:
            return self._create_run(body or {})
        if method == "GET" and not rest:
            return self._list_runs(query or {})
        if method == "GET" and len(rest) == 1:
            return self._get_run(rest[0])
        if method == "GET" and len(rest) == 2 and rest[1] == "events":
            return self._get_events(rest[0], query or {})
        if method == "POST" and len(rest) == 3 and rest[1] == "approvals":
            return self._decide_approval(rest[0], rest[2], body or {})
        if method == "POST" and len(rest) == 2 and rest[1] == "steer":
            return self._steer(rest[0], body or {})
        raise ApiError(404, f"unrouted: {method} {path}", path=path)

    # -- handlers -----------------------------------------------------------

    def _create_run(self, body: Mapping[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("prompt") or "")
        if not prompt.strip():
            raise ApiError(400, "prompt is required", path="/api/runs")
        self._counter += 1
        run_id = f"run-{self._counter:04d}"
        run = _FakeRun(
            run_id=run_id,
            session_id=_opt_str(body.get("session_id")),
            profile=_opt_str(body.get("profile")),
            mode=_opt_str(body.get("mode")),
            status="waiting_approval",
            prompt=prompt,
            started_at=f"t{self._clock()}",
        )
        approval_id = f"{run_id}-ap1"
        run.pending_approvals.add(approval_id)
        self._append(run, "run.started", {"prompt": prompt})
        self._append(run, "agent.message", {"role": "assistant", "text": f"Working on: {prompt}"})
        self._append(
            run,
            "approval.requested",
            {"approval_id": approval_id, "prompt": f"Approve action for: {prompt}?"},
        )
        self._runs[run_id] = run
        return {"run": self._run_meta(run)}

    def _list_runs(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _int(query.get("limit"), 50)
        offset = _int(query.get("offset"), 0)
        rows = [self._run_meta(r) for r in reversed(list(self._runs.values()))]
        session = _opt_str(query.get("session_id"))
        if session is not None:
            rows = [r for r in rows if r.get("session_id") == session]
        window = rows[offset : offset + limit] if limit else rows[offset:]
        return {"runs": window, "limit": limit, "offset": offset}

    def _get_run(self, run_id: str) -> dict[str, Any]:
        return {"run": self._run_meta(self._require(run_id))}

    def _get_events(self, run_id: str, query: Mapping[str, Any]) -> dict[str, Any]:
        run = self._require(run_id)
        start = max(0, _int(query.get("start"), 0))
        limit = max(1, _int(query.get("limit"), 250))
        total = len(run.events)
        page = run.events[start : start + limit]
        return {"run_id": run_id, "total": total, "start": start, "limit": limit, "events": page}

    def _decide_approval(self, run_id: str, approval_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        run = self._require(run_id)
        if approval_id not in run.pending_approvals:
            raise ApiError(404, f"approval not found: {approval_id}", path=f"/api/runs/{run_id}")
        approve = bool(body.get("approve"))
        run.pending_approvals.discard(approval_id)
        self._append(
            run,
            "approval.resolved",
            {"approval_id": approval_id, "approved": approve, "note": _opt_str(body.get("note"))},
        )
        if approve:
            self._append(run, "agent.message", {"role": "assistant", "text": "Approved -- finishing up."})
            self._append(run, "run.completed", {"ok": True})
            run.status = "completed"
            run.ok = True
        else:
            self._append(run, "run.completed", {"ok": False, "reason": "rejected"})
            run.status = "completed"
            run.ok = False
            run.error = "rejected"
        run.ended_at = f"t{self._clock()}"
        return {"ok": True, "run_id": run_id, "approval_id": approval_id, "approved": approve}

    def _steer(self, run_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        run = self._require(run_id)
        text = str(body.get("text") or "")
        self._append(run, "steer.received", {"text": text})
        return {"ok": True, "run_id": run_id}

    # -- internals ----------------------------------------------------------

    def _require(self, run_id: str) -> _FakeRun:
        run = self._runs.get(run_id)
        if run is None:
            raise ApiError(404, f"run not found: {run_id}", path=f"/api/runs/{run_id}")
        return run

    def _append(self, run: _FakeRun, event_type: str, payload: Mapping[str, Any]) -> None:
        idx = len(run.events)
        run.events.append(
            {
                "index": idx,
                "seq": idx,
                "t_ms": self._clock(),
                "event_type": event_type,
                "payload": dict(payload),
            }
        )

    def _run_meta(self, run: _FakeRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "profile": run.profile,
            "mode": run.mode,
            "status": run.status,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "ok": run.ok,
            "error": run.error,
        }


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _status_from_ok(ok: Any) -> str:
    if ok is True:
        return "completed"
    if ok is False:
        return "failed"
    return "unknown"


def _opt_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
