"""CAP-036: recursive, rubric-bound subagent generation.

Acceptance line: prove a generated subagent can recursively create and verify
another rubric-bound subagent.

These tests prove, hermetically (no network, no live model, no subprocess):

* a generated child is a valid, rubric-bound agent definition;
* the generated child recursively generates a grandchild that is itself
  generated AND verified against its own rubric (two levels: parent -> child ->
  grandchild);
* a child that fails its rubric verification is rejected -- recorded but not
  accepted, and its (would-be) descendant is never generated;
* ``max_depth`` stops the recursion cleanly rather than looping forever;
* generation is deterministic given a fixed generator + verifier.

Everything is injected: a pure predicate verifier and an in-memory recursive
plan drive the engine.
"""

from __future__ import annotations

from collections.abc import Callable

from thomas.agent.recursive_agent_gen import (
    STOP_MAX_DEPTH,
    STOP_VERIFICATION_FAILED,
    AgentSpec,
    GeneratedChild,
    Generator,
    PlanGenerator,
    PredicateAgentVerifier,
    SubagentPlan,
    generate_and_verify,
)
from thomas.agent.repo_agents import RepoAgent, validate_agent_definition
from thomas.agent.subtask_graph import Rubric, RubricCriterion

# Tools the generated agents declare; also the "registered" set for validation.
KNOWN_TOOLS = ("read_file", "grep", "shell", "spawn_agent")


def _rubric(*keys: str) -> Rubric:
    return Rubric(criteria=tuple(RubricCriterion(key=k, description=f"criterion {k}") for k in keys))


def _spec(name: str, *, instructions: str, child: SubagentPlan | None = None) -> AgentSpec:
    return AgentSpec(
        name=name,
        description=f"{name} agent",
        tools=("read_file", "shell"),
        model="reasoning",
        instructions=instructions,
        child=child,
    )


def _has_instructions(min_len: int) -> Callable[[RepoAgent], bool]:
    return lambda defn: len(defn.instructions.strip()) >= min_len


def _uses_only_known_tools(defn: RepoAgent) -> bool:
    return bool(defn.tools) and all(t in KNOWN_TOOLS for t in defn.tools)


# ---------------------------------------------------------------------------
# 1. A generated child is a valid rubric-bound agent definition.
# ---------------------------------------------------------------------------


def test_generated_child_is_valid_rubric_bound_agent() -> None:
    rubric = _rubric("has_instructions", "known_tools")
    verifier = PredicateAgentVerifier(
        predicates={
            "has_instructions": _has_instructions(5),
            "known_tools": _uses_only_known_tools,
        }
    )
    spec = _spec("child", instructions="You are the child. Do the work.")

    tree = generate_and_verify(spec, rubric, verifier, max_depth=1, known_tools=KNOWN_TOOLS)

    assert len(tree.nodes) == 1
    node = tree.node_at(1)
    assert node is not None
    # The generated definition is a real, contract-valid agent definition.
    assert isinstance(node.definition, RepoAgent)
    assert validate_agent_definition(node.definition, KNOWN_TOOLS).ok
    assert node.validation.ok
    # It is bound to the rubric it was generated for, and verified against it.
    assert node.rubric is rubric
    assert node.verdict.passed
    assert node.accepted
    assert {c.key for c in node.verdict.checks} == {"has_instructions", "known_tools"}
    # A childless spec is a leaf: recursion ends without needing the depth cap.
    assert tree.stopped_reason == "leaf"
    assert tree.verified_depth == 1


# ---------------------------------------------------------------------------
# 2. Two levels: the generated child recursively generates AND verifies a
#    grandchild bound to its own rubric.
# ---------------------------------------------------------------------------


def test_child_recursively_generates_and_verifies_grandchild() -> None:
    grandchild_rubric = _rubric("has_instructions")
    grandchild = _spec("grandchild", instructions="You are the grandchild.")
    child_rubric = _rubric("has_instructions", "known_tools")
    # The child's spec carries the plan for the grandchild it will itself create.
    child = _spec(
        "child",
        instructions="You are the child; generate a grandchild.",
        child=SubagentPlan(spec=grandchild, rubric=grandchild_rubric),
    )

    verifier = PredicateAgentVerifier(
        predicates={
            "has_instructions": _has_instructions(5),
            "known_tools": _uses_only_known_tools,
        }
    )

    tree = generate_and_verify(child, child_rubric, verifier, max_depth=3, known_tools=KNOWN_TOOLS)

    # Two levels were generated: parent-spec -> child (depth 1) -> grandchild (depth 2).
    assert [n.depth for n in tree.nodes] == [1, 2]
    assert tree.depth_reached == 2
    assert tree.verified_depth == 2

    child_node = tree.node_at(1)
    grand_node = tree.node_at(2)
    assert child_node is not None and grand_node is not None
    assert child_node.definition.name == "child"
    assert grand_node.definition.name == "grandchild"

    # Both levels were generated, validated, AND verified against their own rubric.
    for node in (child_node, grand_node):
        assert node.validation.ok
        assert node.verdict.passed
        assert node.accepted
    # The grandchild was bound to its own (distinct) rubric, not the child's.
    assert grand_node.rubric is grandchild_rubric
    assert grand_node.rubric.keys == ("has_instructions",)
    assert child_node.rubric.keys == ("has_instructions", "known_tools")
    # Recursion ended because the grandchild is a leaf (plans no descendant).
    assert tree.stopped_reason == "leaf"
    assert len(tree.accepted_nodes) == 2


