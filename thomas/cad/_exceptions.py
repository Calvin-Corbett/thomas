"""
Exception classes for the CAD engine.
"""


class CADError(Exception):
    """Base exception for all CAD errors."""

    pass


class GeometryError(CADError):
    """Raised when a geometric operation fails."""

    pass


class ConstraintError(CADError):
    """Raised when a constraint cannot be satisfied."""

    pass


class IOError(CADError):
    """Raised when file I/O operations fail."""

    pass


class IntersectionError(GeometryError):
    """Raised when geometric intersection computation fails."""

    pass


class CurveError(GeometryError):
    """Raised when curve operations fail."""

    pass


class SurfaceError(GeometryError):
    """Raised when surface operations fail."""

    pass


class InvalidParameterError(GeometryError):
    """Raised when an invalid parameter is provided."""

    pass


class DegenerateCaseError(GeometryError):
    """Raised when a degenerate geometric case is encountered."""

    pass


class BooleanOperationError(GeometryError):
    """Raised when boolean operations fail."""

    pass


class AssemblyError(CADError):
    """Raised when assembly operations fail."""

    pass


class DimensioningError(CADError):
    """Raised when dimensioning operations fail."""

    pass


class FormatError(IOError):
    """Raised when file format is invalid."""

    pass


class UnsupportedFormatError(IOError):
    """Raised when file format is not supported."""

    pass
