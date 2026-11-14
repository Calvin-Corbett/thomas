"""Failure attribution keeps missing evidence and dependencies off builder repair."""

from thomas.core.praxis.routing import route


def _checks(*, passed: bool, failed: tuple[str, ...] = ()):
    return {"passed": passed, "checks_failed": list(failed)}


def test_builder_failure_is_routed_to_the_culprit_not_its_dependent():
    result = route(
        ["library", "app"],
        dependencies={"app": ["library"]},
        isolation={"library": _checks(passed=False, failed=("library_check",)), "app": _checks(passed=True)},
        combined={"library": _checks(passed=False), "app": _checks(passed=False)},
    )
    assert result["class"] == "builder_correctness"
    assert result["outcomes"] == {"library": "repair", "app": "accepted"}
    assert result["dependency_caused"] == {"library": ["app"]}
    assert result["consumes_repair"] is True


def test_missing_or_identical_evidence_never_charges_a_builder():
    incomplete = route(
        ["a", "b"], dependencies={}, isolation={"a": _checks(passed=True)}, combined={"a": _checks(passed=True)}
    )
    assert incomplete["class"] == "evaluation_incomplete"
    assert incomplete["outcomes"] == {"a": "stop", "b": "stop"}
    assert incomplete["consumes_repair"] is False
    duplicate = route(
        ["a", "b"],
        dependencies={},
        isolation={
            "a": _checks(passed=False, failed=("same_requirement",)),
            "b": _checks(passed=False, failed=("same_requirement",)),
        },
        combined={"a": _checks(passed=False), "b": _checks(passed=False)},
    )
    assert duplicate["class"] == "possible_spec_defect"
    assert duplicate["reasons"] == ["same_requirement"]
    assert duplicate["routed_to"] == []


def test_combined_failure_without_a_cause_is_system_owned():
    result = route(
        ["a"],
        dependencies={},
        isolation={"a": _checks(passed=True)},
        combined={"a": _checks(passed=False)},
    )
    assert result["class"] == "integration_failure_unattributed"
    assert result["unattributed"] == ["a"]
    assert result["consumes_repair"] is False
