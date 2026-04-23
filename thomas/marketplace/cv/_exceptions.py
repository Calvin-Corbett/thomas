"""Exception types for the computer vision module."""


class CVException(Exception):
    """Base exception for all computer vision module errors."""

    pass


class InvalidImageError(CVException):
    """Raised when image data is invalid or corrupted."""

    pass


class InvalidParameterError(CVException):
    """Raised when invalid parameters are provided to a function."""

    pass


class UnsupportedFormatError(CVException):
    """Raised when an unsupported image format is encountered."""

    pass


class TransformationError(CVException):
    """Raised when a transformation cannot be applied."""

    pass


class FeatureDetectionError(CVException):
    """Raised when feature detection fails."""

    pass


class SegmentationError(CVException):
    """Raised when segmentation operation fails."""

    pass
