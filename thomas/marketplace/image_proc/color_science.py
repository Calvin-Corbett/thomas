"""
Color science module.

Implements CIE color matching functions, color space conversions (XYZ, Lab, LCH),
chromatic adaptation, ICC profiles, color difference metrics, and white point detection.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ._types import Image


@dataclass
class ChromaticityPoint:
    """CIE chromaticity coordinates."""

    x: float
    y: float

    def to_xy(self) -> tuple[float, float]:
        """Return (x, y) tuple."""
        return (self.x, self.y)


@dataclass
class XYZColor:
    """Color in CIE XYZ space."""

    X: float
    Y: float
    Z: float

    def to_array(self) -> np.ndarray:
        """Return as numpy array."""
        return np.array([self.X, self.Y, self.Z])


class Illuminant:
    """Standard CIE illuminants."""

    # D65 (Daylight 6500K) - most common
    D65 = ChromaticityPoint(0.3127, 0.3291)

    # D50 (Daylight 5000K) - print and photography
    D50 = ChromaticityPoint(0.3457, 0.3585)

    # A (Incandescent 2856K)
    A = ChromaticityPoint(0.4476, 0.4074)

    # F11 (Fluorescent cool white)
    F11 = ChromaticityPoint(0.3805, 0.3769)

    @staticmethod
    def get_tristimulus(illuminant: ChromaticityPoint) -> np.ndarray:
        """Get XYZ tristimulus values for illuminant (Y=100)."""
        x, y = illuminant.x, illuminant.y

        if y == 0:
            raise ValueError("Illuminant y coordinate cannot be 0")

        X = (100 * x) / y
        Y = 100.0
        Z = (100 * (1 - x - y)) / y

        return np.array([X, Y, Z])


class ColorScience:
    """
    Color science operations.

    Implements color space conversions, color difference metrics,
    chromatic adaptation, and white point detection.
    """

    # CIE Standard Observer 2° Color Matching Functions (simplified)
    # In practice, use full 380-780nm tables
    CIE_CMF_WAVELENGTHS = np.array([400, 450, 500, 550, 600, 650, 700])
    CIE_CMF_X = np.array([0.0144, 0.0329, 0.0408, 0.9747, 0.7991, 0.2720, 0.0041])
    CIE_CMF_Y = np.array([0.0011, 0.0051, 0.0323, 1.0000, 0.6310, 0.1500, 0.0004])
    CIE_CMF_Z = np.array([0.0772, 0.5535, 1.5640, 0.9149, 0.0061, 0.0000, 0.0000])

    # Bradford chromatic adaptation matrix (for D65 to D50 conversion)
    BRADFORD_M = np.array(
        [
            [0.8951, 0.2664, -0.1614],
            [-0.7502, 1.7135, 0.0367],
            [0.0389, -0.0685, 1.0296],
        ]
    )

    BRADFORD_M_INV = np.linalg.inv(BRADFORD_M)

    @staticmethod
    def rgb_to_xyz(rgb: np.ndarray, color_space: str = "srgb") -> np.ndarray:
        """
        Convert RGB to CIE XYZ.

        Args:
            rgb: RGB values (0-1 or 0-255, inferred from range).
            color_space: 'srgb' or 'linear'.

        Returns:
            XYZ array with same shape as input.
        """
        # Normalize to 0-1
        rgb_norm = rgb.copy()
        if np.max(rgb_norm) > 1:
            rgb_norm = rgb_norm / 255.0

        # Apply gamma correction for sRGB
        if color_space == "srgb":
            mask = rgb_norm > 0.04045
            rgb_norm[mask] = ((rgb_norm[mask] + 0.055) / 1.055) ** 2.4
            rgb_norm[~mask] = rgb_norm[~mask] / 12.92

        # RGB to XYZ transformation matrix (sRGB)
        M = np.array(
            [
                [0.4124564, 0.3575761, 0.1804375],
                [0.2126729, 0.7151522, 0.0721750],
                [0.0193339, 0.1191920, 0.9503041],
            ]
        )

        # Apply to each pixel
        original_shape = rgb_norm.shape
        rgb_flat = rgb_norm.reshape(-1, 3)
        xyz_flat = (M @ rgb_flat.T).T
        xyz = xyz_flat.reshape(original_shape)

        return xyz

    @staticmethod
    def xyz_to_rgb(xyz: np.ndarray, color_space: str = "srgb") -> np.ndarray:
        """
        Convert CIE XYZ to RGB.

        Args:
            xyz: XYZ array.
            color_space: 'srgb' or 'linear'.

        Returns:
            RGB array (0-1 for sRGB, linear for others).
        """
        # XYZ to RGB inverse transformation
        M_inv = np.array(
            [
                [3.2404542, -1.5371385, -0.4985314],
                [-0.9692660, 1.8760108, 0.0415560],
                [0.0556434, -0.2040259, 1.0572252],
            ]
        )

        original_shape = xyz.shape
        xyz_flat = xyz.reshape(-1, 3)
        rgb_flat = (M_inv @ xyz_flat.T).T
        rgb_norm = rgb_flat.reshape(original_shape)

        # Apply inverse gamma for sRGB
        if color_space == "srgb":
            mask = rgb_norm > 0.0031308
            rgb_norm[mask] = 1.055 * (rgb_norm[mask] ** (1 / 2.4)) - 0.055
            rgb_norm[~mask] = 12.92 * rgb_norm[~mask]

        return np.clip(rgb_norm, 0, 1)

    @staticmethod
    def xyz_to_lab(xyz: np.ndarray, illuminant: ChromaticityPoint = Illuminant.D65) -> np.ndarray:
        """
        Convert CIE XYZ to Lab.

        Args:
            xyz: XYZ array.
            illuminant: Reference illuminant (default D65).

        Returns:
            Lab array.
        """
        # Get reference white point
        # Conversion routines in this module operate on XYZ values in [0, 1]
        # (Y ~= 1 for diffuse white), so normalize illuminant white points.
        ref_white = Illuminant.get_tristimulus(illuminant) / 100.0

        # Normalize by reference white
        xyz_norm = xyz.copy() if xyz.ndim == 1 else xyz.copy()
        if xyz.ndim == 3:
            xyz_norm = xyz_norm / ref_white[np.newaxis, np.newaxis, :]
        else:
            xyz_norm = xyz_norm / ref_white

        # Apply Lab transform
        delta = 0.206897

        def f(t):
            """Lab nonlinearity function."""
            return np.where(
                t > delta**3,
                t ** (1 / 3),
                t / (3 * delta**2) + 4 / 29,
            )

        if xyz.ndim == 3:
            f_xyz = np.zeros_like(xyz_norm)
            for c in range(3):
                f_xyz[:, :, c] = f(xyz_norm[:, :, c])

            L = 116 * f_xyz[:, :, 1] - 16
            a = 500 * (f_xyz[:, :, 0] - f_xyz[:, :, 1])
            b = 200 * (f_xyz[:, :, 1] - f_xyz[:, :, 2])

            return np.dstack([L, a, b])
        else:
            f_xyz = f(xyz_norm)
            L = 116 * f_xyz[1] - 16
            a = 500 * (f_xyz[0] - f_xyz[1])
            b = 200 * (f_xyz[1] - f_xyz[2])

            return np.array([L, a, b])

    @staticmethod
    def lab_to_xyz(lab: np.ndarray, illuminant: ChromaticityPoint = Illuminant.D65) -> np.ndarray:
        """
        Convert Lab to CIE XYZ.

        Args:
            lab: Lab array.
            illuminant: Reference illuminant.

        Returns:
            XYZ array.
        """
        ref_white = Illuminant.get_tristimulus(illuminant) / 100.0

        delta = 0.206897

        def f_inv(t):
            """Inverse Lab nonlinearity."""
            t3 = t**3
            return np.where(
                t3 > delta**3,
                t3,
                (t - 4 / 29) * 3 * delta**2,
            )

        if lab.ndim == 3:
            L, a, b = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]

            fy = (L + 16) / 116
            fx = a / 500 + fy
            fz = fy - b / 200

            xyz = np.zeros_like(lab)
            xyz[:, :, 0] = f_inv(fx) * ref_white[0]
            xyz[:, :, 1] = f_inv(fy) * ref_white[1]
            xyz[:, :, 2] = f_inv(fz) * ref_white[2]

            return xyz
        else:
            L, a, b = lab[0], lab[1], lab[2]

            fy = (L + 16) / 116
            fx = a / 500 + fy
            fz = fy - b / 200

            xyz = np.zeros(3)
            xyz[0] = f_inv(fx) * ref_white[0]
            xyz[1] = f_inv(fy) * ref_white[1]
            xyz[2] = f_inv(fz) * ref_white[2]

            return xyz

    @staticmethod
    def lab_to_lch(lab: np.ndarray) -> np.ndarray:
        """Convert Lab to LCH (cylindrical Lab)."""
        L = lab[..., 0]
        a = lab[..., 1]
        b = lab[..., 2]

        C = np.sqrt(a**2 + b**2)
        H = np.arctan2(b, a)

        # Convert H from radians to degrees
        H = np.degrees(H)
        H = np.where(H < 0, H + 360, H)

        if lab.ndim == 3:
            return np.dstack([L, C, H])
        else:
            return np.array([L, C, H])

    @staticmethod
    def lch_to_lab(lch: np.ndarray) -> np.ndarray:
        """Convert LCH to Lab."""
        L = lch[..., 0]
        C = lch[..., 1]
        H = lch[..., 2]

        # Convert H from degrees to radians
        H_rad = np.radians(H)

        a = C * np.cos(H_rad)
        b = C * np.sin(H_rad)

        if lch.ndim == 3:
            return np.dstack([L, a, b])
        else:
            return np.array([L, a, b])

    @staticmethod
    def chromatic_adaptation(
        xyz: np.ndarray, src_illuminant: ChromaticityPoint, dst_illuminant: ChromaticityPoint
    ) -> np.ndarray:
        """
        Perform chromatic adaptation using Bradford transform.

        Args:
            xyz: XYZ color.
            src_illuminant: Source illuminant.
            dst_illuminant: Destination illuminant.

        Returns:
            Adapted XYZ.
        """
        # Get illuminant tristimulus
        src_white = Illuminant.get_tristimulus(src_illuminant)
        dst_white = Illuminant.get_tristimulus(dst_illuminant)

        # Transform to cone response
        M = ColorScience.BRADFORD_M
        M_inv = ColorScience.BRADFORD_M_INV

        src_cone = M @ src_white
        dst_cone = M @ dst_white

        # Adaptation factor
        adapt_matrix = np.diag(dst_cone / (src_cone + 1e-10))

        # Convert color
        if xyz.ndim == 3:
            xyz_flat = xyz.reshape(-1, 3)
            cone = (M @ xyz_flat.T).T
            adapted_cone = (adapt_matrix @ cone.T).T
            adapted_xyz = (M_inv @ adapted_cone.T).T
            return adapted_xyz.reshape(xyz.shape)
        else:
            cone = M @ xyz
            adapted_cone = adapt_matrix @ cone
            return M_inv @ adapted_cone

    @staticmethod
    def delta_e_76(lab1: np.ndarray, lab2: np.ndarray) -> float:
        """
        Compute CIE 1976 color difference (ΔE*).

        Simple Euclidean distance in Lab space.
        """
        return np.sqrt(np.sum((lab1 - lab2) ** 2))

    @staticmethod
    def delta_e_94(lab1: np.ndarray, lab2: np.ndarray, application: str = "graphic") -> float:
        """
        Compute CIE 1994 color difference (ΔE*94).

        Args:
            lab1, lab2: Lab colors.
            application: 'graphic' or 'textile'.

        Returns:
            ΔE*94 value.
        """
        kL = 1.0
        kC = 0.045 if application == "graphic" else 0.048
        kH = 0.015 if application == "graphic" else 0.014

        dL = lab1[0] - lab2[0]
        da = lab1[1] - lab2[1]
        db = lab1[2] - lab2[2]

        dC = np.sqrt(lab1[1] ** 2 + lab1[2] ** 2) - np.sqrt(lab2[1] ** 2 + lab2[2] ** 2)
        dH = np.sqrt(da**2 + db**2 - dC**2)

        term1 = (dL / kL) ** 2
        term2 = (dC / (1 + kC * np.sqrt(lab1[1] ** 2 + lab1[2] ** 2))) ** 2
        term3 = (dH / kH) ** 2

        return np.sqrt(term1 + term2 + term3)

    @staticmethod
    def delta_e_2000(lab1: np.ndarray, lab2: np.ndarray, kL: float = 1.0) -> float:
        """
        Compute CIEDE2000 color difference.

        More accurate perceptual difference than ΔE*94.
        """
        L1, a1, b1 = lab1[0], lab1[1], lab1[2]
        L2, a2, b2 = lab2[0], lab2[1], lab2[2]

        C1 = np.sqrt(a1**2 + b1**2)
        C2 = np.sqrt(a2**2 + b2**2)
        Cbar = (C1 + C2) / 2

        G = 0.5 * (1 - np.sqrt(Cbar**7 / (Cbar**7 + 25**7)))
        a1_p = (1 + G) * a1
        a2_p = (1 + G) * a2

        C1_p = np.sqrt(a1_p**2 + b1**2)
        C2_p = np.sqrt(a2_p**2 + b2**2)

        h1_p = np.degrees(np.arctan2(b1, a1_p)) % 360
        h2_p = np.degrees(np.arctan2(b2, a2_p)) % 360

        dL_p = L2 - L1
        dC_p = C2_p - C1_p

        dh_p = h2_p - h1_p
        if abs(dh_p) > 180:
            dh_p = 360 - abs(dh_p)

        dH_p = 2 * np.sqrt(C1_p * C2_p) * np.sin(np.radians(dh_p / 2))

        Lbar_p = (L1 + L2) / 2
        Cbar_p = (C1_p + C2_p) / 2

        hbar_p = (h1_p + h2_p) / 2 if abs(h1_p - h2_p) <= 180 else (h1_p + h2_p + 360) / 2

        T = (
            1
            - 0.17 * np.cos(np.radians(hbar_p - 30))
            + 0.24 * np.cos(np.radians(2 * hbar_p))
            + 0.32 * np.cos(np.radians(3 * hbar_p + 6))
            - 0.20 * np.cos(np.radians(4 * hbar_p - 63))
        )

        f = 2 * np.sqrt(Cbar_p**4 / (Cbar_p**4 + 1900))
        Sl = 1 + (0.015 * (Lbar_p - 50) ** 2) / np.sqrt(20 + (Lbar_p - 50) ** 2)
        Sc = 1 + 0.045 * Cbar_p
        Sh = 1 + 0.015 * Cbar_p * T

        term1 = (dL_p / (kL * Sl)) ** 2
        term2 = (dC_p / (1 * Sc)) ** 2
        term3 = (dH_p / (1 * Sh)) ** 2

        return np.sqrt(term1 + term2 + term3)

    @staticmethod
    def estimate_white_point(image: Image) -> tuple[float, float]:
        """
        Estimate white point color temperature from image.

        Uses Robertson's method with reference temperatures.

        Args:
            image: Input RGB image.

        Returns:
            (color_temperature_K, xy_chromaticity).
        """
        img_float = image.to_float32()

        # Extract neutral pixels (high brightness, low saturation)
        gray = np.mean(img_float.data, axis=2)
        hsv_sat = np.std(img_float.data, axis=2) / (np.mean(img_float.data, axis=2) + 1e-10)

        neutral_mask = (gray > 0.5) & (hsv_sat < 0.1)

        if not np.any(neutral_mask):
            # Default to D65
            return 6500.0, Illuminant.D65.to_xy()

        neutral_pixels = img_float.data[neutral_mask]
        avg_color = np.mean(neutral_pixels, axis=0)

        # Convert to xy chromaticity
        xyz = ColorScience.rgb_to_xyz(avg_color[np.newaxis, np.newaxis, :])
        X, Y, Z = xyz[0, 0]

        sum_xyz = X + Y + Z
        if sum_xyz < 1e-10:
            return 6500.0, Illuminant.D65.to_xy()

        x = X / sum_xyz
        y = Y / sum_xyz

        # Robertson's method: lookup table approach (simplified)
        cct = 6500.0  # Default
        if y > 0:
            cct = ColorScience._xy_to_cct(x, y)

        return cct, (x, y)

    @staticmethod
    def _xy_to_cct(x: float, y: float) -> float:
        """Convert xy chromaticity to color temperature (Robertson's method)."""
        # Simplified: use planckian locus approximation
        n = (x - 0.3366) / (0.1735 - y)
        cct = 949.2 * (n**3) + 6253.8 * (n**2) + 28000.7 * n + 0.44 * 5000

        return np.clip(cct, 1500, 15000)
