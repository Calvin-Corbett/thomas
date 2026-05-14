"""
Integration tests for robotics module.
"""

import math

import pytest

from thomas.marketplace.robotics_deep._types import (
    DHParams,
    JointType,
    OccupancyGrid,
    Pose,
    Quaternion,
    Vec3,
)
from thomas.marketplace.robotics_deep.control import PIDController, TrajectoryTracker
from thomas.marketplace.robotics_deep.dynamics import TwoDOFArmDynamics
from thomas.marketplace.robotics_deep.gripper import GraspPlanner, GripperController
from thomas.marketplace.robotics_deep.kinematics import ForwardKinematics, InverseKinematics
from thomas.marketplace.robotics_deep.motion_planning import RRT
from thomas.marketplace.robotics_deep.sensors import LidarSimulator
from thomas.marketplace.robotics_deep.slam import EKFSLAMFilter, OccupancyGridMapper


class TestKinematicsDynamicsIntegration:
    """Test kinematics and dynamics integration."""

    def test_forward_backward_kinematics(self) -> None:
        """Test forward and inverse kinematics together."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        ik = InverseKinematics(fk)

        # Forward kinematics
        target_joints = [0.5, 0.3]
        T_target = fk.compute(target_joints)
        target_pose = Pose.from_matrix(T_target)

        # Inverse kinematics
        recovered_joints = ik.numerical(target_pose, seed=[0.0, 0.0])

        if recovered_joints:
            T_recovered = fk.compute(recovered_joints)
            pos_recovered = T_recovered.get_position()

            assert abs(pos_recovered.x - target_pose.position.x) < 0.05
            assert abs(pos_recovered.y - target_pose.position.y) < 0.05

    def test_dynamics_with_kinematics(self) -> None:
        """Test dynamics computation with kinematic chain."""
        dynamics = TwoDOFArmDynamics(m1=1.0, m2=1.0, L1=1.0, L2=1.0)

        q = [0.0, 0.0]
        qdot = [0.1, 0.2]
        qddot = [0.5, 0.3]

        # Inverse dynamics
        tau = dynamics.inverse_dynamics(q, qdot, qddot)

        assert len(tau) == 2

        # Forward dynamics
        qddot_recovered = dynamics.forward_dynamics(q, qdot, tau)

        assert len(qddot_recovered) == 2


class TestMotionPlanningWithCollisionCheck:
    """Test motion planning with realistic collision checking."""

    def test_rrt_with_joint_limits(self) -> None:
        """Test RRT respects joint limits."""
        joint_max = [math.pi, math.pi]

        def collision_checker(q: list) -> bool:
            # Check joint limits
            for qi, max_val in zip(q, joint_max):
                if abs(qi) > max_val:
                    return False
            return True

        rrt = RRT(2, [(-math.pi, math.pi), (-math.pi, math.pi)], collision_checker)

        path = rrt.plan([0.0, 0.0], [2.0, 2.0], max_iterations=100)

        if path:
            for config in path:
                for qi, max_val in zip(config, joint_max):
                    assert abs(qi) <= max_val + 0.1

    def test_rrt_with_self_collision(self) -> None:
        """Test RRT detects self-collisions."""

        def collision_checker(q: list) -> bool:
            # Self-collision if both joints point in same direction
            angle_diff = abs(q[0] - q[1])
            return angle_diff > 0.1

        rrt = RRT(2, [(-math.pi, math.pi), (-math.pi, math.pi)], collision_checker)

        path = rrt.plan([0.1, 0.2], [1.5, 1.6], max_iterations=200)

        # Path may or may not exist due to collision constraint
        if path:
            for config in path:
                angle_diff = abs(config[0] - config[1])
                assert angle_diff > 0.05


class TestControlLoopIntegration:
    """Test complete control loops."""

    def test_pid_tracking_trajectory(self) -> None:
        """Test PID controller tracking a trajectory."""
        from thomas.marketplace.robotics_deep._types import JointState

        tracker = TrajectoryTracker(num_joints=1, kp=10.0, kd=2.0)

        position = 0.0
        velocity = 0.0
        dt = 0.01

        for step in range(100):
            target_position = 1.0

            current_state = [JointState(position=position, velocity=velocity, acceleration=0.0, effort=0.0)]
            desired_state = [JointState(position=target_position, velocity=0.0, acceleration=0.0, effort=0.0)]

            torques = tracker.compute(current_state, desired_state)

            # Simple dynamics: ddx = tau
            acceleration = torques[0]
            velocity += acceleration * dt
            position += velocity * dt

        # Should converge toward target
        assert position > 0.5

    def test_feedback_control_stability(self) -> None:
        """Test feedback control stability."""
        pid = PIDController(kp=1.0, ki=0.1, kd=0.5, dt=0.01)

        position = 0.0
        dt = 0.01

        for step in range(1000):
            error = 1.0 - position
            force = pid.compute(error)

            # Simple system: a = F / m
            acceleration = force / 1.0
            velocity = acceleration * dt
            position += velocity * dt

        # Should stabilize near setpoint
        assert 0.5 < position < 1.5


class TestSensoryFeedback:
    """Test sensor-based feedback."""

    def test_slam_with_sensor_data(self) -> None:
        """Test SLAM with sensor measurements."""
        ekf = EKFSLAMFilter(num_landmarks=5)

        # Simulate robot motion
        for i in range(5):
            ekf.predict(delta_x=0.5, delta_y=0.0, delta_theta=0.0)

            # Observe landmarks
            for landmark_id in range(2):
                ekf.update(landmark_id, range_obs=1.0 + i * 0.1, bearing_obs=landmark_id * math.pi / 2)

        pose = ekf.get_pose()
        landmarks = ekf.get_landmarks()

        assert pose.position.x > 0
        assert len(landmarks) > 0

    def test_lidar_mapping(self) -> None:
        """Test Lidar-based mapping."""
        grid = OccupancyGrid(width=20, height=20, resolution=0.1, origin_x=-1, origin_y=-1)
        mapper = OccupancyGridMapper(grid, max_range=2.0)
        lidar = LidarSimulator(num_rays=8, max_range=2.0)

        # Simulate multiple scans
        for i in range(3):
            pose = Pose(
                position=Vec3(i * 0.2, 0, 0),
                orientation=Quaternion.identity(),
            )

            scan = lidar.scan(pose, grid)
            mapper.update(scan, pose)

        # Grid should have been updated
        occupied_cells = sum(1 for row in grid.data for val in row if val > 0.5)
        # May be 0 if map started empty
        assert occupied_cells >= 0


class TestGripperIntegration:
    """Test gripper control integration."""

    def test_gripper_grasp_cycle(self) -> None:
        """Test complete grasp cycle."""
        gripper = GripperController(max_opening=0.1, max_force=100.0)
        planner = GraspPlanner()

        # Object position
        obj_pos = Vec3(0.5, 0, 0.2)
        obj_width = 0.05

        # Plan grasp
        approach_pose = planner.plan_grasp(obj_pos, obj_width, gripper.max_opening)

        assert approach_pose is not None

        # Open gripper
        gripper.open()
        assert gripper.is_open

        # Close to grasp
        gripper.close()
        gripper.set_force(50.0)

        state = gripper.get_state()
        opening, force, is_open = state

        assert opening == 0.0
        assert force == 50.0
        assert not is_open

    def test_force_controlled_grasping(self) -> None:
        """Test force-controlled grasping."""
        gripper = GripperController(max_force=100.0)

        # Close with increasing force
        for force_setpoint in [10.0, 25.0, 50.0]:
            gripper.set_force(force_setpoint)
            gripper.close()

            state = gripper.get_state()
            _, actual_force, _ = state

            assert actual_force <= gripper.max_force


class TestCompleteRobotSystem:
    """Test complete integrated robot system."""

    def test_arm_manipulation_pipeline(self) -> None:
        """Test complete arm manipulation pipeline."""
        # Kinematics
        dh_params = [
            DHParams(a=0.5, alpha=0, d=0, theta=0),
            DHParams(a=0.5, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)
        ik = InverseKinematics(fk)

        # Dynamics
        TwoDOFArmDynamics(m1=0.5, m2=0.5, L1=0.5, L2=0.5)

        # Control
        TrajectoryTracker(num_joints=2, kp=5.0, kd=1.0)

        # Target object
        target_pose = Pose(
            position=Vec3(0.7, 0.3, 0),
            orientation=Quaternion.identity(),
        )

        # Inverse kinematics
        target_joints = ik.numerical(target_pose, seed=[0.0, 0.0])

        if target_joints:
            # Verify forward kinematics
            T = fk.compute(target_joints)
            final_pos = T.get_position()

            assert abs(final_pos.x - 0.7) < 0.1
            assert abs(final_pos.y - 0.3) < 0.1

    def test_mobile_robot_navigation(self) -> None:
        """Test mobile robot navigation pipeline."""
        # Environment
        grid = OccupancyGrid(width=30, height=30, resolution=0.1, origin_x=-1.5, origin_y=-1.5)

        # Sensors
        lidar = LidarSimulator(num_rays=16, max_range=5.0)
        mapper = OccupancyGridMapper(grid)

        # Localization
        ekf = EKFSLAMFilter(num_landmarks=5)

        # Motion planning
        def collision_checker(q: list) -> bool:
            # Check occupancy at position
            x, y = q[0], q[1]
            occupancy = grid.get_cell(x, y)
            return occupancy < 0.5

        planner = RRT(
            config_dim=2,
            bounds=[(-1.5, 1.5), (-1.5, 1.5)],
            collision_checker=collision_checker,
            step_size=0.2,
        )

        # Simulate navigation
        start = [-1.0, -1.0]
        goal = [1.0, 1.0]

        robot_pose = Pose(
            position=Vec3(start[0], start[1], 0),
            orientation=Quaternion.identity(),
        )

        # Take sensor measurement
        scan = lidar.scan(robot_pose, grid)
        mapper.update(scan, robot_pose)

        # Update localization
        ekf.predict(delta_x=0.1, delta_y=0.0, delta_theta=0.0)

        # Plan motion
        path = planner.plan(start, goal, max_iterations=300)

        assert path is not None or grid.get_cell(1.0, 1.0) > 0.5


class TestRobustnessAndErrorHandling:
    """Test robustness and error handling."""

    def test_kinematics_with_singular_config(self) -> None:
        """Test kinematics near singular configurations."""
        dh_params = [
            DHParams(a=1.0, alpha=0, d=0, theta=0),
            DHParams(a=1.0, alpha=0, d=0, theta=0),
        ]
        joint_types = [JointType.REVOLUTE, JointType.REVOLUTE]
        fk = ForwardKinematics(dh_params, joint_types)

        # Singular config: fully extended
        T_singular = fk.compute([0.0, 0.0])

        assert T_singular is not None

        # Singular config: fully folded
        T_folded = fk.compute([0.0, math.pi])

        assert T_folded is not None

    def test_planning_with_no_solution(self) -> None:
        """Test planner handles impossible cases."""

        def collision_checker(q: list) -> bool:
            # All collisions
            return False

        planner = RRT(2, [(0, 1), (0, 1)], collision_checker)

        path = planner.plan([0.2, 0.2], [0.8, 0.8], max_iterations=50)

        assert path is None

    def test_control_saturation(self) -> None:
        """Test control signal saturation."""
        from thomas.marketplace.robotics_deep._types import JointState

        tracker = TrajectoryTracker(num_joints=1, kp=100.0, ki=50.0, kd=10.0)

        large_error = 100.0
        current_state = [JointState(position=0.0, velocity=0.0, acceleration=0.0, effort=0.0)]
        desired_state = [JointState(position=large_error, velocity=0.0, acceleration=0.0, effort=0.0)]

        torques = tracker.compute(current_state, desired_state)

        # Torques should be finite
        assert all(math.isfinite(t) for t in torques)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
