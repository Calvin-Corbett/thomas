"""Native Agent-Communication-Protocol (ACP) layer for Thomas (stdlib-only).

This module implements a small, deterministic, in-process protocol that lets
agents advertise what they can do, find peers by capability, and exchange
typed request/result envelopes -- with cooperative cancellation of in-flight
work. It is intentionally transport-agnostic and hermetic: nothing here opens a
socket, reads a clock, or draws a random number, so the same inputs always
produce the same outputs.

Four pillars (CAP-033 acceptance):

DISCOVERY
    :class:`AgentRegistry` holds :class:`AgentCard` advertisements (an agent id
    plus the capabilities it serves). :meth:`AgentRegistry.discover` returns the
    cards that serve a capability, in a stable order; an unknown capability
    yields an empty result.

INVOCATION
    :class:`ACPBroker` builds typed :class:`Request` envelopes and dispatches
    them through an injectable :class:`Transport`. The default
    :class:`LocalTransport` routes to the registered handler in the same
    process -- no network. A round-trip returns a typed :class:`Result`.

CANCELLATION
    An invocation is driven through an :class:`Invocation` handle that can be
    cancelled mid-flight. Handlers cooperate by yielding at checkpoints (they
    are written as generators) and checking the :class:`CancelToken`; when a
    cancel is observed the callee stops and the invocation resolves with
    ``Status.CANCELLED``. The callee marks the token *observed* so the caller
    can prove the signal was actually seen.

STRUCTURED RESULT EXCHANGE
    :class:`Request` and :class:`Result` are validated, immutable envelopes with
    stable ``to_dict``/``from_dict`` serialization. :func:`parse_request` /
    :func:`parse_result` reject malformed payloads with :class:`EnvelopeError`.

Determinism
    Request ids come from an injectable, monotonic id factory (a counter by
    default), discovery order is sorted by agent id, and no wall-clock or RNG is
    consulted. Given the same registry, handlers, and request, results are
    byte-for-byte identical across runs.
"""

from __future__ import annotations

import dataclasses
import enum
import types
from collections.abc import Callable, Generator, Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Status",
    "ACPError",
    "EnvelopeError",
    "NoAgentError",
    "AgentCard",
    "Request",
    "Result",
    "CancelToken",
    "Cancelled",
    "AgentRegistry",
    "Transport",
    "LocalTransport",
    "Invocation",
    "ACPBroker",
    "Handler",
    "parse_request",
    "parse_result",
]


class Status(str, enum.Enum):
    """Terminal status of an invocation, carried on every :class:`Result`."""

    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ACPError(Exception):
    """Base class for ACP errors."""


class EnvelopeError(ACPError, ValueError):
    """A request/result envelope failed structural validation."""


class NoAgentError(ACPError, LookupError):
    """No registered agent serves the requested capability."""


class Cancelled(ACPError):
    """Raised inside a handler that chooses to abort via ``raise_if_cancelled``."""


# ---------------------------------------------------------------------------
# Immutable-payload helper
# ---------------------------------------------------------------------------


def _freeze_mapping(value: Any, *, field: str) -> types.MappingProxyType:
    """Validate ``value`` is a string-keyed mapping and return a read-only copy."""
    if not isinstance(value, Mapping):
        raise EnvelopeError(f"{field} must be a mapping, got {type(value).__name__}")
    frozen: dict[str, Any] = {}
    for key in value:
        if not isinstance(key, str):
            raise EnvelopeError(f"{field} keys must be strings, got {type(key).__name__}")
        frozen[key] = value[key]
    return types.MappingProxyType(frozen)


