"""Exception classes for the game engine."""


class GameEngineError(Exception):
    """Base exception for all game engine errors."""

    pass


class EntityError(GameEngineError):
    """Raised when entity operations fail."""

    pass


class ComponentError(GameEngineError):
    """Raised when component operations fail."""

    pass


class SystemError(GameEngineError):
    """Raised when system operations fail."""

    pass


class PhysicsError(GameEngineError):
    """Raised when physics operations fail."""

    pass


class InputError(GameEngineError):
    """Raised when input operations fail."""

    pass


class RenderingError(GameEngineError):
    """Raised when rendering operations fail."""

    pass


class AudioError(GameEngineError):
    """Raised when audio operations fail."""

    pass


class NetworkingError(GameEngineError):
    """Raised when networking operations fail."""

    pass
