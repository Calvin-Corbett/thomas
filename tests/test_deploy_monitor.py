"""Tests for the post-deploy monitoring loop (CAP-121).

Acceptance (L2): "Feed deployed-app health and errors back to the agent with
trace-linked diagnosis."

Proves, against a hermetic fake source and an injected clock:
* a health regression produces AgentFeedback with severity + offending signal;
* an error spike is detected versus a rolling baseline;
* the feedback is trace-linked and query_diagnosis returns the originating run;
* a healthy deploy produces no feedback;
* a full round-trip: ingest -> feedback -> finding -> diagnosis.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.observability.deploy_monitor import (
    AgentFeedback,
    Diagnosis,
    ErrorBaseline,
    FakeMonitorSource,
    HealthSample,
    InMemoryTraceOriginStore,
    OriginRecord,
    PostDeployMonitor,
    Severity,
    ToolTraceOriginStore,
    iter_findings,
)
from thomas.observability.tool_trace import ToolCall, ToolTraceStore


class FakeClock:
    """Deterministic injectable clock returning preset timestamps."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        if self._i < len(self._values):
            v = self._values[self._i]
            self._i += 1
        else:
            v = self._values[-1]
        return v


def _origin_store() -> InMemoryTraceOriginStore:
    store = InMemoryTraceOriginStore()
    store.record_origin(
        OriginRecord(
            trace_id="t-deploy-42",
            run_id="run-42",
            change_ref="pr-1007",
            session_id="sess-9",
            summary="shipped checkout refactor",
            created_at=50.0,
        )
    )
    return store


# --------------------------------------------------------------------------- #
# Health regression -> feedback with severity + signal
# --------------------------------------------------------------------------- #
def test_health_regression_produces_feedback_with_severity_and_signal() -> None:
    healthy = HealthSample(status="healthy", error_count=0, deploy_id="d-9")
    bad = HealthSample(
        status="unhealthy",
        error_count=1,
        deploy_id="d-9",
        trace_id="t-deploy-42",
        span_id="span-3",
    )
    monitor = PostDeployMonitor(
        FakeMonitorSource([healthy, bad]),
        trace_store=_origin_store(),
        clock=FakeClock([100.0, 200.0]),
    )

    assert monitor.poll() == []  # healthy first observation -> no feedback

    feedback = monitor.poll()
    assert len(feedback) == 1
    item = feedback[0]
    assert isinstance(item, AgentFeedback)
    assert item.kind == "health_regression"
    assert item.severity is Severity.CRITICAL
    # The offending signal travels with the feedback.
    assert item.signal is bad
    assert item.detail["previous_status"] == "healthy"
    assert item.detail["current_status"] == "unhealthy"
    assert item.created_at == 200.0

    finding = item.to_finding()
    assert finding["source"] == "post_deploy_monitor"
    assert finding["severity"] == "critical"
    assert finding["signal"]["error_count"] == 1


def test_degraded_regression_is_a_warning() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource(
            [
                HealthSample(status="healthy"),
                HealthSample(status="degraded", trace_id="t1"),
            ]
        ),
        clock=FakeClock([1.0, 2.0]),
    )
    monitor.poll()
    fb = monitor.poll()
    assert len(fb) == 1
    assert fb[0].severity is Severity.WARNING
    assert fb[0].kind == "health_regression"


def test_sustained_unhealthy_does_not_refire_regression() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource(
            [
                HealthSample(status="unhealthy", trace_id="t1"),
                HealthSample(status="unhealthy", trace_id="t1"),
            ]
        ),
        clock=FakeClock([1.0, 2.0]),
    )
    first = monitor.poll()
    second = monitor.poll()
    assert len(first) == 1  # first observation into unhealthy fires
    assert second == []  # no rank increase -> no repeat


# --------------------------------------------------------------------------- #
# Error spike detected versus a baseline
# --------------------------------------------------------------------------- #
def test_error_spike_detected_versus_baseline() -> None:
    # Three healthy low-error samples establish a baseline, then a spike.
    samples = [
        HealthSample(status="healthy", error_count=2),
        HealthSample(status="healthy", error_count=2),
        HealthSample(status="healthy", error_count=2),
        HealthSample(status="healthy", error_count=40, trace_id="t-deploy-42"),
    ]
    monitor = PostDeployMonitor(
        FakeMonitorSource(samples),
        trace_store=_origin_store(),
        baseline=ErrorBaseline(min_samples=3),
        clock=FakeClock([1.0, 2.0, 3.0, 4.0]),
    )
    assert monitor.poll() == []
    assert monitor.poll() == []
    assert monitor.poll() == []  # baseline still healthy, no spike

    feedback = monitor.poll()
    assert len(feedback) == 1
    spike = feedback[0]
    assert spike.kind == "error_spike"
    assert spike.severity is Severity.HIGH  # 40 vs mean 2 -> ratio 20 >= high_ratio
    assert spike.detail["baseline_mean"] == pytest.approx(2.0)
    assert spike.detail["error_count"] == 40
    assert spike.signal.error_count == 40


def test_error_spike_not_fired_before_baseline_ready() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource([HealthSample(status="healthy", error_count=999)]),
        baseline=ErrorBaseline(min_samples=3),
        clock=FakeClock([1.0]),
    )
    # No baseline yet -> a big first number is not a spike.
    assert monitor.poll() == []


