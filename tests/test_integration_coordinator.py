"""Tests for the CAP-056 integration coordinator.

Each test maps to a line in the acceptance criteria:
    * dependency order respected
    * a cycle rejected naming it
    * two disjoint, dependency-free branches are reported parallelizable
    * two branches touching the same file are serialized with the overlap named
    * a diamond dependency orders correctly
    * the plan's stages are deterministic
"""

from __future__ import annotations

import pytest

from thomas.tools.integration_coordinator import (
    Branch,
    IntegrationCoordinator,
    IntegrationCycleError,
)


def _coord(*branches: Branch) -> IntegrationCoordinator:
    return IntegrationCoordinator(branches)


def test_dependency_order_respected():
    # feature depends on base -> base must land in an earlier stage.
    coord = _coord(
        Branch.make("feature", files={"app/feature.py"}, depends_on={"base"}),
        Branch.make("base", files={"app/base.py"}),
    )
    plan = coord.plan()

    assert plan.stage_of("base") < plan.stage_of("feature")
    assert plan.order.index("base") < plan.order.index("feature")


def test_cycle_rejected_naming_it():
    coord = _coord(
        Branch.make("a", depends_on={"b"}),
        Branch.make("b", depends_on={"a"}),
    )
    with pytest.raises(IntegrationCycleError) as exc:
        coord.plan()

    cycle = exc.value.cycle
    # The cycle names the offending branches (closed loop).
    assert set(cycle) == {"a", "b"}
    assert cycle[0] == cycle[-1]  # closed loop
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_self_dependency_is_a_cycle():
    with pytest.raises(IntegrationCycleError) as exc:
        _coord(Branch.make("solo", depends_on={"solo"}))
    assert exc.value.cycle == ["solo", "solo"]


def test_disjoint_no_dep_branches_are_parallelizable():
    # Different files, no dependency edge -> same stage.
    coord = _coord(
        Branch.make("left", files={"a.py"}),
        Branch.make("right", files={"b.py"}),
    )
    plan = coord.plan()

    assert len(plan.stages) == 1
    assert plan.stages[0].branches == ("left", "right")
    assert plan.stages[0].parallelizable is True
    assert plan.parallel_groups == (("left", "right"),)
    assert plan.warnings == ()


def test_overlapping_branches_serialized_with_overlap_named():
    coord = _coord(
        Branch.make("alpha", files={"shared.py", "a.py"}),
        Branch.make("beta", files={"shared.py", "b.py"}),
    )
    plan = coord.plan()

    # Overlapping files force separate stages (serialized).
    assert plan.stage_of("alpha") != plan.stage_of("beta")
    assert len(plan.stages) == 2

    assert len(plan.warnings) == 1
    warn = plan.warnings[0]
    assert {warn.branch_before, warn.branch_after} == {"alpha", "beta"}
    assert warn.shared_files == ("shared.py",)
    # Deterministic serialization order: earlier stage first, name tie-break.
    assert warn.branch_before == "alpha"
    assert warn.branch_after == "beta"
    assert "shared.py" in warn.describe()


def test_diamond_dependency_orders_correctly():
    # d -> {b, c} -> a   (a depends on b and c; b and c depend on d)
    coord = _coord(
        Branch.make("a", files={"a.py"}, depends_on={"b", "c"}),
        Branch.make("b", files={"b.py"}, depends_on={"d"}),
        Branch.make("c", files={"c.py"}, depends_on={"d"}),
        Branch.make("d", files={"d.py"}),
    )
    plan = coord.plan()

    sd = plan.stage_of("d")
    sb = plan.stage_of("b")
    sc = plan.stage_of("c")
    sa = plan.stage_of("a")

    assert sd < sb and sd < sc
    assert sb < sa and sc < sa
    # b and c are disjoint and dependency-siblings -> same stage (parallel).
    assert sb == sc
    assert plan.stages[sb].branches == ("b", "c")
    assert plan.warnings == ()


def test_diamond_with_sibling_overlap_serializes_siblings():
    # Same diamond, but b and c touch a shared file -> they cannot share a stage.
    coord = _coord(
        Branch.make("a", files={"a.py"}, depends_on={"b", "c"}),
        Branch.make("b", files={"shared.py"}, depends_on={"d"}),
        Branch.make("c", files={"shared.py"}, depends_on={"d"}),
        Branch.make("d", files={"d.py"}),
    )
    plan = coord.plan()

    assert plan.stage_of("b") != plan.stage_of("c")
    assert plan.stage_of("a") > max(plan.stage_of("b"), plan.stage_of("c"))
    assert any(w.shared_files == ("shared.py",) for w in plan.warnings)


def test_plan_stages_are_deterministic():
    def build() -> IntegrationCoordinator:
        # Insertion order deliberately scrambled to prove independence.
        return _coord(
            Branch.make("c", files={"c.py"}, depends_on={"a"}),
            Branch.make("a", files={"a.py"}),
            Branch.make("d", files={"shared.py"}, depends_on={"b"}),
            Branch.make("b", files={"shared.py"}),
        )

    first = build().plan()
    second = build().plan()

    assert first.to_dict() == second.to_dict()
    # Structural equality of frozen dataclasses too.
    assert first.stages == second.stages
    assert first.warnings == second.warnings


def test_from_specs_equivalent_and_unknown_dep_rejected():
    plan = IntegrationCoordinator.from_specs(
        {
            "base": {"files": ["base.py"]},
            "feat": {"files": ["feat.py"], "depends_on": ["base"]},
        }
    ).plan()
    assert plan.stage_of("base") < plan.stage_of("feat")

    with pytest.raises(ValueError, match="unknown branch"):
        _coord(Branch.make("x", depends_on={"ghost"}))


def test_duplicate_branch_rejected():
    with pytest.raises(ValueError, match="duplicate branch"):
        _coord(Branch.make("dup"), Branch.make("dup"))


def test_three_way_cycle_named():
    coord = _coord(
        Branch.make("x", depends_on={"y"}),
        Branch.make("y", depends_on={"z"}),
        Branch.make("z", depends_on={"x"}),
    )
    with pytest.raises(IntegrationCycleError) as exc:
        coord.plan()
    assert set(exc.value.cycle) == {"x", "y", "z"}
    assert exc.value.cycle[0] == exc.value.cycle[-1]
