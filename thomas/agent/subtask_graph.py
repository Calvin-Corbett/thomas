"""Goal -> subtask decomposition as a verifiable dependency graph (CAP-053).

Where :mod:`thomas.agent.swarm` models a ``TaskGraph`` of work items with
dependencies, the model-owned execution plan supplies the whole-request
contract. This module sits between them: it represents a *decomposed goal* as
a directed acyclic graph in which
**every node carries its own rubric and its own verifier**.

A node is not "done" because a worker said so. A node is done only when its
verifier checks the node's output against that node's rubric and passes. The
goal is met only when every required node is independently verified, and a
failing node blocks its dependents from counting as done -- so a false
"done" cannot silently roll up into a met goal.

Design
------
``RubricCriterion`` / ``Rubric``
    The structured acceptance criteria for one node. Each criterion has a
    stable ``key`` (which a verifier binds its check to), a human description,
    and a ``required`` flag.

``Verifier`` (protocol) with two concrete, injectable implementations
    ``PredicateVerifier`` -- binds a pure predicate ``(node, output) -> bool``
    to each rubric criterion. Fully hermetic; ideal for tests.

    ``CommandRerunVerifier`` -- binds a *command* to each rubric criterion and
    reruns it in a fresh subprocess, comparing the exit code against the
    expected one. It reuses the same read-only allowlist idea as
    ``evolve_supervisor.independent_verifier``: only test/lint/compile-class
    ``python -m <module>`` invocations, a bare ``pytest``, and read-only
    ``git`` subcommands are ever rerun; anything else is *refused* and its
    criterion fails closed. The command runner is injectable, so tests never
    spawn a real process.

``SubtaskGraph``
    Builds from a decomposition (nodes + deps), validates it is a DAG
    (rejecting cycles and naming the offending nodes), yields a topological
    ready-order, verifies a node's output against its rubric+verifier, and
    rolls the per-node verdicts up into a goal-level status.

This module is intentionally self-contained (stdlib only) and does not import
``swarm`` or ``evolve_supervisor``: it replicates the allowlist *idea* rather
than taking a cross-package dependency, keeping the decomposition layer thin.
"""

from __future__ import annotations

import dataclasses
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CommandRerunVerifier",
    "GraphCycleError",
    "GraphStatus",
    "NodeVerdict",
    "PredicateVerifier",
    "Rubric",
    "RubricCheck",
    "RubricCriterion",
    "SubtaskGraph",
    "SubtaskNode",
    "Verifier",
    "command_allowlist_refusal",
]

DEFAULT_CHECK_TIMEOUT_SECONDS = 600
_SNIPPET_LIMIT = 400
_SHELL_METACHARS = (";", "&", "|", "<", ">", "`", "$(", "\n", "\r")
_PYTHON_EXECUTABLES = frozenset({"python", "python.exe", "python3", "python3.exe", "py", "py.exe"})
ALLOWED_PYTHON_MODULES = frozenset({"pytest", "py_compile", "compileall", "unittest", "ruff"})
ALLOWED_BARE_EXECUTABLES = frozenset({"pytest", "pytest.exe"})
ALLOWED_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "rev-parse"})

# Predicate evaluation errors that are converted into a failed rubric check
# rather than propagated. Anything outside this tuple (e.g. a bug in the graph
# itself) is allowed to surface.
_PREDICATE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, ZeroDivisionError)


def _snippet(value: Any, limit: int = _SNIPPET_LIMIT) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


# ---------------------------------------------------------------------------
# Rubric model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RubricCriterion:
    """One structured acceptance criterion for a node.

    ``key`` is the stable identifier a verifier binds a check to. ``required``
    criteria must pass for the node to verify; non-required criteria are
    reported but do not block the node's verdict.
    """

    key: str
    description: str = ""
    required: bool = True