def _plain(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a plain, JSON-friendly dict copy of a (possibly proxied) mapping."""
    return dict(payload)


# ---------------------------------------------------------------------------
# DISCOVERY -- agent cards + registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AgentCard:
    """An agent's advertisement: who it is and what capabilities it serves."""

    agent_id: str
    capabilities: frozenset[str]
    name: str = ""
    meta: types.MappingProxyType = dataclasses.field(default_factory=lambda: types.MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise EnvelopeError("AgentCard.agent_id must be a non-empty string")
        caps = self.capabilities
        if isinstance(caps, str) or not isinstance(caps, Iterable):
            raise EnvelopeError("AgentCard.capabilities must be an iterable of capability names")
        frozen: set[str] = set()
        for cap in caps:
            if not isinstance(cap, str) or not cap.strip():
                raise EnvelopeError("AgentCard.capabilities entries must be non-empty strings")
            frozen.add(cap)
        object.__setattr__(self, "capabilities", frozenset(frozen))
        object.__setattr__(self, "meta", _freeze_mapping(self.meta, field="AgentCard.meta"))

    def supports(self, capability: str) -> bool:
        """True if this agent advertises ``capability``."""
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            # sorted for stable, deterministic serialization
            "capabilities": sorted(self.capabilities),
            "meta": _plain(self.meta),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentCard:
        if not isinstance(data, Mapping):
            raise EnvelopeError("agent card must be a mapping")
        return cls(
            agent_id=data.get("agent_id", ""),
            capabilities=frozenset(data.get("capabilities", ())),
            name=data.get("name", ""),
            meta=data.get("meta", {}),
        )


# A handler runs a request. It is written as a generator: it yields ``None`` at
# each cooperative cancellation checkpoint and returns its result payload (via
# ``return``) when finished. A plain callable that returns a value directly is
# also accepted for handlers that have no cancellation points.
Handler = Callable[["Request", "CancelToken"], Any]


class AgentRegistry:
    """Holds agent advertisements and their handlers; answers capability queries."""

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, card: AgentCard, handler: Handler | None = None) -> AgentCard:
        """Advertise an agent (optionally with a handler that serves invocations)."""
        if not isinstance(card, AgentCard):
            raise EnvelopeError("register expects an AgentCard")
        self._cards[card.agent_id] = card
        if handler is not None:
            if not callable(handler):
                raise EnvelopeError("handler must be callable")
            self._handlers[card.agent_id] = handler
        return card

    def unregister(self, agent_id: str) -> None:
        """Remove an agent's advertisement and handler (idempotent)."""
        self._cards.pop(agent_id, None)
        self._handlers.pop(agent_id, None)

    def get(self, agent_id: str) -> AgentCard | None:
        return self._cards.get(agent_id)

    def cards(self) -> tuple[AgentCard, ...]:
        """All cards, ordered by agent id."""
        return tuple(self._cards[a] for a in sorted(self._cards))

    def discover(self, capability: str) -> tuple[AgentCard, ...]:
        """Cards serving ``capability``, ordered by agent id (empty if none)."""
        if not isinstance(capability, str) or not capability:
            return ()
        return tuple(self._cards[a] for a in sorted(self._cards) if self._cards[a].supports(capability))

    def resolve(self, capability: str, *, agent_id: str | None = None) -> tuple[AgentCard, Handler]:
        """Pick the handler for a capability (deterministically the lowest agent id).

        If ``agent_id`` is given, that specific agent must serve the capability.
        Raises :class:`NoAgentError` when nothing matches or the match has no
        handler.
        """
        if agent_id is not None:
            card = self._cards.get(agent_id)
            if card is None or not card.supports(capability):
                raise NoAgentError(f"agent {agent_id!r} does not serve capability {capability!r}")
            candidates = [card]
        else:
            candidates = list(self.discover(capability))
        for card in candidates:
            handler = self._handlers.get(card.agent_id)
            if handler is not None:
                return card, handler
        raise NoAgentError(f"no handler serves capability {capability!r}")


# ---------------------------------------------------------------------------
# STRUCTURED RESULT EXCHANGE -- typed envelopes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Request:
    """A validated invocation request envelope."""

    id: str
    capability: str
    payload: types.MappingProxyType = dataclasses.field(default_factory=lambda: types.MappingProxyType({}))
    agent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise EnvelopeError("Request.id must be a non-empty string")
        if not isinstance(self.capability, str) or not self.capability.strip():
            raise EnvelopeError("Request.capability must be a non-empty string")
        if self.agent_id is not None and (not isinstance(self.agent_id, str) or not self.agent_id.strip()):
            raise EnvelopeError("Request.agent_id must be a non-empty string or None")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload, field="Request.payload"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "request",
            "id": self.id,
            "capability": self.capability,
            "payload": _plain(self.payload),
            "agent_id": self.agent_id,
        }


