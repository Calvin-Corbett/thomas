"""Tests for standing specialist-role fan-out with a materiality proof.

Acceptance line (CAP-030): "Run standing specialist roles in parallel and prove
their outputs materially change the result."

Every specialist worker here is a deterministic in-process fake -- no live
model, no network, no clock. Parallelism is proven with a ``threading.Barrier``
that only clears if every role is genuinely in flight at once. Materiality is
proven by showing a role that raises a blocking finding flips the decision vs a
baseline computed without the specialists, with the added finding attributed to
its role -- while a no-op specialist is shown to be non-material.
"""

from __future__ import annotations

import threading

import pytest

from thomas.agent.fanout_synthesis import Evidence
from thomas.agent.specialist_fanout import (
    MaterialityReport,
    PanelRun,
    Severity,
    SpecialistContribution,
    SpecialistPanel,
    SpecialistRequest,
    SpecialistRole,
    standard_panel_roles,
)

# ---------------------------------------------------------------------------
# Deterministic fake specialist workers
# ---------------------------------------------------------------------------


def clean_worker(request: SpecialistRequest):
    """A specialist that finds nothing actionable -- an INFO, non-blocking note."""

    return {
        "finding": f"{request.role}: no issues found",
        "severity": Severity.INFO,
        "blocking": False,
        "evidence": {"summary": f"{request.role} reviewed {request.task!r}", "sources": (f"lens://{request.role}",)},
    }


def noop_worker(request: SpecialistRequest):
    """A specialist that adds literally nothing -- a genuine no-op contribution."""

    return {"finding": "", "severity": Severity.INFO, "blocking": False}


def blocking_security_worker(request: SpecialistRequest):
    """A security specialist that raises a blocking vulnerability finding."""

    return SpecialistContribution(
        role="IGNORED-restamped",
        lens="IGNORED-restamped",
        task="IGNORED-restamped",
        finding="hardcoded secret in payment handler",
        severity=Severity.BLOCKER,
        blocking=True,
        evidence=Evidence(worker_id="IGNORED", summary="line 42 leaks an API key", sources=("audit://payments",)),
    )


def make_panel(**worker_overrides) -> SpecialistPanel:
    """Standing four-role panel; override individual role workers by name."""

    workers = {
        "security": clean_worker,
        "performance": clean_worker,
        "correctness": clean_worker,
        "tests": clean_worker,
    }
    workers.update(worker_overrides)
    return SpecialistPanel(standard_panel_roles(workers))


# ---------------------------------------------------------------------------
# >= 3 standing roles, parallel, role-tagged outputs
# ---------------------------------------------------------------------------


def test_panel_runs_at_least_three_roles_in_parallel_with_role_tagged_outputs():
    """Every role runs concurrently and returns output tagged with its role."""

    n_roles = 4
    barrier = threading.Barrier(n_roles, timeout=5.0)

    def concurrent_worker(request: SpecialistRequest):
        # If the roles did NOT run in parallel, the barrier never reaches its
        # party count and this raises BrokenBarrierError -> the test fails.
        barrier.wait()
        return {"finding": f"{request.role} weighed in", "severity": Severity.LOW}

    panel = SpecialistPanel(
        standard_panel_roles({name: concurrent_worker for name in ("security", "performance", "correctness", "tests")})
    )
    assert len(panel.role_names) == n_roles >= 3

    run = panel.run_panel("ship the payment module")

    # Role-tagged: every contribution carries its role, in stable role order.
    assert [c.role for c in run.contributions] == ["security", "performance", "correctness", "tests"]
    assert run.roles == ("security", "performance", "correctness", "tests")
    for contribution in run.contributions:
        assert contribution.role in contribution.finding
        assert contribution.evidence.worker_id == contribution.role
        assert contribution.task == "ship the payment module"


def test_barrier_proves_true_concurrency_not_serialization():
    """A barrier larger than any single thread only clears under real parallelism."""

    started = threading.Barrier(4, timeout=5.0)

    def worker(request: SpecialistRequest):
        started.wait()  # all four must arrive together
        return {"finding": f"{request.role} ok", "severity": Severity.INFO, "evidence": "seen"}

    panel = SpecialistPanel(
        standard_panel_roles({name: worker for name in ("security", "performance", "correctness", "tests")})
    )
    run = panel.run_panel("task")
    assert not started.broken
    assert len(run.contributions) == 4


# ---------------------------------------------------------------------------
# Materiality: a specialist flips the decision vs baseline
# ---------------------------------------------------------------------------


def test_blocking_specialist_materially_flips_decision_vs_baseline():
    """A security finding flips approve->reject; the flip is attributed to it."""

    panel = make_panel(security=blocking_security_worker)
    run = panel.run_panel("merge the PR", baseline_decision="approve")

    # Baseline (without specialists) approves; with the specialist it rejects.
    assert run.result_without.decision == "approve"
    assert run.result_with.decision == "reject"

    report = run.materiality
    assert isinstance(report, MaterialityReport)
    assert report.changed_decision is True
    assert report.material is True

    # The added blocking finding is attributed to the security role.
    added_roles = {c.role for c in report.added_findings}
    assert "security" in added_roles
    security_added = next(c for c in report.added_findings if c.role == "security")
    assert security_added.finding == "hardcoded secret in payment handler"
    assert security_added.blocking is True
    assert security_added.severity is Severity.BLOCKER

    # Per-role: security is material and is the one that flipped the decision.
    sec = report.role("security")
    assert sec.material is True
    assert sec.flipped_decision is True
    assert sec.added_finding == "hardcoded secret in payment handler"
    # Non-blocking clean reviewers did not flip the decision.
    assert report.role("performance").flipped_decision is False


