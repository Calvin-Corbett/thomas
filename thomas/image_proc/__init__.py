"""
Advanced image processing module for computational photography and digital imaging.

Provides HDR imaging, panorama stitching, denoising, inpainting, super-resolution,
segmentation, color science, compression, and special effects.
"""

from ._exceptions import (
    AlgorithmError,
    CompressionError,
    ImageFormatError,
    ImageProcessingError,
    RegistrationError,
)
from ._types import (
    BlendMode,
    ColorSpace,
    DenoisingConfig,
    ExposureInfo,
    Histogram,
    Image,
    InpaintMask,
    Kernel,
    NoiseModel,
    Panorama,
    Pixel,
    Seam,
    StyleTransferConfig,
    SuperResConfig,
    ToneMap,
)

# Scipy-dependent imports are optional
try:
    from .hdr import HDRProcessor
except ImportError:
    HDRProcessor = None  # type: ignore

try:
    from .panorama import PanoramaStitcher
except ImportError:
    PanoramaStitcher = None  # type: ignore

try:
    from .denoising import Denoiser
except ImportError:
    Denoiser = None  # type: ignore

try:
    from .inpainting import Inpainter
except ImportError:
    Inpainter = None  # type: ignore

try:
    from .super_res import SuperResolution
except ImportError:
    SuperResolution = None  # type: ignore

try:
    from .segmentation_adv import AdvancedSegmentation
except ImportError:
    AdvancedSegmentation = None  # type: ignore

try:
    from .color_science import ColorScience
except ImportError:
    ColorScience = None  # type: ignore

try:
    from .compression import CompressionCodec
except ImportError:
    CompressionCodec = None  # type: ignore

try:
    from .effects import EffectsProcessor
except ImportError:
    EffectsProcessor = None  # type: ignore

__version__ = "1.0.0"
__all__ = [
    "Image",
    "Pixel",
    "ColorSpace",
    "Histogram",
    "Kernel",
    "BlendMode",
    "ToneMap",
    "ExposureInfo",
    "Panorama",
    "Seam",
    "InpaintMask",
    "SuperResConfig",
    "StyleTransferConfig",
    "NoiseModel",
    "DenoisingConfig",
    "ImageProcessingError",
    "ImageFormatError",
    "AlgorithmError",
    "RegistrationError",
    "CompressionError",
    "HDRProcessor",
    "PanoramaStitcher",
    "Denoiser",
    "Inpainter",
    "SuperResolution",
    "AdvancedSegmentation",
    "ColorScience",
    "CompressionCodec",
    "EffectsProcessor",
]