@dataclasses.dataclass(frozen=True)
class Result:
    """A validated invocation result envelope.

    Invariants: an ``OK`` result carries no error; ``ERROR``/``REJECTED``
    results carry a non-empty error string; ``CANCELLED`` results carry no
    result payload.
    """

    id: str
    capability: str
    status: Status
    result: types.MappingProxyType = dataclasses.field(default_factory=lambda: types.MappingProxyType({}))
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise EnvelopeError("Result.id must be a non-empty string")
        if not isinstance(self.capability, str) or not self.capability.strip():
            raise EnvelopeError("Result.capability must be a non-empty string")
        if not isinstance(self.status, Status):
            raise EnvelopeError("Result.status must be a Status")
        object.__setattr__(self, "result", _freeze_mapping(self.result, field="Result.result"))
        if self.status is Status.OK:
            if self.error is not None:
                raise EnvelopeError("Result.error must be None when status is OK")
        elif self.status in (Status.ERROR, Status.REJECTED):
            if not isinstance(self.error, str) or not self.error.strip():
                raise EnvelopeError(f"Result.error must be a non-empty string when status is {self.status.value}")
        elif self.status is Status.CANCELLED:
            if self.result:
                raise EnvelopeError("Result.result must be empty when status is CANCELLED")

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    @property
    def cancelled(self) -> bool:
        return self.status is Status.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "result",
            "id": self.id,
            "capability": self.capability,
            "status": self.status.value,
            "result": _plain(self.result),
            "error": self.error,
        }


def parse_request(data: Mapping[str, Any]) -> Request:
    """Build a :class:`Request` from a raw mapping, raising on any malformation."""
    if not isinstance(data, Mapping):
        raise EnvelopeError("request envelope must be a mapping")
    kind = data.get("kind", "request")
    if kind != "request":
        raise EnvelopeError(f"expected kind 'request', got {kind!r}")
    if "id" not in data or "capability" not in data:
        raise EnvelopeError("request envelope requires 'id' and 'capability'")
    payload = data.get("payload", {})
    return Request(
        id=data["id"],
        capability=data["capability"],
        payload=payload,
        agent_id=data.get("agent_id"),
    )


def parse_result(data: Mapping[str, Any]) -> Result:
    """Build a :class:`Result` from a raw mapping, raising on any malformation."""
    if not isinstance(data, Mapping):
        raise EnvelopeError("result envelope must be a mapping")
    kind = data.get("kind", "result")
    if kind != "result":
        raise EnvelopeError(f"expected kind 'result', got {kind!r}")
    for req in ("id", "capability", "status"):
        if req not in data:
            raise EnvelopeError(f"result envelope requires {req!r}")
    raw_status = data["status"]
    try:
        status = raw_status if isinstance(raw_status, Status) else Status(raw_status)
    except ValueError as exc:
        raise EnvelopeError(f"unknown status {raw_status!r}") from exc
    return Result(
        id=data["id"],
        capability=data["capability"],
        status=status,
        result=data.get("result", {}),
        error=data.get("error"),
    )


# ---------------------------------------------------------------------------
# CANCELLATION -- cooperative token
# ---------------------------------------------------------------------------


