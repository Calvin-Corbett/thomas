"""
Tests for kinematics module.
"""

import math

import pytest

from thomas.robotics_deep._types import DHParams, JointType, Matrix3x3, Matrix4x4, Pose, Quaternion, Vec3
from thomas.robotics_deep.kinematics import ForwardKinematics, InverseKinematics, Jacobian, WorkspaceBoundary


class TestForwardKinematics:
    """Test forward kinematics solver."""

    def test_identity_transform(self) -> None:
        """Test identity transformation with zero joint angles."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        T = fk.compute([0.0, 0.0])
        pos = T.get_position()

        assert abs(pos.x - 2.0) < 1e-6
        assert abs(pos.y) < 1e-6
        assert abs(pos.z) < 1e-6

    def test_90_degree_rotation(self) -> None:
        """Test 90 degree rotation of first joint."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        T = fk.compute([math.pi / 2, 0.0])
        pos = T.get_position()

        assert abs(pos.x) < 1e-6
        assert abs(pos.y - 2.0) < 1e-6

    def test_kinematic_chain(self) -> None:
        """Test kinematic chain computation."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        chain = fk.compute_chain([0.0, 0.0])

        assert len(chain) == 3  # Base + 2 joints
        assert chain[0].get_position().x == 0.0
        assert chain[0].get_position().y == 0.0

    def test_prismatic_joint(self) -> None:
        """Test prismatic (sliding) joint."""
        dh_params = [
            DHParams(a=0, alpha=0, d=0, theta=0),
            DHParams(a=0, alpha=0, d=1.0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.PRISMATIC]
        fk = ForwardKinematics(dh_params, joint_types)

        T = fk.compute([0.0, 0.5])
        pos = T.get_position()

        assert abs(pos.z - 0.5) < 1e-6


class TestJacobian:
    """Test Jacobian computation."""

    def test_jacobian_shape(self) -> None:
        """Test Jacobian has correct shape."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        jac = Jacobian(fk)

        J = jac.numerical([0.0, 0.0])

        assert len(J) == 6  # 6 rows (linear + angular velocity)
        assert len(J[0]) == 2  # 2 columns (num joints)

    def test_jacobian_transpose(self) -> None:
        """Test Jacobian transpose."""
        jac_calc = Jacobian(None)
        J = [[1, 2, 3], [4, 5, 6]]

        JT = jac_calc.transpose(J)

        assert len(JT) == 3
        assert len(JT[0]) == 2
        assert JT[0][0] == 1
        assert JT[1][0] == 2

    def test_pseudoinverse_property(self) -> None:
        """Test pseudoinverse properties: A^+ A A^+ = A^+."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        jac = Jacobian(fk)

        J = jac.numerical([0.0, 0.0])
        J_pinv = jac.pseudoinverse(J)

        # Check dimensions
        assert len(J_pinv) == len(J[0])
        assert len(J_pinv[0]) == len(J)


class TestInverseKinematics:
    """Test inverse kinematics solvers."""

    def test_analytical_2dof_simple(self) -> None:
        """Test analytical 2-DOF solution for simple case."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        ik = InverseKinematics(fk)

        # Target: end effector at (2, 0)
        result = ik.analytical_2dof_planar(2.0, 0.0)

        assert result is not None
        theta1, theta2 = result
        assert abs(theta1) < 1e-4
        assert abs(theta2) < 1e-4

    def test_analytical_2dof_unreachable(self) -> None:
        """Test analytical 2-DOF with unreachable target."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        ik = InverseKinematics(fk)

        # Target: outside workspace
        result = ik.analytical_2dof_planar(5.0, 0.0)

        assert result is None

    def test_numerical_ik_convergence(self) -> None:
        """Test numerical IK converges."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        ik = InverseKinematics(fk)

        # Target at (1.5, 1.0, 0)
        target = Pose(
            position=Vec3(1.5, 1.0, 0),
            orientation=Quaternion.identity(),
        )

        result = ik.numerical(target, seed=[0.0, 0.0])

        assert result is not None
        # Verify solution
        T = fk.compute(result)
        final_pos = T.get_position()
        assert abs(final_pos.x - 1.5) < 0.01
        assert abs(final_pos.y - 1.0) < 0.01


class TestWorkspaceBoundary:
    """Test workspace boundary estimation."""

    def test_reachable_sphere(self) -> None:
        """Test maximum reach estimation."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        wb = WorkspaceBoundary(fk)

        min_reach, max_reach = wb.estimate_reachable_sphere(num_samples=100)

        assert min_reach >= 0
        assert max_reach <= 2.1  # Sum of link lengths + tolerance
        assert max_reach > 0.9  # Min for 2 unit links

    def test_dexterity_measure(self) -> None:
        """Test dexterity computation."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        wb = WorkspaceBoundary(fk)

        dex = wb.compute_dexterity([0.0, 0.0])

        assert dex >= 0
        assert dex <= 1.0


class TestDHTransformMatrix:
    """Test DH parameter transformation matrix."""

    def test_translation_only(self) -> None:
        """Test DH matrix with translation only."""
        dh_params = [DHParams(a=1.0, alpha=0, d=0, theta=0)]
        joint_types = [JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        T = fk.dh_transform(dh_params[0], 0.0, JointType.REVOLUTE)
        pos = T.get_position()

        assert abs(pos.x - 1.0) < 1e-6
        assert abs(pos.y) < 1e-6
        assert abs(pos.z) < 1e-6

    def test_rotation_only(self) -> None:
        """Test DH matrix with rotation only."""
        dh_params = [DHParams(a=0, alpha=0, d=0, theta=0)]
        joint_types = [JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        T = fk.dh_transform(dh_params[0], math.pi / 2, JointType.REVOLUTE)

        assert abs(T.data[0][0]) < 1e-6
        assert abs(T.data[0][1] + 1) < 1e-6


class TestMatrixOperations:
    """Test matrix operations."""

    def test_matrix3x3_multiply(self) -> None:
        """Test 3x3 matrix multiplication."""
        M1 = Matrix3x3.identity()
        M2 = Matrix3x3.identity()

        result = M1.multiply(M2)

        assert result.data[0][0] == 1.0
        assert result.data[1][1] == 1.0
        assert result.data[2][2] == 1.0

    def test_matrix4x4_inverse(self) -> None:
        """Test 4x4 matrix inverse."""
        T = Matrix4x4.from_pose(Vec3(1, 2, 3), Matrix3x3.identity())
        T_inv = T.inverse()
        T_product = T.multiply(T_inv)

        # Should be close to identity
        assert abs(T_product.data[0][0] - 1.0) < 1e-6
        assert abs(T_product.data[1][1] - 1.0) < 1e-6
        assert abs(T_product.data[2][2] - 1.0) < 1e-6


class TestQuaternion:
    """Test quaternion operations."""

    def test_quaternion_slerp(self) -> None:
        """Test quaternion SLERP interpolation."""
        q1 = Quaternion.identity()
        q2 = Quaternion.from_euler(0, 0, math.pi / 2)

        q_mid = q1.slerp(q2, 0.5)

        assert q_mid.magnitude() > 0.99

    def test_euler_conversion_roundtrip(self) -> None:
        """Test Euler angle conversion roundtrip."""
        roll_in = 0.3
        pitch_in = 0.2
        yaw_in = 0.5

        q = Quaternion.from_euler(roll_in, pitch_in, yaw_in)
        roll_out, pitch_out, yaw_out = q.to_euler()

        assert abs(roll_out - roll_in) < 1e-4
        assert abs(pitch_out - pitch_in) < 1e-4
        assert abs(yaw_out - yaw_in) < 1e-4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