def test_error_spike_with_seeded_baseline_fires_immediately() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource([HealthSample(status="healthy", error_count=30, trace_id="t9")]),
        baseline=ErrorBaseline(seed_mean=3.0),
        clock=FakeClock([1.0]),
    )
    fb = monitor.poll()
    assert len(fb) == 1
    assert fb[0].kind == "error_spike"


# --------------------------------------------------------------------------- #
# Healthy deploy -> no feedback
# --------------------------------------------------------------------------- #
def test_healthy_deploy_produces_no_feedback() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource([HealthSample(status="healthy", error_count=1) for _ in range(5)]),
        baseline=ErrorBaseline(min_samples=2),
        clock=FakeClock([1.0, 2.0, 3.0, 4.0, 5.0]),
    )
    assert monitor.run(5) == []


# --------------------------------------------------------------------------- #
# Trace-linked diagnosis
# --------------------------------------------------------------------------- #
def test_feedback_is_trace_linked_and_diagnosis_returns_originating_run() -> None:
    bad = HealthSample(
        status="unhealthy",
        error_count=1,
        deploy_id="d-9",
        trace_id="t-deploy-42",
        span_id="span-3",
    )
    monitor = PostDeployMonitor(
        FakeMonitorSource([HealthSample(status="healthy"), bad]),
        trace_store=_origin_store(),
        clock=FakeClock([1.0, 2.0]),
    )
    monitor.poll()
    feedback = monitor.poll()
    assert feedback[0].trace_id == "t-deploy-42"

    diagnosis = monitor.query_diagnosis("t-deploy-42")
    assert isinstance(diagnosis, Diagnosis)
    assert diagnosis.linked is True
    assert diagnosis.origin is not None
    assert diagnosis.origin.run_id == "run-42"
    assert diagnosis.origin.change_ref == "pr-1007"
    # The triggering feedback is attached to the diagnosis.
    assert len(diagnosis.feedback) == 1
    assert diagnosis.feedback[0].kind == "health_regression"


def test_diagnosis_unlinked_when_trace_unknown() -> None:
    monitor = PostDeployMonitor(
        FakeMonitorSource([HealthSample(status="healthy")]),
        trace_store=InMemoryTraceOriginStore(),
        clock=FakeClock([1.0]),
    )
    diagnosis = monitor.query_diagnosis("nope")
    assert diagnosis.linked is False
    assert diagnosis.origin is None


def test_diagnosis_bridges_cap138_tool_trace_store(tmp_path: Path) -> None:
    # Reuse the durable CAP-138 tool-trace store as the origin source.
    trace_db = tmp_path / "trace.sqlite3"
    trace_store = ToolTraceStore(trace_db, clock=FakeClock([10.0, 11.0, 12.0]))
    trace_store.record(
        ToolCall(
            session_id="sess-ship",
            trace_id="t-deploy-77",
            tool_name="deploy_website",
            tool_input={"env": "prod"},
            started_at=10.0,
            ended_at=11.0,
        )
    )
    origin_store = ToolTraceOriginStore(trace_store)

    monitor = PostDeployMonitor(
        FakeMonitorSource(
            [
                HealthSample(status="healthy"),
                HealthSample(status="unhealthy", trace_id="t-deploy-77", error_count=3),
            ]
        ),
        trace_store=origin_store,
        clock=FakeClock([1.0, 2.0]),
    )
    monitor.poll()
    monitor.poll()

    diagnosis = monitor.query_diagnosis("t-deploy-77")
    assert diagnosis.linked is True
    assert diagnosis.origin is not None
    assert diagnosis.origin.change_ref == "deploy_website"
    assert diagnosis.origin.session_id == "sess-ship"


# --------------------------------------------------------------------------- #
# Round-trip: ingest -> feedback -> finding -> diagnosis
# --------------------------------------------------------------------------- #
def test_round_trip_ingest_feedback_finding_diagnosis() -> None:
    samples = [
        HealthSample(status="healthy", error_count=1),
        HealthSample(status="healthy", error_count=1),
        HealthSample(status="healthy", error_count=1),
        HealthSample(
            status="unhealthy",
            error_count=25,
            deploy_id="d-42",
            trace_id="t-deploy-42",
            span_id="span-x",
        ),
    ]
    monitor = PostDeployMonitor(
        FakeMonitorSource(samples),
        trace_store=_origin_store(),
        baseline=ErrorBaseline(min_samples=3),
        clock=FakeClock([1.0, 2.0, 3.0, 4.0]),
    )
    all_feedback = monitor.run(4)

    # The final sample is both a health regression AND an error spike.
    kinds = sorted(fb.kind for fb in all_feedback)
    assert kinds == ["error_spike", "health_regression"]

    findings = iter_findings(all_feedback)
    assert all(f["source"] == "post_deploy_monitor" for f in findings)
    assert all(f["trace_id"] == "t-deploy-42" for f in findings)

    # Every finding round-trips back to the originating run.
    diagnosis = monitor.query_diagnosis("t-deploy-42")
    assert diagnosis.origin is not None
    assert diagnosis.origin.run_id == "run-42"
    assert len(diagnosis.feedback) == 2

    # to_task payload is agent-loop consumable.
    task = all_feedback[0].to_task()
    assert task["origin_hint"] == "post_deploy_monitor"
    assert task["trace_id"] == "t-deploy-42"
    assert "finding" in task
