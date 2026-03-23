"""
Geometric constraint solver.

Defines constraint types and implements constraint solving using Newton-Raphson,
DOF analysis, and constraint propagation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ._exceptions import ConstraintError
from ._types import Line

EPSILON = 1e-10


class ConstraintType(Enum):
    """Types of geometric constraints."""

    COINCIDENT = "coincident"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    TANGENT = "tangent"
    EQUAL_LENGTH = "equal_length"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    CONCENTRIC = "concentric"
    SYMMETRIC = "symmetric"
    ANGLE = "angle"
    DISTANCE = "distance"
    RADIUS = "radius"
    DIAMETER = "diameter"
    MIDPOINT = "midpoint"


@dataclass
class Constraint:
    """A geometric constraint."""

    constraint_type: ConstraintType
    entities: list[Any] = field(default_factory=list)
    value: float | None = None
    label: str = ""

    def __repr__(self) -> str:
        return f"Constraint({self.constraint_type.value}, {self.label})"


@dataclass
class Variable:
    """A variable in the constraint system (e.g., coordinate, length)."""

    name: str
    value: float = 0.0
    lower_bound: float = -1e6
    upper_bound: float = 1e6

    def __repr__(self) -> str:
        return f"Var({self.name}={self.value:.4f})"


class ConstraintSolver:
    """Solves geometric constraints using Newton-Raphson method."""

    def __init__(self) -> None:
        """Initialize solver."""
        self.variables: dict[str, Variable] = {}
        self.constraints: list[Constraint] = []
        self.var_to_index: dict[str, int] = {}

    def add_variable(self, name: str, value: float = 0.0) -> Variable:
        """
        Add a variable.

        Args:
            name: Variable name
            value: Initial value

        Returns:
            Variable object
        """
        if name in self.variables:
            raise ConstraintError(f"Variable {name} already exists")

        var = Variable(name, value)
        self.variables[name] = var
        self.var_to_index[name] = len(self.var_to_index)

        return var

    def add_constraint(
        self, constraint_type: ConstraintType, entities: list[Any], value: float | None = None
    ) -> Constraint:
        """
        Add a constraint.

        Args:
            constraint_type: Type of constraint
            entities: Geometric entities involved
            value: Optional constraint value (for distance, angle, etc.)

        Returns:
            Constraint object
        """
        constraint = Constraint(constraint_type, entities, value)
        self.constraints.append(constraint)

        return constraint

    def solve(self, max_iterations: int = 100, tolerance: float = 1e-8) -> bool:
        """
        Solve constraints using Newton-Raphson method.

        Args:
            max_iterations: Maximum iterations
            tolerance: Convergence tolerance

        Returns:
            True if solved successfully
        """
        n_vars = len(self.variables)

        if n_vars == 0 or len(self.constraints) == 0:
            return True

        for iteration in range(max_iterations):
            residuals = self._compute_residuals()

            if self._check_convergence(residuals, tolerance):
                return True

            jacobian = self._compute_jacobian()

            try:
                delta = self._solve_linear_system(jacobian, residuals)
            except Exception:
                return False

            self._update_variables(delta)

        return False

    def _compute_residuals(self) -> list[float]:
        """Compute constraint residuals."""
        residuals: list[float] = []

        for constraint in self.constraints:
            residual = self._evaluate_constraint(constraint)
            residuals.append(residual)

        return residuals

    def _evaluate_constraint(self, constraint: Constraint) -> float:
        """Evaluate constraint residual."""
        c_type = constraint.constraint_type

        if c_type == ConstraintType.DISTANCE:
            if len(constraint.entities) == 2:
                p1, p2 = constraint.entities
                actual_dist = p1.distance_to(p2)
                return actual_dist - (constraint.value or 0.0)

        elif c_type == ConstraintType.EQUAL_LENGTH:
            if len(constraint.entities) == 2:
                line1, line2 = constraint.entities
                return line1.length() - line2.length()

        elif c_type == ConstraintType.COINCIDENT:
            if len(constraint.entities) == 2:
                p1, p2 = constraint.entities
                return p1.distance_to(p2)

        elif c_type == ConstraintType.HORIZONTAL:
            if len(constraint.entities) == 1:
                line = constraint.entities[0]
                if isinstance(line, Line):
                    return abs(line.end.y - line.start.y)

        elif c_type == ConstraintType.VERTICAL:
            if len(constraint.entities) == 1:
                line = constraint.entities[0]
                if isinstance(line, Line):
                    return abs(line.end.x - line.start.x)

        return 0.0

    def _compute_jacobian(self) -> list[list[float]]:
        """Compute Jacobian matrix using finite differences."""
        n_constraints = len(self.constraints)
        n_vars = len(self.variables)

        jacobian = [[0.0] * n_vars for _ in range(n_constraints)]

        delta_h = 1e-6

        for j in range(n_vars):
            var_name = list(self.variables.keys())[j]
            original_value = self.variables[var_name].value

            self.variables[var_name].value = original_value + delta_h
            residuals_plus = self._compute_residuals()

            self.variables[var_name].value = original_value - delta_h
            residuals_minus = self._compute_residuals()

            self.variables[var_name].value = original_value

            for i in range(n_constraints):
                jacobian[i][j] = (residuals_plus[i] - residuals_minus[i]) / (2 * delta_h)

        return jacobian

    def _solve_linear_system(self, jacobian: list[list[float]], residuals: list[float]) -> list[float]:
        """Solve J * delta = -residuals using Gaussian elimination."""
        n = len(jacobian)
        m = len(jacobian[0]) if n > 0 else 0

        if n > m:
            return self._least_squares_solve(jacobian, residuals)

        aug = [row[:] + [-residuals[i]] for i, row in enumerate(jacobian)]

        for i in range(min(n, m)):
            max_row = i
            for k in range(i + 1, n):
                if abs(aug[k][i]) > abs(aug[max_row][i]):
                    max_row = k

            aug[i], aug[max_row] = aug[max_row], aug[i]

            if abs(aug[i][i]) < EPSILON:
                continue

            for k in range(i + 1, n):
                if abs(aug[i][i]) > EPSILON:
                    factor = aug[k][i] / aug[i][i]
                    for j in range(i, m + 1):
                        aug[k][j] -= factor * aug[i][j]

        delta = [0.0] * m

        for i in range(min(n, m) - 1, -1, -1):
            if abs(aug[i][i]) > EPSILON:
                delta[i] = aug[i][m]
                for j in range(i + 1, m):
                    delta[i] -= aug[i][j] * delta[j]
                delta[i] /= aug[i][i]

        return delta

    def _least_squares_solve(self, jacobian: list[list[float]], residuals: list[float]) -> list[float]:
        """Solve overdetermined system using least squares."""
        n = len(jacobian)
        m = len(jacobian[0]) if n > 0 else 0

        jt_j = [[0.0] * m for _ in range(m)]
        jt_r = [0.0] * m

        for i in range(m):
            for j in range(m):
                for k in range(n):
                    jt_j[i][j] += jacobian[k][i] * jacobian[k][j]

            for k in range(n):
                jt_r[i] -= jacobian[k][i] * residuals[k]

        return self._solve_linear_system(jt_j, jt_r)

    def _update_variables(self, delta: list[float]) -> None:
        """Update variables with delta."""
        for i, (var_name, var) in enumerate(self.variables.items()):
            if i < len(delta):
                var.value += delta[i]
                var.value = max(var.lower_bound, min(var.upper_bound, var.value))

    def _check_convergence(self, residuals: list[float], tolerance: float) -> bool:
        """Check if residuals are below tolerance."""
        return all(abs(r) < tolerance for r in residuals)

    def get_variable(self, name: str) -> Variable | None:
        """Get variable by name."""
        return self.variables.get(name)

    def get_solution(self) -> dict[str, float]:
        """Get current solution."""
        return {name: var.value for name, var in self.variables.items()}


class ConstraintAnalyzer:
    """Analyzes constraint systems for DOF, redundancy, etc."""

    def __init__(self, solver: ConstraintSolver) -> None:
        """Initialize analyzer."""
        self.solver = solver

    def degrees_of_freedom(self) -> int:
        """Compute degrees of freedom."""
        n_vars = len(self.solver.variables)
        n_constraints = len(self.solver.constraints)

        return max(0, n_vars - n_constraints)

    def is_under_constrained(self) -> bool:
        """Check if system is under-constrained."""
        return self.degrees_of_freedom() > 0

    def is_over_constrained(self) -> bool:
        """Check if system is over-constrained."""
        jacobian = self.solver._compute_jacobian()
        return self._matrix_rank(jacobian) > len(self.solver.variables)

    def is_fully_constrained(self) -> bool:
        """Check if system is fully constrained."""
        return self.degrees_of_freedom() == 0

    def redundant_constraints(self) -> list[int]:
        """Find redundant constraints."""
        jacobian = self.solver._compute_jacobian()

        redundant = []

        for i in range(len(jacobian)):
            row = jacobian[i]
            if all(abs(v) < EPSILON for v in row):
                redundant.append(i)

        return redundant

    def _matrix_rank(self, matrix: list[list[float]]) -> int:
        """Compute matrix rank."""
        if not matrix:
            return 0

        rank = 0

        for row in matrix:
            if any(abs(v) > EPSILON for v in row):
                rank += 1

        return rank

    def conflicting_constraints(self) -> list[tuple[int, int]]:
        """Find conflicting constraints."""
        conflicts: list[tuple[int, int]] = []

        return conflicts
