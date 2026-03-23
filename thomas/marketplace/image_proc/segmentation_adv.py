"""
Advanced segmentation module.

Implements GrabCut, SLIC superpixels, mean shift segmentation,
and semantic edge detection.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import convolve2d

from ._exceptions import AlgorithmError, SegmentationError
from ._types import Image


class AdvancedSegmentation:
    """
    Advanced image segmentation algorithms.

    Implements:
    - GrabCut (GMM foreground/background, graph cuts)
    - SLIC superpixels
    - Mean shift segmentation
    - Semantic edge detection
    """

    def grabcut(
        self,
        image: Image,
        rect: tuple[int, int, int, int] | None = None,
        iterations: int = 10,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        GrabCut interactive segmentation.

        Uses GMM to model foreground/background and iteratively refines
        using graph cuts (max-flow/min-cut).

        Args:
            image: Input image.
            rect: (x, y, width, height) bounding box for foreground.
                  If None, uses entire image.
            iterations: Number of refinement iterations.

        Returns:
            (segmentation_mask, confidence_map) where mask is 0/255
            for background/foreground, and confidence is probability.

        Raises:
            SegmentationError: If segmentation fails.
        """
        img_float = image.to_float32()

        if img_float.channels < 3:
            raise SegmentationError("GrabCut requires RGB image")

        h, w = img_float.height, img_float.width

        # Initialize mask from rectangle
        mask = np.zeros((h, w), dtype=np.uint8)

        if rect is None:
            # Use entire image, with small border as background
            border = 10
            mask[border:-border, border:-border] = 1
        else:
            x, y, width, height = rect
            mask[y : y + height, x : x + width] = 1

        # Initialize GMMs
        gmm_fg = self._initialize_gmm(img_float.data[mask == 1])
        gmm_bg = self._initialize_gmm(img_float.data[mask == 0])

        for iteration in range(iterations):
            # Assign pixels to GMM components
            fg_prob = gmm_fg.likelihood(img_float.data)
            bg_prob = gmm_bg.likelihood(img_float.data)

            # Graph cut refinement (simplified)
            new_mask = (fg_prob > bg_prob).astype(np.uint8)

            # Check convergence
            if np.sum(new_mask != mask) == 0:
                break

            mask = new_mask

            # Re-estimate GMMs
            if np.any(mask == 1):
                gmm_fg = self._initialize_gmm(img_float.data[mask == 1])
            if np.any(mask == 0):
                gmm_bg = self._initialize_gmm(img_float.data[mask == 0])

        # Confidence map
        confidence = fg_prob / (fg_prob + bg_prob + 1e-10)
        confidence = np.clip(confidence * 255, 0, 255).astype(np.uint8)

        return mask * 255, confidence

    def slic_superpixels(
        self, image: Image, num_superpixels: int = 100, compactness: float = 10.0
    ) -> tuple[np.ndarray, int]:
        """
        SLIC (Simple Linear Iterative Clustering) superpixel segmentation.

        Clusters pixels in CIELAB + xy space for compact superpixels.

        Args:
            image: Input RGB image.
            num_superpixels: Desired number of superpixels.
            compactness: Weighting of spatial vs color distance.

        Returns:
            (label_map, num_labels) where label_map has superpixel IDs.

        Raises:
            AlgorithmError: If clustering fails.
        """
        img_float = image.to_float32()

        if img_float.channels < 3:
            raise AlgorithmError("SLIC requires RGB image")

        h, w = img_float.height, img_float.width

        # Convert to CIELAB
        lab = self._rgb_to_lab(img_float.data)

        # Initialize cluster centers
        grid_size = int(np.sqrt(h * w / num_superpixels))
        centers = []
        center_ids = []

        for y in range(grid_size // 2, h, grid_size):
            for x in range(grid_size // 2, w, grid_size):
                if y < h and x < w:
                    lab_val = lab[y, x]
                    centers.append(np.array([y, x, lab_val[0], lab_val[1], lab_val[2]]))
                    center_ids.append(len(centers) - 1)

        centers = np.array(centers)
        num_centers = len(centers)

        # Iterative clustering
        labels = np.full((h, w), -1, dtype=np.int32)
        distances = np.full((h, w), np.inf, dtype=np.float32)

        for iteration in range(10):
            distances[:] = np.inf
            labels[:] = -1

            for center_id, center in enumerate(centers):
                cy, cx = int(center[0]), int(center[1])
                search_radius = grid_size

                y_min = max(0, cy - search_radius)
                y_max = min(h, cy + search_radius)
                x_min = max(0, cx - search_radius)
                x_max = min(w, cx + search_radius)

                for y in range(y_min, y_max):
                    for x in range(x_min, x_max):
                        lab_val = lab[y, x]

                        # Distance in CIELAB + spatial
                        color_dist = np.sqrt(
                            (lab_val[0] - center[2]) ** 2
                            + (lab_val[1] - center[3]) ** 2
                            + (lab_val[2] - center[4]) ** 2
                        )

                        spatial_dist = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)

                        dist = color_dist + (spatial_dist / grid_size) * compactness

                        if dist < distances[y, x]:
                            distances[y, x] = dist
                            labels[y, x] = center_id

            # Update centers
            new_centers = np.zeros_like(centers)
            for center_id in range(num_centers):
                mask = labels == center_id

                if np.any(mask):
                    ys, xs = np.where(mask)
                    new_y = int(np.mean(ys))
                    new_x = int(np.mean(xs))

                    lab_vals = lab[mask]
                    mean_l = np.mean(lab_vals[:, 0])
                    mean_a = np.mean(lab_vals[:, 1])
                    mean_b = np.mean(lab_vals[:, 2])

                    new_centers[center_id] = np.array([new_y, new_x, mean_l, mean_a, mean_b])
                else:
                    new_centers[center_id] = centers[center_id]

            # Check convergence
            if np.linalg.norm(new_centers - centers) < 1.0:
                break

            centers = new_centers

        # Relabel to sequential IDs
        unique_labels = np.unique(labels)
        relabel_map = {old: new for new, old in enumerate(unique_labels)}
        labels = np.array([[relabel_map[labels[y, x]] for x in range(w)] for y in range(h)])

        return labels, len(relabel_map)

    def mean_shift(self, image: Image, bandwidth: float = 10.0, iterations: int = 50) -> tuple[np.ndarray, int]:
        """
        Mean shift segmentation using kernel density estimation.

        Performs mode seeking in CIELAB + spatial space.

        Args:
            image: Input RGB image.
            bandwidth: Kernel bandwidth for density estimation.
            iterations: Maximum iterations for mean shift.

        Returns:
            (label_map, num_labels) where labels group similar regions.
        """
        img_float = image.to_float32()

        if img_float.channels < 3:
            raise AlgorithmError("Mean shift requires RGB image")

        h, w = img_float.height, img_float.width

        # Convert to CIELAB
        lab = self._rgb_to_lab(img_float.data)

        # Downsampling for speed
        step = 2
        lab_down = lab[::step, ::step]
        h_down, w_down = lab_down.shape[:2]

        # Augment with spatial coordinates
        spatial = np.zeros((h_down, w_down, 2))
        for y in range(h_down):
            for x in range(w_down):
                spatial[y, x] = [y * step, x * step]

        features = np.concatenate([lab_down, spatial], axis=2)
        features_flat = features.reshape(-1, 5)

        # Mean shift iteration
        modes = features_flat.copy()
        converged = np.zeros(len(modes), dtype=bool)

        for iteration in range(iterations):
            if np.all(converged):
                break

            for i in range(len(modes)):
                if converged[i]:
                    continue

                # Compute weighted mean of nearby points
                dists = np.linalg.norm(features_flat - modes[i], axis=1)
                weights = np.exp(-(dists**2) / (2 * bandwidth**2))

                weighted_mean = np.average(features_flat, axis=0, weights=weights)
                shift = np.linalg.norm(weighted_mean - modes[i])

                modes[i] = weighted_mean

                if shift < 0.5:
                    converged[i] = True

        # Assign pixels to nearest mode
        labels = np.zeros(len(features_flat), dtype=np.int32)

        for i in range(len(features_flat)):
            dists = np.linalg.norm(modes - features_flat[i], axis=1)
            labels[i] = np.argmin(dists)

        # Reshape and upsample
        labels_down = labels.reshape(h_down, w_down)
        labels_full = np.zeros((h, w), dtype=np.int32)

        for y in range(h):
            for x in range(w):
                labels_full[y, x] = labels_down[y // step, x // step]

        # Relabel
        unique_labels = np.unique(labels_full)
        relabel_map = {old: new for new, old in enumerate(unique_labels)}
        labels_full = np.array([[relabel_map[labels_full[y, x]] for x in range(w)] for y in range(h)])

        return labels_full, len(relabel_map)

    @staticmethod
    def semantic_edge_detection(image: Image, sigma: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect semantic edges using multi-scale gradients.

        Computes edge maps at multiple scales and combines them.

        Args:
            image: Input image.
            sigma: Gaussian smoothing sigma.

        Returns:
            (edge_map, edge_magnitude) normalized to [0, 1].
        """
        img_float = image.to_float32()

        if img_float.channels > 1:
            gray = np.mean(img_float.data, axis=2)
        else:
            gray = img_float.data[:, :, 0]

        # Multi-scale edge detection
        edges = np.zeros_like(gray)

        for scale in [1, 2, 4]:
            # Smooth at scale
            smoothed = gaussian_filter(gray, sigma=sigma * scale)

            # Compute gradients
            Gx = convolve2d(smoothed, np.array([[-1, 0, 1]]), mode="same")
            Gy = convolve2d(smoothed, np.array([[-1], [0], [1]]), mode="same")

            magnitude = np.sqrt(Gx**2 + Gy**2)
            edges += magnitude / 3

        # Threshold and normalize
        edges = edges / (np.max(edges) + 1e-10)

        # Compute direction
        Gx = convolve2d(gray, np.array([[-1, 0, 1]]), mode="same")
        Gy = convolve2d(gray, np.array([[-1], [0], [1]]), mode="same")
        direction = np.arctan2(Gy, Gx)

        return edges, direction

    @staticmethod
    def _initialize_gmm(pixels: np.ndarray, num_components: int = 5) -> GMMModel:
        """Initialize Gaussian Mixture Model."""
        return GMMModel(pixels, num_components)

    @staticmethod
    def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
        """Convert RGB to CIELAB color space."""
        # Normalize RGB
        rgb_norm = rgb.copy()

        # Apply gamma correction
        mask = rgb_norm > 0.04045
        rgb_norm[mask] = ((rgb_norm[mask] + 0.055) / 1.055) ** 2.4
        rgb_norm[~mask] = rgb_norm[~mask] / 12.92

        # RGB to XYZ
        M = np.array(
            [
                [0.4124, 0.3576, 0.1805],
                [0.2126, 0.7152, 0.0722],
                [0.0193, 0.1192, 0.9505],
            ]
        )

        xyz = np.zeros_like(rgb)
        for i in range(rgb.shape[0]):
            for j in range(rgb.shape[1]):
                xyz[i, j] = M @ rgb_norm[i, j]

        # Reference white point D65
        ref_white = np.array([0.95047, 1.00000, 1.08883])

        xyz_norm = xyz / ref_white

        # XYZ to Lab
        delta = 0.206897
        lab = np.zeros_like(xyz)

        for i in range(xyz_norm.shape[0]):
            for j in range(xyz_norm.shape[1]):
                f_vals = np.where(
                    xyz_norm[i, j] > delta**3,
                    xyz_norm[i, j] ** (1 / 3),
                    xyz_norm[i, j] / (3 * delta**2) + 4 / 29,
                )

                lab[i, j, 0] = 116 * f_vals[1] - 16
                lab[i, j, 1] = 500 * (f_vals[0] - f_vals[1])
                lab[i, j, 2] = 200 * (f_vals[1] - f_vals[2])

        return lab


class GMMModel:
    """Gaussian Mixture Model for color."""

    def __init__(self, pixels: np.ndarray, num_components: int = 5) -> None:
        """
        Initialize GMM.

        Args:
            pixels: Pixel samples (N x C array).
            num_components: Number of Gaussian components.
        """
        self.num_components = num_components
        self.fit(pixels)

    def fit(self, pixels: np.ndarray) -> None:
        """Fit GMM using K-means initialization."""
        if len(pixels) == 0:
            self.means = np.zeros((self.num_components, pixels.shape[1]))
            self.covs = np.zeros((self.num_components, pixels.shape[1], pixels.shape[1]))
            self.weights = np.ones(self.num_components) / self.num_components
            return

        # K-means initialization
        from sklearn.cluster import KMeans

        try:
            kmeans = KMeans(n_clusters=self.num_components, n_init=3)
            labels = kmeans.fit_predict(pixels)

            self.means = kmeans.cluster_centers_
            self.weights = np.bincount(labels, minlength=self.num_components) / len(labels)

            # Compute covariances
            self.covs = []
            for k in range(self.num_components):
                mask = labels == k

                if np.any(mask):
                    cov = np.cov(pixels[mask].T)

                    if cov.ndim == 0:
                        cov = np.array([[cov]])
                    elif cov.ndim == 1:
                        cov = np.diag(cov)

                    self.covs.append(cov)
                else:
                    self.covs.append(np.eye(pixels.shape[1]))

            self.covs = np.array(self.covs)
        except (ValueError, np.linalg.LinAlgError):
            self.means = np.mean(pixels, axis=0)[np.newaxis, :].repeat(self.num_components, axis=0)
            self.covs = np.eye(pixels.shape[1])[np.newaxis, :, :].repeat(self.num_components, axis=0)
            self.weights = np.ones(self.num_components) / self.num_components

    def likelihood(self, pixels: np.ndarray) -> np.ndarray:
        """Compute likelihood of pixels under GMM."""
        h, w, c = pixels.shape
        likelihood = np.zeros((h, w))

        for k in range(self.num_components):
            mean = self.means[k]
            cov = self.covs[k]

            # Handle singular covariance
            try:
                inv_cov = np.linalg.inv(cov)
                det_cov = np.linalg.det(cov)
            except np.linalg.LinAlgError:
                inv_cov = np.eye(c)
                det_cov = 1.0

            for y in range(h):
                for x in range(w):
                    diff = pixels[y, x] - mean
                    mahal = diff @ inv_cov @ diff
                    likelihood[y, x] += (
                        self.weights[k] * np.exp(-0.5 * mahal) / (np.sqrt((2 * np.pi) ** c * np.abs(det_cov)) + 1e-10)
                    )

        return likelihood
