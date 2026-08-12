"""Post-deploy monitoring loop (CAP-121).

Feed a **deployed application's health and errors back to the agent** as
structured, trace-linked findings the agent loop can pick up as new work.

The loop has three moving parts, each behind an injectable seam so the whole
thing runs deterministically and offline under test:

1. **Ingest** -- a :class:`MonitorSource` yields :class:`HealthSample` signals
   (health status + error count + trace identity) for the deployed app. The real
   default :class:`HttpHealthSource` polls an HTTP health endpoint over stdlib
   ``urllib`` and parses its JSON body; :class:`FakeMonitorSource` replays a
   scripted list of samples for hermetic tests.

2. **Feed back to the agent** -- :class:`PostDeployMonitor` turns a detected
   *health regression* (status got worse than the last observation) or an *error
   spike* (error count jumped versus a rolling :class:`ErrorBaseline`) into an
   :class:`AgentFeedback` item carrying *what regressed*, a *severity*, and the
   *offending signal*. :meth:`AgentFeedback.to_finding` / :meth:`~AgentFeedback.to_task`
   render it in the shape the agent loop consumes.

3. **Trace-linked diagnosis** -- every sample and every feedback carries a
   ``trace_id`` / ``span_id``. :meth:`PostDeployMonitor.query_diagnosis` resolves
   that trace back through an injected :class:`TraceOriginStore` to the
   originating change / run, so the diagnosis points at the *likely cause*. The
   default :class:`InMemoryTraceOriginStore` is a live in-process registry;
   :class:`ToolTraceOriginStore` bridges to the durable CAP-138
   :class:`~thomas.observability.tool_trace.ToolTraceStore` so deployed errors
   link to actually-recorded runs.

This module lives in the ``observability`` (infra) tier and only imports from
``core``, the sibling ``tool_trace`` module, and the standard library.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Health status ranked worst-last; a *higher* rank is a worse state, so a rank
# increase between consecutive samples is a regression.
_STATUS_RANK: dict[str, int] = {
    "healthy": 0,
    "degraded": 1,
    "unhealthy": 2,
    "unreachable": 3,
}


class Severity(IntEnum):
    """Feedback severity, ordered so a larger value is more urgent."""

    INFO = 10
    WARNING = 20
    HIGH = 30
    CRITICAL = 40

    @property
    def label(self) -> str:
        return self.name.lower()


# Severity assigned to a regression *into* each status.
_STATUS_SEVERITY: dict[str, Severity] = {
    "degraded": Severity.WARNING,
    "unhealthy": Severity.CRITICAL,
    "unreachable": Severity.CRITICAL,
}


@dataclass(frozen=True)
class HealthSample:
    """One observation of a deployed app's health and error volume.

    ``status`` is one of ``healthy``/``degraded``/``unhealthy``/``unreachable``.
    ``trace_id`` / ``span_id`` tie the observation to the change/run that is
    running in the deployment, enabling trace-linked diagnosis.
    """

    status: str
    error_count: int = 0
    deploy_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    observed_at: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"

    @property
    def rank(self) -> int:
        return _STATUS_RANK.get(self.status, _STATUS_RANK["unhealthy"])

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error_count": self.error_count,
            "deploy_id": self.deploy_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "observed_at": self.observed_at,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class OriginRecord:
    """The change/run that produced a deployed trace -- the diagnosis target."""

    trace_id: str
    run_id: str
    change_ref: str | None = None
    session_id: str | None = None
    summary: str = ""
    created_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "change_ref": self.change_ref,
            "session_id": self.session_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AgentFeedback:
    """A regression/spike rendered as a finding the agent loop can consume.

    Carries *what regressed* (``kind`` + ``summary``), the ``severity``, the
    *offending signal* (``signal``), and the trace identity so it can be linked
    back to the originating run via :meth:`PostDeployMonitor.query_diagnosis`.
    """

    kind: str
    severity: Severity
    summary: str
    signal: HealthSample
    trace_id: str | None = None
    span_id: str | None = None
    deploy_id: str | None = None
    created_at: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_finding(self) -> dict[str, Any]:
        """Render as a structured finding dict for the agent loop."""

        return {
            "source": "post_deploy_monitor",
            "kind": self.kind,
            "severity": self.severity.label,
            "summary": self.summary,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "deploy_id": self.deploy_id,
            "signal": self.signal.as_dict(),
            "detail": dict(self.detail),
            "created_at": self.created_at,
        }

    def to_task(self) -> dict[str, Any]:
        """Render as a new-task payload the agent loop can enqueue."""

        return {
            "title": self.summary,
            "kind": self.kind,
            "severity": self.severity.label,
            "trace_id": self.trace_id,
            "origin_hint": "post_deploy_monitor",
            "finding": self.to_finding(),
        }


@dataclass(frozen=True)
class Diagnosis:
    """Result of linking a deployed error trace back to its originating run."""

    trace_id: str
    linked: bool
    origin: OriginRecord | None
    feedback: tuple[AgentFeedback, ...] = ()
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "linked": self.linked,
            "origin": self.origin.as_dict() if self.origin else None,
            "feedback": [fb.to_finding() for fb in self.feedback],
            "summary": self.summary,
        }


# --------------------------------------------------------------------------- #
# Injectable seams: monitor source + trace-origin store
# --------------------------------------------------------------------------- #
@runtime_checkable
class MonitorSource(Protocol):
    """Yields the next :class:`HealthSample` for the deployed app."""

    def fetch(self) -> HealthSample: ...


@runtime_checkable
class TraceOriginStore(Protocol):
    """Resolves a deployed ``trace_id`` to the change/run that produced it."""

    def lookup(self, trace_id: str) -> OriginRecord | None: ...


class FakeMonitorSource:
    """Hermetic source replaying a scripted list of samples, in order.

    Once the script is exhausted the final sample is repeated so a loop can keep
    polling deterministically.
    """

    def __init__(self, samples: Sequence[HealthSample]) -> None:
        if not samples:
            raise ValueError("FakeMonitorSource requires at least one sample")
        self._samples = list(samples)
        self._i = 0

    def fetch(self) -> HealthSample:
        if self._i < len(self._samples):
            sample = self._samples[self._i]
            self._i += 1
        else:
            sample = self._samples[-1]
        return sample


class HttpHealthSource:
    """Real default source: poll an HTTP health endpoint over stdlib urllib.

    The endpoint is expected to return a JSON body such as::

        {"status": "healthy", "errors": 0, "deploy_id": "d-9",
         "trace_id": "t-9", "span_id": "s-9"}

    A transport failure or unparseable body is itself reported as an
    ``unreachable`` sample rather than raising, so the monitoring loop keeps
    running and surfaces the outage as a regression.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 5.0,
        deploy_id: str | None = None,
        opener: urllib.request.OpenerDirector | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._deploy_id = deploy_id
        self._opener = opener or urllib.request.build_opener()
        self._clock: Callable[[], float] = clock or time.time

    def fetch(self) -> HealthSample:
        req = urllib.request.Request(self._url, headers={"Accept": "application/json"})
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                http_status = getattr(resp, "status", 200) or 200
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("health poll of %s failed: %s", self._url, exc)
            return HealthSample(
                status="unreachable",
                error_count=0,
                deploy_id=self._deploy_id,
                observed_at=self._clock(),
                detail={"error": str(exc)},
            )
        return self._parse(raw, int(http_status))

    def _parse(self, raw: str, http_status: int) -> HealthSample:
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("health body was not a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("health body from %s was unparseable: %s", self._url, exc)
            status = "healthy" if 200 <= http_status < 300 else "unhealthy"
            return HealthSample(
                status=status,
                error_count=0,
                deploy_id=self._deploy_id,
                observed_at=self._clock(),
                detail={"http_status": http_status, "parse_error": str(exc)},
            )
        status = str(body.get("status") or ("healthy" if 200 <= http_status < 300 else "unhealthy"))
        if status not in _STATUS_RANK:
            status = "healthy" if 200 <= http_status < 300 else "unhealthy"
        return HealthSample(
            status=status,
            error_count=int(body.get("errors", body.get("error_count", 0)) or 0),
            deploy_id=str(body["deploy_id"]) if body.get("deploy_id") else self._deploy_id,
            trace_id=str(body["trace_id"]) if body.get("trace_id") else None,
            span_id=str(body["span_id"]) if body.get("span_id") else None,
            observed_at=self._clock(),
            detail={"http_status": http_status},
        )


class InMemoryTraceOriginStore:
    """Live in-process registry mapping deployed ``trace_id`` to its origin."""

    def __init__(self) -> None:
        self._by_trace: dict[str, OriginRecord] = {}

    def record_origin(self, origin: OriginRecord) -> None:
        self._by_trace[origin.trace_id] = origin

    def lookup(self, trace_id: str) -> OriginRecord | None:
        return self._by_trace.get(trace_id)


class ToolTraceOriginStore:
    """Bridge the CAP-138 tool-trace store as a trace-origin source.

    Given a deployed ``trace_id``, walk the durable
    :class:`~thomas.observability.tool_trace.ToolTraceStore` link graph and treat
    the *earliest* recorded call in the connected chain as the originating run --
    so a deployed error links back to the tool run that shipped the change.
    """

    def __init__(self, trace_store: Any) -> None:
        self._store = trace_store

    def lookup(self, trace_id: str) -> OriginRecord | None:
        calls = self._store.query_trace(trace_id)
        if not calls:
            return None
        origin_call = min(calls, key=lambda c: c.started_at or 0.0)
        return OriginRecord(
            trace_id=trace_id,
            run_id=origin_call.call_id,
            change_ref=origin_call.tool_name,
            session_id=origin_call.session_id,
            summary=f"originating run: {origin_call.tool_name} in session {origin_call.session_id}",
            created_at=origin_call.started_at,
        )


class ErrorBaseline:
    """Rolling baseline of error counts used for spike detection.

    Keeps the most recent ``window`` error counts. A spike is judged once at
    least ``min_samples`` have been seen (or an explicit ``seed_mean`` was given),
    against the running mean of those samples.
    """

    def __init__(
        self,
        *,
        window: int = 20,
        min_samples: int = 3,
        seed_mean: float | None = None,
    ) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        self._min_samples = min_samples
        self._seed_mean = seed_mean

    def observe(self, error_count: int) -> None:
        self._samples.append(float(error_count))

    def mean(self) -> float:
        if self._samples:
            return sum(self._samples) / len(self._samples)
        return self._seed_mean if self._seed_mean is not None else 0.0

    def ready(self) -> bool:
        return len(self._samples) >= self._min_samples or self._seed_mean is not None


class PostDeployMonitor:
    """Poll a deployed app's health/errors and feed regressions to the agent.

    Parameters
    ----------
    source:
        Injectable :class:`MonitorSource` (real HTTP poller or hermetic fake).
    trace_store:
        Injectable :class:`TraceOriginStore` for trace-linked diagnosis; defaults
        to an empty :class:`InMemoryTraceOriginStore`.
    baseline:
        Injectable :class:`ErrorBaseline`; defaults to a fresh rolling baseline.
    spike_factor:
        An error count above ``baseline_mean * spike_factor`` (and above
        ``min_spike_errors``) is a spike.
    high_ratio:
        A spike whose error count is at least ``high_ratio``x the baseline mean is
        escalated to :attr:`Severity.HIGH`.
    min_spike_errors:
        Absolute floor so tiny absolute jumps off a near-zero baseline do not fire.
    clock:
        ``() -> float`` seconds source for feedback timestamps; injectable.
    """

    def __init__(
        self,
        source: MonitorSource,
        *,
        trace_store: TraceOriginStore | None = None,
        baseline: ErrorBaseline | None = None,
        spike_factor: float = 3.0,
        high_ratio: float = 5.0,
        min_spike_errors: int = 5,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._source = source
        self._trace_store = trace_store or InMemoryTraceOriginStore()
        self._baseline = baseline or ErrorBaseline()
        self._spike_factor = spike_factor
        self._high_ratio = high_ratio
        self._min_spike_errors = min_spike_errors
        self._clock: Callable[[], float] = clock or time.time
        self._last_rank: int | None = None
        self._feedback_by_trace: dict[str, list[AgentFeedback]] = {}

    @property
    def trace_store(self) -> TraceOriginStore:
        return self._trace_store

    def poll(self) -> list[AgentFeedback]:
        """Fetch the next sample and return any feedback it triggers."""

        return self.observe(self._source.fetch())

    def run(self, max_polls: int) -> list[AgentFeedback]:
        """Poll up to ``max_polls`` times, returning all feedback produced."""

        collected: list[AgentFeedback] = []
        for _ in range(max_polls):
            collected.extend(self.poll())
        return collected

    def observe(self, sample: HealthSample) -> list[AgentFeedback]:
        """Evaluate a single sample against health/error baselines.

        Returns a (possibly empty) list of :class:`AgentFeedback`. A healthy
        sample with no error spike yields no feedback.
        """

        now = self._clock()
        feedback: list[AgentFeedback] = []

        regression = self._detect_health_regression(sample, now)
        if regression is not None:
            feedback.append(regression)

        spike = self._detect_error_spike(sample, now)
        if spike is not None:
            feedback.append(spike)

        # Update state *after* evaluation so a sample is judged against prior
        # observations, never against itself.
        self._last_rank = sample.rank
        self._baseline.observe(sample.error_count)

        for fb in feedback:
            if fb.trace_id:
                self._feedback_by_trace.setdefault(fb.trace_id, []).append(fb)
        return feedback

    def _detect_health_regression(self, sample: HealthSample, now: float) -> AgentFeedback | None:
        prev_rank = self._last_rank
        if prev_rank is not None and sample.rank <= prev_rank:
            return None
        if sample.healthy:
            return None
        severity = _STATUS_SEVERITY.get(sample.status, Severity.HIGH)
        prev_status = _rank_status(prev_rank)
        summary = (
            f"deploy health regressed to '{sample.status}'"
            + (f" from '{prev_status}'" if prev_status else "")
            + (f" (deploy {sample.deploy_id})" if sample.deploy_id else "")
        )
        return AgentFeedback(
            kind="health_regression",
            severity=severity,
            summary=summary,
            signal=sample,
            trace_id=sample.trace_id,
            span_id=sample.span_id,
            deploy_id=sample.deploy_id,
            created_at=now,
            detail={
                "previous_status": prev_status,
                "current_status": sample.status,
            },
        )

    def _detect_error_spike(self, sample: HealthSample, now: float) -> AgentFeedback | None:
        if not self._baseline.ready():
            return None
        mean = self._baseline.mean()
        threshold = max(float(self._min_spike_errors), mean * self._spike_factor)
        if sample.error_count <= threshold:
            return None
        ratio = sample.error_count / mean if mean > 0 else float("inf")
        severity = Severity.HIGH if ratio >= self._high_ratio else Severity.WARNING
        summary = (
            f"error spike: {sample.error_count} errors vs baseline mean "
            f"{mean:.2f} (>{threshold:.2f} threshold)" + (f" on deploy {sample.deploy_id}" if sample.deploy_id else "")
        )
        return AgentFeedback(
            kind="error_spike",
            severity=severity,
            summary=summary,
            signal=sample,
            trace_id=sample.trace_id,
            span_id=sample.span_id,
            deploy_id=sample.deploy_id,
            created_at=now,
            detail={
                "baseline_mean": mean,
                "threshold": threshold,
                "error_count": sample.error_count,
                "ratio": ratio,
            },
        )

    def query_diagnosis(self, trace_id: str) -> Diagnosis:
        """Link a deployed error ``trace_id`` back to its originating run.

        Resolves the trace through the injected :class:`TraceOriginStore` and
        attaches any feedback this monitor emitted for that trace, so the
        diagnosis points at the likely cause.
        """

        origin = self._trace_store.lookup(trace_id)
        emitted = tuple(self._feedback_by_trace.get(trace_id, ()))
        if origin is not None:
            summary = f"trace {trace_id} links to originating run {origin.run_id}" + (
                f" ({origin.change_ref})" if origin.change_ref else ""
            )
        else:
            summary = f"no originating run recorded for trace {trace_id}"
        return Diagnosis(
            trace_id=trace_id,
            linked=origin is not None,
            origin=origin,
            feedback=emitted,
            summary=summary,
        )


def _rank_status(rank: int | None) -> str | None:
    if rank is None:
        return None
    for status, value in _STATUS_RANK.items():
        if value == rank:
            return status
    return None


def iter_findings(feedback: Iterable[AgentFeedback]) -> list[dict[str, Any]]:
    """Convenience: render a batch of feedback as agent-loop finding dicts."""

    return [fb.to_finding() for fb in feedback]
