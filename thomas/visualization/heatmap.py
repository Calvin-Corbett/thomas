"""Heatmap and related matrix visualization implementations."""

import math
from datetime import datetime

from thomas.visualization._exceptions import InvalidDataError
from thomas.visualization._types import Color, ColorMap, Series
from thomas.visualization.scales import BaseScale


class Heatmap:
    """Heatmap renderer with annotations and dendrograms."""

    def __init__(self, color_map: ColorMap) -> None:
        """Initialize heatmap.

        Args:
            color_map: Color mapping for values
        """
        self.color_map = color_map
        self.show_values = False
        self.font_size = 10

    def set_show_values(self, show: bool) -> None:
        """Toggle value annotations on cells.

        Args:
            show: Whether to show cell values
        """
        self.show_values = show

    def set_font_size(self, size: int) -> None:
        """Set font size for annotations.

        Args:
            size: Font size in pixels
        """
        self.font_size = max(1, size)

    def generate_cells(
        self,
        data: list[list[float]],
        x_scale: BaseScale,
        y_scale: BaseScale,
        width: float,
        height: float,
    ) -> list[tuple[float, float, float, float, Color, float]]:
        """Generate heatmap cells with colors.

        Args:
            data: 2D data array
            x_scale: X-axis scale
            y_scale: Y-axis scale
            width: Chart width
            height: Chart height

        Returns:
            List of (x, y, cell_width, cell_height, color, value) tuples
        """
        cells = []

        if not data or not data[0]:
            return cells

        rows = len(data)
        cols = len(data[0])

        cell_width = width / cols if cols > 0 else width
        cell_height = height / rows if rows > 0 else height

        min_val, max_val = self._get_data_range(data)
        self.color_map.value_range = (min_val, max_val)

        for i, row in enumerate(data):
            for j, value in enumerate(row):
                if value is None or not isinstance(value, (int, float)):
                    continue

                cell_x = x_scale.map_value(j)
                cell_y = y_scale.map_value(i)
                color = self.color_map.get_color(value)

                cells.append((cell_x, cell_y, cell_width, cell_height, color, value))

        return cells

    def generate_calendar_heatmap(
        self,
        series: Series,
        start_date: datetime,
        x_scale: BaseScale,
        y_scale: BaseScale,
        cell_size: float = 15.0,
    ) -> list[tuple[float, float, float, float, Color, str]]:
        """Generate GitHub-style calendar heatmap.

        Args:
            series: Data series with datetime x values
            start_date: Starting date
            x_scale: X-axis scale
            y_scale: Y-axis scale
            cell_size: Cell size in pixels

        Returns:
            List of (x, y, width, height, color, date_str) tuples
        """
        cells = []

        valid_points = [
            (p.x, p.y) for p in series.points if isinstance(p.x, datetime) and isinstance(p.y, (int, float))
        ]

        if not valid_points:
            return cells

        value_range = (min(v[1] for v in valid_points), max(v[1] for v in valid_points))
        self.color_map.value_range = value_range

        date_dict = {}
        for date_val, value in valid_points:
            days_since = (date_val - start_date).days
            week = days_since // 7
            day_of_week = days_since % 7

            cell_x = week * cell_size
            cell_y = day_of_week * cell_size
            color = self.color_map.get_color(value)

            date_str = date_val.strftime("%Y-%m-%d")
            cells.append((cell_x, cell_y, cell_size, cell_size, color, date_str))

        return cells

    def generate_correlation_matrix(
        self,
        series_list: list[Series],
        threshold: float | None = None,
    ) -> tuple[list[list[float]], list[str]]:
        """Generate correlation matrix from multiple series.

        Args:
            series_list: List of data series
            threshold: Optional significance threshold

        Returns:
            Tuple of (correlation_matrix, series_names)
        """
        if not series_list:
            return ([], [])

        series_names = [s.name for s in series_list]
        n_series = len(series_list)

        corr_matrix = [[0.0] * n_series for _ in range(n_series)]

        for i, series_i in enumerate(series_list):
            for j, series_j in enumerate(series_list):
                if i == j:
                    corr_matrix[i][j] = 1.0
                elif i < j:
                    corr = self._calculate_correlation(series_i, series_j)
                    corr_matrix[i][j] = corr
                    corr_matrix[j][i] = corr

        return (corr_matrix, series_names)

    def generate_dendrogram_tree(
        self,
        data: list[list[float]],
        max_depth: int = 5,
    ) -> list[tuple[int, int, float, int]]:
        """Generate hierarchical clustering dendrogram.

        Args:
            data: Data matrix
            max_depth: Maximum clustering depth

        Returns:
            List of (cluster1_id, cluster2_id, distance, depth) tuples
        """
        if not data or not data[0]:
            return []

        clusters = list(range(len(data)))
        linkages = []
        depth = 0

        while len(clusters) > 1 and depth < max_depth:
            min_dist = float("inf")
            merge_i, merge_j = 0, 1

            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    dist = self._euclidean_distance(data[clusters[i]], data[clusters[j]])
                    if dist < min_dist:
                        min_dist = dist
                        merge_i, merge_j = i, j

            c_i = clusters.pop(merge_j)
            c_j = clusters.pop(merge_i)

            linkages.append((c_j, c_i, min_dist, depth))

            cluster_avg = self._average_cluster(data, [c_i, c_j])
            data.append(cluster_avg)
            clusters.append(len(data) - 1)

            depth += 1

        return linkages

    def generate_annotated_heatmap(
        self,
        data: list[list[float]],
        x_labels: list[str],
        y_labels: list[str],
        x_scale: BaseScale,
        y_scale: BaseScale,
        width: float,
        height: float,
    ) -> tuple[list[tuple[float, float, float, float, Color, float]], list[tuple[float, float, str]]]:
        """Generate heatmap with cell and axis annotations.

        Args:
            data: 2D data array
            x_labels: Column labels
            y_labels: Row labels
            x_scale: X-axis scale
            y_scale: Y-axis scale
            width: Chart width
            height: Chart height

        Returns:
            Tuple of (cells, annotations)
        """
        cells = self.generate_cells(data, x_scale, y_scale, width, height)

        annotations = []
        if self.show_values:
            rows = len(data)
            cols = len(data[0]) if data else 0

            cell_width = width / cols if cols > 0 else width
            cell_height = height / rows if rows > 0 else height

            for i, row in enumerate(data):
                for j, value in enumerate(row):
                    if value is None or not isinstance(value, (int, float)):
                        continue

                    cell_x = x_scale.map_value(j) + cell_width / 2
                    cell_y = y_scale.map_value(i) + cell_height / 2

                    label = f"{value:.1f}" if isinstance(value, float) else str(value)
                    annotations.append((cell_x, cell_y, label))

        return (cells, annotations)

    def _get_data_range(self, data: list[list[float]]) -> tuple[float, float]:
        """Get min and max values from data.

        Args:
            data: 2D data array

        Returns:
            Tuple of (min_value, max_value)
        """
        values = []
        for row in data:
            for value in row:
                if isinstance(value, (int, float)):
                    values.append(value)

        if not values:
            return (0.0, 1.0)

        return (min(values), max(values))

    @staticmethod
    def _calculate_correlation(series1: Series, series2: Series) -> float:
        """Calculate Pearson correlation between two series.

        Args:
            series1: First data series
            series2: Second data series

        Returns:
            Correlation coefficient (-1.0 to 1.0)
        """
        values1 = [p.y for p in series1.points if isinstance(p.y, (int, float))]
        values2 = [p.y for p in series2.points if isinstance(p.y, (int, float))]

        if len(values1) < 2 or len(values2) < 2:
            return 0.0

        n = min(len(values1), len(values2))
        values1 = values1[:n]
        values2 = values2[:n]

        mean1 = sum(values1) / n
        mean2 = sum(values2) / n

        numerator = sum((values1[i] - mean1) * (values2[i] - mean2) for i in range(n))
        denom1 = sum((values1[i] - mean1) ** 2 for i in range(n))
        denom2 = sum((values2[i] - mean2) ** 2 for i in range(n))

        if denom1 == 0 or denom2 == 0:
            return 0.0

        return numerator / math.sqrt(denom1 * denom2)

    @staticmethod
    def _euclidean_distance(v1: list[float], v2: list[float]) -> float:
        """Calculate Euclidean distance between vectors.

        Args:
            v1: First vector
            v2: Second vector

        Returns:
            Distance
        """
        if len(v1) != len(v2):
            raise InvalidDataError("Vectors must have same length")

        return math.sqrt(sum((v1[i] - v2[i]) ** 2 for i in range(len(v1))))

    @staticmethod
    def _average_cluster(data: list[list[float]], cluster_indices: list[int]) -> list[float]:
        """Calculate average of cluster points.

        Args:
            data: Data matrix
            cluster_indices: Indices of cluster members

        Returns:
            Average vector
        """
        if not cluster_indices:
            return []

        num_features = len(data[0]) if data else 0
        if num_features == 0:
            return []

        average = [0.0] * num_features

        for idx in cluster_indices:
            for j in range(num_features):
                average[j] += data[idx][j]

        for j in range(num_features):
            average[j] /= len(cluster_indices)

        return average
