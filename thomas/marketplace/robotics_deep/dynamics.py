"""
Robot dynamics: Newton-Euler formulation, mass matrix, Coriolis, gravity, inverse/forward dynamics.
"""

import math
from collections.abc import Callable


class RobotDynamics:
    """General robot dynamics using Newton-Euler formulation."""

    def __init__(
        self,
        mass_matrix_fn: Callable[[list[float]], list[list[float]]],
        coriolis_fn: Callable[[list[float], list[float]], list[float]],
        gravity_fn: Callable[[list[float]], list[float]],
    ) -> None:
        """
        Initialize robot dynamics.

        Args:
            mass_matrix_fn: Function M(q) returning mass matrix
            coriolis_fn: Function C(q, qdot) returning Coriolis/centrifugal vector
            gravity_fn: Function g(q) returning gravity vector
        """
        self.mass_matrix_fn = mass_matrix_fn
        self.coriolis_fn = coriolis_fn
        self.gravity_fn = gravity_fn

    def forward_dynamics(self, q: list[float], qdot: list[float], tau: list[float]) -> list[float]:
        """
        Compute forward dynamics: given torques, compute acceleration.

        Args:
            q: Joint positions
            qdot: Joint velocities
            tau: Applied torques

        Returns:
            Joint accelerations (qddot)
        """
        n = len(q)
        M = self.mass_matrix_fn(q)
        C = self.coriolis_fn(q, qdot)
        g = self.gravity_fn(q)

        # M * qddot = tau - C - g
        # qddot = M^-1 * (tau - C - g)

        b = [tau[i] - C[i] - g[i] for i in range(n)]
        qddot = self._solve_linear(M, b)

        return qddot

    def inverse_dynamics(self, q: list[float], qdot: list[float], qddot: list[float]) -> list[float]:
        """
        Compute inverse dynamics: given motion, compute torques.

        Args:
            q: Joint positions
            qdot: Joint velocities
            qddot: Joint accelerations

        Returns:
            Required torques
        """
        n = len(q)
        M = self.mass_matrix_fn(q)
        C = self.coriolis_fn(q, qdot)
        g = self.gravity_fn(q)

        # tau = M * qddot + C + g
        tau = [0.0] * n
        for i in range(n):
            tau[i] = sum(M[i][j] * qddot[j] for j in range(n))
            tau[i] += C[i] + g[i]

        return tau

    def compute_kinetic_energy(self, qdot: list[float], q: list[float]) -> float:
        """
        Compute kinetic energy: 0.5 * qdot^T * M * qdot.

        Args:
            qdot: Joint velocities
            q: Joint positions

        Returns:
            Kinetic energy
        """
        M = self.mass_matrix_fn(q)
        n = len(qdot)

        energy = 0.0
        for i in range(n):
            for j in range(n):
                energy += 0.5 * qdot[i] * M[i][j] * qdot[j]

        return energy

    def compute_potential_energy(self, q: list[float], height_fn: Callable[[list[float]], float]) -> float:
        """
        Compute potential energy.

        Args:
            q: Joint positions
            height_fn: Function returning height of center of mass

        Returns:
            Potential energy
        """
        h = height_fn(q)
        g = 9.81
        # Approximate mass as sum of diagonal of mass matrix
        M = self.mass_matrix_fn(q)
        total_mass = sum(M[i][i] for i in range(len(M)))
        return total_mass * g * h

    def _solve_linear(self, A: list[list[float]], b: list[float]) -> list[float]:
        """Solve linear system Ax = b using Gaussian elimination."""
        n = len(A)
        aug = [A[i][:] + [b[i]] for i in range(n)]

        # Forward elimination
        for i in range(n):
            max_row = i
            for k in range(i + 1, n):
                if abs(aug[k][i]) > abs(aug[max_row][i]):
                    max_row = k
            aug[i], aug[max_row] = aug[max_row], aug[i]

            if abs(aug[i][i]) < 1e-10:
                continue

            for k in range(i + 1, n):
                factor = aug[k][i] / aug[i][i]
                for j in range(i, n + 1):
                    aug[k][j] -= factor * aug[i][j]

        # Back substitution
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            x[i] = aug[i][n]
            for j in range(i + 1, n):
                x[i] -= aug[i][j] * x[j]
            if abs(aug[i][i]) > 1e-10:
                x[i] /= aug[i][i]

        return x


