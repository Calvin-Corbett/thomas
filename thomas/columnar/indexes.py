"""
Columnar indexes: bitmap indexes, zone maps, bloom filters, and inverted indexes.

Provides efficient data structures for predicate pushdown and query optimization.
"""

import hashlib
import math
import struct
from typing import Any

from thomas.columnar._exceptions import IndexError
from thomas.columnar._types import Statistics


class BitmapIndex:
    """Bitmap index with sparse encoding (WAH compression for sparse bitmaps)."""

    def __init__(self, value: Any) -> None:
        """Initialize bitmap index for specific value.

        Args:
            value: Value this bitmap tracks
        """
        self.value = value
        self.bitmap: bytearray = bytearray()
        self.num_rows = 0

    def set(self, row_id: int) -> None:
        """Mark row as matching this value."""
        byte_idx = row_id // 8
        bit_idx = row_id % 8

        # Extend bitmap if needed
        while byte_idx >= len(self.bitmap):
            self.bitmap.append(0)

        self.bitmap[byte_idx] |= 1 << bit_idx
        self.num_rows = max(self.num_rows, row_id + 1)

    def clear(self, row_id: int) -> None:
        """Mark row as not matching this value."""
        byte_idx = row_id // 8
        bit_idx = row_id % 8

        if byte_idx < len(self.bitmap):
            self.bitmap[byte_idx] &= ~(1 << bit_idx)

    def is_set(self, row_id: int) -> bool:
        """Check if row matches this value."""
        byte_idx = row_id // 8
        bit_idx = row_id % 8

        if byte_idx >= len(self.bitmap):
            return False

        return (self.bitmap[byte_idx] >> bit_idx) & 1 != 0

    def and_mask(self, other: "BitmapIndex") -> list[bool]:
        """AND operation with another bitmap."""
        max_bytes = max(len(self.bitmap), len(other.bitmap))
        result = []

        for i in range(max_bytes * 8):
            byte_idx = i // 8
            bit_idx = i % 8

            bit1 = (self.bitmap[byte_idx] >> bit_idx) & 1 if byte_idx < len(self.bitmap) else 0
            bit2 = (other.bitmap[byte_idx] >> bit_idx) & 1 if byte_idx < len(other.bitmap) else 0
            result.append(bool(bit1 & bit2))

        return result

    def or_mask(self, other: "BitmapIndex") -> list[bool]:
        """OR operation with another bitmap."""
        max_bytes = max(len(self.bitmap), len(other.bitmap))
        result = []

        for i in range(max_bytes * 8):
            byte_idx = i // 8
            bit_idx = i % 8

            bit1 = (self.bitmap[byte_idx] >> bit_idx) & 1 if byte_idx < len(self.bitmap) else 0
            bit2 = (other.bitmap[byte_idx] >> bit_idx) & 1 if byte_idx < len(other.bitmap) else 0
            result.append(bool(bit1 | bit2))

        return result

    def not_mask(self) -> list[bool]:
        """NOT operation on bitmap."""
        result = []
        for byte in self.bitmap:
            for bit_idx in range(8):
                result.append(not ((byte >> bit_idx) & 1))
        return result

    def count(self) -> int:
        """Count set bits (popcount)."""
        count = 0
        for byte in self.bitmap:
            count += bin(byte).count("1")
        return count

    def to_mask(self, length: int) -> list[bool]:
        """Convert to boolean mask of specified length."""
        result = []
        for i in range(length):
            result.append(self.is_set(i))
        return result

    def serialize(self) -> bytes:
        """Serialize bitmap to bytes."""
        return struct.pack("<I", self.num_rows) + bytes(self.bitmap)

    @classmethod
    def deserialize(cls, value: Any, data: bytes) -> "BitmapIndex":
        """Deserialize bitmap from bytes."""
        idx = cls(value)
        if len(data) >= 4:
            idx.num_rows = struct.unpack("<I", data[:4])[0]
            idx.bitmap = bytearray(data[4:])
        return idx


