"""Thomas Computer Vision Module - A complete CV engine built from scratch."""

from thomas.cv import color, core, edges, features, filters, io_formats, morphology, segmentation, transforms
from thomas.cv._exceptions import (
    CVException,
    InvalidImageError,
    InvalidParameterError,
    UnsupportedFormatError,
)
from thomas.cv._types import (
    ROI,
    BoundingBox,
    Color,
    ColorSpace,
    Contour,
    Descriptor,
    Feature,
    Histogram,
    Image,
    ImageFormat,
    Kernel,
    Match,
    Pixel,
    Point,
    Transform2D,
)

__all__ = [
    "Image",
    "Pixel",
    "Color",
    "BoundingBox",
    "Point",
    "Contour",
    "Histogram",
    "Kernel",
    "ColorSpace",
    "ImageFormat",
    "Feature",
    "Descriptor",
    "Match",
    "Transform2D",
    "ROI",
    "CVException",
    "InvalidImageError",
    "InvalidParameterError",
    "UnsupportedFormatError",
    "core",
    "filters",
    "edges",
    "features",
    "morphology",
    "color",
    "segmentation",
    "transforms",
    "io_formats",
]

__version__ = "0.1.0"