# ---------------------------------------------------------------------------
# 3. A child failing its rubric verification is rejected (not accepted) and its
#    descendant is never generated.
# ---------------------------------------------------------------------------


def test_child_failing_rubric_is_rejected_and_blocks_recursion() -> None:
    grandchild = _spec("grandchild", instructions="You are the grandchild.")
    child = _spec(
        "child",
        instructions="short",
        child=SubagentPlan(spec=grandchild, rubric=_rubric("has_instructions")),
    )
    # The child's rubric demands instructions >= 200 chars; the child has few.
    child_rubric = _rubric("long_instructions")
    verifier = PredicateAgentVerifier(predicates={"long_instructions": _has_instructions(200)})

    tree = generate_and_verify(child, child_rubric, verifier, max_depth=5, known_tools=KNOWN_TOOLS)

    # Exactly one node: the failing child. No grandchild was generated.
    assert len(tree.nodes) == 1
    node = tree.node_at(1)
    assert node is not None
    # The definition is still structurally valid -- it failed the *rubric*, not validation.
    assert node.validation.ok
    assert not node.verdict.passed
    assert not node.accepted
    assert "verification failed" in node.reason
    # It was NOT added as a verified/accepted node.
    assert tree.accepted_nodes == ()
    assert tree.verified_depth == 0
    assert tree.stopped_reason == STOP_VERIFICATION_FAILED


# ---------------------------------------------------------------------------
# 4. max_depth stops recursion cleanly even when the plan would recurse forever.
# ---------------------------------------------------------------------------


class _InfiniteGenerator:
    """A generator whose every child plans another identical child, forever."""

    def generate(self, spec: AgentSpec, rubric: Rubric, depth: int) -> GeneratedChild:
        definition = RepoAgent(
            name=f"agent-{depth}",
            description="endless",
            tools=("read_file",),
            model="reasoning",
            instructions="Recurse forever unless bounded.",
            source=f"generated:depth-{depth}",
            origin="test",
        )
        # Always advertises a next level -> only max_depth can stop it.
        return GeneratedChild(definition=definition, next_spec=spec, next_rubric=rubric)


def test_max_depth_stops_recursion_cleanly() -> None:
    # Sanity: the generator itself is a Generator and would never self-terminate.
    assert isinstance(_InfiniteGenerator(), Generator)
    rubric = _rubric("ok")
    verifier = PredicateAgentVerifier(predicates={"ok": lambda defn: True})
    spec = _spec("root", instructions="root instructions")

    tree = generate_and_verify(spec, rubric, verifier, generator=_InfiniteGenerator(), max_depth=3)

    # Clean stop: exactly max_depth nodes, all accepted, no crash, no infinite loop.
    assert len(tree.nodes) == 3
    assert [n.depth for n in tree.nodes] == [1, 2, 3]
    assert all(n.accepted for n in tree.nodes)
    assert tree.stopped_reason == STOP_MAX_DEPTH
    assert tree.depth_reached == 3

    # max_depth below 1 generates nothing, cleanly.
    empty = generate_and_verify(spec, rubric, verifier, generator=_InfiniteGenerator(), max_depth=0)
    assert empty.nodes == ()
    assert empty.stopped_reason == STOP_MAX_DEPTH


# ---------------------------------------------------------------------------
# 5. Determinism: fixed generator + verifier -> identical tree.
# ---------------------------------------------------------------------------


def test_generation_is_deterministic() -> None:
    grandchild = _spec("grandchild", instructions="You are the grandchild.")
    child = _spec(
        "child",
        instructions="You are the child; generate a grandchild.",
        child=SubagentPlan(spec=grandchild, rubric=_rubric("has_instructions")),
    )
    rubric = _rubric("has_instructions", "known_tools")
    verifier = PredicateAgentVerifier(
        predicates={
            "has_instructions": _has_instructions(5),
            "known_tools": _uses_only_known_tools,
        }
    )
    generator = PlanGenerator()

    tree_a = generate_and_verify(child, rubric, verifier, generator=generator, max_depth=4, known_tools=KNOWN_TOOLS)
    tree_b = generate_and_verify(child, rubric, verifier, generator=generator, max_depth=4, known_tools=KNOWN_TOOLS)

    # Frozen dataclasses compare structurally; identical inputs -> equal trees.
    assert tree_a == tree_b
    assert [n.definition.source for n in tree_a.nodes] == [n.definition.source for n in tree_b.nodes]
    assert tree_a.stopped_reason == tree_b.stopped_reason == "leaf"