class ZoneMap:
    """Zone map (min/max index) for column chunks for predicate pushdown."""

    def __init__(self, column_name: str) -> None:
        """Initialize zone map.

        Args:
            column_name: Name of indexed column
        """
        self.column_name = column_name
        self.zones: list[tuple[Any, Any]] = []  # (min, max) per zone

    def add_zone(self, min_value: Any, max_value: Any) -> None:
        """Add zone (column chunk) statistics.

        Args:
            min_value: Minimum value in zone
            max_value: Maximum value in zone
        """
        self.zones.append((min_value, max_value))

    def find_matching_zones(self, operator: str, value: Any) -> list[int]:
        """Find zones matching predicate using zone map.

        Args:
            operator: Comparison operator (==, !=, <, <=, >, >=, in, between)
            value: Value to compare against (or tuple (low, high) for between)

        Returns:
            List of zone IDs that may contain matching rows
        """
        matching = []

        for zone_id, (zone_min, zone_max) in enumerate(self.zones):
            if zone_min is None or zone_max is None:
                # Zone contains all nulls, can skip for some predicates
                if operator == "is_not_null":
                    continue
                matching.append(zone_id)
                continue

            matches = False

            if operator == "==":
                matches = zone_min <= value <= zone_max
            elif operator == "!=":
                matches = True  # May contain non-matching values
            elif operator == "<":
                matches = zone_min < value
            elif operator == "<=":
                matches = zone_min <= value
            elif operator == ">":
                matches = zone_max > value
            elif operator == ">=":
                matches = zone_max >= value
            elif operator == "between":
                low, high = value
                matches = zone_min <= high and zone_max >= low
            elif operator == "is_null":
                matches = True  # May contain nulls
            elif operator == "is_not_null":
                matches = True  # May contain non-nulls

            if matches:
                matching.append(zone_id)

        return matching

    def prune_zones(self, operator: str, value: Any) -> list[int]:
        """Prune zones based on predicate (inverse of find_matching_zones).

        Args:
            operator: Comparison operator
            value: Value to compare against

        Returns:
            List of zone IDs to skip
        """
        all_zones = set(range(len(self.zones)))
        matching = set(self.find_matching_zones(operator, value))
        return sorted(list(all_zones - matching))