class CancelToken:
    """A cooperative cancellation signal shared between caller and callee.

    The caller calls :meth:`cancel`; the callee polls :attr:`cancelled` at its
    checkpoints and calls :meth:`mark_observed` when it acts on the signal, so
    the caller can prove the cancel was actually seen by the invoked side.
    """

    __slots__ = ("_cancelled", "_observed")

    def __init__(self) -> None:
        self._cancelled = False
        self._observed = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def observed(self) -> bool:
        return self._observed

    def cancel(self) -> None:
        self._cancelled = True

    def mark_observed(self) -> None:
        """Called by the callee to acknowledge it saw and honored the cancel."""
        self._observed = True

    def raise_if_cancelled(self) -> None:
        """Convenience for handlers that prefer to abort via exception."""
        if self._cancelled:
            self._observed = True
            raise Cancelled()


# ---------------------------------------------------------------------------
# INVOCATION -- transport + drivable handle
# ---------------------------------------------------------------------------


@runtime_checkable
class Transport(Protocol):
    """Dispatches a request to a callee, yielding at each cooperative checkpoint.

    ``run`` is a generator: it yields ``None`` once per checkpoint reached in
    the callee and *returns* (via ``StopIteration.value``) the terminal
    :class:`Result`. This single shape serves both one-shot invocation
    (exhaust the generator) and step-wise cancellation (advance it between
    caller decisions). Implementations must not touch the network, a clock, or
    an RNG.
    """

    def run(self, request: Request, cancel: CancelToken) -> Generator[None, None, Result]: ...


