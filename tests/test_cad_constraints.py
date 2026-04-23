"""
Tests for constraint solver.
"""

import pytest

from thomas.marketplace.cad._types import Line, Point2D
from thomas.marketplace.cad.constraints import (
    ConstraintAnalyzer,
    ConstraintSolver,
    ConstraintType,
    Variable,
)


class TestVariable:
    """Tests for constraint variables."""

    def test_variable_creation(self) -> None:
        """Test variable creation."""
        var = Variable("x", value=5.0)
        assert var.name == "x"
        assert var.value == pytest.approx(5.0)

    def test_variable_bounds(self) -> None:
        """Test variable bounds."""
        var = Variable("x", value=5.0, lower_bound=0, upper_bound=10)
        assert var.lower_bound == 0
        assert var.upper_bound == 10


class TestConstraintSolver:
    """Tests for constraint solver."""

    def test_solver_creation(self) -> None:
        """Test solver creation."""
        solver = ConstraintSolver()
        assert len(solver.variables) == 0
        assert len(solver.constraints) == 0

    def test_add_variable(self) -> None:
        """Test adding variables."""
        solver = ConstraintSolver()

        x = solver.add_variable("x", 0.0)
        y = solver.add_variable("y", 0.0)

        assert len(solver.variables) == 2
        assert solver.get_variable("x") is x
        assert solver.get_variable("y") is y

    def test_add_constraint(self) -> None:
        """Test adding constraints."""
        solver = ConstraintSolver()

        solver.add_variable("x")
        solver.add_variable("y")

        p1 = Point2D(0, 0)
        p2 = Point2D(5, 0)

        constraint = solver.add_constraint(ConstraintType.DISTANCE, [p1, p2], value=5.0)

        assert len(solver.constraints) == 1
        assert constraint.constraint_type == ConstraintType.DISTANCE

    def test_duplicate_variable_error(self) -> None:
        """Test error on duplicate variable."""
        from thomas.marketplace.cad._exceptions import ConstraintError

        solver = ConstraintSolver()
        solver.add_variable("x")

        with pytest.raises(ConstraintError):
            solver.add_variable("x")

    def test_get_solution(self) -> None:
        """Test getting solution."""
        solver = ConstraintSolver()

        solver.add_variable("x", 3.0)
        solver.add_variable("y", 4.0)

        solution = solver.get_solution()

        assert solution["x"] == pytest.approx(3.0)
        assert solution["y"] == pytest.approx(4.0)


class TestConstraintAnalyzer:
    """Tests for constraint analyzer."""

    def test_degrees_of_freedom(self) -> None:
        """Test DOF calculation."""
        solver = ConstraintSolver()

        solver.add_variable("x")
        solver.add_variable("y")
        solver.add_variable("z")

        analyzer = ConstraintAnalyzer(solver)

        dof = analyzer.degrees_of_freedom()
        assert dof == 3

    def test_under_constrained(self) -> None:
        """Test under-constrained detection."""
        solver = ConstraintSolver()

        solver.add_variable("x")
        solver.add_variable("y")

        p1 = Point2D(0, 0)
        p2 = Point2D(5, 0)

        solver.add_constraint(ConstraintType.DISTANCE, [p1, p2], value=5.0)

        analyzer = ConstraintAnalyzer(solver)

        assert analyzer.is_under_constrained()

    def test_fully_constrained(self) -> None:
        """Test fully-constrained detection."""
        solver = ConstraintSolver()

        solver.add_variable("x")
        solver.add_variable("y")

        p1 = Point2D(0, 0)
        p2 = Point2D(5, 0)
        p3 = Point2D(0, 3)

        solver.add_constraint(ConstraintType.DISTANCE, [p1, p2], value=5.0)
        solver.add_constraint(ConstraintType.DISTANCE, [p1, p3], value=3.0)

        analyzer = ConstraintAnalyzer(solver)

        assert not analyzer.is_under_constrained()


class TestConstraintTypes:
    """Tests for different constraint types."""

    def test_distance_constraint(self) -> None:
        """Test distance constraint."""
        solver = ConstraintSolver()

        solver.add_variable("x")
        solver.add_variable("y")

        p1 = Point2D(0, 0)
        p2 = Point2D(3, 4)

        constraint = solver.add_constraint(ConstraintType.DISTANCE, [p1, p2], value=5.0)

        assert constraint.value == 5.0

    def test_equal_length_constraint(self) -> None:
        """Test equal length constraint."""
        solver = ConstraintSolver()

        line1 = Line(Point2D(0, 0), Point2D(5, 0))
        line2 = Line(Point2D(0, 0), Point2D(0, 5))

        constraint = solver.add_constraint(ConstraintType.EQUAL_LENGTH, [line1, line2])

        assert constraint.constraint_type == ConstraintType.EQUAL_LENGTH

    def test_horizontal_constraint(self) -> None:
        """Test horizontal constraint."""
        solver = ConstraintSolver()

        line = Line(Point2D(0, 0), Point2D(5, 0))

        constraint = solver.add_constraint(ConstraintType.HORIZONTAL, [line])

        assert constraint.constraint_type == ConstraintType.HORIZONTAL

    def test_vertical_constraint(self) -> None:
        """Test vertical constraint."""
        solver = ConstraintSolver()

        line = Line(Point2D(0, 0), Point2D(0, 5))

        constraint = solver.add_constraint(ConstraintType.VERTICAL, [line])

        assert constraint.constraint_type == ConstraintType.VERTICAL

    def test_coincident_constraint(self) -> None:
        """Test coincident constraint."""
        solver = ConstraintSolver()

        p1 = Point2D(0, 0)
        p2 = Point2D(0, 0)

        constraint = solver.add_constraint(ConstraintType.COINCIDENT, [p1, p2])

        assert constraint.constraint_type == ConstraintType.COINCIDENT


class TestSolverConvergence:
    """Tests for solver convergence."""

    def test_solver_empty_system(self) -> None:
        """Test solver with empty system."""
        solver = ConstraintSolver()

        result = solver.solve()
        assert result

    def test_solver_with_variables_no_constraints(self) -> None:
        """Test solver with variables but no constraints."""
        solver = ConstraintSolver()

        solver.add_variable("x", 5.0)
        solver.add_variable("y", 3.0)

        result = solver.solve()
        assert result

        solution = solver.get_solution()
        assert solution["x"] == pytest.approx(5.0)
        assert solution["y"] == pytest.approx(3.0)
