"""CAP-053: goal -> subtask decomposition as a verifiable dependency graph.

Acceptance line: represent subtasks as a dependency graph with a rubric and a
verifier for each node. These tests prove, hermetically:

* a multi-node graph produces a topological order that respects deps;
* a cycle is rejected and the offending nodes are named;
* a node passes/fails its own rubric via its own verifier, with per-criterion
  details;
* the goal roll-up is met only when all required nodes verify;
* a failing verifier blocks its dependents from counting as done.

Everything is injectable: predicate verifiers and a fake command runner keep
the suite free of live subprocesses and models.
"""

from __future__ import annotations

import pytest

from thomas.agent.subtask_graph import (
    CommandRerunVerifier,
    GraphCycleError,
    NodeVerdict,
    PredicateVerifier,
    Rubric,
    RubricCriterion,
    SubtaskGraph,
    SubtaskNode,
    command_allowlist_refusal,
)


def _always_pass_verifier() -> PredicateVerifier:
    return PredicateVerifier(predicates={"ok": lambda node, output: True})


def _pass_rubric() -> Rubric:
    return Rubric.of(RubricCriterion(key="ok", description="node output is acceptable"))


def _node(nid: str, *, deps: tuple[str, ...] = (), required: bool = True, verifier=None) -> SubtaskNode:
    return SubtaskNode(
        id=nid,
        description=f"subtask {nid}",
        rubric=_pass_rubric(),
        verifier=verifier or _always_pass_verifier(),
        deps=deps,
        required=required,
    )


# ---------------------------------------------------------------------------
# Topological order respects dependencies
# ---------------------------------------------------------------------------


def test_topological_order_respects_dependencies():
    # goal -> {design} -> {impl} -> {test, docs}; docs also needs design.
    graph = SubtaskGraph.from_decomposition(
        "ship feature",
        [
            _node("test", deps=("impl",)),
            _node("docs", deps=("impl", "design")),
            _node("impl", deps=("design",)),
            _node("design"),
        ],
    )
    order = graph.topological_order()
    assert set(order) == {"design", "impl", "test", "docs"}
    pos = {nid: i for i, nid in enumerate(order)}
    assert pos["design"] < pos["impl"]
    assert pos["impl"] < pos["test"]
    assert pos["impl"] < pos["docs"]
    assert pos["design"] < pos["docs"]


def test_ready_nodes_advance_as_dependencies_verify():
    graph = SubtaskGraph.from_decomposition(
        "two-step goal",
        [_node("a"), _node("b", deps=("a",))],
    )
    # Only the root is ready initially.
    assert graph.ready_nodes() == ["a"]
    graph.verify_node("a", output=None)
    # Now that a is done, b becomes ready and a drops out.
    assert graph.ready_nodes() == ["b"]


# ---------------------------------------------------------------------------
# Cycles are rejected, naming the offending nodes
# ---------------------------------------------------------------------------


def test_cycle_is_rejected_and_names_the_cycle():
    with pytest.raises(GraphCycleError) as excinfo:
        SubtaskGraph.from_decomposition(
            "cyclic goal",
            [
                _node("a", deps=("c",)),
                _node("b", deps=("a",)),
                _node("c", deps=("b",)),
            ],
        )
    cycle = excinfo.value.cycle
    # Every node in the a->b->c->a loop is named.
    assert {"a", "b", "c"}.issubset(set(cycle))
    assert "cycle" in str(excinfo.value)


def test_missing_dependency_is_rejected():
    with pytest.raises(ValueError, match="depends on missing node 'ghost'"):
        SubtaskGraph.from_decomposition("dangling", [_node("a", deps=("ghost",))])


# ---------------------------------------------------------------------------
# A node passes / fails its own rubric via its own verifier, with details
# ---------------------------------------------------------------------------