@dataclasses.dataclass(frozen=True)
class Rubric:
    """The acceptance criteria for a single subtask node."""

    criteria: tuple[RubricCriterion, ...] = ()

    @staticmethod
    def of(*criteria: RubricCriterion | tuple[str, str] | str) -> Rubric:
        """Convenience builder accepting criteria, ``(key, description)`` pairs, or bare keys."""
        rows: list[RubricCriterion] = []
        for item in criteria:
            if isinstance(item, RubricCriterion):
                rows.append(item)
            elif isinstance(item, tuple):
                key = str(item[0])
                desc = str(item[1]) if len(item) > 1 else ""
                rows.append(RubricCriterion(key=key, description=desc))
            else:
                rows.append(RubricCriterion(key=str(item)))
        return Rubric(criteria=tuple(rows))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.criteria)

    def required_keys(self) -> frozenset[str]:
        return frozenset(c.key for c in self.criteria if c.required)


@dataclasses.dataclass(frozen=True)
class RubricCheck:
    """Outcome of evaluating one rubric criterion against a node's output."""

    key: str
    description: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "description": self.description,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclasses.dataclass(frozen=True)
class NodeVerdict:
    """Verifier result for one node: did its output satisfy its rubric?"""

    node_id: str
    passed: bool
    checks: tuple[RubricCheck, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "passed": self.passed,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
        }


def _build_verdict(node: SubtaskNode, checks: Sequence[RubricCheck]) -> NodeVerdict:
    required = node.rubric.required_keys()
    failed = [c for c in checks if c.key in required and not c.passed]
    if failed:
        reason = "; ".join(f"{c.key}: {c.detail or 'failed'}" for c in failed)
        return NodeVerdict(node.id, False, tuple(checks), reason)
    return NodeVerdict(node.id, True, tuple(checks), "all required rubric criteria passed")


# ---------------------------------------------------------------------------
# Verifiers
# ---------------------------------------------------------------------------


@runtime_checkable
class Verifier(Protocol):
    """A node verifier: check ``output`` against ``node``'s rubric."""

    def verify(self, node: SubtaskNode, output: Any) -> NodeVerdict: ...


PredicateFn = Callable[["SubtaskNode", Any], bool]
# runner(argv, cwd, timeout_seconds) -> (returncode, stdout, stderr)
CommandRunner = Callable[[list[str], "str | None", int], "tuple[int, str, str]"]


@dataclasses.dataclass(frozen=True)
class PredicateVerifier:
    """Bind a pure predicate to each rubric criterion.

    ``predicates`` maps a criterion ``key`` to a ``(node, output) -> bool``
    callable. A criterion with no bound predicate fails closed. Predicate
    evaluation errors in the expected families become a failed check rather
    than propagating, so one broken predicate cannot crash a graph roll-up.
    """

    predicates: Mapping[str, PredicateFn]

    def verify(self, node: SubtaskNode, output: Any) -> NodeVerdict:
        checks: list[RubricCheck] = []
        for crit in node.rubric.criteria:
            pred = self.predicates.get(crit.key)
            if pred is None:
                checks.append(RubricCheck(crit.key, crit.description, False, "no predicate bound to criterion"))
                continue
            try:
                ok = bool(pred(node, output))
                detail = "" if ok else "predicate returned False"
            except _PREDICATE_ERRORS as exc:
                ok = False
                detail = f"predicate raised {type(exc).__name__}: {exc}"
            checks.append(RubricCheck(crit.key, crit.description, ok, detail))
        return _build_verdict(node, checks)


def _parse_command(command: str | Sequence[str]) -> tuple[list[str], str]:
    """Return (argv, refusal_reason). argv is empty when refused."""
    if isinstance(command, (list, tuple)):
        argv = [str(part) for part in command]
        return (argv, "") if argv else ([], "empty command")
    raw = str(command or "").strip()
    if not raw:
        return [], "empty command"
    for char in _SHELL_METACHARS:
        if char in raw:
            return [], f"shell metacharacter {char!r} in command"
    try:
        argv = shlex.split(raw, posix=True)
    except ValueError as exc:
        return [], f"unparseable command: {exc}"
    return (argv, "") if argv else ([], "empty command")


