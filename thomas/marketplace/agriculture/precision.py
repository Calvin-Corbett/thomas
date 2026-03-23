"""Precision agriculture module for data-driven farm management."""

from dataclasses import dataclass

from thomas.marketplace.agriculture._exceptions import PrecisionError


@dataclass
class Point2D:
    """2D coordinate for field mapping."""

    x: float
    y: float


class NDVICalculator:
    """Calculates Normalized Difference Vegetation Index (NDVI)."""

    @staticmethod
    def calculate_ndvi(
        near_infrared_reflectance: float,
        red_reflectance: float,
    ) -> float:
        """Calculate NDVI from spectral bands.

        NDVI = (NIR - RED) / (NIR + RED)

        Values typically range from -1 to 1:
        - < 0: Water or non-vegetative
        - 0-0.3: Sparse vegetation
        - 0.3-0.6: Moderate vegetation
        - > 0.6: Dense vegetation

        Args:
            near_infrared_reflectance: Reflectance in near-infrared band
            red_reflectance: Reflectance in red band

        Returns:
            NDVI value (-1 to 1)
        """
        denominator = near_infrared_reflectance + red_reflectance
        if denominator == 0:
            return 0.0

        ndvi = (near_infrared_reflectance - red_reflectance) / denominator
        return round(ndvi, 3)

    @staticmethod
    def interpret_ndvi(ndvi_value: float) -> str:
        """Interpret NDVI value.

        Args:
            ndvi_value: NDVI value

        Returns:
            Vegetation classification
        """
        if ndvi_value < 0:
            return "Water or Bare Soil"
        elif ndvi_value < 0.2:
            return "Sparse Vegetation"
        elif ndvi_value < 0.4:
            return "Low Vegetation"
        elif ndvi_value < 0.6:
            return "Moderate Vegetation"
        else:
            return "Dense Healthy Vegetation"


class ZoneManagement:
    """Creates management zones for variable rate application."""

    @staticmethod
    def kmeans_clustering(
        data_points: list[list[float]],
        k: int = 3,
        iterations: int = 10,
    ) -> dict[int, list[int]]:
        """Simple k-means clustering for zone creation.

        Clusters field into k zones based on multispectral properties.

        Args:
            data_points: List of [ndvi, yield, soil_test, ...] values
            k: Number of zones to create
            iterations: Maximum iterations

        Returns:
            Dictionary of zone: [point_indices] mapping
        """
        if not data_points or k <= 0:
            raise PrecisionError("Invalid data points or k value")

        n = len(data_points)
        if k > n:
            k = n

        # Initialize cluster assignments randomly
        assignments = {}
        for i in range(n):
            assignments[i] = i % k

        for _ in range(iterations):
            # Calculate cluster centers
            centers = {}
            for cluster_id in range(k):
                points_in_cluster = [data_points[i] for i in range(n) if assignments[i] == cluster_id]
                if points_in_cluster:
                    center = [
                        sum(p[j] for p in points_in_cluster) / len(points_in_cluster)
                        for j in range(len(data_points[0]))
                    ]
                    centers[cluster_id] = center

            # Reassign to nearest center
            old_assignments = assignments.copy()
            for i in range(n):
                min_distance = float("inf")
                nearest_cluster = 0
                for cluster_id, center in centers.items():
                    distance = sum((data_points[i][j] - center[j]) ** 2 for j in range(len(data_points[0])))
                    if distance < min_distance:
                        min_distance = distance
                        nearest_cluster = cluster_id
                assignments[i] = nearest_cluster

            # Check for convergence
            if old_assignments == assignments:
                break

        # Group points by cluster
        zones = {}
        for cluster_id in range(k):
            zones[cluster_id] = [i for i in range(n) if assignments[i] == cluster_id]

        return zones