def test_predicate_verifier_reports_pass_with_details():
    rubric = Rubric.of(
        RubricCriterion(key="nonempty", description="output is non-empty"),
        RubricCriterion(key="has_ok", description="output contains OK"),
    )
    verifier = PredicateVerifier(
        predicates={
            "nonempty": lambda node, output: bool(output),
            "has_ok": lambda node, output: "OK" in str(output),
        }
    )
    node = SubtaskNode(id="n", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("n", output="all OK here")
    assert isinstance(verdict, NodeVerdict)
    assert verdict.passed is True
    detail_by_key = {c.key: c for c in verdict.checks}
    assert detail_by_key["nonempty"].passed is True
    assert detail_by_key["has_ok"].passed is True


def test_predicate_verifier_reports_failure_with_details():
    rubric = Rubric.of(
        RubricCriterion(key="nonempty", description="output is non-empty"),
        RubricCriterion(key="has_ok", description="output contains OK"),
    )
    verifier = PredicateVerifier(
        predicates={
            "nonempty": lambda node, output: bool(output),
            "has_ok": lambda node, output: "OK" in str(output),
        }
    )
    node = SubtaskNode(id="n", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("n", output="missing token")
    assert verdict.passed is False
    checks = {c.key: c for c in verdict.checks}
    assert checks["nonempty"].passed is True
    assert checks["has_ok"].passed is False
    assert "predicate returned False" in checks["has_ok"].detail
    assert "has_ok" in verdict.reason


def test_predicate_error_becomes_failed_check_not_crash():
    rubric = Rubric.of(RubricCriterion(key="boom", description="raises"))

    def _boom(node, output):
        raise ValueError("kaboom")

    node = SubtaskNode(id="n", description="", rubric=rubric, verifier=PredicateVerifier(predicates={"boom": _boom}))
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("n", output=None)
    assert verdict.passed is False
    assert "kaboom" in verdict.checks[0].detail


def test_non_required_criterion_does_not_block_node():
    rubric = Rubric.of(
        RubricCriterion(key="core", description="core requirement", required=True),
        RubricCriterion(key="nice", description="nice to have", required=False),
    )
    verifier = PredicateVerifier(
        predicates={
            "core": lambda node, output: True,
            "nice": lambda node, output: False,
        }
    )
    node = SubtaskNode(id="n", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("n", output=None)
    assert verdict.passed is True  # optional criterion failing does not sink the node
    assert {c.key: c.passed for c in verdict.checks} == {"core": True, "nice": False}


# ---------------------------------------------------------------------------
# Command-rerun verifier: injectable runner + read-only allowlist
# ---------------------------------------------------------------------------


def test_command_rerun_verifier_passes_with_fake_runner():
    calls: list[list[str]] = []

    def fake_runner(argv, cwd, timeout):
        calls.append(argv)
        return (0, "5 passed", "")

    rubric = Rubric.of(RubricCriterion(key="tests", description="pytest is green"))
    verifier = CommandRerunVerifier(
        commands={"tests": "python -m pytest tests/test_thing.py"},
        runner=fake_runner,
    )
    node = SubtaskNode(id="impl", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("impl", output=None)
    assert verdict.passed is True
    assert verdict.checks[0].detail == "exit 0"
    # The pinned-python argv was actually handed to the runner.
    assert calls and calls[0][:3] == ["python", "-m", "pytest"]


def test_command_rerun_verifier_fails_on_nonzero_exit():
    def fake_runner(argv, cwd, timeout):
        return (1, "", "1 failed")

    rubric = Rubric.of(RubricCriterion(key="tests", description="pytest is green"))
    verifier = CommandRerunVerifier(commands={"tests": "python -m pytest"}, runner=fake_runner)
    node = SubtaskNode(id="impl", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("impl", output=None)
    assert verdict.passed is False
    assert "expected exit 0, got 1" in verdict.checks[0].detail


def test_command_rerun_verifier_refuses_non_allowlisted_command():
    sentinel = {"ran": False}

    def fake_runner(argv, cwd, timeout):
        sentinel["ran"] = True
        return (0, "", "")

    rubric = Rubric.of(RubricCriterion(key="danger", description="mutating command"))
    verifier = CommandRerunVerifier(commands={"danger": "rm -rf /"}, runner=fake_runner)
    node = SubtaskNode(id="n", description="", rubric=rubric, verifier=verifier)
    graph = SubtaskGraph("goal", [node])
    verdict = graph.verify_node("n", output=None)
    assert verdict.passed is False
    assert "refused" in verdict.checks[0].detail
    assert sentinel["ran"] is False  # refused commands never reach the runner


def test_allowlist_refusal_matches_read_only_policy():
    assert command_allowlist_refusal(["python", "-m", "pytest"]) == ""
    assert command_allowlist_refusal(["pytest"]) == ""
    assert command_allowlist_refusal(["git", "status"]) == ""
    assert command_allowlist_refusal(["git", "push"]) != ""
    assert command_allowlist_refusal(["python", "-c", "print(1)"]) != ""
    assert command_allowlist_refusal(["rm", "-rf", "/"]) != ""


# ---------------------------------------------------------------------------
# Goal roll-up + failing verifier blocks dependents
# ---------------------------------------------------------------------------


def test_goal_met_only_when_all_required_nodes_verify():
    graph = SubtaskGraph.from_decomposition(
        "goal",
        [_node("a"), _node("b", deps=("a",))],
    )
    assert graph.status().goal_met is False
    graph.verify_node("a", output=None)
    assert graph.status().goal_met is False  # b still unverified
    graph.verify_node("b", output=None)
    status = graph.status()
    assert status.goal_met is True
    assert set(status.done) == {"a", "b"}
    assert status.pending == ()


def test_optional_node_is_not_required_for_goal():
    graph = SubtaskGraph.from_decomposition(
        "goal",
        [_node("core"), _node("extra", required=False)],
    )
    graph.verify_node("core", output=None)
    # 'extra' is optional and unverified, but the required set is satisfied.
    status = graph.status()
    assert status.goal_met is True
    assert "extra" not in status.required
    assert "extra" in status.pending


def test_failing_verifier_blocks_dependents_from_being_done():
    fail_verifier = PredicateVerifier(predicates={"ok": lambda node, output: False})
    graph = SubtaskGraph.from_decomposition(
        "goal",
        [
            _node("root", verifier=fail_verifier),
            _node("child", deps=("root",)),
        ],
    )
    # root fails its own rubric
    root_verdict = graph.verify_node("root", output=None)
    assert root_verdict.passed is False
    # child passes its OWN rubric...
    child_verdict = graph.verify_node("child", output=None)
    assert child_verdict.passed is True
    # ...but is NOT done, because its dependency failed.
    assert graph.is_done("child") is False
    status = graph.status()
    assert status.goal_met is False
    assert "root" in status.failed
    assert "child" in status.blocked


# ---------------------------------------------------------------------------
# from_dict decomposition entry
# ---------------------------------------------------------------------------


def test_from_decomposition_accepts_dict_nodes():
    graph = SubtaskGraph.from_decomposition(
        "goal",
        [
            {
                "id": "a",
                "description": "first",
                "rubric": _pass_rubric(),
                "verifier": _always_pass_verifier(),
            },
            {
                "id": "b",
                "description": "second",
                "rubric": _pass_rubric(),
                "verifier": _always_pass_verifier(),
                "deps": ["a"],
            },
        ],
    )
    assert graph.topological_order() == ["a", "b"]


def test_duplicate_node_id_rejected():
    with pytest.raises(ValueError, match="duplicate subtask id"):
        SubtaskGraph("goal", [_node("a"), _node("a")])
