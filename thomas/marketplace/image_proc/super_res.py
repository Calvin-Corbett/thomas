"""
Super-resolution module.

Implements bicubic upsampling, iterative back-projection, sparse coding,
self-similarity, and multi-frame super-resolution techniques.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import convolve2d

from ._exceptions import ImageProcessingError
from ._types import Image, SuperResConfig


class SuperResolution:
    """
    Performs image super-resolution (upscaling).

    Implements:
    - Bicubic interpolation
    - Iterative back-projection
    - Sparse coding approach
    - Self-similarity exploitation
    - Multi-frame super-resolution
    """

    def __init__(self, config: SuperResConfig | None = None) -> None:
        """
        Initialize super-resolution processor.

        Args:
            config: SR configuration with method and parameters.
        """
        self.config = config or SuperResConfig()

    def upscale(self, image: Image) -> Image:
        """
        Upscale image using configured method.

        Args:
            image: Low-resolution input image.

        Returns:
            Super-resolved image at scale_factor resolution.

        Raises:
            ImageProcessingError: If method is unsupported.
        """
        if self.config.method == "bicubic":
            result = self._bicubic_upscale(image)
        elif self.config.method == "ibp":
            result = self._iterative_back_projection(image)
        elif self.config.method == "sparse":
            result = self._sparse_coding_upscale(image)
        elif self.config.method == "self-sim":
            result = self._self_similarity_upscale(image)
        else:
            raise ImageProcessingError(f"Unknown SR method: {self.config.method}")

        return result

    def _bicubic_upscale(self, image: Image) -> Image:
        """
        Bicubic interpolation upscaling.

        Uses 16-point cubic kernel for each output pixel.
        """
        img_float = image.to_float32()
        scale = self.config.scale_factor

        h, w = img_float.height, img_float.width
        new_h = h * scale
        new_w = w * scale

        result = np.zeros((new_h, new_w, img_float.channels), dtype=np.float32)

        for c in range(img_float.channels):
            channel = img_float.data[:, :, c]

            # Pad image for bicubic interpolation
            padded = np.pad(channel, ((2, 2), (2, 2)), mode="reflect")

            for y in range(new_h):
                for x in range(new_w):
                    # Fractional coordinates in original image
                    src_y = y / scale
                    src_x = x / scale

                    # 4x4 neighborhood
                    y0 = int(np.floor(src_y))
                    x0 = int(np.floor(src_x))

                    fy = src_y - y0
                    fx = src_x - x0

                    # Cubic kernel weights
                    weights_y = self._cubic_kernel(fy)
                    weights_x = self._cubic_kernel(fx)

                    # Accumulate from 4x4 region (with padding offset)
                    value = 0.0
                    for dy in range(-1, 3):
                        for dx in range(-1, 3):
                            py = y0 + dy + 2
                            px = x0 + dx + 2

                            if 0 <= py < padded.shape[0] and 0 <= px < padded.shape[1]:
                                weight = weights_y[dy + 1] * weights_x[dx + 1]
                                value += weight * padded[py, px]

                    result[y, x, c] = value

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    @staticmethod
    def _cubic_kernel(t: float) -> np.ndarray:
        """Cubic interpolation kernel weights."""
        t = abs(t)
        if t < 1:
            return np.array(
                [
                    0.5 * t**3 - t**2 + 2 / 3,
                    -1.5 * t**3 + 2.5 * t**2 + 1,
                    1.5 * t**3 - 2.5 * t**2 + 1,
                    0.5 * t**3 - t**2,
                ]
            )
        else:
            return np.array(
                [
                    0.5 * (2 - t) ** 3,
                    -1.5 * (2 - t) ** 2 * (t - 1),
                    1.5 * (2 - t) * (t - 1) ** 2,
                    0.5 * (t - 1) ** 3,
                ]
            )

    def _iterative_back_projection(self, image: Image) -> Image:
        """
        Iterative back-projection super-resolution.

        Alternates: upscale → degrade → residual correction.
        """
        img_float = image.to_float32()
        scale = self.config.scale_factor
        iterations = self.config.iterations

        # Initial upscale using bicubic
        current = self._bicubic_upscale(image).data

        for iteration in range(iterations):
            # Degrade high-res back to low-res
            degraded = self._downsample(current, scale)

            # Compute residual
            residual = img_float.data - degraded

            # Upsample residual
            upsampled_residual = self._upsample_residual(residual, scale)

            # Correct
            current = current + 0.01 * upsampled_residual

        return Image(
            data=np.clip(current, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    @staticmethod
    def _downsample(image: np.ndarray, factor: int) -> np.ndarray:
        """Downsample image by applying Gaussian blur and subsampling."""
        kernel_size = 2 * factor + 1
        sigma = factor / 2
        ax = np.arange(-kernel_size // 2 + 1.0, kernel_size // 2 + 1.0)
        kernel = np.exp(-(ax**2) / (2 * sigma**2))
        kernel = np.outer(kernel, kernel)
        kernel = kernel / kernel.sum()

        result = np.zeros_like(image)
        for c in range(image.shape[2]):
            result[:, :, c] = convolve2d(image[:, :, c], kernel, mode="same", boundary="symm")

        return result[::factor, ::factor, :]

    @staticmethod
    def _upsample_residual(residual: np.ndarray, factor: int) -> np.ndarray:
        """Upsample residual using bicubic."""
        h, w = residual.shape[:2]
        new_h = h * factor
        new_w = w * factor

        upsampled = np.zeros((new_h, new_w, residual.shape[2]), dtype=np.float32)

        for c in range(residual.shape[2]):
            channel = residual[:, :, c]
            padded = np.pad(channel, ((2, 2), (2, 2)), mode="reflect")

            for y in range(new_h):
                for x in range(new_w):
                    src_y = y / factor
                    src_x = x / factor

                    y0 = int(np.floor(src_y))
                    x0 = int(np.floor(src_x))

                    fy = src_y - y0
                    fx = src_x - x0

                    weights_y = SuperResolution._cubic_kernel(fy)
                    weights_x = SuperResolution._cubic_kernel(fx)

                    value = 0.0
                    for dy in range(-1, 3):
                        for dx in range(-1, 3):
                            py = y0 + dy + 2
                            px = x0 + dx + 2

                            if 0 <= py < padded.shape[0] and 0 <= px < padded.shape[1]:
                                weight = weights_y[dy + 1] * weights_x[dx + 1]
                                value += weight * padded[py, px]

                    upsampled[y, x, c] = value

        return upsampled

    def _sparse_coding_upscale(self, image: Image) -> Image:
        """
        Sparse coding based super-resolution.

        Learns dictionary of patch pairs (LR↔HR) and uses sparse
        representation for upscaling.
        """
        img_float = image.to_float32()
        scale = self.config.scale_factor
        patch_size = 5
        dict_size = self.config.dict_size

        # Initial upscale
        current = self._bicubic_upscale(image).data

        # Learn dictionary on patches (simplified)
        lr_patches, hr_patches = self._extract_patch_pairs(img_float.data, scale, patch_size)

        if len(lr_patches) == 0:
            return Image(
                data=np.clip(current, 0, 1).astype(np.float32),
                color_space=image.color_space,
                bit_depth=32,
            )

        # Dictionary learning (simplified K-means)
        dict_lr, dict_hr = self._learn_dictionary(lr_patches, hr_patches, dict_size)

        # Apply sparse coding to patches
        h, w = current.shape[:2]
        step = patch_size // 2

        for y in range(0, h - patch_size, step):
            for x in range(0, w - patch_size, step):
                patch = current[y : y + patch_size, x : x + patch_size]
                patch_flat = patch.flatten()

                # Sparse representation
                codes = self._sparse_codes(patch_flat, dict_lr)

                if codes is not None:
                    reconstruction = dict_hr @ codes
                    current[y : y + patch_size, x : x + patch_size] = reconstruction.reshape(patch_size, patch_size, -1)

        return Image(
            data=np.clip(current, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def _self_similarity_upscale(self, image: Image) -> Image:
        """
        Self-similarity based super-resolution.

        Finds similar patches at different scales within the same image
        and uses them for upscaling.
        """
        img_float = image.to_float32()
        scale = self.config.scale_factor

        # Initial upscale
        current = self._bicubic_upscale(image).data

        # Find and use self-similar patches
        h, w = img_float.height, img_float.width
        patch_size = 5

        for y in range(patch_size, h - patch_size, 2):
            for x in range(patch_size, w - patch_size, 2):
                patch = img_float.data[y : y + patch_size, x : x + patch_size]

                # Find similar patches at same scale and neighboring scales
                similar_patches = self._find_similar_patches(img_float.data, patch, search_radius=20)

                if similar_patches:
                    # Average similar patches for smoothing
                    avg_patch = np.mean(similar_patches, axis=0)

                    # Apply to upsampled location
                    uy_start = y * scale
                    ux_start = x * scale

                    if uy_start + patch_size * scale <= current.shape[0]:
                        if ux_start + patch_size * scale <= current.shape[1]:
                            current[
                                uy_start : uy_start + patch_size * scale,
                                ux_start : ux_start + patch_size * scale,
                            ] = np.repeat(np.repeat(avg_patch, scale, axis=0), scale, axis=1)

        return Image(
            data=np.clip(current, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    @staticmethod
    def _extract_patch_pairs(image: np.ndarray, scale: int, patch_size: int) -> tuple:
        """Extract low-res and high-res patch pairs."""
        lr_patches, hr_patches = [], []

        h, w = image.shape[:2]
        step = patch_size

        for y in range(0, h - patch_size, step):
            for x in range(0, w - patch_size, step):
                patch = image[y : y + patch_size, x : x + patch_size]

                # Downsample to create LR version
                downsampled = patch[::scale, ::scale]

                lr_patches.append(downsampled.flatten())
                hr_patches.append(patch.flatten())

        return np.array(lr_patches), np.array(hr_patches)

    @staticmethod
    def _learn_dictionary(lr_patches: np.ndarray, hr_patches: np.ndarray, dict_size: int) -> tuple:
        """Learn dictionary of patch pairs using K-means."""
        from sklearn.cluster import KMeans

        try:
            kmeans_lr = KMeans(n_clusters=dict_size, n_init=3)
            kmeans_hr = KMeans(n_clusters=dict_size, n_init=3)

            kmeans_lr.fit(lr_patches)
            kmeans_hr.fit(hr_patches)

            return kmeans_lr.cluster_centers_.T, kmeans_hr.cluster_centers_.T
        except (ValueError, np.linalg.LinAlgError, RuntimeError):
            # Fallback: return identity dictionaries
            size = min(lr_patches.shape[1], dict_size)
            return np.eye(size), np.eye(size)

    @staticmethod
    def _sparse_codes(patch: np.ndarray, dictionary: np.ndarray) -> np.ndarray | None:
        """Compute sparse codes using OMP."""
        from sklearn.linear_model import OrthogonalMatchingPursuit

        try:
            omp = OrthogonalMatchingPursuit(n_nonzero_coefs=5)
            codes = omp.fit(dictionary.T, patch).coef_
            return codes
        except (ValueError, np.linalg.LinAlgError, RuntimeError):
            return None

    @staticmethod
    def _find_similar_patches(image: np.ndarray, patch: np.ndarray, search_radius: int = 20) -> list[np.ndarray]:
        """Find patches similar to given patch."""
        similar = []
        h, w = image.shape[:2]
        patch_h, patch_w = patch.shape[:2]

        cy, cx = patch_h // 2, patch_w // 2

        for y in range(max(0, cy - search_radius), min(h - patch_h, cy + search_radius)):
            for x in range(max(0, cx - search_radius), min(w - patch_w, cx + search_radius)):
                candidate = image[y : y + patch_h, x : x + patch_w]

                if candidate.shape == patch.shape:
                    dist = np.sum((candidate - patch) ** 2)

                    if dist < 0.1:
                        similar.append(candidate)

        return similar