class LocalTransport:
    """In-process transport that routes requests to registered handlers."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def run(self, request: Request, cancel: CancelToken) -> Generator[None, None, Result]:
        try:
            card, handler = self._registry.resolve(request.capability, agent_id=request.agent_id)
        except NoAgentError as exc:
            return Result(
                id=request.id,
                capability=request.capability,
                status=Status.ERROR,
                error=str(exc),
            )
        # Honor a cancel requested before the callee ever ran.
        if cancel.cancelled:
            cancel.mark_observed()
            return Result(id=request.id, capability=request.capability, status=Status.CANCELLED)

        try:
            outcome = handler(request, cancel)
        except Cancelled:
            cancel.mark_observed()
            return Result(id=request.id, capability=request.capability, status=Status.CANCELLED)
        except (ValueError, KeyError, TypeError, ArithmeticError, LookupError) as exc:
            return Result(
                id=request.id,
                capability=request.capability,
                status=Status.ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

        payload: Any
        if isinstance(outcome, types.GeneratorType):
            payload, cancelled = yield from self._drive(outcome, cancel, request)
            if cancelled:
                return Result(id=request.id, capability=request.capability, status=Status.CANCELLED)
        else:
            payload = outcome
            if cancel.cancelled:
                cancel.mark_observed()
                return Result(id=request.id, capability=request.capability, status=Status.CANCELLED)

        if payload is None:
            payload = {}
        try:
            return Result(id=request.id, capability=request.capability, status=Status.OK, result=payload)
        except EnvelopeError as exc:
            return Result(
                id=request.id,
                capability=request.capability,
                status=Status.ERROR,
                error=f"handler returned invalid result payload: {exc}",
            )

    def _drive(
        self,
        gen: Generator[None, None, Any],
        cancel: CancelToken,
        request: Request,
    ) -> Generator[None, None, tuple[Any, bool]]:
        """Advance a generator handler, surfacing each checkpoint to the caller.

        Returns ``(payload, cancelled)``. The handler observes cancellation at
        its own checkpoints (polling ``cancel.cancelled`` / calling
        ``raise_if_cancelled``); we also treat an explicit ``Cancelled`` raise
        or a still-pending cancel at completion as a cancellation.
        """
        payload: Any = None
        try:
            while True:
                gen.send(None)
                # Surface this checkpoint to whoever is driving the transport.
                yield
        except StopIteration as stop:
            payload = stop.value
        except Cancelled:
            cancel.mark_observed()
            return None, True
        if cancel.cancelled:
            cancel.mark_observed()
            return None, True
        return payload, False


class Invocation:
    """A drivable handle over a single in-flight invocation.

    Step-wise driving (:meth:`step`) lets a caller advance the callee one
    cooperative checkpoint at a time and :meth:`cancel` between steps;
    :meth:`run` exhausts it in one go. Either way the terminal :class:`Result`
    is available from :attr:`result` once :attr:`finished`.
    """

    def __init__(self, request: Request, cancel: CancelToken, driver: Generator[None, None, Result]) -> None:
        self.request = request
        self._cancel = cancel
        self._driver = driver
        self._result: Result | None = None
        self._finished = False

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def cancel_token(self) -> CancelToken:
        return self._cancel

    @property
    def result(self) -> Result | None:
        return self._result

    def cancel(self) -> None:
        """Request cancellation; the callee observes it at its next checkpoint."""
        self._cancel.cancel()

    def step(self) -> bool:
        """Advance one checkpoint. Returns True while more work remains."""
        if self._finished:
            return False
        try:
            next(self._driver)
            return True
        except StopIteration as stop:
            self._result = stop.value
            self._finished = True
            return False

    def run(self) -> Result:
        """Drive the invocation to completion and return the terminal result."""
        while self.step():
            pass
        assert self._result is not None  # a transport generator always returns a Result
        return self._result


def _default_id_factory() -> Callable[[], str]:
    counter = 0

    def factory() -> str:
        nonlocal counter
        counter += 1
        return f"req-{counter}"

    return factory


class ACPBroker:
    """Top-level ACP node: registry + envelope construction + dispatch.

    The broker is the surface an agent uses to advertise itself, discover
    peers, and invoke them. Determinism comes from an injectable ``id_factory``
    (a monotonic counter by default) -- never a clock or RNG.
    """

    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        transport: Transport | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry or AgentRegistry()
        self.transport: Transport = transport or LocalTransport(self.registry)
        self._id_factory = id_factory or _default_id_factory()

    # -- DISCOVERY --------------------------------------------------------

    def advertise(
        self, agent_id: str, capabilities: Iterable[str], *, handler: Handler | None = None, **kw: Any
    ) -> AgentCard:
        """Register an agent card and (optionally) its serving handler."""
        card = AgentCard(
            agent_id=agent_id, capabilities=frozenset(capabilities), name=kw.get("name", ""), meta=kw.get("meta", {})
        )
        self.registry.register(card, handler)
        return card

    def register(self, card: AgentCard, handler: Handler | None = None) -> AgentCard:
        return self.registry.register(card, handler)

    def discover(self, capability: str) -> tuple[AgentCard, ...]:
        return self.registry.discover(capability)

    # -- INVOCATION -------------------------------------------------------

    def new_request(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
        *,
        agent_id: str | None = None,
        request_id: str | None = None,
    ) -> Request:
        """Build a typed :class:`Request` with a deterministic id."""
        return Request(
            id=request_id or self._id_factory(),
            capability=capability,
            payload=payload or {},
            agent_id=agent_id,
        )

    def begin(self, request: Request) -> Invocation:
        """Open a cancellable invocation without running it yet."""
        if not isinstance(request, Request):
            raise EnvelopeError("begin expects a Request envelope")
        cancel = CancelToken()
        driver = self.transport.run(request, cancel)
        return Invocation(request, cancel, driver)

    def invoke(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
        *,
        agent_id: str | None = None,
        request_id: str | None = None,
    ) -> Result:
        """One-shot: build a request, dispatch it, and return the result."""
        request = self.new_request(capability, payload, agent_id=agent_id, request_id=request_id)
        return self.begin(request).run()

    def submit(self, raw: Mapping[str, Any]) -> Result:
        """Dispatch a raw request mapping, returning a REJECTED result if malformed."""
        try:
            request = parse_request(raw)
        except EnvelopeError as exc:
            rid = (
                raw.get("id")
                if isinstance(raw, Mapping) and isinstance(raw.get("id"), str) and raw.get("id")
                else "malformed"
            )
            cap = (
                raw.get("capability")
                if isinstance(raw, Mapping) and isinstance(raw.get("capability"), str) and raw.get("capability")
                else "unknown"
            )
            return Result(id=rid, capability=cap, status=Status.REJECTED, error=str(exc))
        return self.begin(request).run()