class BloomFilter:
    """Bloom filter for set membership testing on column chunks."""

    def __init__(self, expected_elements: int = 10000, false_positive_rate: float = 0.01) -> None:
        """Initialize Bloom filter.

        Args:
            expected_elements: Expected number of elements
            false_positive_rate: Desired false positive rate
        """
        if expected_elements <= 0:
            raise IndexError("expected_elements must be positive")
        if not (0.0 < false_positive_rate < 1.0):
            raise IndexError("false_positive_rate must be in (0, 1)")

        # Calculate optimal bit array size and hash count.
        ln2 = math.log(2.0)
        bit_size = -expected_elements * math.log(false_positive_rate) / (ln2 * ln2)
        hash_count = (bit_size / expected_elements) * ln2

        self.bit_size = max(8, int(bit_size) + 1)
        self.num_hashes = max(1, int(hash_count) + 1)

        self.bits = bytearray((self.bit_size + 7) // 8)
        self.num_elements = 0

    def add(self, value: Any) -> None:
        """Add value to Bloom filter.

        Args:
            value: Value to add
        """
        for i in range(self.num_hashes):
            hash_val = self._hash(value, i)
            bit_idx = hash_val % self.bit_size
            byte_idx = bit_idx // 8
            bit_pos = bit_idx % 8
            self.bits[byte_idx] |= 1 << bit_pos

        self.num_elements += 1

    def contains(self, value: Any) -> bool:
        """Check if value may be in filter (may have false positives).

        Args:
            value: Value to check

        Returns:
            True if value may be present, False if definitely not present
        """
        for i in range(self.num_hashes):
            hash_val = self._hash(value, i)
            bit_idx = hash_val % self.bit_size
            byte_idx = bit_idx // 8
            bit_pos = bit_idx % 8

            if not ((self.bits[byte_idx] >> bit_pos) & 1):
                return False

        return True

    def _hash(self, value: Any, seed: int) -> int:
        """Compute hash value for value with seed."""
        h = hashlib.md5(f"{value}_{seed}".encode()).digest()
        return struct.unpack("<I", h[:4])[0]

    def serialize(self) -> bytes:
        """Serialize Bloom filter to bytes."""
        return struct.pack("<II", self.bit_size, self.num_hashes) + bytes(self.bits)

    @classmethod
    def deserialize(cls, data: bytes) -> "BloomFilter":
        """Deserialize Bloom filter from bytes."""
        bf = cls.__new__(cls)
        bf.bit_size = struct.unpack("<I", data[:4])[0]
        bf.num_hashes = struct.unpack("<I", data[4:8])[0]
        bf.bits = bytearray(data[8:])
        bf.num_elements = 0
        return bf


class InvertedIndex:
    """Inverted index for string column values."""

    def __init__(self, column_name: str) -> None:
        """Initialize inverted index.

        Args:
            column_name: Name of indexed column
        """
        self.column_name = column_name
        self.term_to_rows: dict[str, set[int]] = {}

    def add(self, row_id: int, value: str) -> None:
        """Add value to inverted index.

        Args:
            row_id: Row identifier
            value: String value to index
        """
        if value is None:
            return

        # Index terms (words)
        terms = value.lower().split()
        for term in terms:
            if term not in self.term_to_rows:
                self.term_to_rows[term] = set()
            self.term_to_rows[term].add(row_id)

    def search(self, query: str) -> set[int]:
        """Search index for rows matching query terms.

        Args:
            query: Query string (space-separated terms)

        Returns:
            Set of matching row IDs
        """
        terms = query.lower().split()
        if not terms:
            return set()

        # AND semantics: all terms must match
        result = None
        for term in terms:
            matching_rows = self.term_to_rows.get(term, set())
            if result is None:
                result = matching_rows.copy()
            else:
                result = result.intersection(matching_rows)

        return result or set()

    def search_or(self, query: str) -> set[int]:
        """Search index with OR semantics (any term matches).

        Args:
            query: Query string (space-separated terms)

        Returns:
            Set of matching row IDs
        """
        terms = query.lower().split()
        result = set()

        for term in terms:
            matching_rows = self.term_to_rows.get(term, set())
            result = result.union(matching_rows)

        return result

    def get_term_rows(self, term: str) -> set[int]:
        """Get all rows containing term.

        Args:
            term: Term to look up

        Returns:
            Set of matching row IDs
        """
        return self.term_to_rows.get(term.lower(), set())


class IndexAdvisor:
    """Advisor for selecting which indexes to create based on cardinality analysis."""

    @staticmethod
    def recommend_indexes(
        columns: dict[str, Statistics],
    ) -> dict[str, str]:
        """Recommend indexes for columns based on statistics.

        Args:
            columns: Dictionary mapping column_name -> Statistics

        Returns:
            Dictionary mapping column_name -> recommended_index_type
        """
        recommendations = {}

        for col_name, stats in columns.items():
            if stats.distinct_count == 0:
                continue

            total = stats.total_value_count
            if total == 0:
                continue

            cardinality_ratio = stats.distinct_count / total

            # High cardinality (>50%) -> use zone map only
            if cardinality_ratio > 0.5:
                recommendations[col_name] = "zone_map"

            # Medium cardinality (10-50%) -> use bitmap index
            elif cardinality_ratio > 0.1:
                recommendations[col_name] = "bitmap_index"

            # Low cardinality (<10%) -> use bitmap index + bloom filter
            else:
                recommendations[col_name] = "bitmap_index,bloom_filter"

        return recommendations

    @staticmethod
    def should_create_bitmap(stats: Statistics) -> bool:
        """Determine if bitmap index should be created.

        Args:
            stats: Column statistics

        Returns:
            True if bitmap index is recommended
        """
        if stats.total_value_count == 0:
            return False

        cardinality_ratio = stats.distinct_count / stats.total_value_count
        return cardinality_ratio < 0.5

    @staticmethod
    def should_create_bloom_filter(stats: Statistics) -> bool:
        """Determine if Bloom filter should be created.

        Args:
            stats: Column statistics

        Returns:
            True if Bloom filter is recommended
        """
        if stats.total_value_count == 0:
            return False

        cardinality_ratio = stats.distinct_count / stats.total_value_count
        return cardinality_ratio < 0.2

    @staticmethod
    def should_create_inverted_index(stats: Statistics) -> bool:
        """Determine if inverted index should be created.

        Args:
            stats: Column statistics

        Returns:
            True if inverted index is recommended
        """
        # Inverted indexes good for string columns with high cardinality
        if stats.total_value_count == 0:
            return False

        cardinality_ratio = stats.distinct_count / stats.total_value_count
        return cardinality_ratio > 0.2