class TwoDOFArmDynamics:
    """Explicit dynamics for 2-DOF planar arm."""

    def __init__(self, m1: float, m2: float, L1: float, L2: float) -> None:
        """
        Initialize 2-DOF arm dynamics.

        Args:
            m1: Mass of link 1
            m2: Mass of link 2
            L1: Length of link 1
            L2: Length of link 2
        """
        self.m1 = m1
        self.m2 = m2
        self.L1 = L1
        self.L2 = L2

    def mass_matrix(self, q: list[float]) -> list[list[float]]:
        """
        Compute mass matrix for 2-DOF arm.

        Args:
            q: Joint positions [q1, q2]

        Returns:
            2x2 mass matrix
        """
        _q1, q2 = q[0], q[1]
        c2 = math.cos(q2)
        math.sin(q2)

        m1 = self.m1
        m2 = self.m2
        L1 = self.L1
        L2 = self.L2

        # Moment of inertia contributions
        I1 = (m1 * L1**2) / 3  # Rod about center
        I2 = (m2 * L2**2) / 3

        M11 = I1 + I2 + m2 * L1**2 + 2 * m2 * L1 * L2 * c2
        M12 = I2 + m2 * L1 * L2 * c2
        M21 = I2 + m2 * L1 * L2 * c2
        M22 = I2

        return [[M11, M12], [M21, M22]]

    def coriolis_vector(self, q: list[float], qdot: list[float]) -> list[float]:
        """
        Compute Coriolis and centrifugal vector.

        Args:
            q: Joint positions
            qdot: Joint velocities

        Returns:
            Coriolis vector
        """
        _q1, q2 = q[0], q[1]
        q1dot, q2dot = qdot[0], qdot[1]

        s2 = math.sin(q2)

        m2 = self.m2
        L1 = self.L1
        L2 = self.L2

        C1 = -m2 * L1 * L2 * s2 * (2 * q1dot * q2dot + q2dot**2)
        C2 = m2 * L1 * L2 * s2 * q1dot**2

        return [C1, C2]

    def gravity_vector(self, q: list[float]) -> list[float]:
        """
        Compute gravity vector.

        Args:
            q: Joint positions

        Returns:
            Gravity vector
        """
        q1, q2 = q[0], q[1]
        c1 = math.cos(q1)
        c12 = math.cos(q1 + q2)

        g = 9.81
        m1 = self.m1
        m2 = self.m2
        L1 = self.L1
        L2 = self.L2

        # Gravity torques (about joint axes)
        tau1 = (m1 * L1 / 2 + m2 * L1) * g * c1 + (m2 * L2 / 2) * g * c12
        tau2 = (m2 * L2 / 2) * g * c12

        return [tau1, tau2]

    def forward_dynamics(self, q: list[float], qdot: list[float], tau: list[float]) -> list[float]:
        """
        Forward dynamics for 2-DOF arm.

        Args:
            q: Joint positions
            qdot: Joint velocities
            tau: Applied torques

        Returns:
            Joint accelerations
        """
        M = self.mass_matrix(q)
        C = self.coriolis_vector(q, qdot)
        g = self.gravity_vector(q)

        # M * qddot = tau - C - g
        b = [tau[i] - C[i] - g[i] for i in range(2)]

        # Solve 2x2 system
        det = M[0][0] * M[1][1] - M[0][1] * M[1][0]
        if abs(det) < 1e-10:
            return [0.0, 0.0]

        qddot = [
            (M[1][1] * b[0] - M[0][1] * b[1]) / det,
            (-M[1][0] * b[0] + M[0][0] * b[1]) / det,
        ]

        return qddot

    def inverse_dynamics(self, q: list[float], qdot: list[float], qddot: list[float]) -> list[float]:
        """
        Inverse dynamics for 2-DOF arm.

        Args:
            q: Joint positions
            qdot: Joint velocities
            qddot: Joint accelerations

        Returns:
            Required torques
        """
        M = self.mass_matrix(q)
        C = self.coriolis_vector(q, qdot)
        g = self.gravity_vector(q)

        # tau = M * qddot + C + g
        tau = [0.0] * 2
        for i in range(2):
            tau[i] = sum(M[i][j] * qddot[j] for j in range(2))
            tau[i] += C[i] + g[i]

        return tau
