"""
Forward and inverse kinematics for robot manipulators.
"""

import math

from thomas.robotics_deep._exceptions import KinematicsError
from thomas.robotics_deep._types import DHParams, JointType, Matrix4x4, Pose


class ForwardKinematics:
    """Compute forward kinematics using DH parameters."""

    def __init__(self, dh_params: list[DHParams], joint_types: list[JointType]) -> None:
        """
        Initialize forward kinematics solver.

        Args:
            dh_params: List of DH parameters for each link
            joint_types: Type of each joint (REVOLUTE or PRISMATIC)
        """
        if len(dh_params) != len(joint_types):
            raise KinematicsError("DH params and joint types must have same length")
        self.dh_params = dh_params
        self.joint_types = joint_types
        self.num_joints = len(dh_params)

    def dh_transform(self, dh: DHParams, joint_value: float, joint_type: JointType) -> Matrix4x4:
        """
        Compute 4x4 DH transformation matrix for a single joint.

        Args:
            dh: DH parameters
            joint_value: Joint angle (revolute) or displacement (prismatic)
            joint_type: Type of joint

        Returns:
            4x4 homogeneous transformation matrix
        """
        if joint_type == JointType.REVOLUTE:
            theta = joint_value + dh.theta
            d = dh.d
        elif joint_type == JointType.PRISMATIC:
            theta = dh.theta
            d = joint_value + dh.d
        else:
            theta = dh.theta
            d = dh.d

        a = dh.a
        alpha = dh.alpha

        # Build DH transformation matrix
        T = Matrix4x4.identity()
        c_theta = math.cos(theta)
        s_theta = math.sin(theta)
        c_alpha = math.cos(alpha)
        s_alpha = math.sin(alpha)

        T.data[0][0] = c_theta
        T.data[0][1] = -s_theta * c_alpha
        T.data[0][2] = s_theta * s_alpha
        T.data[0][3] = a * c_theta

        T.data[1][0] = s_theta
        T.data[1][1] = c_theta * c_alpha
        T.data[1][2] = -c_theta * s_alpha
        T.data[1][3] = a * s_theta

        T.data[2][0] = 0
        T.data[2][1] = s_alpha
        T.data[2][2] = c_alpha
        T.data[2][3] = d

        return T

    def compute(self, joint_positions: list[float]) -> Matrix4x4:
        """
        Compute end-effector transformation from joint angles.

        Args:
            joint_positions: Joint angles/displacements

        Returns:
            4x4 end-effector transformation matrix
        """
        if len(joint_positions) != self.num_joints:
            raise KinematicsError(f"Expected {self.num_joints} joint positions")

        T = Matrix4x4.identity()
        for i in range(self.num_joints):
            T = T.multiply(self.dh_transform(self.dh_params[i], joint_positions[i], self.joint_types[i]))
        return T

    def compute_chain(self, joint_positions: list[float]) -> list[Matrix4x4]:
        """
        Compute transformations for all frames in kinematic chain.

        Args:
            joint_positions: Joint angles/displacements

        Returns:
            List of transformation matrices from base to each joint
        """
        chain = [Matrix4x4.identity()]
        T = Matrix4x4.identity()

        for i in range(self.num_joints):
            T = T.multiply(self.dh_transform(self.dh_params[i], joint_positions[i], self.joint_types[i]))
            chain.append(T)

        return chain