class VariableRateMap:
    """Generates variable rate application maps."""

    @staticmethod
    def create_vr_nitrogen_map(
        zones: dict[int, list[int]],
        yield_data: list[float],
        base_rate_lbs_acre: float,
    ) -> dict[int, float]:
        """Create variable rate N map based on yield zones.

        Args:
            zones: Dictionary of zone_id: [point_indices]
            yield_data: Yield values for each point
            base_rate_lbs_acre: Base N application rate

        Returns:
            Dictionary of zone_id: recommended_n_rate
        """
        vr_map = {}

        for zone_id, point_indices in zones.items():
            if not point_indices:
                continue

            zone_yields = [yield_data[i] for i in point_indices]
            avg_yield = sum(zone_yields) / len(zone_yields)

            # Adjust N rate based on zone yield
            # High yield zones get more N, low yield zones get less
            if avg_yield > 160:
                multiplier = 1.3  # 30% more
            elif avg_yield > 140:
                multiplier = 1.15  # 15% more
            elif avg_yield > 120:
                multiplier = 1.0  # Baseline
            elif avg_yield > 100:
                multiplier = 0.85  # 15% less
            else:
                multiplier = 0.70  # 30% less

            vr_map[zone_id] = round(base_rate_lbs_acre * multiplier, 0)

        return vr_map


class YieldMonitorProcessing:
    """Processes and cleans yield monitor data."""

    @staticmethod
    def clean_yield_data(
        yield_values: list[float],
        std_dev_threshold: float = 2.0,
    ) -> list[float]:
        """Remove outliers from yield monitor data.

        Removes points beyond std_dev_threshold standard deviations from mean.

        Args:
            yield_values: List of yield values
            std_dev_threshold: Number of standard deviations for outlier detection

        Returns:
            Cleaned yield data
        """
        if len(yield_values) < 3:
            return yield_values

        mean = sum(yield_values) / len(yield_values)
        variance = sum((x - mean) ** 2 for x in yield_values) / len(yield_values)
        std_dev = variance**0.5

        if std_dev == 0:
            return yield_values

        cleaned = [y for y in yield_values if abs(y - mean) <= std_dev_threshold * std_dev]

        return cleaned if cleaned else yield_values

    @staticmethod
    def interpolate_missing_values(
        yield_data: dict[Point2D, float],
        missing_points: list[Point2D],
        search_radius: float = 100.0,
    ) -> dict[Point2D, float]:
        """Interpolate missing yield values using nearby data.

        Uses inverse distance weighting.

        Args:
            yield_data: Dictionary of point: yield_value
            missing_points: List of points needing interpolation
            search_radius: Search radius for nearby points

        Returns:
            Dictionary with interpolated values
        """
        results = yield_data.copy()

        for missing_point in missing_points:
            # Find nearby points within search radius
            nearby = []
            for point, value in yield_data.items():
                distance = ((point.x - missing_point.x) ** 2 + (point.y - missing_point.y) ** 2) ** 0.5

                if distance <= search_radius and distance > 0:
                    nearby.append((distance, value))

            if nearby:
                # Inverse distance weighting
                total_weight = 0.0
                weighted_sum = 0.0
                for distance, value in nearby:
                    weight = 1.0 / distance
                    weighted_sum += value * weight
                    total_weight += weight

                interpolated_value = weighted_sum / total_weight if total_weight > 0 else 0
                results[missing_point] = round(interpolated_value, 1)

        return results


