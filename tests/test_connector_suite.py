"""CAP-073: Breadth connectors -- governed suite + composed cross-app workflow.

Acceptance line: "Expand to a governed productivity/deploy connector set and
prove one composed cross-app workflow."

These tests prove, hermetically against the in-memory fake backend + an injected
deterministic clock:

* each connector in the set CONFORMS to the byo_connector contract (the byo
  conformance harness certifies all three);
* a governance-denied action is REFUSED with a reason and never reaches the
  connector;
* a composed workflow across THREE connectors runs end-to-end, passing outputs
  of earlier steps into later steps, and returns a combined result;
* a mid-workflow failure is SURFACED (not silently partial) in both modes;
* atomic (all-or-nothing) rollback undoes committed steps; recorded-partial
  keeps them and reports the failure;
* the runner is deterministic.

No network, no credentials, no disk -- BYO breadth is a framework.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.integrations.byo_connector import run_conformance
from thomas.integrations.connector_suite import (
    DeployConnector,
    DocsConnector,
    FileStorageBackend,
    GovernancePolicy,
    GovernedConnectorSuite,
    InMemoryStorageBackend,
    IssueConnector,
    Ref,
    WorkflowRunner,
    WorkflowStep,
    build_connector_suite,
    build_connectors,
    certify_suite,
)


def _fake_clock():
    """Deterministic monotonic clock (1, 2, 3, ...)."""
    counter = itertools.count(1)
    return lambda: next(counter)


def _suite(policy: GovernancePolicy | None = None) -> GovernedConnectorSuite:
    backend = InMemoryStorageBackend()
    connectors = build_connectors(backend, clock=_fake_clock())
    return GovernedConnectorSuite(connectors, policy or GovernancePolicy.allow_all())


def _seed_task(suite: GovernedConnectorSuite, **fields) -> str:
    env = suite.invoke("issues", "create_task", fields)
    assert env["ok"], env
    return env["result"]["id"]


# ---------------------------------------------------------------------------
# Conformance -- each connector honours the byo contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("factory", [DocsConnector, IssueConnector, DeployConnector])
def test_each_connector_conforms(factory):
    connector = factory(InMemoryStorageBackend(), clock=_fake_clock())
    report = run_conformance(connector)
    assert report.certified, report.first_failure()


def test_certify_suite_reports_all_certified():
    suite = _suite()
    assert certify_suite(suite) == {"deploy": True, "docs": True, "issues": True}


# ---------------------------------------------------------------------------
# Governance -- denied actions are refused with a reason
# ---------------------------------------------------------------------------
def test_denied_action_is_refused_with_reason():
    # Allow everything except creating docs.
    policy = GovernancePolicy(
        allow={"docs": frozenset({"get_doc", "list_docs"}), "issues": frozenset({"*"}), "deploy": frozenset({"*"})},
        default_allow=False,
    )
    suite = _suite(policy)
    env = suite.invoke("docs", "create_doc", {"title": "blocked"})
    assert env["ok"] is False
    assert "governance" in env["error"]
    assert "deny" in env["error"] or "not on the allow list" in env["error"]
    # Denial never touched the connector: no doc was created.
    listing = suite.connector("docs").invoke("list_docs", {})
    assert listing["result"]["docs"] == []


def test_explicit_deny_beats_allow():
    policy = GovernancePolicy(
        allow={"deploy": frozenset({"*"})},
        deny={"deploy": frozenset({"record_deploy"})},
        default_allow=True,
    )
    suite = _suite(policy)
    env = suite.invoke("deploy", "record_deploy", {"service": "web"})
    assert env["ok"] is False
    assert "deny list" in env["error"]


def test_unknown_connector_is_refused():
    suite = _suite()
    env = suite.invoke("ghost", "do", {})
    assert env["ok"] is False
    assert "unknown connector" in env["error"]


# ---------------------------------------------------------------------------
# Composed cross-app workflow -- three connectors, data threaded between steps
# ---------------------------------------------------------------------------
def _compose_steps(task_id: str) -> list[WorkflowStep]:
    return [
        WorkflowStep(id="read", connector="issues", action="get_task", params={"id": task_id}),
        WorkflowStep(
            id="doc",
            connector="docs",
            action="create_doc",
            bindings={"title": Ref("read", "title"), "body": Ref("read", "description")},
            compensate="delete_doc",
        ),
        WorkflowStep(
            id="deploy",
            connector="deploy",
            action="record_deploy",
            params={"service": "web", "ref": "v1"},
            bindings={"doc_id": Ref("doc", "id")},
            compensate="delete_deploy",
        ),
    ]


def test_composed_workflow_threads_data_across_three_connectors():
    suite = _suite()
    task_id = _seed_task(suite, title="Ship it", description="release notes body")
    runner = WorkflowRunner(suite)

    result = runner.run(_compose_steps(task_id), atomic=True)

    assert result.ok, result.to_dict()
    assert [s.status for s in result.steps] == ["ok", "ok", "ok"]
    # Output of step "read" fed the doc title/body.
    doc = result.outputs["doc"]
    assert doc["title"] == "Ship it"
    assert doc["body"] == "release notes body"
    # Output of step "doc" fed the deploy's doc_id -> cross-app linkage.
    deploy = result.outputs["deploy"]
    assert deploy["doc_id"] == doc["id"]
    assert deploy["service"] == "web"
    # The doc and deploy really persisted.
    assert suite.connector("docs").invoke("get_doc", {"id": doc["id"]})["ok"] is True
    assert suite.connector("deploy").invoke("get_deploy", {"id": deploy["id"]})["ok"] is True


# ---------------------------------------------------------------------------
# Mid-workflow failure is surfaced, not silently partial
# ---------------------------------------------------------------------------
def test_atomic_rollback_undoes_committed_steps():
    suite = _suite()
    task_id = _seed_task(suite, title="Ship it", description="body")
    runner = WorkflowRunner(suite)

    steps = _compose_steps(task_id)
    # Break the final step: record_deploy requires 'service'; drop it.
    steps[2] = WorkflowStep(
        id="deploy",
        connector="deploy",
        action="record_deploy",
        params={"ref": "v1"},  # no service -> ValueError -> ok=False
        bindings={"doc_id": Ref("doc", "id")},
        compensate="delete_deploy",
    )

    result = runner.run(steps, atomic=True)

    assert result.ok is False
    assert result.failed_step == "deploy"
    assert "missing required param" in result.error
    statuses = {s.id: s.status for s in result.steps}
    assert statuses == {"read": "rolled_back", "doc": "rolled_back", "deploy": "failed"}
    assert result.committed() == []
    # All-or-nothing: the doc created mid-workflow was compensated away.
    assert suite.connector("docs").invoke("list_docs", {})["result"]["docs"] == []


def test_recorded_partial_keeps_committed_steps_and_surfaces_failure():
    suite = _suite()
    task_id = _seed_task(suite, title="Ship it", description="body")
    runner = WorkflowRunner(suite)

    steps = _compose_steps(task_id)
    steps[2] = WorkflowStep(
        id="deploy",
        connector="deploy",
        action="record_deploy",
        params={"ref": "v1"},  # missing service -> failure
        bindings={"doc_id": Ref("doc", "id")},
        compensate="delete_deploy",
    )

    result = runner.run(steps, atomic=False)

    assert result.ok is False
    assert result.failed_step == "deploy"
    statuses = {s.id: s.status for s in result.steps}
    assert statuses == {"read": "committed", "doc": "committed", "deploy": "failed"}
    assert result.committed() == ["read", "doc"]
    # Recorded-partial: the doc is kept (not silently dropped, and not rolled back).
    docs = suite.connector("docs").invoke("list_docs", {})["result"]["docs"]
    assert len(docs) == 1


def test_governance_denial_mid_workflow_triggers_rollback():
    # Deploy recording is denied by policy; the doc created earlier must roll back.
    policy = GovernancePolicy(
        allow={"issues": frozenset({"*"}), "docs": frozenset({"*"})},
        deny={"deploy": frozenset({"record_deploy"})},
        default_allow=True,
    )
    suite = _suite(policy)
    task_id = _seed_task(suite, title="Ship it", description="body")
    runner = WorkflowRunner(suite)

    result = runner.run(_compose_steps(task_id), atomic=True)

    assert result.ok is False
    assert result.failed_step == "deploy"
    assert "governance" in result.error
    assert suite.connector("docs").invoke("list_docs", {})["result"]["docs"] == []


def test_unresolvable_binding_is_surfaced_as_failure():
    suite = _suite()
    runner = WorkflowRunner(suite)
    steps = [
        WorkflowStep(id="a", connector="docs", action="create_doc", params={"title": "t"}, compensate="delete_doc"),
        # Binding points at a field that does not exist in step "a" result.
        WorkflowStep(
            id="b",
            connector="deploy",
            action="record_deploy",
            params={"service": "web"},
            bindings={"doc_id": Ref("a", "nonexistent.field")},
        ),
    ]
    result = runner.run(steps, atomic=True)
    assert result.ok is False
    assert result.failed_step == "b"
    assert "not found" in result.error
    # Atomic rollback removed the doc created by step "a".
    assert suite.connector("docs").invoke("list_docs", {})["result"]["docs"] == []


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_workflow_is_deterministic():
    def run_once():
        suite = _suite()
        task_id = _seed_task(suite, title="Ship it", description="body")
        return WorkflowRunner(suite).run(_compose_steps(task_id), atomic=True).to_dict()

    assert run_once() == run_once()


# ---------------------------------------------------------------------------
# Real default backend (FileStorageBackend) round-trips on disk
# ---------------------------------------------------------------------------
def test_file_backend_persists_across_suite_instances(tmp_path):
    root = tmp_path / "store"
    suite = build_connector_suite(root=root, clock=_fake_clock())
    env = suite.invoke("docs", "create_doc", {"title": "durable", "body": "x"})
    assert env["ok"]
    doc_id = env["result"]["id"]

    # A fresh suite over the SAME directory sees the persisted doc.
    reopened = build_connector_suite(root=root, clock=_fake_clock())
    got = reopened.invoke("docs", "get_doc", {"id": doc_id})
    assert got["ok"] is True
    assert got["result"]["title"] == "durable"


def test_file_backend_is_a_storage_backend(tmp_path):
    backend = FileStorageBackend(tmp_path / "s")
    backend.put("ns", "k", {"id": "k", "v": 1})
    assert backend.get("ns", "k") == {"id": "k", "v": 1}
    assert backend.list("ns") == [{"id": "k", "v": 1}]
    assert backend.delete("ns", "k") is True
    assert backend.get("ns", "k") is None
