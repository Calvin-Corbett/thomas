"""
Custom exceptions for physics engine.
"""


class PhysicsError(Exception):
    """Base exception for all physics errors."""

    pass


class CollisionError(PhysicsError):
    """Exception raised for collision detection/resolution errors."""

    pass


class IntegrationError(PhysicsError):
    """Exception raised for numerical integration errors."""

    pass
