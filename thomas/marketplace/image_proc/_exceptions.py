"""
Custom exceptions for image processing module.
"""


class ImageProcessingError(Exception):
    """
    Base exception for all image processing errors.

    Raised when a general image processing operation fails.
    """

    pass


class ImageFormatError(ImageProcessingError):
    """
    Raised when image format is invalid or unsupported.

    Occurs when attempting to load, save, or process images
    in unsupported formats or with invalid dimensions.
    """

    pass


class AlgorithmError(ImageProcessingError):
    """
    Raised when an algorithm fails to converge or produce valid output.

    Indicates mathematical or numerical issues during algorithm execution,
    such as singular matrices, non-convergence, or invalid parameters.
    """

    pass


class RegistrationError(AlgorithmError):
    """
    Raised when image registration (alignment) fails.

    Occurs when feature matching, homography estimation, or
    other registration techniques cannot find sufficient alignment.
    """

    pass


class CompressionError(ImageProcessingError):
    """
    Raised when image compression or decompression fails.

    Indicates issues with codec implementation or corrupted data.
    """

    pass


class InpaintingError(AlgorithmError):
    """
    Raised when inpainting operation fails.

    Occurs when the inpainting mask is invalid or algorithm
    cannot find suitable exemplar patches.
    """

    pass


class SegmentationError(AlgorithmError):
    """
    Raised when segmentation operation fails.

    Indicates convergence issues or invalid input parameters
    for segmentation algorithms.
    """

    pass


class ColorConversionError(ImageProcessingError):
    """
    Raised when color space conversion fails.

    Occurs when attempting invalid color space transformations
    or with invalid color data.
    """

    pass
