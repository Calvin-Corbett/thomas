"""CAP-074: Bring-Your-Own (BYO) custom-connector support.

This module is a *framework*, not an external-service client. It gives third
parties a documented, first-class path to plug their own connector into Thomas
and a conformance harness that certifies a candidate connector against the
contract before it is trusted.

Three pieces make up the path:

1. The :class:`Connector` contract -- a runtime-checkable ``Protocol`` (with an
   optional :class:`BaseConnector` ABC to subclass) describing the four methods
   every connector must expose::

       metadata()  -> Mapping   # name, version, description, ...
       capabilities() -> Sequence[Mapping]  # declared actions this connector serves
       invoke(action, params) -> Mapping    # structured result envelope
       health() -> Mapping                  # liveness / status report

   ``invoke`` never raises for a normal failure: it returns a *structured
   envelope* (see :data:`ENVELOPE_KEYS`) so callers get a uniform result shape
   regardless of which third party wrote the connector.

2. :func:`run_conformance` -- the conformance harness. It validates a candidate
   connector against the contract (required methods present, metadata
   well-formed, capabilities declared, ``invoke`` returns the structured
   envelope for each declared capability, unknown-action errors are handled
   without raising, slow calls are bounded by a timeout, and ``health`` reports)
   and returns a deterministic :class:`ConformanceReport` with a per-check
   pass/fail breakdown and an overall ``certified`` boolean.

3. :class:`ConnectorRegistry` -- register / discover custom connectors. By
   default registration runs the conformance harness first and refuses to
   register a connector that is not certified, so only conformant connectors
   become invokable through the registry.

The whole module is hermetic and self-contained: no network, no credentials,
no external service. A connector *implementation* written by a third party may
of course talk to a real service inside ``invoke`` -- the framework only cares
that it honours the contract, which the harness proves offline against a fake.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Version of the conformance contract this harness enforces. Bumped when the
# envelope shape or required-method set changes in a backward-incompatible way.
CONFORMANCE_VERSION = "1.0"

# The exact keys a well-formed ``invoke`` envelope must contain.
ENVELOPE_KEYS: frozenset[str] = frozenset({"ok", "action", "result", "error"})

# Methods every connector must expose (the contract surface).
REQUIRED_METHODS: tuple[str, ...] = ("metadata", "capabilities", "invoke", "health")

# Default per-invoke wall-clock budget used by the harness and the registry.
DEFAULT_TIMEOUT_S = 5.0

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
_ACTION_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
@runtime_checkable
class Connector(Protocol):
    """The first-class custom-connector contract.

    A third party implements these four methods (directly, or by subclassing
    :class:`BaseConnector`). All methods are synchronous and side-effect scoped
    to a single call so the harness can validate them deterministically.
    """

    def metadata(self) -> Mapping[str, Any]:
        """Return static descriptor: ``name`` and ``version`` are required."""
        ...

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        """Return the declared actions. Each entry needs an ``action`` name.

        An entry may also carry ``description`` and a ``sample`` params mapping
        the harness feeds to ``invoke`` when exercising the capability.
        """
        ...

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute ``action`` with ``params`` and return a structured envelope.

        The envelope MUST contain the keys in :data:`ENVELOPE_KEYS`. Normal
        failures (unknown action, validation error, downstream error) are
        reported as ``{"ok": False, "error": "..."}`` -- not raised.
        """
        ...

    def health(self) -> Mapping[str, Any]:
        """Return a liveness report. Must contain a boolean ``ok`` key."""
        ...