def command_allowlist_refusal(argv: Sequence[str]) -> str:
    """Explain why ``argv`` is not rerunnable, or '' when it is read-only allowlisted.

    Mirrors ``evolve_supervisor.independent_verifier.allowlist_refusal_reason``:
    only test/lint/compile-class ``python -m`` modules, a bare ``pytest``, and
    read-only ``git`` subcommands may be rerun.
    """
    argv = list(argv)
    if not argv:
        return "empty command"
    executable = Path(argv[0]).name.lower()
    if executable in _PYTHON_EXECUTABLES:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in ALLOWED_PYTHON_MODULES:
            return ""
        if len(argv) >= 2 and argv[1] == "-m":
            module = argv[2] if len(argv) > 2 else "<missing>"
            return f"python module {module!r} is not allowlisted"
        return "only 'python -m <allowlisted module>' invocations are rerunnable"
    if executable in ALLOWED_BARE_EXECUTABLES:
        return ""
    if executable in ("git", "git.exe"):
        subcommand = argv[1] if len(argv) > 1 else ""
        if subcommand in ALLOWED_GIT_SUBCOMMANDS:
            return ""
        return f"git subcommand {subcommand!r} is not read-only allowlisted"
    return f"executable {executable!r} is not allowlisted for independent rerun"


def _pin_python(argv: list[str]) -> list[str]:
    pinned = list(argv)
    if pinned and Path(pinned[0]).name.lower() in _PYTHON_EXECUTABLES:
        pinned[0] = sys.executable
    return pinned


