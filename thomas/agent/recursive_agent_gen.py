"""Recursive, rubric-bound subagent generation (CAP-036).

Where :mod:`thomas.agent.repo_agents` defines a *single* agent's contract
(tools/model/instructions + :func:`validate_agent_definition`), and
:mod:`thomas.agent.subtask_graph` binds a *rubric + verifier* to each node of a
decomposed goal, this module composes both ideas into a **generator**: an agent
definition can generate a *child* agent definition that carries its own explicit
acceptance rubric, and that generated child can itself recursively generate and
verify a *grandchild* bound to its own rubric -- proven at least two levels deep.

Contract
--------
``generate_and_verify(spec, rubric, verifier, generator, max_depth)`` walks a
recursive plan, and at every level:

1. **Generates** a concrete :class:`~thomas.agent.repo_agents.RepoAgent`
   definition from the level's spec via an injectable :class:`Generator`.
2. **Validates** it with :func:`~thomas.agent.repo_agents.validate_agent_definition`
   (the same semantic contract repo agents must satisfy). An invalid definition
   is *rejected* -- recorded, never accepted, and recursion stops.
3. **Verifies** the definition against the level's :class:`Rubric` via an
   injectable :class:`AgentVerifier` *before it is accepted*. A child that fails
   its rubric is rejected (not added as verified) and recursion stops.
4. **Recurses**: only an accepted (valid + verified) child generates its own
   grandchild -- the generated agent is itself the thing that creates and
   verifies the next level. A configurable ``max_depth`` bounds the recursion:
   exceeding it stops cleanly (never crashes, never loops forever).

The result is a :class:`GenerationTree` of :class:`GenerationNode`\\s, each
carrying its ``definition``, its ``rubric``, and its ``verdict`` -- a spine of
parent -> child -> grandchild, each link independently verified.

Reuse, not duplication
-----------------------
Agent definitions, validation, and the :class:`Rubric` / :class:`NodeVerdict` /
:class:`RubricCheck` value objects are imported from the existing modules rather
than reimplemented; this module only adds the generator/recursion layer on top.
It is agent-tier code importing agent-tier code, which the architecture allows.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol, runtime_checkable

from thomas.agent.repo_agents import RepoAgent, ValidationResult, validate_agent_definition
from thomas.agent.subtask_graph import NodeVerdict, Rubric, RubricCheck

__all__ = [
    "AgentSpec",
    "AgentVerifier",
    "GeneratedChild",
    "GenerationNode",
    "GenerationTree",
    "Generator",
    "PlanGenerator",
    "PredicateAgentVerifier",
    "SubagentPlan",
    "generate_and_verify",
]

# Predicate/verifier evaluation errors converted into a failed rubric check
# rather than propagated; a bug outside this family surfaces normally.
_PREDICATE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, ZeroDivisionError)

# Recursion stop reasons (also the ``GenerationTree.stopped_reason`` values).
STOP_LEAF = "leaf"
STOP_MAX_DEPTH = "max_depth"
STOP_VALIDATION_FAILED = "validation_failed"
STOP_VERIFICATION_FAILED = "verification_failed"


# ---------------------------------------------------------------------------
# Recursive plan / spec model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AgentSpec:
    """A request to generate one agent, plus an optional plan for its own child.

    The generation fields (``name``/``description``/``tools``/``model``/
    ``instructions``) mirror :class:`~thomas.agent.repo_agents.RepoAgent`'s
    contract. ``child`` -- when present -- is the descendant this agent should
    itself recursively generate, giving the plan its depth.
    """

    name: str
    description: str = ""
    tools: tuple[str, ...] = ()
    model: str = ""
    instructions: str = ""
    child: SubagentPlan | None = None


@dataclasses.dataclass(frozen=True)
class SubagentPlan:
    """A descendant to generate (``spec``) bound to the rubric it must satisfy."""

    spec: AgentSpec
    rubric: Rubric = dataclasses.field(default_factory=Rubric)


# ---------------------------------------------------------------------------
# Verifier: check a generated definition against its rubric
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentVerifier(Protocol):
    """Verify a generated agent ``definition`` against its ``rubric``."""

    def verify(self, definition: RepoAgent, rubric: Rubric) -> NodeVerdict: ...


AgentPredicateFn = Callable[[RepoAgent], bool]


def _verdict_from_checks(node_id: str, rubric: Rubric, checks: list[RubricCheck]) -> NodeVerdict:
    required = rubric.required_keys()
    failed = [c for c in checks if c.key in required and not c.passed]
    if failed:
        reason = "; ".join(f"{c.key}: {c.detail or 'failed'}" for c in failed)
        return NodeVerdict(node_id, False, tuple(checks), reason)
    return NodeVerdict(node_id, True, tuple(checks), "all required rubric criteria passed")


@dataclasses.dataclass(frozen=True)
class PredicateAgentVerifier:
    """Bind a pure ``(definition) -> bool`` predicate to each rubric criterion.

    ``predicates`` maps a criterion ``key`` to its check. A criterion with no
    bound predicate fails closed, and a predicate that raises an expected error
    becomes a failed check rather than propagating -- so one broken predicate
    cannot crash a generation. Fully hermetic; ideal for injection in tests.
    """

    predicates: Mapping[str, AgentPredicateFn]

    def verify(self, definition: RepoAgent, rubric: Rubric) -> NodeVerdict:
        checks: list[RubricCheck] = []
        for crit in rubric.criteria:
            pred = self.predicates.get(crit.key)
            if pred is None:
                checks.append(RubricCheck(crit.key, crit.description, False, "no predicate bound to criterion"))
                continue
            try:
                ok = bool(pred(definition))
                detail = "" if ok else "predicate returned False"
            except _PREDICATE_ERRORS as exc:
                ok = False
                detail = f"predicate raised {type(exc).__name__}: {exc}"
            checks.append(RubricCheck(crit.key, crit.description, ok, detail))
        return _verdict_from_checks(definition.name, rubric, checks)


# ---------------------------------------------------------------------------
# Generator: turn a spec into a definition + the plan for the next level
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class GeneratedChild:
    """What a :class:`Generator` emits for one level.

    ``definition`` is the concrete agent produced for this level.
    ``next_spec`` / ``next_rubric`` describe the grandchild this agent should
    itself generate next; ``next_spec is None`` marks a leaf (no descendant).
    """

    definition: RepoAgent
    next_spec: AgentSpec | None = None
    next_rubric: Rubric | None = None


@runtime_checkable
class Generator(Protocol):
    """Produce the agent definition for a level, and the plan for the next.

    Given the ``spec`` and ``rubric`` for the current level (and its ``depth``,
    1-based), return a :class:`GeneratedChild`. A generator is deterministic
    when equal inputs yield an equal :class:`GeneratedChild`.
    """

    def generate(self, spec: AgentSpec, rubric: Rubric, depth: int) -> GeneratedChild: ...


@dataclasses.dataclass(frozen=True)
class PlanGenerator:
    """Default generator: materialize a spec into a :class:`RepoAgent`.

    Purely mechanical and deterministic -- it copies the spec's contract fields
    onto a :class:`~thomas.agent.repo_agents.RepoAgent` and forwards the spec's
    embedded ``child`` plan as the next level. This is the seam a real runner
    would replace with a model-backed generator; the recursion engine treats
    both identically.
    """

    origin: str = "recursive_agent_gen"

    def generate(self, spec: AgentSpec, rubric: Rubric, depth: int) -> GeneratedChild:
        definition = RepoAgent(
            name=spec.name,
            description=spec.description,
            tools=tuple(spec.tools),
            model=spec.model,
            instructions=spec.instructions,
            source=f"generated:depth-{depth}",
            origin=self.origin,
        )
        if spec.child is None:
            return GeneratedChild(definition=definition, next_spec=None, next_rubric=None)
        return GeneratedChild(
            definition=definition,
            next_spec=spec.child.spec,
            next_rubric=spec.child.rubric,
        )


# ---------------------------------------------------------------------------
# Result tree
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class GenerationNode:
    """One generated agent: its definition, rubric, validation and verdict.

    ``accepted`` is ``True`` only when the definition both validates *and* its
    verifier passes it against ``rubric`` -- the precondition for recursing into
    a grandchild.
    """

    depth: int
    definition: RepoAgent
    rubric: Rubric
    validation: ValidationResult
    verdict: NodeVerdict
    accepted: bool
    reason: str = ""


@dataclasses.dataclass(frozen=True)
class GenerationTree:
    """The parent -> child -> grandchild spine produced by :func:`generate_and_verify`.

    ``nodes`` are ordered by increasing depth (1-based). ``stopped_reason`` is
    why recursion ended: a leaf plan, ``max_depth``, or a validation/
    verification rejection.
    """

    nodes: tuple[GenerationNode, ...]
    stopped_reason: str
    max_depth: int

    @property
    def accepted_nodes(self) -> tuple[GenerationNode, ...]:
        """Nodes that were valid *and* verified against their rubric."""
        return tuple(n for n in self.nodes if n.accepted)

    @property
    def depth_reached(self) -> int:
        """The deepest level generated (0 when nothing was generated)."""
        return max((n.depth for n in self.nodes), default=0)

    @property
    def verified_depth(self) -> int:
        """The deepest level that was accepted (valid + verified)."""
        return max((n.depth for n in self.accepted_nodes), default=0)

    def node_at(self, depth: int) -> GenerationNode | None:
        for node in self.nodes:
            if node.depth == depth:
                return node
        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def generate_and_verify(
    spec: AgentSpec,
    rubric: Rubric,
    verifier: AgentVerifier,
    generator: Generator | None = None,
    max_depth: int = 8,
    known_tools: Iterable[str] | None = None,
) -> GenerationTree:
    """Recursively generate and verify rubric-bound subagents.

    Starting from ``spec`` (the first child to generate) and ``rubric`` (the
    criteria it must satisfy), generate a definition, validate it, verify it
    against its rubric, and -- only if accepted -- recurse into the grandchild
    the generated agent itself plans. ``max_depth`` (>= 1) bounds the recursion:
    exceeding it stops cleanly. ``generator`` defaults to :class:`PlanGenerator`;
    ``known_tools``, when given, tightens validation to registered tool names.

    Returns a :class:`GenerationTree` whose nodes each carry a definition, its
    rubric, and its verdict.
    """
    gen = generator if generator is not None else PlanGenerator()
    tools = None if known_tools is None else {str(item) for item in known_tools}

    try:
        depth_cap = int(max_depth)
    except (TypeError, ValueError):
        depth_cap = 0

    nodes: list[GenerationNode] = []
    if depth_cap < 1:
        return GenerationTree(nodes=(), stopped_reason=STOP_MAX_DEPTH, max_depth=depth_cap)

    cur_spec: AgentSpec = spec
    cur_rubric: Rubric = rubric
    depth = 1
    stopped = STOP_LEAF

    while True:
        if depth > depth_cap:
            stopped = STOP_MAX_DEPTH
            break

        child = gen.generate(cur_spec, cur_rubric, depth)
        definition = child.definition
        validation = validate_agent_definition(definition, tools)

        if not validation.ok:
            verdict = NodeVerdict(
                definition.name,
                False,
                (),
                "not verified: definition failed validation",
            )
            nodes.append(
                GenerationNode(
                    depth=depth,
                    definition=definition,
                    rubric=cur_rubric,
                    validation=validation,
                    verdict=verdict,
                    accepted=False,
                    reason="validation failed: " + "; ".join(validation.errors),
                )
            )
            stopped = STOP_VALIDATION_FAILED
            break

        verdict = verifier.verify(definition, cur_rubric)
        accepted = bool(verdict.passed)
        nodes.append(
            GenerationNode(
                depth=depth,
                definition=definition,
                rubric=cur_rubric,
                validation=validation,
                verdict=verdict,
                accepted=accepted,
                reason=("generated, validated, and verified" if accepted else f"verification failed: {verdict.reason}"),
            )
        )

        if not accepted:
            stopped = STOP_VERIFICATION_FAILED
            break

        if child.next_spec is None:
            stopped = STOP_LEAF
            break

        cur_spec = child.next_spec
        cur_rubric = child.next_rubric if child.next_rubric is not None else Rubric()
        depth += 1

    return GenerationTree(nodes=tuple(nodes), stopped_reason=stopped, max_depth=depth_cap)