def make_envelope(
    action: str,
    *,
    ok: bool,
    result: Any = None,
    error: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build a contract-shaped ``invoke`` envelope.

    Helper for connector authors so they do not have to remember the exact
    key set. Extra keys (e.g. ``meta``) are allowed and preserved.
    """
    envelope: dict[str, Any] = {
        "ok": bool(ok),
        "action": str(action),
        "result": result,
        "error": str(error or ""),
    }
    envelope.update(extra)
    return envelope


class BaseConnector:
    """Optional ABC-style base making the contract easy to implement.

    Subclasses declare :meth:`metadata` and :meth:`capabilities`, register
    handlers via :meth:`handle`, and get ``invoke``/``health`` for free with
    correct envelope shaping, unknown-action handling, and exception capture.
    """

    def metadata(self) -> Mapping[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError

    def capabilities(self) -> Sequence[Mapping[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        """Dispatch ``action`` to real work. Override this in a subclass.

        Raise :class:`KeyError` for an unknown action; return the raw result
        for a known one. ``invoke`` wraps the return value in an envelope and
        turns raised errors into ``ok=False`` envelopes.
        """
        raise KeyError(action)

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        declared = {str(cap.get("action", "")) for cap in self.capabilities()}
        if action not in declared:
            return make_envelope(action, ok=False, error=f"unknown action: {action!r}")
        try:
            result = self.handle(action, dict(params or {}))
        except KeyError:
            return make_envelope(action, ok=False, error=f"unknown action: {action!r}")
        except (ValueError, TypeError, LookupError, RuntimeError) as exc:
            return make_envelope(action, ok=False, error=f"{type(exc).__name__}: {exc}")
        return make_envelope(action, ok=True, result=result)

    def health(self) -> Mapping[str, Any]:
        return {"ok": True, "status": "healthy"}


# ---------------------------------------------------------------------------
# Conformance report
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single conformance check."""

    check: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ConformanceReport:
    """Result of running the conformance harness against a connector."""

    connector: str
    version: str
    checks: tuple[CheckResult, ...]
    certified: bool

    def failing(self) -> list[CheckResult]:
        """Return only the checks that did not pass, in run order."""
        return [c for c in self.checks if not c.passed]

    def first_failure(self) -> CheckResult | None:
        """Return the first failing check (the precise cause), or ``None``."""
        failures = self.failing()
        return failures[0] if failures else None

    def check(self, name: str) -> CheckResult | None:
        for c in self.checks:
            if c.check == name:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "version": self.version,
            "certified": self.certified,
            "checks": [c.to_dict() for c in self.checks],
        }


class ConformanceError(RuntimeError):
    """Raised when a connector fails conformance during a certifying register."""

    def __init__(self, report: ConformanceReport) -> None:
        self.report = report
        failing = ", ".join(c.check for c in report.failing()) or "unknown"
        super().__init__(f"connector {report.connector!r} failed conformance: {failing}")


# ---------------------------------------------------------------------------
# Timeout guard (bounds third-party invoke without trusting it to cooperate)
# ---------------------------------------------------------------------------
@dataclass
class _CallOutcome:
    completed: bool = False
    value: Any = None
    error: BaseException | None = None


def _call_with_timeout(fn: Any, timeout: float) -> _CallOutcome:
    """Run ``fn()`` on a worker thread, bounded by ``timeout`` seconds.

    Returns an outcome describing whether it completed, its value, or the
    exception it raised. A call that overruns the budget is reported as not
    completed (the daemon worker is abandoned -- we never trust third-party
    code to be interruptible).
    """
    outcome = _CallOutcome()

    def _runner() -> None:
        try:
            outcome.value = fn()
            outcome.completed = True
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            LookupError,
            AttributeError,
            RuntimeError,
            OSError,
            ArithmeticError,
            AssertionError,
            NotImplementedError,
            ImportError,
            UnicodeError,
            StopIteration,
            RecursionError,
            MemoryError,
            TimeoutError,
        ) as exc:
            # A conformant connector raises only standard faults, all captured here as a
            # check failure. Anything more exotic (a custom BaseException subclass) escapes
            # into the abandoned daemon worker and is reported as "did not complete" below.
            outcome.error = exc
            outcome.completed = True

    worker = threading.Thread(target=_runner, daemon=True, name="byo-conformance-invoke")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return _CallOutcome(completed=False, error=None)
    return outcome


# ---------------------------------------------------------------------------
# Envelope validation
# ---------------------------------------------------------------------------
def _validate_envelope(value: Any, expected_action: str, *, expect_ok: bool) -> str:
    """Return an empty string if ``value`` is a well-formed envelope, else why not."""
    if not isinstance(value, Mapping):
        return f"invoke returned {type(value).__name__}, expected a mapping envelope"
    missing = ENVELOPE_KEYS - set(value.keys())
    if missing:
        return f"envelope missing keys: {sorted(missing)}"
    if not isinstance(value.get("ok"), bool):
        return "envelope 'ok' must be a bool"
    if not isinstance(value.get("action"), str):
        return "envelope 'action' must be a str"
    if value.get("action") != expected_action:
        return f"envelope 'action' is {value.get('action')!r}, expected {expected_action!r}"
    error = value.get("error")
    if not isinstance(error, str):
        return "envelope 'error' must be a str"
    if expect_ok:
        if value.get("ok") is not True:
            return f"expected ok=True for declared capability, got error={error!r}"
        if error:
            return f"ok=True but 'error' is non-empty: {error!r}"
    else:
        if value.get("ok") is not False:
            return "expected ok=False for the error case"
        if not error:
            return "ok=False but 'error' is empty (no reason given)"
    return ""