def _default_command_runner(argv: list[str], cwd: str | None, timeout_seconds: int) -> tuple[int, str, str]:
    env = dict(os.environ)
    if cwd:
        env["PYTHONPATH"] = str(cwd)
    try:
        completed = subprocess.run(
            _pin_python(argv),
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, _snippet(exc.stdout), _snippet(exc.stderr) or "timed out"
    except OSError as exc:
        return 127, "", f"command failed to launch: {exc}"
    return int(completed.returncode), _snippet(completed.stdout), _snippet(completed.stderr)


@dataclasses.dataclass(frozen=True)
class CommandRerunVerifier:
    """Verify a node by rerunning a command bound to each rubric criterion.

    ``commands`` maps a criterion ``key`` to the command that proves it. Each
    command is parsed and screened by :func:`command_allowlist_refusal`; a
    refused command fails its criterion closed (never executes). Allowed
    commands run through the injectable ``runner`` (default: a real, pinned-
    python subprocess in ``cwd``) and pass when the exit code matches
    ``expected_returncode``. A criterion with no bound command fails closed.
    """

    commands: Mapping[str, str | Sequence[str]]
    cwd: str = ""
    expected_returncode: int = 0
    timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS
    runner: CommandRunner | None = None

    def verify(self, node: SubtaskNode, output: Any) -> NodeVerdict:
        runner = self.runner or _default_command_runner
        cwd = str(self.cwd or "").strip()
        cwd_ok = bool(cwd) and Path(cwd).is_dir()
        checks: list[RubricCheck] = []
        for crit in node.rubric.criteria:
            command = self.commands.get(crit.key)
            if command is None:
                checks.append(RubricCheck(crit.key, crit.description, False, "no command bound to criterion"))
                continue
            argv, parse_refusal = _parse_command(command)
            refusal = parse_refusal or command_allowlist_refusal(argv)
            if refusal:
                checks.append(RubricCheck(crit.key, crit.description, False, f"refused: {refusal}"))
                continue
            if self.runner is None and not cwd_ok:
                checks.append(
                    RubricCheck(crit.key, crit.description, False, f"cwd is missing or not a directory: {cwd!r}")
                )
                continue
            rc, out, err = runner(argv, cwd or None, self.timeout_seconds)
            passed = int(rc) == int(self.expected_returncode)
            if passed:
                detail = f"exit {rc}"
            else:
                tail = _snippet(err or out, limit=200)
                detail = f"expected exit {self.expected_returncode}, got {rc}" + (f"; {tail}" if tail else "")
            checks.append(RubricCheck(crit.key, crit.description, passed, detail))
        return _build_verdict(node, checks)


# ---------------------------------------------------------------------------
# Graph model
# ---------------------------------------------------------------------------


class GraphCycleError(ValueError):
    """Raised when a decomposition is not a DAG. Names the offending cycle."""

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        joined = " -> ".join(self.cycle)
        super().__init__(f"subtask graph is not a DAG; cycle: {joined}")


@dataclasses.dataclass(frozen=True)
class SubtaskNode:
    """One subtask: a description, its dependency edges, its rubric, its verifier.

    ``required`` nodes must verify for the goal to be met (defaults to True).
    A verifier is any object implementing the :class:`Verifier` protocol.
    """

    id: str
    description: str
    rubric: Rubric
    verifier: Verifier
    deps: tuple[str, ...] = ()
    required: bool = True

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> SubtaskNode:
        if not isinstance(data, Mapping):
            raise ValueError("subtask node must be a mapping")
        nid = str(data.get("id") or "").strip()
        if not nid:
            raise ValueError("subtask node requires a non-empty 'id'")
        rubric = data.get("rubric")
        if not isinstance(rubric, Rubric):
            raise ValueError(f"node {nid!r}: 'rubric' must be a Rubric instance")
        verifier = data.get("verifier")
        if not isinstance(verifier, Verifier):
            raise ValueError(f"node {nid!r}: 'verifier' must implement the Verifier protocol (a .verify method)")
        deps = data.get("deps") or ()
        if not isinstance(deps, (list, tuple)) or not all(isinstance(d, str) for d in deps):
            raise ValueError(f"node {nid!r}: 'deps' must be a list of node-id strings")
        return SubtaskNode(
            id=nid,
            description=str(data.get("description") or ""),
            rubric=rubric,
            verifier=verifier,
            deps=tuple(deps),
            required=bool(data.get("required", True)),
        )


@dataclasses.dataclass(frozen=True)
class GraphStatus:
    """Roll-up of per-node verdicts into a goal-level status."""

    goal_met: bool
    node_states: dict[str, str]  # node_id -> done | failed | blocked | pending
    done: tuple[str, ...]
    failed: tuple[str, ...]
    blocked: tuple[str, ...]
    pending: tuple[str, ...]
    required: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_met": self.goal_met,
            "node_states": dict(self.node_states),
            "done": list(self.done),
            "failed": list(self.failed),
            "blocked": list(self.blocked),
            "pending": list(self.pending),
            "required": list(self.required),
        }


