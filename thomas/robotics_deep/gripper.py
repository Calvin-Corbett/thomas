"""
Gripper control: grasp planning, force control, object detection, grasp quality.
"""

import math

from thomas.robotics_deep._types import Pose, Vec3


class GripperController:
    """Control parallel jaw gripper."""

    def __init__(
        self,
        max_opening: float = 0.1,
        max_force: float = 100.0,
        max_velocity: float = 0.1,
    ) -> None:
        """
        Initialize gripper controller.

        Args:
            max_opening: Maximum gripper opening distance
            max_force: Maximum gripper force
            max_velocity: Maximum jaw velocity
        """
        self.max_opening = max_opening
        self.max_force = max_force
        self.max_velocity = max_velocity

        self.current_opening = max_opening  # Start open
        self.current_force = 0.0
        self.is_open = True

    def open(self, amount: float | None = None) -> None:
        """
        Open gripper.

        Args:
            amount: Opening distance (None = fully open)
        """
        if amount is None:
            self.current_opening = self.max_opening
        else:
            self.current_opening = min(self.max_opening, max(0, amount))
        self.current_force = 0.0
        self.is_open = True

    def close(self) -> None:
        """Close gripper."""
        self.current_opening = 0.0
        self.is_open = False

    def set_opening(self, opening: float) -> None:
        """
        Set gripper opening distance.

        Args:
            opening: Opening distance [0, max_opening]
        """
        self.current_opening = max(0.0, min(self.max_opening, opening))

    def set_force(self, force: float) -> None:
        """
        Set gripper closing force.

        Args:
            force: Closing force [0, max_force]
        """
        self.current_force = max(0.0, min(self.max_force, force))

    def get_state(self) -> tuple[float, float, bool]:
        """
        Get gripper state.

        Returns:
            Tuple of (opening, force, is_open)
        """
        return self.current_opening, self.current_force, self.is_open

    def is_grasping(self, force_threshold: float = 10.0) -> bool:
        """
        Check if gripper is grasping (closed and applying force).

        Args:
            force_threshold: Minimum force to consider grasping

        Returns:
            True if grasping
        """
        return self.current_opening < 0.01 and self.current_force > force_threshold


class GraspPlanner:
    """Plan grasps for objects."""

    def __init__(self) -> None:
        """Initialize grasp planner."""
        pass

    def plan_grasp(
        self,
        object_position: Vec3,
        object_width: float,
        gripper_max_opening: float,
    ) -> Pose | None:
        """
        Plan grasp approach for object.

        Args:
            object_position: Object center position
            object_width: Object width
            gripper_max_opening: Maximum gripper opening

        Returns:
            Grasp approach pose, or None if unreachable
        """
        if object_width > gripper_max_opening:
            return None

        # Approach from above
        approach_distance = 0.1
        approach_pose = Pose(
            position=Vec3(
                object_position.x,
                object_position.y,
                object_position.z + approach_distance,
            ),
            orientation=object_position.orientation if hasattr(object_position, "orientation") else None,
        )

        return approach_pose

    def plan_two_finger_grasp(self, object_position: Vec3, object_radius: float) -> tuple[Vec3, Vec3, float]:
        """
        Plan two-finger grasp using contact points.

        Args:
            object_position: Object center
            object_radius: Object radius

        Returns:
            Tuple of (finger1_contact, finger2_contact, grasp_width)
        """
        # Symmetric grasp from opposite sides
        finger1 = Vec3(
            object_position.x + object_radius,
            object_position.y,
            object_position.z,
        )
        finger2 = Vec3(
            object_position.x - object_radius,
            object_position.y,
            object_position.z,
        )
        grasp_width = 2 * object_radius

        return finger1, finger2, grasp_width

    def plan_force_closure_grasp(
        self,
        object_position: Vec3,
        friction_coefficient: float = 0.5,
        num_fingers: int = 2,
    ) -> list[Vec3] | None:
        """
        Plan grasp achieving force closure.

        Args:
            object_position: Object center
            friction_coefficient: Friction coefficient
            num_fingers: Number of fingers

        Returns:
            List of contact points for force closure, or None if impossible
        """
        if num_fingers < 2:
            return None

        # For 2-finger grasp, compute contact points for force closure
        contact_points = []
        angle_between = 2 * math.pi / num_fingers

        object_radius = 0.05  # Assume small object
        min_contact_angle = math.atan(friction_coefficient)

        for i in range(num_fingers):
            angle = i * angle_between
            contact_x = object_position.x + object_radius * math.cos(angle)
            contact_y = object_position.y + object_radius * math.sin(angle)
            contact_z = object_position.z

            contact_points.append(Vec3(contact_x, contact_y, contact_z))

        return contact_points


