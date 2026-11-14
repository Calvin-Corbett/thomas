"""Validate a model-authored Praxis fan-out plan before any child owns work."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

KINDS = frozenset({"research", "review", "write", "verify", "interface"})
PARALLEL_REASONS = frozenset({"independent_reads", "disjoint_writes", "independent_verification"})


def _cited(text: Any, source: str) -> bool:
    quote = " ".join(str(text or "").split()).casefold()
    return bool(quote) and quote in " ".join(source.split()).casefold()


def _owned_path(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = raw.strip().replace("\\", "/")
    parts = PurePosixPath(path).parts
    if (
        path.startswith("/")
        or path.startswith("//")
        or ":" in path
        or any(part in {".", ".."} for part in path.split("/"))
        or not parts
    ):
        return None
    return "/".join(parts).casefold()


def _overlap(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def _has_cycle(dependencies: dict[str, tuple[str, ...]]) -> bool:
    active: set[str] = set()
    finished: set[str] = set()

    def visit(unit: str) -> bool:
        if unit in active:
            return True
        if unit in finished:
            return False
        active.add(unit)
        for parent in dependencies.get(unit, ()):
            if visit(parent):
                return True
        active.remove(unit)
        finished.add(unit)
        return False

    return any(visit(unit) for unit in dependencies)


def plan_problems(plan: Mapping[str, Any], *, instructions: str, effort: str = "max") -> tuple[str, ...]:
    """Return stable repairable codes; capacity affects scheduling, not validity.

    The model chooses the number of units. This validator neither adds units
    nor imposes an arbitrary 64/100-agent ceiling.
    """
    problems: set[str] = set()
    units = plan.get("units")
    if not isinstance(units, list) or not units or any(not isinstance(unit, Mapping) for unit in units):
        return ("invalid_units",)
    if plan.get("why_parallel") not in PARALLEL_REASONS:
        problems.add("missing_parallel_reason")

    ids = [str(unit.get("id") or "").strip() for unit in units]
    if any(not unit for unit in ids) or len(set(ids)) != len(ids):
        problems.add("duplicate_or_missing_id")
    known = set(ids)
    interfaces = {ids[index] for index, unit in enumerate(units) if unit.get("kind") == "interface"}
    owned: list[tuple[str, str]] = []
    dependencies: dict[str, tuple[str, ...]] = {}
    for index, unit in enumerate(units):
        kind = unit.get("kind")
        if kind not in KINDS:
            problems.add("unknown_kind")
        if not str(unit.get("reason") or "").strip() or not str(unit.get("brief") or "").strip():
            problems.add("empty_reason_or_brief")
        raw_deps = unit.get("depends_on") or []
        if not isinstance(raw_deps, list) or any(not isinstance(dep, str) for dep in raw_deps):
            problems.add("invalid_dependencies")
            raw_deps = []
        deps = tuple(raw_deps)
        dependencies[ids[index]] = deps
        if any(dep not in known or dep == ids[index] for dep in deps):
            problems.add("invalid_dependencies")

        raw_paths = unit.get("owned_paths") or []
        if not isinstance(raw_paths, list):
            problems.add("invalid_owned_path")
            raw_paths = []
        paths = [_owned_path(path) for path in raw_paths]
        if any(path is None for path in paths):
            problems.add("invalid_owned_path")
        if kind == "write":
            if not paths or any(path is None for path in paths):
                problems.add("writer_without_path")
            if len(set(path for path in paths if path is not None)) != len(paths):
                problems.add("duplicate_owned_path")
            if effort != "max":
                problems.add("kind_not_allowed_at_effort")
            if not interfaces.intersection(deps):
                problems.add("writers_without_interface_unit")
            owned.extend((ids[index], path) for path in paths if path is not None)

        acceptance = unit.get("acceptance") or []
        if not isinstance(acceptance, list):
            problems.add("invalid_acceptance")
            acceptance = []
        if not acceptance:
            problems.add("missing_acceptance")
        for check in acceptance:
            if not isinstance(check, Mapping) or not _cited(check.get("cites"), instructions):
                problems.add("uncited_acceptance")

    if any(
        _overlap(first, second) and first_owner != second_owner
        for pos, (first_owner, first) in enumerate(owned)
        for second_owner, second in owned[pos + 1 :]
    ):
        problems.add("overlapping_owners")
    if "invalid_dependencies" not in problems and "duplicate_or_missing_id" not in problems:
        if _has_cycle(dependencies):
            problems.add("dependency_cycle")
    return tuple(sorted(problems))


__all__ = ["plan_problems"]
