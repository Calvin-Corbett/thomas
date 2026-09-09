"""Integration coordinator (CAP-056).

An explicit merge / integration coordinator that takes a set of branches --
each declaring the files it touches and its dependencies on other branches --
and produces a deterministic :class:`IntegrationPlan`.

The coordinator does three things:

1. **Orders branches** for integration respecting declared dependencies
   (topological order). A dependency cycle is rejected with an
   :class:`IntegrationCycleError` that names the offending cycle.

2. **Resolves non-overlapping dependencies.** Branches whose file sets are
   disjoint *and* which have no dependency edge between them may be integrated
   in parallel / any order -- they are placed in the same stage
   (a "parallelizable group"). Branches that touch overlapping files are
   serialized into separate stages in a deterministic order, and the shared
   files are named in an :class:`OverlapWarning`.

3. **Produces an :class:`IntegrationPlan`** -- ordered stages, each stage a set
   of branches that are safe to integrate together, plus any overlap warnings.

The logic is pure and deterministic: it operates entirely on the declared
metadata and needs no real git. The same inputs always yield byte-identical
plans (branch names are sorted within every stage, stages are ordered, and
warnings are sorted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

__all__ = [
    "Branch",
    "IntegrationStage",
    "OverlapWarning",
    "IntegrationPlan",
    "IntegrationCoordinator",
    "IntegrationCycleError",
]


class IntegrationCycleError(ValueError):
    """Raised when the declared dependencies contain a cycle.

    The ``cycle`` attribute holds the branch names forming the cycle, in order,
    with the first branch repeated at the end (e.g. ``["a", "b", "a"]``).
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle: list[str] = list(cycle)
        joined = " -> ".join(self.cycle)
        super().__init__(f"dependency cycle detected: {joined}")


@dataclass(frozen=True)
class Branch:
    """A branch awaiting integration.

    Attributes:
        name: Unique branch name.
        files: The set of file paths the branch touches.
        depends_on: Names of branches that must be integrated *before* this one.
    """

    name: str
    files: frozenset[str] = field(default_factory=frozenset)
    depends_on: frozenset[str] = field(default_factory=frozenset)

    @staticmethod
    def make(
        name: str,
        files: Iterable[str] = (),
        depends_on: Iterable[str] = (),
    ) -> Branch:
        """Construct a :class:`Branch`, normalizing iterables to frozensets."""
        return Branch(
            name=name,
            files=frozenset(files),
            depends_on=frozenset(depends_on),
        )


@dataclass(frozen=True)
class IntegrationStage:
    """A group of branches safe to integrate together (any order / parallel)."""

    index: int
    branches: tuple[str, ...]

    @property
    def parallelizable(self) -> bool:
        """True when the stage holds more than one branch."""
        return len(self.branches) > 1


@dataclass(frozen=True)
class OverlapWarning:
    """Two branches touch overlapping files and were serialized.

    ``branch_before`` is scheduled in an earlier (or equal-then-tiebroken)
    stage than ``branch_after``; ``shared_files`` names the overlap.
    """

    branch_before: str
    branch_after: str
    shared_files: tuple[str, ...]

    def describe(self) -> str:
        files = ", ".join(self.shared_files)
        return (
            f"{self.branch_before} and {self.branch_after} both touch "
            f"[{files}]; serialized {self.branch_before} before "
            f"{self.branch_after}"
        )


@dataclass(frozen=True)
class IntegrationPlan:
    """The full plan: ordered stages, a flat order, and overlap warnings."""

    stages: tuple[IntegrationStage, ...]
    warnings: tuple[OverlapWarning, ...]

    @property
    def order(self) -> tuple[str, ...]:
        """Flat integration order: branch names concatenated stage by stage."""
        result: list[str] = []
        for stage in self.stages:
            result.extend(stage.branches)
        return tuple(result)

    @property
    def parallel_groups(self) -> tuple[tuple[str, ...], ...]:
        """Stages that contain more than one branch (integratable in parallel)."""
        return tuple(s.branches for s in self.stages if s.parallelizable)

    def stage_of(self, branch: str) -> int:
        """Return the stage index a branch was placed in."""
        for stage in self.stages:
            if branch in stage.branches:
                return stage.index
        raise KeyError(branch)

    def to_dict(self) -> dict:
        return {
            "stages": [{"index": s.index, "branches": list(s.branches)} for s in self.stages],
            "order": list(self.order),
            "warnings": [
                {
                    "branch_before": w.branch_before,
                    "branch_after": w.branch_after,
                    "shared_files": list(w.shared_files),
                }
                for w in self.warnings
            ],
        }