class GPSFieldBoundary:
    """Manages GPS field boundary data."""

    def __init__(self) -> None:
        """Initialize GPS boundary manager."""
        self.boundary_points: list[tuple[float, float]] = []

    def add_boundary_point(
        self,
        latitude: float,
        longitude: float,
    ) -> None:
        """Add a boundary point.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
        """
        if not (-90 <= latitude <= 90):
            raise PrecisionError("Invalid latitude")
        if not (-180 <= longitude <= 180):
            raise PrecisionError("Invalid longitude")

        self.boundary_points.append((latitude, longitude))

    def calculate_field_area_acres(self) -> float:
        """Calculate field area using boundary points.

        Uses Shoelace formula for polygon area. Simplified for small areas
        assuming planar coordinates.

        Returns:
            Estimated field area in acres
        """
        if len(self.boundary_points) < 3:
            raise PrecisionError("Need at least 3 boundary points")

        # Simplified calculation assuming planar coordinates
        # In production, use proper geodetic calculations
        n = len(self.boundary_points)
        area = 0.0

        for i in range(n):
            j = (i + 1) % n
            area += self.boundary_points[i][0] * self.boundary_points[j][1]
            area -= self.boundary_points[j][0] * self.boundary_points[i][1]

        area = abs(area) / 2.0

        # Convert to acres (approximate: 1 degree = ~364,000 feet at 40°N)
        # 640 acres per square degree
        acres = area * 640
        return acres


class AsAppliedVsAsPresc:
    """Compares as-applied vs as-prescribed fertilizer maps."""

    @staticmethod
    def calculate_deviation(
        as_prescribed_lbs: float,
        as_applied_lbs: float,
    ) -> dict[str, float]:
        """Calculate deviation from prescription.

        Args:
            as_prescribed_lbs: Prescribed application rate
            as_applied_lbs: Actual application rate

        Returns:
            Dictionary with deviation metrics
        """
        if as_prescribed_lbs <= 0:
            raise PrecisionError("Prescribed rate must be positive")

        difference = as_applied_lbs - as_prescribed_lbs
        percent_error = (difference / as_prescribed_lbs) * 100

        return {
            "absolute_difference_lbs": round(difference, 1),
            "percent_error": round(percent_error, 1),
            "applied_vs_prescribed_ratio": round(as_applied_lbs / as_prescribed_lbs, 2),
        }

    @staticmethod
    def field_compliance_report(
        deviations: list[dict[str, float]],
        tolerance_percent: float = 5.0,
    ) -> dict[str, any]:
        """Generate field compliance report.

        Args:
            deviations: List of deviation dictionaries
            tolerance_percent: Acceptable deviation percentage

        Returns:
            Compliance report with statistics
        """
        if not deviations:
            return {"compliance_pct": 100.0, "passes": True}

        errors = [abs(d["percent_error"]) for d in deviations]
        compliant_points = sum(1 for e in errors if e <= tolerance_percent)
        compliance_pct = (compliant_points / len(errors)) * 100 if errors else 100

        return {
            "compliance_pct": round(compliance_pct, 1),
            "passes": compliance_pct >= 90,
            "avg_error": round(sum(errors) / len(errors), 1),
            "max_error": round(max(errors), 1),
            "total_points": len(errors),
        }


class SiteSpcMgmtZones:
    """Site-specific management zones for targeted decisions."""

    @staticmethod
    def define_zones_from_layers(
        ndvi_data: list[float],
        yield_data: list[float],
        soil_cec_data: list[float],
    ) -> dict[str, list[int]]:
        """Define zones combining multiple data layers.

        Args:
            ndvi_data: NDVI values by location
            yield_data: Yield values by location
            soil_cec_data: Soil CEC values by location

        Returns:
            Dictionary of zone_name: [point_indices]
        """
        zones = {"Low": [], "Medium": [], "High": []}

        # Normalize data to 0-1 scale
        n = len(ndvi_data)
        for i in range(n):
            # Weighted score: 40% NDVI, 40% yield, 20% soil
            score = (
                0.4 * (ndvi_data[i] / max(ndvi_data))
                if ndvi_data[i] > 0
                else 0 + 0.4 * (yield_data[i] / max(yield_data))
                if yield_data[i] > 0
                else 0 + 0.2 * (soil_cec_data[i] / max(soil_cec_data))
                if soil_cec_data[i] > 0
                else 0
            )

            if score < 0.4:
                zones["Low"].append(i)
            elif score < 0.7:
                zones["Medium"].append(i)
            else:
                zones["High"].append(i)

        return zones