class Jacobian:
    """Compute robot Jacobian matrix."""

    def __init__(self, fk: ForwardKinematics) -> None:
        """
        Initialize Jacobian calculator.

        Args:
            fk: ForwardKinematics solver
        """
        self.fk = fk

    def numerical(self, joint_positions: list[float], epsilon: float = 1e-6) -> list[list[float]]:
        """
        Compute numerical Jacobian using finite differences.

        Args:
            joint_positions: Current joint positions
            epsilon: Perturbation for finite differences

        Returns:
            6 x num_joints Jacobian matrix (rows: vx,vy,vz,wx,wy,wz)
        """
        num_joints = len(joint_positions)
        jacobian = [[0.0] * num_joints for _ in range(6)]

        # Get nominal end-effector pose
        T0 = self.fk.compute(joint_positions)
        p0 = T0.get_position()

        for j in range(num_joints):
            # Perturb joint j
            joint_plus = joint_positions[:]
            joint_plus[j] += epsilon

            # Compute perturbed pose
            T_plus = self.fk.compute(joint_plus)
            p_plus = T_plus.get_position()

            # Numerical derivative of position
            dp = (p_plus - p0) * (1.0 / epsilon)

            jacobian[0][j] = dp.x
            jacobian[1][j] = dp.y
            jacobian[2][j] = dp.z

            # Angular velocity approximation (rotation axis from differential)
            dR = T_plus.get_rotation().multiply(T0.get_rotation().transpose())
            theta = math.acos(min(1.0, max(-1.0, (dR.data[0][0] + dR.data[1][1] + dR.data[2][2] - 1) / 2)))

            if abs(theta) > 1e-6:
                omega_scale = theta / epsilon
                jacobian[3][j] = (dR.data[2][1] - dR.data[1][2]) * omega_scale / 2
                jacobian[4][j] = (dR.data[0][2] - dR.data[2][0]) * omega_scale / 2
                jacobian[5][j] = (dR.data[1][0] - dR.data[0][1]) * omega_scale / 2

        return jacobian

    def transpose(self, jacobian: list[list[float]]) -> list[list[float]]:
        """Compute matrix transpose."""
        if not jacobian:
            return []
        return [[jacobian[i][j] for i in range(len(jacobian))] for j in range(len(jacobian[0]))]

    def pseudoinverse(self, jacobian: list[list[float]]) -> list[list[float]]:
        """
        Compute Moore-Penrose pseudoinverse using least squares.

        Args:
            jacobian: m x n Jacobian matrix

        Returns:
            n x m pseudoinverse matrix
        """
        m = len(jacobian)
        n = len(jacobian[0]) if jacobian else 0

        # Compute J^T
        JT = self.transpose(jacobian)

        # Compute J^T * J
        JTJ = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                JTJ[i][j] = sum(JT[i][k] * jacobian[k][j] for k in range(m))

        # Add regularization (damping)
        lambda_sq = 1e-4
        for i in range(n):
            JTJ[i][i] += lambda_sq

        # Invert J^T*J using Gauss-Jordan
        inv = self._gauss_jordan(JTJ)

        # Compute (J^T*J)^-1 * J^T
        pinv = [[0.0] * m for _ in range(n)]
        for i in range(n):
            for j in range(m):
                pinv[i][j] = sum(inv[i][k] * JT[k][j] for k in range(n))

        return pinv

    def _gauss_jordan(self, matrix: list[list[float]]) -> list[list[float]]:
        """Gauss-Jordan elimination for matrix inversion."""
        n = len(matrix)
        aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]

        for i in range(n):
            # Find pivot
            max_row = i
            for k in range(i + 1, n):
                if abs(aug[k][i]) > abs(aug[max_row][i]):
                    max_row = k
            aug[i], aug[max_row] = aug[max_row], aug[i]

            if abs(aug[i][i]) < 1e-10:
                continue

            # Scale pivot row
            pivot = aug[i][i]
            for j in range(2 * n):
                aug[i][j] /= pivot

            # Eliminate column
            for k in range(n):
                if k != i:
                    factor = aug[k][i]
                    for j in range(2 * n):
                        aug[k][j] -= factor * aug[i][j]

        # Extract inverse
        inv = [[aug[i][j] for j in range(n, 2 * n)] for i in range(n)]
        return inv


