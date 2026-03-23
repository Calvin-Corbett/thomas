"""Time-series indexing for the Thomas TSDB.

Provides efficient lookups by metric name, tags, and time ranges.
Includes metric name index, tag index, time range index, and bloom filters.
"""

import hashlib
from collections import defaultdict


class BloomFilter:
    """Simple Bloom filter for membership testing.

    Useful for quickly determining if a metric name might exist
    without doing a full lookup.
    """

    def __init__(self, expected_elements: int = 10000, false_positive_rate: float = 0.01) -> None:
        """Initialize a Bloom filter.

        Args:
            expected_elements: Expected number of elements to add
            false_positive_rate: Desired false positive rate
        """
        # Calculate optimal bit array size
        self.bit_array_size = self._optimal_bit_array_size(expected_elements, false_positive_rate)
        self.hash_count = self._optimal_hash_count(self.bit_array_size, expected_elements)
        self.bit_array = [False] * self.bit_array_size

    def add(self, item: str) -> None:
        """Add an item to the Bloom filter.

        Args:
            item: Item to add (typically a metric name)
        """
        for i in range(self.hash_count):
            hash_value = self._hash(item, i)
            self.bit_array[hash_value] = True

    def contains(self, item: str) -> bool:
        """Check if an item might be in the filter.

        Args:
            item: Item to check

        Returns:
            False if definitely not in set, True if possibly in set
        """
        for i in range(self.hash_count):
            hash_value = self._hash(item, i)
            if not self.bit_array[hash_value]:
                return False
        return True

    def _hash(self, item: str, seed: int) -> int:
        """Hash an item with a specific seed.

        Args:
            item: Item to hash
            seed: Seed for hash function

        Returns:
            Hash value in range [0, bit_array_size)
        """
        data = f"{item}:{seed}".encode()
        hash_value = int(hashlib.md5(data).hexdigest(), 16)
        return hash_value % self.bit_array_size

    @staticmethod
    def _optimal_bit_array_size(n: int, p: float) -> int:
        """Calculate optimal bit array size.

        Args:
            n: Expected number of elements
            p: Desired false positive rate

        Returns:
            Optimal bit array size
        """
        import math

        return int(-1 * n * math.log(p) / (math.log(2) ** 2))

    @staticmethod
    def _optimal_hash_count(m: int, n: int) -> int:
        """Calculate optimal number of hash functions.

        Args:
            m: Bit array size
            n: Expected number of elements

        Returns:
            Optimal number of hash functions
        """
        import math

        if n == 0:
            return 1
        return max(1, int(m / n * math.log(2)))


class MetricIndex:
    """Index for fast metric name lookups."""

    def __init__(self) -> None:
        """Initialize the metric index."""
        self.metrics: dict[str, set[int]] = {}  # metric_name -> set of series ids
        self.next_series_id = 0
        self.bloom_filter = BloomFilter()

    def add_metric(self, metric_name: str) -> int:
        """Add a metric to the index.

        Args:
            metric_name: Name of the metric

        Returns:
            Series ID for this metric instance
        """
        series_id = self.next_series_id
        self.next_series_id += 1

        if metric_name not in self.metrics:
            self.metrics[metric_name] = set()
            self.bloom_filter.add(metric_name)

        self.metrics[metric_name].add(series_id)
        return series_id

    def get_series_ids(self, metric_name: str) -> set[int]:
        """Get all series IDs for a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Set of series IDs, or empty set if metric not found
        """
        return self.metrics.get(metric_name, set())

    def metric_exists(self, metric_name: str) -> bool:
        """Check if a metric exists (using Bloom filter).

        Args:
            metric_name: Name of the metric

        Returns:
            True if metric might exist, False if definitely doesn't
        """
        return self.bloom_filter.contains(metric_name)

    def get_all_metrics(self) -> list[str]:
        """Get all metric names.

        Returns:
            List of all metric names
        """
        return list(self.metrics.keys())

    def metric_count(self) -> int:
        """Get number of unique metrics.

        Returns:
            Number of metrics
        """
        return len(self.metrics)

    def series_count(self) -> int:
        """Get total number of series.

        Returns:
            Total number of series
        """
        return sum(len(ids) for ids in self.metrics.values())


class TagIndex:
    """Inverted index for tag-based queries.

    Maps (tag_key, tag_value) pairs to sets of series IDs.
    """

    def __init__(self) -> None:
        """Initialize the tag index."""
        # (tag_key, tag_value) -> set of series ids
        self.tag_index: dict[tuple[str, str], set[int]] = defaultdict(set)
        # series_id -> dict of tags
        self.series_tags: dict[int, dict[str, str]] = {}

    def add_series_tags(self, series_id: int, tags: dict[str, str]) -> None:
        """Add tags for a series.

        Args:
            series_id: ID of the series
            tags: Dictionary of tag key-value pairs
        """
        self.series_tags[series_id] = tags.copy()

        for key, value in tags.items():
            self.tag_index[(key, value)].add(series_id)

    def get_series_by_tag(self, tag_key: str, tag_value: str) -> set[int]:
        """Get series with a specific tag key-value pair.

        Args:
            tag_key: Tag key
            tag_value: Tag value

        Returns:
            Set of series IDs
        """
        return self.tag_index.get((tag_key, tag_value), set()).copy()

    def get_series_by_tag_key(self, tag_key: str) -> set[int]:
        """Get all series that have a specific tag key.

        Args:
            tag_key: Tag key

        Returns:
            Set of series IDs
        """
        result = set()
        for (key, _), series_ids in self.tag_index.items():
            if key == tag_key:
                result.update(series_ids)
        return result

    def filter_series(self, series_ids: set[int], tag_key: str, tag_value: str) -> set[int]:
        """Filter series by tag value.

        Args:
            series_ids: Set of series IDs to filter
            tag_key: Tag key to filter on
            tag_value: Tag value to match

        Returns:
            Filtered set of series IDs
        """
        matching = self.get_series_by_tag(tag_key, tag_value)
        return series_ids & matching

    def get_tags(self, series_id: int) -> dict[str, str]:
        """Get all tags for a series.

        Args:
            series_id: ID of the series

        Returns:
            Dictionary of tags
        """
        return self.series_tags.get(series_id, {}).copy()

    def get_tag_values(self, tag_key: str) -> set[str]:
        """Get all values for a tag key.

        Args:
            tag_key: Tag key

        Returns:
            Set of all values
        """
        values = set()
        for (key, value), _ in self.tag_index.items():
            if key == tag_key:
                values.add(value)
        return values


