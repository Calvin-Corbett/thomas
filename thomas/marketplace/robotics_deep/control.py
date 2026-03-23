"""
Robot control: PID, trajectory tracking, computed torque, impedance, velocity control.
"""

from thomas.marketplace.robotics_deep._types import JointState, Vec3


class PIDController:
    """PID controller with anti-windup."""

    def __init__(self, kp: float, ki: float, kd: float, max_integral: float = 1.0, dt: float = 0.01) -> None:
        """
        Initialize PID controller.

        Args:
            kp: Proportional gain
            ki: Integral gain
            kd: Derivative gain
            max_integral: Anti-windup limit
            dt: Time step
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.max_integral = max_integral
        self.dt = dt

        self.integral = 0.0
        self.last_error = 0.0

    def compute(self, error: float) -> float:
        """
        Compute PID control signal.

        Args:
            error: Control error (setpoint - measurement)

        Returns:
            Control signal
        """
        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        self.integral += error * self.dt
        self.integral = max(-self.max_integral, min(self.max_integral, self.integral))
        i_term = self.ki * self.integral

        # Derivative term
        d_term = self.kd * (error - self.last_error) / self.dt
        self.last_error = error

        return p_term + i_term + d_term

    def reset(self) -> None:
        """Reset controller state."""
        self.integral = 0.0
        self.last_error = 0.0


class TrajectoryTracker:
    """Track joint-space trajectories with PID control."""

    def __init__(self, num_joints: int, kp: float = 10.0, kd: float = 1.0) -> None:
        """
        Initialize trajectory tracker.

        Args:
            num_joints: Number of robot joints
            kp: Proportional gain
            kd: Derivative gain
        """
        self.num_joints = num_joints
        self.pid_controllers = [PIDController(kp=kp, ki=0.1, kd=kd) for _ in range(num_joints)]

    def compute(self, current_state: list[JointState], desired_state: list[JointState]) -> list[float]:
        """
        Compute control torques to track desired trajectory.

        Args:
            current_state: Current joint states
            desired_state: Desired joint states

        Returns:
            Control torques
        """
        if len(current_state) != self.num_joints or len(desired_state) != self.num_joints:
            raise ValueError("Mismatch in number of joints")

        torques = []
        for i in range(self.num_joints):
            # Position error
            error = desired_state[i].position - current_state[i].position

            # Add feedforward from desired velocity
            control = self.pid_controllers[i].compute(error)
            control += desired_state[i].velocity

            torques.append(control)

        return torques


class ComputedTorqueController:
    """Model-based control with inverse dynamics."""

    def __init__(self, mass_matrix_fn, coriolis_fn, gravity_fn, kp: float = 10.0, kd: float = 1.0) -> None:
        """
        Initialize computed torque controller.

        Args:
            mass_matrix_fn: Function returning mass matrix M(q)
            coriolis_fn: Function returning coriolis vector C(q, qdot)
            gravity_fn: Function returning gravity vector g(q)
            kp: Position feedback gain
            kd: Velocity feedback gain
        """
        self.mass_matrix_fn = mass_matrix_fn
        self.coriolis_fn = coriolis_fn
        self.gravity_fn = gravity_fn
        self.kp = kp
        self.kd = kd

    def compute(
        self,
        q: list[float],
        qdot: list[float],
        q_desired: list[float],
        qdot_desired: list[float],
        qddot_desired: list[float],
    ) -> list[float]:
        """
        Compute control torques using inverse dynamics.

        Args:
            q: Current joint positions
            qdot: Current joint velocities
            q_desired: Desired joint positions
            qdot_desired: Desired joint velocities
            qddot_desired: Desired joint accelerations

        Returns:
            Control torques
        """
        n = len(q)

        # Position and velocity errors
        q_error = [q_desired[i] - q[i] for i in range(n)]
        qdot_error = [qdot_desired[i] - qdot[i] for i in range(n)]

        # Feedback part
        u_fb = [self.kp * q_error[i] + self.kd * qdot_error[i] for i in range(n)]

        # Feedforward part: inverse dynamics
        M = self.mass_matrix_fn(q)
        C = self.coriolis_fn(q, qdot)
        g = self.gravity_fn(q)

        # u_ff = M * qddot_desired + C + g
        u_ff = [0.0] * n
        for i in range(n):
            u_ff[i] = sum(M[i][j] * qddot_desired[j] for j in range(n))
            u_ff[i] += C[i] + g[i]

        # Total torque
        tau = [u_ff[i] + u_fb[i] for i in range(n)]
        return tau


class ImpedanceController:
    """Impedance control for compliant behavior."""

    def __init__(
        self,
        mass: float = 1.0,
        damping: float = 0.5,
        stiffness: float = 100.0,
    ) -> None:
        """
        Initialize impedance controller.

        Args:
            mass: Desired virtual mass
            damping: Desired damping coefficient
            stiffness: Desired stiffness
        """
        self.mass = mass
        self.damping = damping
        self.stiffness = stiffness

        self.velocity = Vec3(0, 0, 0)

    def compute(self, position_error: Vec3, external_force: Vec3) -> Vec3:
        """
        Compute force for impedance control.

        Args:
            position_error: Position error from desired
            external_force: Measured external force

        Returns:
            Desired force
        """
        # Second-order system: M*a + D*v + K*x = F_ext
        # Solve for desired acceleration
        # a = (F_ext - D*v - K*x) / M

        # Spring force (stiffness)
        spring_force = position_error * (-self.stiffness)

        # Update velocity (simple integration)
        accel = (external_force + spring_force) * (1.0 / self.mass)
        self.velocity = self.velocity + accel * 0.01

        # Damping force
        damping_force = self.velocity * (-self.damping)

        # Total desired force
        desired_force = spring_force + damping_force + external_force

        return desired_force


class VelocityController:
    """Task-space velocity control using Jacobian."""

    def __init__(self, jacobian_fn, num_joints: int) -> None:
        """
        Initialize velocity controller.

        Args:
            jacobian_fn: Function returning Jacobian matrix
            num_joints: Number of joints
        """
        self.jacobian_fn = jacobian_fn
        self.num_joints = num_joints

    def compute(self, desired_velocity: list[float], q: list[float]) -> list[float]:
        """
        Compute joint velocities from desired task-space velocity.

        Args:
            desired_velocity: Desired task-space velocity [vx, vy, vz, wx, wy, wz]
            q: Current joint positions

        Returns:
            Joint velocities
        """
        J = self.jacobian_fn(q)

        # Compute pseudoinverse of Jacobian
        J_pinv = self._pseudoinverse(J)

        # qdot = J^+ * v_desired
        qdot = [
            sum(J_pinv[i][j] * desired_velocity[j] for j in range(len(desired_velocity)))
            for i in range(self.num_joints)
        ]

        return qdot

    def _pseudoinverse(self, J: list[list[float]]) -> list[list[float]]:
        """Compute Moore-Penrose pseudoinverse."""
        m = len(J)
        n = len(J[0]) if J else 0

        # J^T
        JT = [[J[i][j] for i in range(m)] for j in range(n)]

        # J^T * J
        JTJ = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                JTJ[i][j] = sum(JT[i][k] * J[k][j] for k in range(m))

        # (J^T*J)^-1 with damping
        lambda_sq = 1e-4
        for i in range(n):
            JTJ[i][i] += lambda_sq

        # Invert
        inv = self._gauss_jordan(JTJ)

        # (J^T*J)^-1 * J^T
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
            max_row = i
            for k in range(i + 1, n):
                if abs(aug[k][i]) > abs(aug[max_row][i]):
                    max_row = k
            aug[i], aug[max_row] = aug[max_row], aug[i]

            if abs(aug[i][i]) < 1e-10:
                continue

            pivot = aug[i][i]
            for j in range(2 * n):
                aug[i][j] /= pivot

            for k in range(n):
                if k != i:
                    factor = aug[k][i]
                    for j in range(2 * n):
                        aug[k][j] -= factor * aug[i][j]

        inv = [[aug[i][j] for j in range(n, 2 * n)] for i in range(n)]
        return inv