def test_noop_specialist_is_non_material():
    """A specialist that adds nothing is reported as non-material."""

    panel = make_panel(performance=noop_worker)
    run = panel.run_panel("review the change")

    report = run.materiality
    perf = report.role("performance")
    assert perf.material is False
    assert perf.added_finding is None
    # The no-op contribution never appears among the added findings.
    assert all(c.role != "performance" for c in report.added_findings)
    # With every reviewer clean/no-op and none blocking, the decision holds.
    assert report.changed_decision is False
    assert run.result_with.decision == run.result_without.decision


def test_clean_reviewers_add_findings_but_do_not_change_decision():
    """Non-blocking findings are material additions yet leave the decision intact."""

    panel = make_panel()  # all four clean, non-blocking
    run = panel.run_panel("audit config")

    report = run.materiality
    # Clean reviewers each add a (non-blocking) finding -> material additions.
    assert len(report.added_findings) == 4
    assert report.material is True
    # ...but no blocking finding, so the decision is unchanged.
    assert report.changed_decision is False
    assert run.decision == "approve"
    for name in ("security", "performance", "correctness", "tests"):
        assert report.role(name).flipped_decision is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_run_is_deterministic_across_repeats():
    """Identical inputs yield byte-identical role order, findings, and decision."""

    def slow_first_worker(request: SpecialistRequest):
        # The security thread does more "work" (a spin) so it tends to finish
        # last; the panel must still return it first (role order), proving the
        # output order is independent of completion order.
        if request.role == "security":
            total = 0
            for i in range(50_000):
                total += i
        return {"finding": f"{request.role} verdict", "severity": Severity.MEDIUM, "blocking": False}

    panel = SpecialistPanel(
        standard_panel_roles({name: slow_first_worker for name in ("security", "performance", "correctness", "tests")})
    )

    runs = [panel.run_panel("stable task") for _ in range(5)]
    signatures = [
        (
            r.roles,
            tuple((c.role, c.finding, c.severity, c.blocking) for c in r.contributions),
            r.result_with.decision,
            r.materiality.describe(),
        )
        for r in runs
    ]
    assert all(sig == signatures[0] for sig in signatures)
    # Security is always first despite finishing last.
    assert runs[0].contributions[0].role == "security"


# ---------------------------------------------------------------------------
# Standing / configurable: same roles reused across tasks
# ---------------------------------------------------------------------------


def test_roles_are_standing_and_reused_across_tasks():
    """One configured panel serves many tasks with the same standing roles."""

    seen_tasks: dict[str, list[str]] = {}

    def recording_worker(request: SpecialistRequest):
        seen_tasks.setdefault(request.role, []).append(request.task)
        return {"finding": f"{request.role}: {request.task}", "severity": Severity.LOW}

    panel = SpecialistPanel(
        standard_panel_roles({name: recording_worker for name in ("security", "performance", "correctness", "tests")})
    )
    # The panel's role identity is fixed up front.
    assert panel.role_names == ("security", "performance", "correctness", "tests")

    tasks = ["task-a", "task-b", "task-c"]
    runs = [panel.run_panel(t) for t in tasks]

    # The SAME four standing roles ran on every task.
    for run in runs:
        assert run.roles == ("security", "performance", "correctness", "tests")
    for role in ("security", "performance", "correctness", "tests"):
        assert seen_tasks[role] == tasks


def test_run_panel_can_override_roles_for_a_single_call():
    """A subset override runs just those roles without mutating the panel."""

    panel = make_panel(security=blocking_security_worker)
    only_security = [r for r in panel.roles if r.name == "security"]

    run = panel.run_panel("hotfix", roles=only_security)
    assert run.roles == ("security",)
    assert run.result_with.decision == "reject"
    # The standing panel is unchanged for the next full task.
    full = panel.run_panel("next task")
    assert full.roles == ("security", "performance", "correctness", "tests")


# ---------------------------------------------------------------------------
# Construction / coercion guards
# ---------------------------------------------------------------------------


def test_panel_rejects_duplicate_role_names():
    role = SpecialistRole(name="security", lens="x", worker=clean_worker)
    dup = SpecialistRole(name="security", lens="y", worker=clean_worker)
    with pytest.raises(ValueError, match="unique"):
        SpecialistPanel([role, dup])


def test_panel_requires_at_least_one_role():
    with pytest.raises(ValueError, match="at least one role"):
        SpecialistPanel([])


def test_worker_mapping_without_finding_key_is_rejected():
    bad = SpecialistRole(name="security", lens="x", worker=lambda req: {"severity": Severity.LOW})
    panel = SpecialistPanel([bad])
    with pytest.raises(ValueError, match="without a 'finding' key"):
        panel.run_panel("t")


def test_severity_coercion_from_string_and_int():
    assert Severity.coerce("blocker") is Severity.BLOCKER
    assert Severity.coerce("HIGH") is Severity.HIGH
    assert Severity.coerce(4) is Severity.BLOCKER
    with pytest.raises(ValueError, match="unknown severity"):
        Severity.coerce("nope")
