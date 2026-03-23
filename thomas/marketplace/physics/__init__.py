"""
Thomas Physics Engine - Complete physics simulation module.

Public API for rigid body dynamics, collision detection, constraints, and particles.
"""

from thomas.marketplace.physics._exceptions import (
    CollisionError,
    IntegrationError,
    PhysicsError,
)
from thomas.marketplace.physics._types import (
    AABB,
    Material,
    PhysicsConfig,
    Plane,
    Ray,
    RigidBodyType,
    Sphere,
    Vec2,
    Vec3,
)
from thomas.marketplace.physics.broadphase import (
    AABBTree,
    SpatialHashGrid,
    SweepAndPrune,
)
from thomas.marketplace.physics.cloth import ClothMesh
from thomas.marketplace.physics.collision_detection import (
    collide_aabb_aabb,
    collide_aabb_sphere,
    collide_sphere_plane,
    collide_sphere_sphere,
    generate_collision_manifold,
    gjk_collision,
    ray_aabb_intersection,
    ray_plane_intersection,
    ray_sphere_intersection,
    sat_collision_2d,
)
from thomas.marketplace.physics.collision_response import (
    apply_friction_impulse,
    resolve_collision,
    warm_start_contact,
)
from thomas.marketplace.physics.constraints import (
    Constraint,
    ConstraintSolver,
    ContactConstraint,
    DistanceConstraint,
    HingeJoint,
    SliderJoint,
)
from thomas.marketplace.physics.integrator import (
    AdaptiveIntegrator,
    EulerIntegrator,
    Integrator,
    RK4Integrator,
    SymplecticEulerIntegrator,
    VerletIntegrator,
)
from thomas.marketplace.physics.particles import ParticleEmitter, ParticleSystem
from thomas.marketplace.physics.rigid_body import RigidBody
from thomas.marketplace.physics.world import PhysicsWorld

__all__ = [
    # Types
    "Vec2",
    "Vec3",
    "AABB",
    "Sphere",
    "Plane",
    "Ray",
    "Material",
    "PhysicsConfig",
    "RigidBodyType",
    # Exceptions
    "PhysicsError",
    "CollisionError",
    "IntegrationError",
    # Core physics
    "RigidBody",
    "PhysicsWorld",
    # Collision
    "collide_sphere_sphere",
    "collide_aabb_aabb",
    "collide_sphere_plane",
    "collide_aabb_sphere",
    "ray_sphere_intersection",
    "ray_aabb_intersection",
    "ray_plane_intersection",
    "gjk_collision",
    "sat_collision_2d",
    "generate_collision_manifold",
    "resolve_collision",
    "apply_friction_impulse",
    "warm_start_contact",
    # Broadphase
    "SpatialHashGrid",
    "SweepAndPrune",
    "AABBTree",
    # Constraints
    "Constraint",
    "DistanceConstraint",
    "HingeJoint",
    "SliderJoint",
    "ContactConstraint",
    "ConstraintSolver",
    # Integration
    "Integrator",
    "EulerIntegrator",
    "SymplecticEulerIntegrator",
    "VerletIntegrator",
    "RK4Integrator",
    "AdaptiveIntegrator",
    # Particles
    "ParticleEmitter",
    "ParticleSystem",
    # Cloth
    "ClothMesh",
]

__version__ = "1.0.0"