class GraspQuality:
    """Compute grasp quality metrics."""

    @staticmethod
    def ferrari_canny_metric(
        contact_points: list[Vec3],
        friction_coefficient: float = 0.5,
        wrench_norm: float = 1.0,
    ) -> float:
        """
        Compute Ferrari-Canny quality metric (grasp isotropy).

        Args:
            contact_points: List of contact points on object
            friction_coefficient: Friction coefficient
            wrench_norm: Normalization factor

        Returns:
            Quality metric [0, 1]
        """
        if len(contact_points) < 3:
            return 0.0

        # Simplified FC metric: measure isotropy of contact directions
        num_contacts = len(contact_points)

        # Compute average outward normal
        avg_normal = Vec3(0, 0, 0)
        for point in contact_points:
            normal = point.normalize()
            avg_normal = avg_normal + normal

        avg_normal = avg_normal.normalize()

        # Measure variation from average
        variation = 0.0
        for point in contact_points:
            normal = point.normalize()
            angle = abs(normal.x * avg_normal.x + normal.y * avg_normal.y + normal.z * avg_normal.z)
            variation += (1.0 - angle) ** 2

        isotropy = 1.0 - (variation / num_contacts)
        return max(0.0, min(1.0, isotropy))

    @staticmethod
    def wrench_space_metric(
        contact_points: list[Vec3],
        object_center: Vec3,
        friction_coefficient: float = 0.5,
    ) -> float:
        """
        Compute wrench space volume metric.

        Args:
            contact_points: List of contact points
            object_center: Object center position
            friction_coefficient: Friction coefficient

        Returns:
            Normalized wrench metric
        """
        if len(contact_points) < 2:
            return 0.0

        # Compute wrench cone volume approximation
        contact_vectors = [p - object_center for p in contact_points]

        total_moment = 0.0
        for vec in contact_vectors:
            moment = vec.magnitude()
            total_moment += moment

        avg_moment = total_moment / len(contact_vectors) if contact_vectors else 0.0

        # Metric based on average moment arm
        metric = min(1.0, avg_moment / 0.1)
        return metric

    @staticmethod
    def grasp_stability(
        contact_points: list[Vec3],
        object_center: Vec3,
        normal_forces: list[float],
        tangential_forces: list[float],
    ) -> float:
        """
        Compute grasp stability.

        Args:
            contact_points: List of contact points
            object_center: Object center
            normal_forces: Normal forces at contacts
            tangential_forces: Tangential forces at contacts

        Returns:
            Stability measure [0, 1]
        """
        if not normal_forces:
            return 0.0

        # Check if all forces are positive (pushing inward)
        total_normal = sum(normal_forces)
        if total_normal < 1e-6:
            return 0.0

        # Stability increases with normal force and decreases with tangential
        total_tangential = sum(tangential_forces)
        ratio = total_normal / (total_normal + total_tangential + 1e-6)

        return min(1.0, ratio)

    @staticmethod
    def grasp_force_closure(
        contact_points: list[Vec3],
        object_center: Vec3,
        friction_coefficient: float = 0.5,
    ) -> bool:
        """
        Check if grasp achieves force closure.

        Args:
            contact_points: List of contact points
            object_center: Object center
            friction_coefficient: Friction coefficient

        Returns:
            True if force closure is achieved
        """
        if len(contact_points) < 4:
            return len(contact_points) == 2 and friction_coefficient > 0.3

        # For 4+ contact points, check if they span the object
        min_x = min(p.x for p in contact_points)
        max_x = max(p.x for p in contact_points)
        min_y = min(p.y for p in contact_points)
        max_y = max(p.y for p in contact_points)

        span_x = max_x - min_x
        span_y = max_y - min_y

        # Check if contacts surround object
        object_radius = 0.05
        return span_x > 2 * object_radius * 0.8 and span_y > 2 * object_radius * 0.8
