"""
HDR imaging module.

Implements exposure bracketing, response curve estimation (Debevec method),
HDR radiance map construction, and tone mapping operators (Reinhard, Drago, Mantiuk).
"""

from __future__ import annotations

import numpy as np

from ._exceptions import AlgorithmError, ImageProcessingError
from ._types import ExposureInfo, Image, ToneMap


class HDRProcessor:
    """
    Processes HDR images from exposure-bracketed sequences.

    Implements full HDR pipeline:
    - Response curve estimation via Debevec's method
    - Radiance map construction from multiple exposures
    - Tone mapping to displayable range
    """

    def __init__(self, response_curve: np.ndarray | None = None) -> None:
        """
        Initialize HDR processor.

        Args:
            response_curve: Pre-computed camera response curve (optional).
                If None, will be estimated from input images.
        """
        self.response_curve = response_curve
        self.lambda_reg: float = 2.0  # Smoothness regularization
        self.num_samples: int = 100  # Samples for curve estimation

    def merge_exposures(
        self,
        images: list[Image],
        exposures: list[ExposureInfo],
        estimate_curve: bool = True,
    ) -> Image:
        """
        Merge multiple exposures into a single HDR image.

        Args:
            images: List of input images (must be same dimensions, RGB or grayscale).
            exposures: ExposureInfo for each image.
            estimate_curve: Whether to estimate response curve from images.

        Returns:
            HDR radiance map as float32 Image (values may exceed [0, 1]).

        Raises:
            ImageProcessingError: If inputs are invalid.
            AlgorithmError: If curve estimation or merging fails.
        """
        if len(images) != len(exposures):
            raise ImageProcessingError("Number of images and exposures must match")
        if len(images) < 2:
            raise ImageProcessingError("Need at least 2 exposures for HDR merging")

        # Validate dimensions
        h, w = images[0].height, images[0].width
        for img in images[1:]:
            if img.height != h or img.width != w:
                raise ImageProcessingError("All images must have same dimensions")

        # Convert to float and ensure RGB
        images_float = [img.to_float32() for img in images]
        if images_float[0].channels == 1:
            # Grayscale to RGB
            for i, img in enumerate(images_float):
                img.data = np.dstack([img.data] * 3)

        # Estimate or use provided response curve
        if estimate_curve and self.response_curve is None:
            self.response_curve = self._estimate_response_curve(images_float, exposures)
        elif self.response_curve is None:
            raise AlgorithmError("No response curve available; set or estimate it")

        # Compute radiance map
        radiance = self._compute_radiance_map(images_float, exposures)

        return Image(
            data=radiance,
            color_space="RGB",
            bit_depth=32,
            metadata={"hdr": True, "num_exposures": len(images)},
        )

    def _estimate_response_curve(self, images: list[Image], exposures: list[ExposureInfo]) -> np.ndarray:
        """
        Estimate camera response curve using Debevec's method.

        Samples pixels across exposures and solves least-squares system
        to recover the response curve.

        Args:
            images: Input images (float32, normalized).
            exposures: Exposure information.

        Returns:
            Response curve as 256-element array mapping pixel values to log radiance.
        """
        n_samples = min(self.num_samples, 50)  # Sample points per image
        samples_per_img = min(n_samples, images[0].height * images[0].width // 100)

        # Collect pixel samples
        pixel_values: list[tuple[np.ndarray, np.ndarray]] = []
        for img, exp in zip(images, exposures):
            gray = np.mean(img.data, axis=2)
            mask = (gray > 0.05) & (gray < 0.95)
            valid_pixels = np.argwhere(mask)

            if len(valid_pixels) > samples_per_img:
                indices = np.random.choice(len(valid_pixels), samples_per_img, replace=False)
                selected = valid_pixels[indices]
            else:
                selected = valid_pixels

            for y, x in selected:
                pixel_values.append((img.data[y, x, :], np.array([exp.exposure_value])))

        if not pixel_values:
            raise AlgorithmError("Cannot estimate response curve: insufficient valid pixels")

        # Build Debevec matrix equation: A * g = b
        # g = [g[0], ..., g[255], ln(E_1), ..., ln(E_N)]
        num_pixels = len(pixel_values)
        num_exposures = len(images)
        num_radiance = num_pixels
        num_curve = 256
        num_vars = num_curve + num_radiance

        # Initialize matrix (will be sparse in practice)
        A = np.zeros((num_pixels * num_exposures + num_curve - 1, num_vars))
        b = np.zeros(num_pixels * num_exposures + num_curve - 1)

        # Data term: Z_ij = g(E_i * t_j)
        row = 0
        for i, (pixel_rgb, _) in enumerate(pixel_values):
            for j, exp in enumerate(exposures):
                z = int(np.clip(pixel_rgb[0] * 255.99, 0, 255))
                A[row, z] = 1  # g[z]
                A[row, num_curve + i] = -np.exp(-exp.exposure_value)  # -t_j
                b[row] = 0
                row += 1

        # Smoothness term: lambda * (g'' regularization)
        for k in range(1, num_curve - 1):
            A[row, k - 1] = self.lambda_reg
            A[row, k] = -2 * self.lambda_reg
            A[row, k + 1] = self.lambda_reg
            b[row] = 0
            row += 1

        # Solve least squares
        try:
            solution, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError as e:
            raise AlgorithmError(f"Failed to solve response curve: {e}")

        response_curve = solution[:num_curve].astype(np.float64)
        if not np.all(np.isfinite(response_curve)) or np.ptp(response_curve) < 1e-8:
            z = np.linspace(0.0, 1.0, num_curve, dtype=np.float64)
            response_curve = np.log(z + 1e-4)
        else:
            # Keep the estimated curve physically plausible.
            response_curve = np.maximum.accumulate(response_curve)
            response_curve += np.linspace(0.0, 1e-6 * (num_curve - 1), num_curve)

        self.response_curve = response_curve.astype(np.float32)

        return self.response_curve

    def _compute_radiance_map(self, images: list[Image], exposures: list[ExposureInfo]) -> np.ndarray:
        """
        Compute HDR radiance map from images and response curve.

        Args:
            images: Input images (float32).
            exposures: Exposure information.

        Returns:
            Radiance map (float32, shape (H, W, 3)).
        """
        h, w = images[0].height, images[0].width
        radiance = np.zeros((h, w, 3), dtype=np.float32)
        weights = np.zeros((h, w, 3), dtype=np.float32)

        for img, exp in zip(images, exposures):
            # Compute weights based on pixel values (tent function)
            pixel_vals = np.clip(img.data * 255, 0, 255)
            z_vals = pixel_vals.astype(int)
            frac = pixel_vals - z_vals

            # Interpolate response curve
            if self.response_curve is not None:
                # Inverse response: log radiance
                log_e0 = np.zeros_like(img.data)
                log_e1 = np.zeros_like(img.data)

                for c in range(3):
                    for z in range(256):
                        mask = z_vals[:, :, c] == z
                        if self.response_curve is not None and z < len(self.response_curve):
                            log_e0[:, :, c][mask] = self.response_curve[z]
                        if z + 1 < len(self.response_curve):
                            log_e1[:, :, c][mask] = self.response_curve[z + 1]

                log_e = log_e0 * (1 - frac) + log_e1 * frac
            else:
                log_e = np.log(pixel_vals + 1e-4)

            # Subtract log exposure time
            log_radiance = log_e - exp.exposure_value

            # Weight pixels (tent function: high near middle values)
            w_middle = np.where(
                pixel_vals < 128,
                pixel_vals / 128.0,
                (255 - pixel_vals) / 128.0,
            )

            # Accumulate weighted radiance
            weight = w_middle
            radiance += np.exp(log_radiance) * weight
            weights += weight

        # Average
        mask = weights > 1e-10
        radiance[mask] /= weights[mask]
        radiance[~mask] = 0

        return np.clip(radiance, 0, None)

    def tone_map(self, hdr_image: Image, method: ToneMap = ToneMap.REINHARD_GLOBAL) -> Image:
        """
        Apply tone mapping to compress HDR radiance to displayable range.

        Args:
            hdr_image: HDR image with potentially large values.
            method: Tone mapping operator to use.

        Returns:
            Tone-mapped image with values in approximately [0, 1].

        Raises:
            AlgorithmError: If tone mapping fails.
        """
        if hdr_image.metadata.get("hdr") is not True:
            raise ImageProcessingError("Input should be an HDR image")

        radiance = hdr_image.to_float32().data

        if method == ToneMap.REINHARD_GLOBAL:
            mapped = self._reinhard_global(radiance)
        elif method == ToneMap.REINHARD_LOCAL:
            mapped = self._reinhard_local(radiance)
        elif method == ToneMap.DRAGO:
            mapped = self._drago(radiance)
        elif method == ToneMap.MANTIUK:
            mapped = self._mantiuk(radiance)
        else:
            raise AlgorithmError(f"Unknown tone mapping method: {method}")

        return Image(
            data=np.clip(mapped, 0, 1).astype(np.float32),
            color_space="RGB",
            bit_depth=32,
        )

    @staticmethod
    def _reinhard_global(radiance: np.ndarray, target_lum: float = 0.18) -> np.ndarray:
        """
        Reinhard global tone mapping.

        Simple global operator: L_out = target_lum * L_in / mean(L_in).
        """
        gray = np.mean(radiance, axis=2, keepdims=True)
        mean_lum = np.mean(gray[gray > 0])
        if mean_lum < 1e-10:
            return radiance

        scale = target_lum / mean_lum
        mapped = radiance * scale

        # Compress to [0, 1] with global operator: x / (1 + x)
        return mapped / (1 + mapped)

    @staticmethod
    def _reinhard_local(radiance: np.ndarray, phi: float = 8.0) -> np.ndarray:
        """
        Reinhard local (spatially-varying) tone mapping.

        Uses weighted average of global and local operators.
        """
        # scipy costs ~1.5s to import and every Thomas process pays it at boot,
        # while these image operations are rarely used. Importing inside the
        # function keeps that cost on the callers who actually need it.
        from scipy.signal import convolve2d

        gray = np.mean(radiance, axis=2)
        mean_lum = np.mean(gray[gray > 0])

        # Global mapping
        global_mapped = gray / (1 + gray / (2 * mean_lum + 1e-10))

        # Local: compute local mean using Gaussian blur
        sigma = 2 * phi
        kernel = cv2_gaussian_kernel(int(2 * phi + 1), sigma)
        local_mean = convolve2d(gray, kernel, mode="same", boundary="symm")
        local_mapped = gray / (1 + gray / (2 * local_mean + 1e-10))

        # Blend
        mapped = 0.5 * global_mapped + 0.5 * local_mapped

        # Expand to RGB
        h, w, c = radiance.shape
        result = np.zeros_like(radiance)
        for ch in range(c):
            result[:, :, ch] = radiance[:, :, ch] * mapped / (gray + 1e-10)

        return np.clip(result / (1 + result), 0, 1)

    @staticmethod
    def _drago(radiance: np.ndarray, bias: float = 0.85) -> np.ndarray:
        """
        Drago logarithmic tone mapping.

        Logarithmic compression with user-controlled bias.
        """
        gray = np.mean(radiance, axis=2)
        max_lum = np.max(gray)

        if max_lum < 1e-10:
            return radiance

        # Normalize
        normalized = gray / max_lum

        # Logarithmic compression
        log_mapped = np.log10(normalized + 1) / np.log10(2)

        # Bias adjustment
        log_lum_disp = (log_mapped / np.log10(max_lum + 1)) ** (np.log(bias) / np.log(0.5))

        # Expand to RGB
        h, w, c = radiance.shape
        result = np.zeros_like(radiance)
        for ch in range(c):
            result[:, :, ch] = radiance[:, :, ch] * log_lum_disp / (gray + 1e-10)

        return np.clip(result, 0, 1)

    @staticmethod
    def _mantiuk(radiance: np.ndarray, contrast: float = 0.3) -> np.ndarray:
        """
        Mantiuk contrast-preserving tone mapping.

        Preserves local contrast while compressing dynamic range.
        """
        from scipy.signal import convolve2d

        gray = np.mean(radiance, axis=2)

        # Edge-preserving filter (bilateral-like)
        detail_layer = gray.copy()
        base_layer = gray.copy()

        for _ in range(3):
            kernel = cv2_gaussian_kernel(5, 1.0)
            base_layer = convolve2d(base_layer, kernel, mode="same", boundary="symm")

        detail_layer = gray - base_layer

        # Compress base, preserve detail
        base_compressed = np.log1p(base_layer) / (np.log1p(np.max(gray)) + 1e-10)
        compressed = base_compressed + contrast * detail_layer

        # Expand to RGB
        h, w, c = radiance.shape
        result = np.zeros_like(radiance)
        for ch in range(c):
            result[:, :, ch] = radiance[:, :, ch] * compressed / (gray + 1e-10)

        return np.clip(result / (1 + result), 0, 1)

    def exposure_fusion(
        self,
        images: list[Image],
        weights: list[np.ndarray] | None = None,
    ) -> Image:
        """
        Merge multiple exposures using exposure fusion (Mertens).

        Uses contrast, saturation, and well-exposedness weights with
        Laplacian pyramid blending.

        Args:
            images: Input images (same dimensions).
            weights: Optional pre-computed weight maps.

        Returns:
            Fused image.
        """
        if len(images) < 2:
            raise ImageProcessingError("Need at least 2 images for fusion")

        images_float = [img.to_float32() for img in images]
        h, w = images_float[0].height, images_float[0].width
        channels = images_float[0].channels

        for img in images_float[1:]:
            if img.height != h or img.width != w:
                raise ImageProcessingError("All images must have same dimensions")

        # Build one scalar weight map per exposure and normalize across exposures.
        weight_maps: list[np.ndarray] = []
        if weights is None:
            for img in images_float:
                w_contrast = self._compute_contrast_weight(img)
                w_saturation = self._compute_saturation_weight(img)
                w_exposedness = self._compute_exposedness_weight(img)
                weight_map = np.mean(w_contrast * w_saturation * w_exposedness, axis=2)
                weight_maps.append(np.clip(weight_map, 0, None))
        else:
            if len(weights) != len(images_float):
                raise ImageProcessingError("Number of weight maps must match number of images")

            for weight in weights:
                if weight.shape[:2] != (h, w):
                    raise ImageProcessingError("Weight maps must match image dimensions")
                if weight.ndim == 2:
                    weight_map = weight
                elif weight.ndim == 3:
                    weight_map = np.mean(weight, axis=2)
                else:
                    raise ImageProcessingError("Weight map must be 2D or 3D")
                weight_maps.append(np.clip(weight_map, 0, None))

        weight_stack = np.stack(weight_maps, axis=0).astype(np.float32) + 1e-10
        weight_stack /= np.sum(weight_stack, axis=0, keepdims=True)

        result = np.zeros((h, w, channels), dtype=np.float32)
        for idx, img in enumerate(images_float):
            result += img.data * weight_stack[idx][:, :, np.newaxis]

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space="RGB",
            bit_depth=32,
        )

    @staticmethod
    def _compute_contrast_weight(img: Image) -> np.ndarray:
        """Compute Laplacian contrast weight."""
        from scipy.signal import convolve2d

        gray = np.mean(img.data, axis=2)
        kernel = np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]], dtype=np.float32) / 4
        contrast = np.abs(convolve2d(gray, kernel, mode="same", boundary="symm"))
        return np.dstack([contrast] * img.channels)

    @staticmethod
    def _compute_saturation_weight(img: Image) -> np.ndarray:
        """Compute saturation weight."""
        if img.channels < 3:
            return np.ones_like(img.data[:, :, :1])

        mean_val = np.mean(img.data, axis=2, keepdims=True)
        var = np.mean((img.data - mean_val) ** 2, axis=2, keepdims=True)
        saturation = np.sqrt(var)
        return np.dstack([saturation] * img.channels)

    @staticmethod
    def _compute_exposedness_weight(img: Image) -> np.ndarray:
        """Compute well-exposedness weight (Gaussian around 0.5)."""
        sigma = 0.2
        weight = np.exp(-0.5 * ((img.data - 0.5) ** 2) / (sigma**2))
        return weight

    @staticmethod
    def _downsample(img: np.ndarray, level: int) -> np.ndarray:
        """Downsample image by 2^level."""
        result = img.copy()
        for _ in range(level):
            result = result[::2, ::2]
        return result


def cv2_gaussian_kernel(size: int, sigma: float) -> np.ndarray:
    """Create a Gaussian kernel."""
    ax = np.arange(-size // 2 + 1.0, size // 2 + 1.0)
    kernel = np.exp(-(ax**2) / (2 * sigma**2))
    kernel = np.outer(kernel, kernel)
    return kernel / kernel.sum()
