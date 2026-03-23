"""Bloom filter for probabilistic membership testing."""

import math
import struct

from ._types import BloomFilterConfig

__all__ = ["BloomFilter", "BloomFilterConfig"]


class BloomFilter:
    """A Bloom filter for fast membership testing with configurable false positive rate.

    Uses multiple hash functions to provide O(1) membership tests with no false negatives.
    """

    def __init__(self, expected_items: int, false_positive_rate: float):
        """Initialize a Bloom filter.

        Args:
            expected_items: Expected number of items to be added
            false_positive_rate: Desired false positive rate (e.g., 0.01 for 1%)

        Raises:
            ValueError: If parameters are invalid
        """
        if expected_items <= 0:
            raise ValueError("expected_items must be positive")
        if not (0 < false_positive_rate < 1):
            raise ValueError("false_positive_rate must be in (0, 1)")

        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate

        # Calculate bit array size: -1/(ln 2)^2 * n * ln(p)
        self.bit_array_size = self._calculate_bit_size(expected_items, false_positive_rate)

        # Calculate optimal number of hash functions: (m/n) * ln(2)
        self.num_hashes = self._calculate_num_hashes(self.bit_array_size, expected_items)

        # Initialize bit array (as a bytearray for mutability)
        self.bit_array = bytearray((self.bit_array_size + 7) // 8)
        self.items_added = 0

    @staticmethod
    def _calculate_bit_size(expected_items: int, fpp: float) -> int:
        """Calculate required bit array size.

        Uses formula: m = -1/(ln 2)^2 * n * ln(p)
        """
        ln2_squared = 0.4804530139592
        return int(-expected_items * math.log(fpp) / ln2_squared)

    @staticmethod
    def _calculate_num_hashes(bit_size: int, expected_items: int) -> int:
        """Calculate optimal number of hash functions.

        Uses formula: k = (m/n) * ln(2)
        """
        ln2 = 0.693147180560
        return max(1, int((bit_size / expected_items) * ln2))

    def _hash(self, item: bytes, seed: int) -> int:
        """Generate a hash value using seed-based hashing.

        Uses a simple but effective hash combining CRC32-style operations.

        Args:
            item: The item to hash
            seed: The seed value

        Returns:
            A hash value in range [0, bit_array_size)
        """
        # Use a simple multiplicative hash with seed
        h = seed
        for byte in item:
            h = (h * 31 + byte) & 0xFFFFFFFF
        return (h ^ (h >> 16)) % self.bit_array_size

    def add(self, item: bytes) -> None:
        """Add an item to the filter.

        Args:
            item: The item to add (usually a key)
        """
        if not item:
            raise ValueError("Item cannot be empty")

        for i in range(self.num_hashes):
            bit_pos = self._hash(item, i)
            byte_index = bit_pos // 8
            bit_index = bit_pos % 8
            self.bit_array[byte_index] |= 1 << bit_index

        self.items_added += 1

    def might_contain(self, item: bytes) -> bool:
        """Test if item might be in the set.

        Returns True if the item might be present (could be false positive).
        Returns False if the item is definitely not present.

        Args:
            item: The item to check

        Returns:
            True if item might be in filter, False if definitely not
        """
        if not item:
            raise ValueError("Item cannot be empty")

        for i in range(self.num_hashes):
            bit_pos = self._hash(item, i)
            byte_index = bit_pos // 8
            bit_index = bit_pos % 8

            if not (self.bit_array[byte_index] & (1 << bit_index)):
                return False

        return True

    def serialize(self) -> bytes:
        """Serialize filter to bytes.

        Format: [expected_items:4][fpp_encoded:4][num_hashes:2][bit_array]

        Returns:
            Serialized bloom filter
        """
        # Encode FPP as fixed-point (multiply by 10^6)
        fpp_encoded = int(self.false_positive_rate * 1_000_000)

        header = struct.pack(">IIH", self.expected_items, fpp_encoded, self.num_hashes)
        return header + bytes(self.bit_array)

    @staticmethod
    def deserialize(data: bytes) -> "BloomFilter":
        """Deserialize filter from bytes.

        Args:
            data: Serialized bloom filter

        Returns:
            A new BloomFilter instance

        Raises:
            ValueError: If data is corrupt
        """
        if len(data) < 10:
            raise ValueError("Bloom filter data too short")

        expected_items, fpp_encoded, num_hashes = struct.unpack(">IIH", data[:10])
        bit_array_data = data[10:]

        if expected_items <= 0:
            raise ValueError("Invalid expected_items in serialized data")

        fpp = fpp_encoded / 1_000_000

        # Create filter and restore state
        bf = BloomFilter(expected_items, fpp)
        bf.bit_array = bytearray(bit_array_data)
        bf.num_hashes = num_hashes
        bf.items_added = len(bit_array_data)  # Reset items_added

        return bf

    def size_bytes(self) -> int:
        """Get size of serialized filter.

        Returns:
            Size in bytes
        """
        return 10 + len(self.bit_array)

    def __len__(self) -> int:
        """Get number of items added.

        Returns:
            Count of items added
        """
        return self.items_added

    def clear(self) -> None:
        """Clear all bits."""
        self.bit_array = bytearray((self.bit_array_size + 7) // 8)
        self.items_added = 0