class IntegrationCoordinator:
    """Order branches and resolve non-overlapping dependencies deterministically."""

    def __init__(self, branches: Iterable[Branch]) -> None:
        by_name: dict[str, Branch] = {}
        for br in branches:
            if br.name in by_name:
                raise ValueError(f"duplicate branch name: {br.name!r}")
            by_name[br.name] = br
        self._branches: dict[str, Branch] = by_name
        self._validate_dependencies()

    # -- construction helpers ------------------------------------------------

    @classmethod
    def from_specs(cls, specs: Mapping[str, Mapping[str, Iterable[str]]]) -> IntegrationCoordinator:
        """Build from a plain mapping ``{name: {"files": [...], "depends_on": [...]}}``."""
        branches = [
            Branch.make(
                name=name,
                files=spec.get("files", ()),
                depends_on=spec.get("depends_on", ()),
            )
            for name, spec in specs.items()
        ]
        return cls(branches)

    def _validate_dependencies(self) -> None:
        for br in self._branches.values():
            if br.name in br.depends_on:
                raise IntegrationCycleError([br.name, br.name])
            for dep in br.depends_on:
                if dep not in self._branches:
                    raise ValueError(f"branch {br.name!r} depends on unknown branch {dep!r}")

    # -- topological ordering ------------------------------------------------

    def _find_cycle(self) -> list[str] | None:
        """Return an explicit dependency cycle (names) if one exists, else None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {name: WHITE for name in self._branches}
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
            color[node] = GRAY
            stack.append(node)
            for dep in sorted(self._branches[node].depends_on):
                if color[dep] == GRAY:
                    idx = stack.index(dep)
                    return stack[idx:] + [dep]
                if color[dep] == WHITE:
                    found = visit(dep)
                    if found is not None:
                        return found
            stack.pop()
            color[node] = BLACK
            return None

        for name in sorted(self._branches):
            if color[name] == WHITE:
                found = visit(name)
                if found is not None:
                    return found
        return None

    def topological_order(self) -> list[str]:
        """Deterministic dependency-respecting order (Kahn's, name tie-break)."""
        cycle = self._find_cycle()
        if cycle is not None:
            raise IntegrationCycleError(cycle)

        indegree: dict[str, int] = {name: 0 for name in self._branches}
        # edge: dep -> branch (dep must come first)
        dependents: dict[str, list[str]] = {name: [] for name in self._branches}
        for name, br in self._branches.items():
            for dep in br.depends_on:
                indegree[name] += 1
                dependents[dep].append(name)

        ready = sorted(n for n, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            newly_ready: list[str] = []
            for child in dependents[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly_ready.append(child)
            if newly_ready:
                # keep `ready` sorted for determinism
                ready = sorted(ready + newly_ready)
        return order

    # -- plan construction ---------------------------------------------------

    def plan(self) -> IntegrationPlan:
        """Compute the deterministic integration plan."""
        order = self.topological_order()

        # Greedy stage assignment over the topological order.
        # Stage membership guarantees, for every pair in a stage:
        #   * neither depends on the other (enforced by min_stage), and
        #   * their files are disjoint (enforced by the overlap check).
        stages: list[list[str]] = []
        stage_of: dict[str, int] = {}

        for name in order:
            br = self._branches[name]
            # Must land strictly after every dependency's stage.
            min_stage = 0
            for dep in br.depends_on:
                min_stage = max(min_stage, stage_of[dep] + 1)

            placed = -1
            for idx in range(min_stage, len(stages)):
                if self._fits_in_stage(br, stages[idx]):
                    stages[idx].append(name)
                    placed = idx
                    break
            if placed == -1:
                stages.append([name])
                placed = len(stages) - 1
            stage_of[name] = placed

        warnings = self._collect_warnings(stage_of)

        frozen_stages = tuple(
            IntegrationStage(index=i, branches=tuple(sorted(members))) for i, members in enumerate(stages)
        )
        return IntegrationPlan(stages=frozen_stages, warnings=warnings)

    def _fits_in_stage(self, br: Branch, members: list[str]) -> bool:
        for other in members:
            if br.files & self._branches[other].files:
                return False
        return True

    def _collect_warnings(self, stage_of: Mapping[str, int]) -> tuple[OverlapWarning, ...]:
        names = sorted(self._branches)
        warnings: list[OverlapWarning] = []
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                shared = self._branches[a].files & self._branches[b].files
                if not shared:
                    continue
                # Determine which was serialized first (earlier stage wins;
                # ties -- which cannot happen for overlapping files -- fall back
                # to name order for determinism).
                if stage_of[a] <= stage_of[b]:
                    before, after = a, b
                else:
                    before, after = b, a
                warnings.append(
                    OverlapWarning(
                        branch_before=before,
                        branch_after=after,
                        shared_files=tuple(sorted(shared)),
                    )
                )
        return tuple(warnings)