class InverseKinematics:
    """Inverse kinematics solvers."""

    def __init__(self, fk: ForwardKinematics, max_iterations: int = 100) -> None:
        """
        Initialize IK solver.

        Args:
            fk: ForwardKinematics solver
            max_iterations: Maximum iterations for numerical IK
        """
        self.fk = fk
        self.max_iterations = max_iterations
        self.jacobian_calc = Jacobian(fk)

    def analytical_2dof_planar(self, target_x: float, target_y: float) -> tuple[float, float] | None:
        """
        Analytical inverse kinematics for 2-DOF planar arm.

        Args:
            target_x: Target x position
            target_y: Target y position

        Returns:
            Tuple of (theta1, theta2) or None if no solution
        """
        # Assumes: L1, L2 link lengths from DH params
        if self.fk.num_joints < 2:
            return None

        L1 = self.fk.dh_params[0].a if self.fk.dh_params[0].a > 0 else 1.0
        L2 = self.fk.dh_params[1].a if self.fk.dh_params[1].a > 0 else 1.0

        d = math.sqrt(target_x**2 + target_y**2)

        # Check workspace
        if d > L1 + L2 or d < abs(L1 - L2):
            return None

        # Law of cosines: theta2
        cos_theta2 = (d**2 - L1**2 - L2**2) / (2 * L1 * L2)
        cos_theta2 = max(-1.0, min(1.0, cos_theta2))
        theta2 = math.acos(cos_theta2)

        # theta1
        k1 = L1 + L2 * math.cos(theta2)
        k2 = L2 * math.sin(theta2)
        theta1 = math.atan2(target_y, target_x) - math.atan2(k2, k1)

        return theta1, theta2

    def numerical(
        self, target_pose: Pose, seed: list[float] | None = None, tolerance: float = 1e-4
    ) -> list[float] | None:
        """
        Numerical inverse kinematics using Jacobian pseudoinverse.

        Args:
            target_pose: Target end-effector pose
            seed: Initial joint configuration
            tolerance: Position error tolerance

        Returns:
            Joint configuration achieving target, or None if no solution found
        """
        if seed is None:
            q = [0.0] * self.fk.num_joints
        else:
            q = seed[:]

        target_T = target_pose.to_matrix()
        target_p = target_T.get_position()

        for iteration in range(self.max_iterations):
            # Compute current pose
            T = self.fk.compute(q)
            p = T.get_position()

            # Position error
            dp = target_p - p
            error = dp.magnitude()

            if error < tolerance:
                return q

            # Compute Jacobian
            J = self.jacobian_calc.numerical(q)

            # Compute pseudoinverse
            J_pinv = self.jacobian_calc.pseudoinverse(J)

            # Desired velocity: proportional to error
            Kp = 0.5
            vel = [Kp * dp.x, Kp * dp.y, Kp * dp.z, 0, 0, 0]

            # Compute joint velocity
            dq = [sum(J_pinv[i][j] * vel[j] for j in range(6)) for i in range(self.fk.num_joints)]

            # Update joint positions
            step_size = 0.1
            for i in range(self.fk.num_joints):
                q[i] += step_size * dq[i]

        return None


class WorkspaceBoundary:
    """Estimate robot workspace boundary."""

    def __init__(self, fk: ForwardKinematics) -> None:
        """
        Initialize workspace analyzer.

        Args:
            fk: ForwardKinematics solver
        """
        self.fk = fk

    def estimate_reachable_sphere(self, num_samples: int = 1000) -> tuple[float, float]:
        """
        Estimate maximum and minimum reachable distances from base.

        Args:
            num_samples: Number of random configurations to sample

        Returns:
            Tuple of (min_reach, max_reach)
        """
        import random

        min_reach = float("inf")
        max_reach = 0.0

        for _ in range(num_samples):
            # Random configuration
            q = [random.uniform(-math.pi, math.pi) for _ in range(self.fk.num_joints)]

            # Compute end-effector position
            T = self.fk.compute(q)
            p = T.get_position()
            dist = p.magnitude()

            min_reach = min(min_reach, dist)
            max_reach = max(max_reach, dist)

        return min_reach, max_reach

    def compute_dexterity(self, joint_positions: list[float]) -> float:
        """
        Compute dexterity measure at configuration (determinant of J*J^T).

        Args:
            joint_positions: Current joint configuration

        Returns:
            Dexterity measure (higher = more dexterous)
        """
        jac = Jacobian(self.fk)
        J = jac.numerical(joint_positions)

        # Compute J * J^T
        JJT = [[0.0] * 6 for _ in range(6)]
        for i in range(6):
            for j in range(6):
                JJT[i][j] = sum(J[i][k] * J[j][k] for k in range(len(joint_positions)))

        # Compute determinant (simplified for 6x6)
        det = self._determinant_6x6(JJT)
        return abs(det) ** (1 / 6)  # Sixth root for normalization

    def _determinant_6x6(self, matrix: list[list[float]]) -> float:
        """Compute 6x6 determinant using Laplace expansion."""
        # Simplified: use LU decomposition estimate
        det = 1.0
        a = [row[:] for row in matrix]

        for i in range(6):
            # Find pivot
            max_row = i
            for k in range(i + 1, 6):
                if abs(a[k][i]) > abs(a[max_row][i]):
                    max_row = k

            if abs(a[max_row][i]) < 1e-10:
                return 0.0

            if max_row != i:
                a[i], a[max_row] = a[max_row], a[i]
                det *= -1

            det *= a[i][i]

            for k in range(i + 1, 6):
                factor = a[k][i] / a[i][i]
                for j in range(i, 6):
                    a[k][j] -= factor * a[i][j]

        return det
