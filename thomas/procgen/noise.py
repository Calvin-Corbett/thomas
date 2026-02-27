"""
Noise functions for procedural generation.

Implements multiple noise algorithms including Perlin, Simplex, Worley,
and various fractal combinations.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from thomas.procgen._exceptions import InvalidConfigError


@dataclass
class PerlinNoise:
    """
    Perlin noise implementation with permutation table and gradient interpolation.

    Classic smooth noise for natural-looking terrain generation.
    """

    seed: int = 42
    _permutation: list[int] = None

    def __post_init__(self) -> None:
        """Initialize permutation table from seed."""
        random.seed(self.seed)
        base_perm = list(range(256))
        random.shuffle(base_perm)
        self._permutation = base_perm + base_perm

    def _fade(self, t: float) -> float:
        """Fade function using Hermite curve: 6t^5 - 15t^4 + 10t^3."""
        return t * t * t * (t * (t * 6 - 15) + 10)

    def _lerp(self, t: float, a: float, b: float) -> float:
        """Linear interpolation between two values."""
        return a + t * (b - a)

    def _gradient(self, hash_val: int, x: float, y: float) -> float:
        """Calculate gradient dot product for 2D Perlin noise."""
        # 16 gradient vectors
        h = hash_val & 15
        u = x if h < 8 else y
        v = y if h < 8 else x
        return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)

    def get_2d(self, x: float, y: float) -> float:
        """
        Get 2D Perlin noise value at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Noise value in range [-1, 1]
        """
        xi = int(x) & 255
        yi = int(y) & 255

        xf = x - int(x)
        yf = y - int(y)

        u = self._fade(xf)
        v = self._fade(yf)

        perm = self._permutation
        a = perm[xi] + yi
        aa = perm[a]
        ab = perm[a + 1]
        b = perm[xi + 1] + yi
        ba = perm[b]
        bb = perm[b + 1]

        g_aa = self._gradient(perm[aa], xf, yf)
        g_ba = self._gradient(perm[ba], xf - 1, yf)
        g_ab = self._gradient(perm[ab], xf, yf - 1)
        g_bb = self._gradient(perm[bb], xf - 1, yf - 1)

        lerp_x1 = self._lerp(u, g_aa, g_ba)
        lerp_x2 = self._lerp(u, g_ab, g_bb)
        return self._lerp(v, lerp_x1, lerp_x2)

    def get_3d(self, x: float, y: float, z: float) -> float:
        """
        Get 3D Perlin noise value at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            z: Z coordinate

        Returns:
            Noise value in range [-1, 1]
        """
        xi = int(x) & 255
        yi = int(y) & 255
        zi = int(z) & 255

        xf = x - int(x)
        yf = y - int(y)
        zf = z - int(z)

        u = self._fade(xf)
        v = self._fade(yf)
        w = self._fade(zf)

        perm = self._permutation

        a = perm[xi] + yi
        aa = perm[a] + zi
        ab = perm[a + 1] + zi
        b = perm[xi + 1] + yi
        ba = perm[b] + zi
        bb = perm[b + 1] + zi

        g_aaa = self._gradient(perm[aa], xf, yf)
        g_baa = self._gradient(perm[ba], xf - 1, yf)
        g_aba = self._gradient(perm[ab], xf, yf - 1)
        g_bba = self._gradient(perm[bb], xf - 1, yf - 1)

        lerp_x1 = self._lerp(u, g_aaa, g_baa)
        lerp_x2 = self._lerp(u, g_aba, g_bba)
        lerp_y1 = self._lerp(v, lerp_x1, lerp_x2)

        g_aab = self._gradient(perm[aa + 1], xf, yf - 1 - zf)
        g_bab = self._gradient(perm[ba + 1], xf - 1, yf - zf)
        g_abb = self._gradient(perm[ab + 1], xf, yf - 1 - 1 - zf)
        g_bbb = self._gradient(perm[bb + 1], xf - 1, yf - 1 - zf)

        lerp_x3 = self._lerp(u, g_aab, g_bab)
        lerp_x4 = self._lerp(u, g_abb, g_bbb)
        lerp_y2 = self._lerp(v, lerp_x3, lerp_x4)

        return self._lerp(w, lerp_y1, lerp_y2)


@dataclass
class SimplexNoise:
    """
    Simplex noise implementation with coordinate skewing.

    Faster than Perlin noise with better high-dimension scaling.
    """

    seed: int = 42
    _permutation: list[int] = None
    _grad3: list[tuple[int, int, int]] = None

    def __post_init__(self) -> None:
        """Initialize permutation table and gradients."""
        random.seed(self.seed)
        base_perm = list(range(256))
        random.shuffle(base_perm)
        self._permutation = base_perm + base_perm

        self._grad3 = [
            (1, 1, 0),
            (-1, 1, 0),
            (1, -1, 0),
            (-1, -1, 0),
            (1, 0, 1),
            (-1, 0, 1),
            (1, 0, -1),
            (-1, 0, -1),
            (0, 1, 1),
            (0, -1, 1),
            (0, 1, -1),
            (0, -1, -1),
        ]

    def _dot(self, g: tuple[int, int, int], x: float, y: float) -> float:
        """Dot product of gradient and offset."""
        return g[0] * x + g[1] * y

    def get_2d(self, x: float, y: float) -> float:
        """
        Get 2D Simplex noise value.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Noise value in range [-1, 1]
        """
        F2 = 0.5 * (math.sqrt(3.0) - 1.0)
        s = (x + y) * F2
        i = int(x + s)
        j = int(y + s)

        G2 = (3.0 - math.sqrt(3.0)) / 6.0
        t0 = (i + j) * G2
        x0 = i - t0
        y0 = j - t0
        x0_rel = x - x0
        y0_rel = y - y0

        # Determine which simplex we're in
        if x0_rel > y0_rel:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1

        x1 = x0_rel - i1 + G2
        y1 = y0_rel - j1 + G2
        x2 = x0_rel - 1.0 + 2.0 * G2
        y2 = y0_rel - 1.0 + 2.0 * G2

        ii = i & 255
        jj = j & 255
        perm = self._permutation

        gi0 = perm[ii + perm[jj]] % 12
        gi1 = perm[ii + i1 + perm[jj + j1]] % 12
        gi2 = perm[ii + 1 + perm[jj + 1]] % 12

        t0 = 0.5 - x0_rel * x0_rel - y0_rel * y0_rel
        n0 = 0.0 if t0 < 0 else (t0**4) * self._dot(self._grad3[gi0], x0_rel, y0_rel)

        t1 = 0.5 - x1 * x1 - y1 * y1
        n1 = 0.0 if t1 < 0 else (t1**4) * self._dot(self._grad3[gi1], x1, y1)

        t2 = 0.5 - x2 * x2 - y2 * y2
        n2 = 0.0 if t2 < 0 else (t2**4) * self._dot(self._grad3[gi2], x2, y2)

        return 70.0 * (n0 + n1 + n2)


@dataclass
class WorleyNoise:
    """
    Worley/Cellular noise using distance to nearest points.

    Useful for generating cellular patterns, stone textures, and organic structures.
    """

    seed: int = 42
    cell_size: float = 25.0
    distance_metric: str = "euclidean"
    _feature_points: dict[tuple[int, int], list[tuple[float, float]]] = None

    def __post_init__(self) -> None:
        """Initialize feature points grid."""
        if self.distance_metric not in ("euclidean", "manhattan", "chebyshev"):
            raise InvalidConfigError(
                f"Unknown distance metric: {self.distance_metric}",
                "distance_metric",
            )
        self._feature_points = {}
        random.seed(self.seed)

    def _get_feature_points(self, grid_x: int, grid_y: int) -> list[tuple[float, float]]:
        """Get or generate feature points for a cell."""
        key = (grid_x, grid_y)
        if key not in self._feature_points:
            random.seed(self.seed + grid_x * 73856093 ^ grid_y * 19349663)
            points = []
            for _ in range(random.randint(1, 3)):
                px = grid_x * self.cell_size + random.uniform(0, self.cell_size)
                py = grid_y * self.cell_size + random.uniform(0, self.cell_size)
                points.append((px, py))
            self._feature_points[key] = points
        return self._feature_points[key]

    def _distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate distance based on selected metric."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)

        if self.distance_metric == "euclidean":
            return math.sqrt(dx * dx + dy * dy)
        elif self.distance_metric == "manhattan":
            return dx + dy
        else:  # chebyshev
            return max(dx, dy)

    def get_f1(self, x: float, y: float) -> float:
        """
        Get F1 distance (closest feature point).

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Distance to nearest feature point
        """
        grid_x = int(x / self.cell_size)
        grid_y = int(y / self.cell_size)

        min_distance = float("inf")

        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                points = self._get_feature_points(grid_x + dx, grid_y + dy)
                for px, py in points:
                    dist = self._distance(x, y, px, py)
                    if dist < min_distance:
                        min_distance = dist

        return min_distance / self.cell_size

    def get_f2(self, x: float, y: float) -> float:
        """
        Get F2 distance (second nearest feature point).

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Distance to second nearest feature point
        """
        grid_x = int(x / self.cell_size)
        grid_y = int(y / self.cell_size)

        distances = []

        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                points = self._get_feature_points(grid_x + dx, grid_y + dy)
                for px, py in points:
                    dist = self._distance(x, y, px, py)
                    distances.append(dist)

        distances.sort()
        return distances[1] / self.cell_size if len(distances) > 1 else 1.0


def fractal_brownian_motion(
    noise_func: Callable[[float, float], float],
    x: float,
    y: float,
    octaves: int = 4,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
    amplitude: float = 1.0,
    frequency: float = 1.0,
) -> float:
    """
    Generate fractional Brownian motion by layering octaves of noise.

    Args:
        noise_func: Noise function that takes (x, y) and returns [-1, 1]
        x: X coordinate
        y: Y coordinate
        octaves: Number of octaves to layer
        persistence: Amplitude reduction per octave
        lacunarity: Frequency multiplication per octave
        amplitude: Initial amplitude
        frequency: Initial frequency

    Returns:
        Composite noise value
    """
    if octaves < 1:
        raise InvalidConfigError("Octaves must be >= 1", "octaves")
    if not (0 < persistence <= 1):
        raise InvalidConfigError("Persistence must be in (0, 1]", "persistence")
    if lacunarity <= 1:
        raise InvalidConfigError("Lacunarity must be > 1", "lacunarity")

    result = 0.0
    max_amplitude = 0.0

    for _ in range(octaves):
        result += noise_func(x * frequency, y * frequency) * amplitude
        max_amplitude += amplitude

        amplitude *= persistence
        frequency *= lacunarity

    return result / max_amplitude if max_amplitude > 0 else 0.0


def domain_warp(
    noise_func: Callable[[float, float], float],
    warp_func: Callable[[float, float], float],
    x: float,
    y: float,
    warp_strength: float = 0.1,
) -> float:
    """
    Apply domain warping to noise by displacing coordinates.

    Args:
        noise_func: Noise function to warp
        warp_func: Noise function for displacement
        x: X coordinate
        y: Y coordinate
        warp_strength: How much to displace coordinates

    Returns:
        Warped noise value
    """
    warp_x = warp_func(x, y) * warp_strength
    warp_y = warp_func(x + 1000, y + 1000) * warp_strength

    return noise_func(x + warp_x, y + warp_y)


def value_noise(x: float, y: float, seed: int = 42, scale: float = 1.0) -> float:
    """
    Simple value noise based on grid values and interpolation.

    Args:
        x: X coordinate
        y: Y coordinate
        seed: Random seed for reproducibility
        scale: Frequency scale

    Returns:
        Noise value in range [-1, 1]
    """
    x *= scale
    y *= scale

    xi = int(x)
    yi = int(y)
    xf = x - xi
    yf = y - yi

    # Fade function
    u = xf * xf * (3.0 - 2.0 * xf)
    v = yf * yf * (3.0 - 2.0 * yf)

    def hash_value(ix: int, iy: int) -> float:
        random.seed(seed + ix * 73856093 ^ iy * 19349663)
        return random.uniform(-1, 1)

    n00 = hash_value(xi, yi)
    n10 = hash_value(xi + 1, yi)
    n01 = hash_value(xi, yi + 1)
    n11 = hash_value(xi + 1, yi + 1)

    nx0 = n00 + u * (n10 - n00)
    nx1 = n01 + u * (n11 - n01)

    return nx0 + v * (nx1 - nx0)


def turbulence(
    noise_func: Callable[[float, float], float],
    x: float,
    y: float,
    octaves: int = 4,
) -> float:
    """
    Generate turbulence by taking absolute values of noise octaves.

    Useful for creating chaotic patterns.

    Args:
        noise_func: Noise function that takes (x, y)
        x: X coordinate
        y: Y coordinate
        octaves: Number of octaves to layer

    Returns:
        Turbulent noise value
    """
    result = 0.0
    amplitude = 1.0
    frequency = 1.0
    max_amplitude = 0.0

    for _ in range(octaves):
        result += abs(noise_func(x * frequency, y * frequency)) * amplitude
        max_amplitude += amplitude
        amplitude *= 0.5
        frequency *= 2.0

    return result / max_amplitude if max_amplitude > 0 else 0.0


def ridged_multifractal(
    noise_func: Callable[[float, float], float],
    x: float,
    y: float,
    octaves: int = 4,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> float:
    """
    Generate ridged multifractal noise (inverted sharp peaks).

    Useful for mountain ranges and sharp terrain features.

    Args:
        noise_func: Noise function that takes (x, y)
        x: X coordinate
        y: Y coordinate
        octaves: Number of octaves
        persistence: Amplitude reduction per octave
        lacunarity: Frequency multiplication per octave

    Returns:
        Ridged noise value
    """
    result = 0.0
    amplitude = 1.0
    frequency = 1.0
    max_amplitude = 0.0
    ridge_offset = 1.0

    for _ in range(octaves):
        sample = noise_func(x * frequency, y * frequency)
        sample = ridge_offset - abs(sample)
        sample = sample * sample
        result += sample * amplitude
        max_amplitude += amplitude

        amplitude *= persistence
        frequency *= lacunarity

    return result / max_amplitude if max_amplitude > 0 else 0.0
