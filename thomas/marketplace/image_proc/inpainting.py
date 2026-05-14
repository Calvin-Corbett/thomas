"""
Image inpainting module.

Implements exemplar-based inpainting (Criminisi), diffusion-based inpainting,
texture synthesis (Efros-Leung), and PatchMatch for fast nearest neighbors.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import convolve

from ._exceptions import ImageProcessingError
from ._types import Image, InpaintMask


class Inpainter:
    """
    Performs image inpainting (content-aware hole filling).

    Implements:
    - Exemplar-based inpainting (Criminisi algorithm)
    - Diffusion-based inpainting
    - Texture synthesis (Efros-Leung)
    - PatchMatch for fast nearest neighbor field
    """

    def __init__(self, patch_size: int = 9, search_radius: int = 100) -> None:
        """
        Initialize inpainter.

        Args:
            patch_size: Size of inpainting patches (odd number).
            search_radius: Search radius for similar patches.
        """
        self.patch_size = patch_size
        self.search_radius = search_radius
        self.max_iterations = 100

    def inpaint_exemplar(self, image: Image, mask: InpaintMask) -> Image:
        """
        Exemplar-based inpainting (Criminisi algorithm).

        Iteratively fills holes by finding and copying best-matching patches
        from valid regions, guided by priority computation.

        Args:
            image: Input image with holes.
            mask: Inpainting mask (>0 indicates region to inpaint).

        Returns:
            Inpainted image.

        Raises:
            InpaintingError: If inpainting fails.
        """
        if mask.data.shape != (image.height, image.width):
            raise ImageProcessingError("Mask dimensions must match image")

        img_float = image.to_float32()
        mask_work = mask.data.copy().astype(np.uint8)
        mask_work[mask_work > 0] = 255

        result = img_float.data.copy()
        min_val = float(np.min(img_float.data))
        max_val = float(np.max(img_float.data))
        half_patch = self.patch_size // 2

        # Dilate mask for boundary
        boundary = self._find_boundary(mask_work)

        for iteration in range(self.max_iterations):
            if not np.any(mask_work > 0):
                break

            # Update boundary
            boundary = self._find_boundary(mask_work)

            if len(boundary) == 0:
                break

            # Compute priority for boundary pixels
            priorities = self._compute_priorities(result, mask_work, boundary, img_float)

            # Find highest priority pixel
            if len(priorities) == 0:
                break

            p = max(priorities, key=priorities.get)
            py, px = p

            # Find best matching patch
            best_patch, best_pos = self._find_best_patch(result, mask_work, py, px, self.patch_size)

            if best_patch is None:
                break

            # Copy patch
            y_start = max(0, py - half_patch)
            y_end = min(img_float.height, py + half_patch + 1)
            x_start = max(0, px - half_patch)
            x_end = min(img_float.width, px + half_patch + 1)
            patch_h = y_end - y_start
            patch_w = x_end - x_start
            result[y_start:y_end, x_start:x_end, :] = best_patch[:patch_h, :patch_w, :]

            # Update mask
            mask_work[y_start:y_end, x_start:x_end] = 0

        return Image(
            data=np.clip(result, min_val, max_val).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def inpaint_diffusion(self, image: Image, mask: InpaintMask, iterations: int = 100) -> Image:
        """
        Diffusion-based inpainting.

        Solves Laplace equation iteratively in masked regions to smooth fill.

        Args:
            image: Input image.
            mask: Inpainting mask.
            iterations: Number of diffusion iterations.

        Returns:
            Inpainted image.
        """
        if mask.data.shape != (image.height, image.width):
            raise ImageProcessingError("Mask dimensions must match image")

        img_float = image.to_float32()
        mask_binary = (mask.data > 0).astype(float)

        result = img_float.data.copy()
        min_val = float(np.min(img_float.data))
        max_val = float(np.max(img_float.data))

        # Laplacian kernel
        laplacian = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32) / 4

        for _ in range(iterations):
            for c in range(img_float.channels):
                channel = result[:, :, c]

                # Apply Laplacian in inpainting region
                laplacian_result = convolve(channel, laplacian, mode="reflect")

                # Update: smooth pixels in masked region
                result[:, :, c] = channel * (1 - mask_binary) + (channel + 0.5 * laplacian_result) * mask_binary

        return Image(
            data=np.clip(result, min_val, max_val).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def inpaint_texture_synthesis(self, image: Image, mask: InpaintMask) -> Image:
        """
        Texture synthesis inpainting (Efros-Leung).

        Grows texture by finding similar patches at the boundary and expanding.

        Args:
            image: Input image.
            mask: Inpainting mask.

        Returns:
            Inpainted image.
        """
        img_float = image.to_float32()
        mask_work = (mask.data > 0).astype(np.uint8)

        result = img_float.data.copy()
        min_val = float(np.min(img_float.data))
        max_val = float(np.max(img_float.data))
        half_patch = self.patch_size // 2

        # PatchMatch for acceleration
        self._patchmatch(result, mask_work)

        # Grow from boundary
        boundary = self._find_boundary(mask_work)

        processed = set()

        while len(boundary) > 0:
            # Process boundary pixels
            for py, px in list(boundary)[:100]:  # Limit per iteration
                if mask_work[py, px] == 0:
                    continue

                # Find best match in search radius
                best_patch = None
                best_dist = float("inf")

                for dy in range(-self.search_radius, self.search_radius):
                    for dx in range(-self.search_radius, self.search_radius):
                        by, bx = py + dy, px + dx

                        if 0 <= by < img_float.height and 0 <= bx < img_float.width:
                            if mask_work[by, bx] == 0:  # Valid region
                                patch = result[
                                    max(0, by - half_patch) : min(img_float.height, by + half_patch + 1),
                                    max(0, bx - half_patch) : min(img_float.width, bx + half_patch + 1),
                                ]

                                if patch.shape == (self.patch_size, self.patch_size, img_float.channels):
                                    # Compute distance to patches near (py, px)
                                    ref_patch = result[
                                        max(0, py - half_patch) : min(img_float.height, py + half_patch + 1),
                                        max(0, px - half_patch) : min(img_float.width, px + half_patch + 1),
                                    ]

                                    if ref_patch.shape == patch.shape:
                                        dist = np.sum((ref_patch - patch) ** 2)

                                        if dist < best_dist:
                                            best_dist = dist
                                            best_patch = patch.copy()

                if best_patch is not None:
                    y_start = max(0, py - half_patch)
                    y_end = min(img_float.height, py + half_patch + 1)
                    x_start = max(0, px - half_patch)
                    x_end = min(img_float.width, px + half_patch + 1)

                    result[y_start:y_end, x_start:x_end] = best_patch[: y_end - y_start, : x_end - x_start]
                    mask_work[y_start:y_end, x_start:x_end] = 0
                    processed.add((py, px))

            boundary = self._find_boundary(mask_work)
            if len(boundary) == len(processed):
                break

        return Image(
            data=np.clip(result, min_val, max_val).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    @staticmethod
    def _find_boundary(mask: np.ndarray) -> list:
        """Find boundary pixels between masked and unmasked regions."""
        boundary = []

        h, w = mask.shape
        for y in range(h):
            for x in range(w):
                if mask[y, x] > 0:
                    # Check if adjacent to unmasked region
                    has_valid_neighbor = False
                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] == 0:
                            has_valid_neighbor = True
                            break

                    if has_valid_neighbor:
                        boundary.append((y, x))

        return boundary

    def _compute_priorities(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        boundary: list,
        img_obj: Image,
    ) -> dict:
        """Compute priority for boundary pixels (confidence and data terms)."""
        priorities = {}
        half_patch = self.patch_size // 2

        # Compute confidence map
        confidence = 1.0 - (mask.astype(float) / 255.0)

        # Compute gradients for data term
        Gx = convolve(np.mean(image[:, :, :3], axis=2), np.array([[-1, 0, 1]]))
        Gy = convolve(np.mean(image[:, :, :3], axis=2), np.array([[-1], [0], [1]]))
        gradient = np.sqrt(Gx**2 + Gy**2)

        for py, px in boundary:
            # Confidence term: average confidence in patch
            patch_conf = np.mean(
                confidence[
                    max(0, py - half_patch) : min(image.shape[0], py + half_patch + 1),
                    max(0, px - half_patch) : min(image.shape[1], px + half_patch + 1),
                ]
            )

            # Data term: strength of edges perpendicular to boundary
            data = np.mean(
                gradient[
                    max(0, py - 2) : min(image.shape[0], py + 3),
                    max(0, px - 2) : min(image.shape[1], px + 3),
                ]
            )

            priority = patch_conf * (data + 1e-10)
            priorities[(py, px)] = priority

        return priorities

    def _find_best_patch(
        self, image: np.ndarray, mask: np.ndarray, py: int, px: int, patch_size: int
    ) -> tuple[np.ndarray | None, tuple[int, int] | None]:
        """Find best matching patch in valid region."""
        half_patch = patch_size // 2
        best_dist = float("inf")
        best_patch = None
        best_pos = None

        h, w = image.shape[:2]

        ref_patch = image[
            max(0, py - half_patch) : min(h, py + half_patch + 1),
            max(0, px - half_patch) : min(w, px + half_patch + 1),
        ]

        for sy in range(max(0, py - self.search_radius), min(h, py + self.search_radius)):
            for sx in range(max(0, px - self.search_radius), min(w, px + self.search_radius)):
                # Only consider patches in valid regions
                if mask[sy, sx] > 0:
                    continue

                search_patch = image[
                    max(0, sy - half_patch) : min(h, sy + half_patch + 1),
                    max(0, sx - half_patch) : min(w, sx + half_patch + 1),
                ]

                if search_patch.shape != ref_patch.shape:
                    continue

                # SSD distance
                dist = np.sum((ref_patch - search_patch) ** 2)

                if dist < best_dist:
                    best_dist = dist
                    best_patch = search_patch.copy()
                    best_pos = (sy, sx)

        return best_patch, best_pos

    @staticmethod
    def _patchmatch(image: np.ndarray, mask: np.ndarray) -> dict:
        """
        Compute approximate nearest neighbor field using PatchMatch.

        Returns mapping from masked patches to nearest valid patches.
        """
        h, w = image.shape[:2]
        nnf = {}

        # Simplified version: random search
        patch_size = 5
        patch_size // 2

        for y in range(h):
            for x in range(w):
                if mask[y, x] > 0:
                    # Random search for valid patch
                    for _ in range(10):
                        ry = np.random.randint(0, h)
                        rx = np.random.randint(0, w)

                        if mask[ry, rx] == 0:
                            nnf[(y, x)] = (ry, rx)
                            break

        return nnf
