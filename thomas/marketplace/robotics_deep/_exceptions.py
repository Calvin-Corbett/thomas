"""
Exception classes for robotics module.
"""


class RoboticsError(Exception):
    """Base exception for all robotics errors."""

    pass


class KinematicsError(RoboticsError):
    """Exception for kinematics computation errors."""

    pass


class PlanningError(RoboticsError):
    """Exception for motion planning errors."""

    pass


class SLAMError(RoboticsError):
    """Exception for SLAM computation errors."""

    pass