class SubtaskGraph:
    """A DAG of verifiable subtasks decomposed from a goal."""

    def __init__(self, goal: str, nodes: Sequence[SubtaskNode]) -> None:
        self.goal = str(goal or "")
        ordered: dict[str, SubtaskNode] = {}
        for node in nodes:
            if node.id in ordered:
                raise ValueError(f"duplicate subtask id: {node.id!r}")
            ordered[node.id] = node
        self.nodes: dict[str, SubtaskNode] = ordered
        self._verdicts: dict[str, NodeVerdict] = {}
        self.validate()

    # -- construction --------------------------------------------------------

    @classmethod
    def from_decomposition(cls, goal: str, nodes: Sequence[SubtaskNode | Mapping[str, Any]]) -> SubtaskGraph:
        """Build a graph from a decomposition: a list of nodes (with deps)."""
        built = [n if isinstance(n, SubtaskNode) else SubtaskNode.from_dict(n) for n in nodes]
        return cls(goal, built)

    # -- validation ----------------------------------------------------------

    def validate(self) -> None:
        """Reject dangling deps and any cycle (naming the offending nodes)."""
        for nid, node in self.nodes.items():
            for dep in node.deps:
                if dep not in self.nodes:
                    raise ValueError(f"node {nid!r} depends on missing node {dep!r}")
        cycle = self._find_cycle()
        if cycle:
            raise GraphCycleError(cycle)

    def _find_cycle(self) -> list[str] | None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        stack: list[str] = []

        def visit(nid: str) -> list[str] | None:
            color[nid] = GRAY
            stack.append(nid)
            for dep in self.nodes[nid].deps:
                if color[dep] == GRAY:
                    # Found a back-edge: slice the stack from dep to close the cycle.
                    start = stack.index(dep)
                    return stack[start:] + [dep]
                if color[dep] == WHITE:
                    found = visit(dep)
                    if found is not None:
                        return found
            color[nid] = BLACK
            stack.pop()
            return None

        for nid in self.nodes:
            if color[nid] == WHITE:
                found = visit(nid)
                if found is not None:
                    return found
        return None

    # -- ordering ------------------------------------------------------------

    def topological_order(self) -> list[str]:
        """Dependency-respecting order: every dep precedes the node needing it.

        Stable by insertion order among nodes whose deps are already satisfied
        (Kahn's algorithm), so the same decomposition yields the same order.
        """
        indegree = {nid: 0 for nid in self.nodes}
        dependents: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for nid, node in self.nodes.items():
            indegree[nid] = len(node.deps)
            for dep in node.deps:
                dependents[dep].append(nid)
        ready = [nid for nid in self.nodes if indegree[nid] == 0]
        order: list[str] = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for child in dependents[nid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(order) != len(self.nodes):
            # validate() rejects cycles, so this is unreachable in a valid graph.
            raise GraphCycleError(sorted(n for n in self.nodes if n not in order))
        return order

    def ready_nodes(self) -> list[str]:
        """Nodes whose dependencies are all verified done and that are not yet done."""
        return [nid for nid in self.topological_order() if not self.is_done(nid) and self._deps_done(nid)]

    def _deps_done(self, node_id: str) -> bool:
        return all(self.is_done(dep) for dep in self.nodes[node_id].deps)

    # -- verification --------------------------------------------------------

    def verify_node(self, node_id: str, output: Any) -> NodeVerdict:
        """Verify one node's output against its own rubric via its own verifier."""
        if node_id not in self.nodes:
            raise KeyError(f"unknown subtask node: {node_id!r}")
        node = self.nodes[node_id]
        verdict = node.verifier.verify(node, output)
        self._verdicts[node_id] = verdict
        return verdict

    def verdict(self, node_id: str) -> NodeVerdict | None:
        return self._verdicts.get(node_id)

    def is_done(self, node_id: str) -> bool:
        """A node is done only when its verifier passed AND every dep is done.

        A failing (or unverified) dependency therefore blocks a dependent from
        ever counting as done, no matter what its own verdict says.
        """
        verdict = self._verdicts.get(node_id)
        if verdict is None or not verdict.passed:
            return False
        return all(self.is_done(dep) for dep in self.nodes[node_id].deps)

    def _node_state(self, node_id: str) -> str:
        verdict = self._verdicts.get(node_id)
        if verdict is not None and not verdict.passed:
            return "failed"
        # A node whose dep failed or is blocked cannot be done regardless of its own verdict.
        for dep in self.nodes[node_id].deps:
            dep_state = self._node_state(dep)
            if dep_state in ("failed", "blocked"):
                return "blocked"
        if self.is_done(node_id):
            return "done"
        return "pending"

    def status(self) -> GraphStatus:
        """Roll node verdicts up into a goal status.

        The goal is met only when every *required* node is verified done.
        """
        states = {nid: self._node_state(nid) for nid in self.nodes}
        required = tuple(nid for nid, n in self.nodes.items() if n.required)
        goal_met = bool(required) and all(self.is_done(nid) for nid in required)

        def _by_state(target: str) -> tuple[str, ...]:
            return tuple(nid for nid in self.nodes if states[nid] == target)

        return GraphStatus(
            goal_met=goal_met,
            node_states=states,
            done=_by_state("done"),
            failed=_by_state("failed"),
            blocked=_by_state("blocked"),
            pending=_by_state("pending"),
            required=required,
        )