def _sample_params(cap: Mapping[str, Any]) -> dict[str, Any]:
    sample = cap.get("sample")
    return dict(sample) if isinstance(sample, Mapping) else {}


def _unknown_action(declared: set[str]) -> str:
    """A synthetic action name guaranteed not to collide with declared ones."""
    candidate = "__byo_conformance_unknown__"
    while candidate in declared:
        candidate += "_x"
    return candidate


# ---------------------------------------------------------------------------
# Conformance harness
# ---------------------------------------------------------------------------
def run_conformance(
    connector: Any,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> ConformanceReport:
    """Validate ``connector`` against the :class:`Connector` contract.

    Deterministic: the same connector produces the same report (checks run in a
    fixed order and short-circuit dependent checks on failure). Never raises for
    a non-conformant connector -- the non-conformance is captured in the report.

    Checks, in order:

    * ``methods_present``     -- all of :data:`REQUIRED_METHODS` exist & are callable
    * ``metadata_wellformed`` -- ``metadata()`` returns a mapping with a valid
                                  ``name`` and non-empty ``version``
    * ``capabilities_declared`` -- ``capabilities()`` returns a non-empty
                                  sequence of mappings, each with a unique, valid
                                  ``action`` name
    * ``invoke_envelope``     -- each declared capability's ``invoke`` returns a
                                  well-formed ``ok=True`` envelope within budget
    * ``error_handled``       -- an unknown action returns a well-formed
                                  ``ok=False`` envelope (does not raise)
    * ``timeout_handled``     -- ``invoke`` completes within the timeout budget
                                  (a hanging call fails this check)
    * ``health_reports``      -- ``health()`` returns a mapping with a bool ``ok``
    """
    name = _connector_name(connector)
    checks: list[CheckResult] = []

    # 1) Required methods present and callable.
    missing_methods = [m for m in REQUIRED_METHODS if not callable(getattr(connector, m, None))]
    methods_ok = not missing_methods
    checks.append(
        CheckResult(
            "methods_present",
            methods_ok,
            "" if methods_ok else f"missing/uncallable methods: {missing_methods}",
        )
    )
    if not methods_ok:
        # Nothing else can be trusted without the method surface.
        return _finalize(name, checks, remaining_after="methods_present")

    # 2) Metadata well-formed.
    meta_detail = _check_metadata(connector, timeout)
    checks.append(CheckResult("metadata_wellformed", not meta_detail, meta_detail))

    # 3) Capabilities declared.
    caps, caps_detail = _collect_capabilities(connector, timeout)
    checks.append(CheckResult("capabilities_declared", not caps_detail, caps_detail))
    if caps_detail:
        return _finalize(name, checks, remaining_after="capabilities_declared")

    declared = {str(cap.get("action", "")) for cap in caps}

    # 4) invoke returns a well-formed ok envelope for each declared capability,
    #    and 6) each such call finishes within the timeout budget.
    invoke_detail = ""
    timeout_detail = ""
    for cap in caps:
        action = str(cap.get("action", ""))
        params = _sample_params(cap)
        outcome = _call_with_timeout(lambda a=action, p=params: connector.invoke(a, p), timeout)
        if not outcome.completed:
            timeout_detail = f"invoke({action!r}) exceeded {timeout:g}s budget"
            invoke_detail = invoke_detail or f"invoke({action!r}) did not return within budget"
            break
        if outcome.error is not None:
            invoke_detail = f"invoke({action!r}) raised {type(outcome.error).__name__}: {outcome.error}"
            break
        problem = _validate_envelope(outcome.value, action, expect_ok=True)
        if problem:
            invoke_detail = f"invoke({action!r}): {problem}"
            break
    checks.append(CheckResult("invoke_envelope", not invoke_detail, invoke_detail))

    # 5) Unknown action is handled as an error envelope, not raised.
    error_detail = _check_error_handling(connector, declared, timeout)
    checks.append(CheckResult("error_handled", not error_detail, error_detail))

    # 6) Timeout handling (surfaces the overrun captured above, if any).
    checks.append(CheckResult("timeout_handled", not timeout_detail, timeout_detail))

    # 7) Health reports.
    health_detail = _check_health(connector, timeout)
    checks.append(CheckResult("health_reports", not health_detail, health_detail))

    certified = all(c.passed for c in checks)
    return ConformanceReport(name, CONFORMANCE_VERSION, tuple(checks), certified)


def _finalize(name: str, checks: list[CheckResult], *, remaining_after: str) -> ConformanceReport:
    """Fill in the checks that were skipped after an early short-circuit.

    Keeps the report shape stable (same check names, same order) regardless of
    where validation stopped -- important for determinism and for callers that
    look up checks by name.
    """
    ordered = [
        "methods_present",
        "metadata_wellformed",
        "capabilities_declared",
        "invoke_envelope",
        "error_handled",
        "timeout_handled",
        "health_reports",
    ]
    have = {c.check for c in checks}
    for check_name in ordered:
        if check_name not in have:
            checks.append(CheckResult(check_name, False, f"skipped: blocked by {remaining_after}"))
    # Re-sort into the canonical order.
    by_name = {c.check: c for c in checks}
    ordered_checks = tuple(by_name[n] for n in ordered)
    return ConformanceReport(name, CONFORMANCE_VERSION, ordered_checks, False)


def _connector_name(connector: Any) -> str:
    try:
        meta = connector.metadata()
        if isinstance(meta, Mapping):
            candidate = str(meta.get("name", "")).strip()
            if candidate:
                return candidate
    except (AttributeError, TypeError, ValueError, RuntimeError, LookupError):
        pass
    return type(connector).__name__


def _check_metadata(connector: Any, timeout: float) -> str:
    outcome = _call_with_timeout(connector.metadata, timeout)
    if not outcome.completed:
        return f"metadata() exceeded {timeout:g}s budget"
    if outcome.error is not None:
        return f"metadata() raised {type(outcome.error).__name__}: {outcome.error}"
    meta = outcome.value
    if not isinstance(meta, Mapping):
        return f"metadata() returned {type(meta).__name__}, expected a mapping"
    name = str(meta.get("name", "")).strip()
    if not name:
        return "metadata 'name' is missing or empty"
    if not _NAME_RE.match(name):
        return f"metadata 'name' {name!r} is not a valid identifier"
    version = str(meta.get("version", "")).strip()
    if not version:
        return "metadata 'version' is missing or empty"
    return ""


def _collect_capabilities(connector: Any, timeout: float) -> tuple[list[Mapping[str, Any]], str]:
    outcome = _call_with_timeout(connector.capabilities, timeout)
    if not outcome.completed:
        return [], f"capabilities() exceeded {timeout:g}s budget"
    if outcome.error is not None:
        return [], f"capabilities() raised {type(outcome.error).__name__}: {outcome.error}"
    caps = outcome.value
    if not isinstance(caps, Sequence) or isinstance(caps, (str, bytes)):
        return [], f"capabilities() returned {type(caps).__name__}, expected a sequence"
    caps_list = list(caps)
    if not caps_list:
        return [], "capabilities() is empty; a connector must declare at least one action"
    seen: set[str] = set()
    for idx, cap in enumerate(caps_list):
        if not isinstance(cap, Mapping):
            return [], f"capability #{idx} is {type(cap).__name__}, expected a mapping"
        action = str(cap.get("action", "")).strip()
        if not action:
            return [], f"capability #{idx} has no 'action' name"
        if not _ACTION_RE.match(action):
            return [], f"capability action {action!r} is not a valid identifier"
        if action in seen:
            return [], f"duplicate capability action {action!r}"
        seen.add(action)
    return caps_list, ""


def _check_error_handling(connector: Any, declared: set[str], timeout: float) -> str:
    unknown = _unknown_action(declared)
    outcome = _call_with_timeout(lambda: connector.invoke(unknown, {}), timeout)
    if not outcome.completed:
        return f"invoke({unknown!r}) exceeded {timeout:g}s budget"
    if outcome.error is not None:
        return (
            f"invoke() raised {type(outcome.error).__name__} on unknown action instead of returning an error envelope"
        )
    problem = _validate_envelope(outcome.value, unknown, expect_ok=False)
    return f"unknown-action envelope invalid: {problem}" if problem else ""


def _check_health(connector: Any, timeout: float) -> str:
    outcome = _call_with_timeout(connector.health, timeout)
    if not outcome.completed:
        return f"health() exceeded {timeout:g}s budget"
    if outcome.error is not None:
        return f"health() raised {type(outcome.error).__name__}: {outcome.error}"
    report = outcome.value
    if not isinstance(report, Mapping):
        return f"health() returned {type(report).__name__}, expected a mapping"
    if not isinstance(report.get("ok"), bool):
        return "health report must contain a bool 'ok'"
    return ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass
class _Entry:
    connector: Any
    report: ConformanceReport
    metadata: dict[str, Any] = field(default_factory=dict)


class ConnectorRegistry:
    """Register and discover certified custom connectors.

    By default :meth:`register` runs the conformance harness and refuses any
    connector that is not certified, so only conformant connectors ever become
    invokable through :meth:`invoke`.
    """

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._timeout = timeout
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.RLock()

    def register(
        self,
        connector: Any,
        *,
        certify: bool = True,
        timeout: float | None = None,
    ) -> ConformanceReport:
        """Register ``connector`` and return its conformance report.

        With ``certify=True`` (default) a non-conformant connector raises
        :class:`ConformanceError` and is NOT stored. With ``certify=False`` the
        connector is stored regardless (useful for diagnostics) but the report
        still reflects its true conformance.
        """
        budget = self._timeout if timeout is None else timeout
        report = run_conformance(connector, timeout=budget)
        if certify and not report.certified:
            raise ConformanceError(report)
        meta = _safe_metadata(connector)
        name = report.connector
        with self._lock:
            self._entries[name] = _Entry(connector=connector, report=report, metadata=meta)
        return report

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._entries.pop(name, None) is not None

    def get(self, name: str) -> Any:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            raise KeyError(name)
        return entry.connector

    def report_for(self, name: str) -> ConformanceReport:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            raise KeyError(name)
        return entry.report

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._entries)

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def discover(self) -> list[dict[str, Any]]:
        """Return a metadata + capability summary for every registered connector."""
        with self._lock:
            entries = list(self._entries.values())
        summary: list[dict[str, Any]] = []
        for entry in entries:
            actions = _safe_actions(entry.connector)
            summary.append(
                {
                    "name": entry.report.connector,
                    "metadata": dict(entry.metadata),
                    "actions": actions,
                    "certified": entry.report.certified,
                }
            )
        return sorted(summary, key=lambda item: item["name"])

    def invoke(
        self,
        name: str,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Invoke ``action`` on the registered connector ``name``.

        Returns a contract envelope. Bounds the call with the registry timeout;
        an overrun yields an ``ok=False`` timeout envelope rather than hanging
        the caller.
        """
        connector = self.get(name)
        budget = self._timeout if timeout is None else timeout
        payload = dict(params or {})
        outcome = _call_with_timeout(lambda: connector.invoke(action, payload), budget)
        if not outcome.completed:
            return make_envelope(action, ok=False, error=f"timeout: exceeded {budget:g}s budget")
        if outcome.error is not None:
            return make_envelope(
                action,
                ok=False,
                error=f"connector raised {type(outcome.error).__name__}: {outcome.error}",
            )
        value = outcome.value
        if not isinstance(value, Mapping):
            return make_envelope(action, ok=False, error="connector returned a non-envelope result")
        return dict(value)


def _safe_metadata(connector: Any) -> dict[str, Any]:
    try:
        meta = connector.metadata()
    except (AttributeError, TypeError, ValueError, RuntimeError, LookupError):
        return {}
    return dict(meta) if isinstance(meta, Mapping) else {}


def _safe_actions(connector: Any) -> list[str]:
    try:
        caps = connector.capabilities()
    except (AttributeError, TypeError, ValueError, RuntimeError, LookupError):
        return []
    if not isinstance(caps, Sequence) or isinstance(caps, (str, bytes)):
        return []
    actions = [str(cap.get("action", "")) for cap in caps if isinstance(cap, Mapping)]
    return sorted(a for a in actions if a)


__all__ = [
    "CONFORMANCE_VERSION",
    "ENVELOPE_KEYS",
    "REQUIRED_METHODS",
    "DEFAULT_TIMEOUT_S",
    "Connector",
    "BaseConnector",
    "make_envelope",
    "CheckResult",
    "ConformanceReport",
    "ConformanceError",
    "ConnectorRegistry",
    "run_conformance",
]
