"""
thomasrobotics_deep: A comprehensive robotics module.

Provides kinematics, motion planning, SLAM, control, dynamics, and sensor simulation
for robotic systems.
"""

from thomas.robotics_deep._exceptions import (
    KinematicsError,
    PlanningError,
    RoboticsError,
    SLAMError,
)
from thomas.robotics_deep._types import (
    DHParams,
    JointState,
    JointType,
    LaserScan,
    Matrix3x3,
    Matrix4x4,
    OccupancyGrid,
    Pose,
    Quaternion,
    SensorReading,
    Trajectory,
    Vec3,
)
from thomas.robotics_deep.control import (
    ComputedTorqueController,
    ImpedanceController,
    PIDController,
    TrajectoryTracker,
    VelocityController,
)
from thomas.robotics_deep.dynamics import (
    RobotDynamics,
    TwoDOFArmDynamics,
)
from thomas.robotics_deep.gripper import (
    GraspPlanner,
    GraspQuality,
    GripperController,
)
from thomas.robotics_deep.kinematics import (
    ForwardKinematics,
    InverseKinematics,
    Jacobian,
    WorkspaceBoundary,
)
from thomas.robotics_deep.localization import (
    ExtendedKalmanFilterLocalizer,
    ICPScanMatcher,
    OdometryFilter,
)
from thomas.robotics_deep.localization import (
    ParticleFilterLocalizer as PFLocalizer,
)
from thomas.robotics_deep.motion_planning import (
    PRM,
    RRT,
    PathSmoother,
    RRTStar,
)
from thomas.robotics_deep.path_tracking import (
    PurePursuit,
    StanleyController,
    TrajectoryGenerator,
    WaypointFollower,
)
from thomas.robotics_deep.sensors import (
    CameraModel,
    EncoderSimulator,
    IMUSimulator,
    LidarSimulator,
    SensorFusion,
)
from thomas.robotics_deep.slam import (
    EKFSLAMFilter,
    OccupancyGridMapper,
    ParticleFilterLocalizer,
)

__version__ = "0.1.0"
__all__ = [
    "Vec3",
    "Matrix3x3",
    "Matrix4x4",
    "Quaternion",
    "JointType",
    "DHParams",
    "JointState",
    "Pose",
    "Trajectory",
    "SensorReading",
    "LaserScan",
    "OccupancyGrid",
    "RoboticsError",
    "KinematicsError",
    "PlanningError",
    "SLAMError",
    "ForwardKinematics",
    "InverseKinematics",
    "Jacobian",
    "WorkspaceBoundary",
    "RRT",
    "RRTStar",
    "PRM",
    "PathSmoother",
    "EKFSLAMFilter",
    "OccupancyGridMapper",
    "ParticleFilterLocalizer",
    "PIDController",
    "TrajectoryTracker",
    "ComputedTorqueController",
    "ImpedanceController",
    "VelocityController",
    "LidarSimulator",
    "CameraModel",
    "IMUSimulator",
    "EncoderSimulator",
    "SensorFusion",
    "RobotDynamics",
    "TwoDOFArmDynamics",
    "PurePursuit",
    "StanleyController",
    "TrajectoryGenerator",
    "WaypointFollower",
    "OdometryFilter",
    "ExtendedKalmanFilterLocalizer",
    "PFLocalizer",
    "ICPScanMatcher",
    "GripperController",
    "GraspPlanner",
    "GraspQuality",
]
