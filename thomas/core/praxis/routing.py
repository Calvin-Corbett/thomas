"""Attribute observed Praxis failures before charging an owner with repair.

The evaluator must supply isolation and combined check results. Missing or
ambiguous evidence stops routing; it does not become a builder failure.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

ACCEPTED, REPAIR, STOP, ABSENT = "accepted", "repair", "stop", "absent"


def _transitive(owner: str, dependencies: Mapping[str, Sequence[str]]) -> set[str]:
    seen: set[str] = set()
    pending = list(dependencies.get(owner, ()))
    while pending:
        candidate = pending.pop()
        if candidate == owner or candidate in seen:
            continue
        seen.add(candidate)
        pending.extend(dependencies.get(candidate, ()))
    return seen


def route(
    owners: Sequence[str],
    *,
    dependencies: Mapping[str, Sequence[str]],
    isolation: Mapping[str, Mapping[str, Any]],
    combined: Mapping[str, Mapping[str, Any]],
    absent: Sequence[str] = (),
    child_problems: Sequence[str] = (),
    system_passed: bool = True,
) -> dict[str, Any]:
    """Return per-owner outcomes and causal evidence from independent checks."""
    owner_ids = tuple(str(owner) for owner in owners)
    if not owner_ids or len(set(owner_ids)) != len(owner_ids):
        raise ValueError("distinct owners are required")
    missing = set(absent)
    if missing - set(owner_ids):
        raise ValueError("absent owner is not registered")
    problems = list(child_problems)
    for owner in owner_ids:
        if owner not in missing and (owner not in isolation or owner not in combined):
            problems.append(f"missing_evaluation:{owner}")
    base: dict[str, Any] = {"absent": sorted(missing), "dependency_caused": {}, "waiting_on_absent": {}}
    if problems:
        return {
            **base,
            "class": "evaluation_incomplete",
            "routed_to": [],
            "outcomes": {owner: ABSENT if owner in missing else STOP for owner in owner_ids},
            "owner_evidence": {},
            "unattributed": [],
            "reasons": sorted(set(problems)),
            "consumes_repair": False,
        }
    failing = sorted(owner for owner in owner_ids if owner not in missing and not isolation[owner].get("passed"))
    combined_failing = sorted(
        owner for owner in owner_ids if owner not in missing and not combined[owner].get("passed")
    )

    # The same failing acceptance check across independent owners may be a bad
    # requirement. Halt attribution until a check review can settle it.
    repeated = Counter(
        str(check) for owner in failing for check in set(isolation[owner].get("checks_failed") or ()) if str(check)
    )
    possible_spec_defect = sorted(check for check, count in repeated.items() if count > 1)
    if possible_spec_defect:
        return {
            **base,
            "class": "possible_spec_defect",
            "routed_to": [],
            "outcomes": {owner: ABSENT if owner in missing else STOP for owner in owner_ids},
            "owner_evidence": {},
            "unattributed": [],
            "reasons": possible_spec_defect,
            "consumes_repair": False,
        }

    dependency_caused: dict[str, list[str]] = {}
    waiting_on_absent: dict[str, list[str]] = {}
    unattributed: list[str] = []
    for dependent in combined_failing:
        if dependent in failing:
            continue
        transitive = _transitive(dependent, dependencies)
        culprits = sorted(transitive.intersection(failing))
        missing_dependencies = sorted(transitive.intersection(missing))
        if culprits:
            for culprit in culprits:
                dependency_caused.setdefault(culprit, []).append(dependent)
        elif missing_dependencies:
            waiting_on_absent[dependent] = missing_dependencies
        else:
            unattributed.append(dependent)
    if not system_passed and not failing and not missing:
        unattributed.append("system")

    if failing:
        classification = "builder_correctness"
        outcomes = {
            owner: ABSENT if owner in missing else (REPAIR if owner in failing else ACCEPTED) for owner in owner_ids
        }
    elif unattributed:
        classification = "integration_failure_unattributed"
        outcomes = {owner: ABSENT if owner in missing else STOP for owner in owner_ids}
    elif missing:
        classification = "waiting_for_absent_owners"
        outcomes = {owner: ABSENT if owner in missing else ACCEPTED for owner in owner_ids}
    else:
        classification = ACCEPTED
        outcomes = {owner: ACCEPTED for owner in owner_ids}
    evidence = {
        owner: {
            "isolation_failed_checks": list(isolation[owner].get("checks_failed") or ())[:10],
            "breaks_dependents": sorted(dependency_caused.get(owner, ())),
        }
        for owner in failing
    }
    return {
        **base,
        "class": classification,
        "routed_to": failing,
        "outcomes": outcomes,
        "dependency_caused": dependency_caused,
        "waiting_on_absent": waiting_on_absent,
        "owner_evidence": evidence,
        "unattributed": unattributed,
        "reasons": [],
        "consumes_repair": classification == "builder_correctness",
    }


__all__ = ["ABSENT", "ACCEPTED", "REPAIR", "STOP", "route"]