class TimeRangeIndex:
    """Index for tracking which chunks cover which time ranges."""

    def __init__(self) -> None:
        """Initialize the time range index."""
        # chunk_id -> (start_time, end_time)
        self.chunk_ranges: dict[int, tuple[int, int]] = {}
        self.next_chunk_id = 0
        # series_id -> list of chunk ids
        self.series_chunks: dict[int, list[int]] = defaultdict(list)

    def add_chunk(self, series_id: int, start_time: int, end_time: int) -> int:
        """Add a chunk to the index.

        Args:
            series_id: ID of the series
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Chunk ID
        """
        chunk_id = self.next_chunk_id
        self.next_chunk_id += 1

        self.chunk_ranges[chunk_id] = (start_time, end_time)
        self.series_chunks[series_id].append(chunk_id)

        return chunk_id

    def get_chunks_for_series(self, series_id: int) -> list[int]:
        """Get all chunk IDs for a series.

        Args:
            series_id: ID of the series

        Returns:
            List of chunk IDs
        """
        return self.series_chunks.get(series_id, [])

    def get_chunks_in_time_range(self, series_id: int, start_time: int, end_time: int) -> list[int]:
        """Get chunks that overlap with a time range.

        Args:
            series_id: ID of the series
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            List of chunk IDs that overlap
        """
        result = []
        for chunk_id in self.series_chunks.get(series_id, []):
            chunk_start, chunk_end = self.chunk_ranges[chunk_id]
            # Check if ranges overlap
            if chunk_start < end_time and chunk_end > start_time:
                result.append(chunk_id)
        return result

    def get_chunk_range(self, chunk_id: int) -> tuple[int, int]:
        """Get the time range of a chunk.

        Args:
            chunk_id: ID of the chunk

        Returns:
            Tuple of (start_time, end_time)

        Raises:
            KeyError: If chunk not found
        """
        return self.chunk_ranges[chunk_id]

    def remove_chunk(self, series_id: int, chunk_id: int) -> None:
        """Remove a chunk from the index.

        Args:
            series_id: ID of the series
            chunk_id: ID of the chunk
        """
        if series_id in self.series_chunks:
            if chunk_id in self.series_chunks[series_id]:
                self.series_chunks[series_id].remove(chunk_id)
            if not self.series_chunks[series_id]:
                del self.series_chunks[series_id]

        if chunk_id in self.chunk_ranges:
            del self.chunk_ranges[chunk_id]


class TSDBIndex:
    """Complete index combining metric, tag, and time range indices."""

    def __init__(self) -> None:
        """Initialize the complete index."""
        self.metric_index = MetricIndex()
        self.tag_index = TagIndex()
        self.time_index = TimeRangeIndex()

    def add_metric(self, metric_name: str, tags: dict[str, str] = None) -> int:
        """Add a metric to all indices.

        Args:
            metric_name: Name of the metric
            tags: Optional dictionary of tags

        Returns:
            Series ID
        """
        series_id = self.metric_index.add_metric(metric_name)
        if tags:
            self.tag_index.add_series_tags(series_id, tags)
        return series_id

    def add_chunk(self, series_id: int, start_time: int, end_time: int) -> int:
        """Add a chunk to the time range index.

        Args:
            series_id: ID of the series
            start_time: Start timestamp
            end_time: End timestamp

        Returns:
            Chunk ID
        """
        return self.time_index.add_chunk(series_id, start_time, end_time)

    def find_series(self, metric_name: str, tag_filters: list[tuple[str, str]] = None) -> set[int]:
        """Find series matching metric name and optional tag filters.

        Args:
            metric_name: Metric name to search for
            tag_filters: Optional list of (tag_key, tag_value) tuples

        Returns:
            Set of matching series IDs
        """
        series_ids = self.metric_index.get_series_ids(metric_name)

        if tag_filters:
            for tag_key, tag_value in tag_filters:
                series_ids = self.tag_index.filter_series(series_ids, tag_key, tag_value)

        return series_ids

    def get_series_tags(self, series_id: int) -> dict[str, str]:
        """Get tags for a series.

        Args:
            series_id: ID of the series

        Returns:
            Dictionary of tags
        """
        return self.tag_index.get_tags(series_id)

    def get_stats(self) -> dict[str, int]:
        """Get index statistics.

        Returns:
            Dictionary of statistics
        """
        return {
            "unique_metrics": self.metric_index.metric_count(),
            "total_series": self.metric_index.series_count(),
            "total_chunks": len(self.time_index.chunk_ranges),
            "tag_pairs": len(self.tag_index.tag_index),
        }
