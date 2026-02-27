"""
Data partitioning: range, hash, list, and composite partitioning schemes.

Provides partition creation, pruning, and optimization for distributed query execution.
"""

from typing import Any

from thomas.columnar._exceptions import PartitionError
from thomas.columnar._types import Statistics


class PartitionScheme:
    """Base class for partition schemes."""

    def get_partition(self, value: Any) -> int:
        """Get partition ID for value.

        Args:
            value: Value to partition

        Returns:
            Partition ID
        """
        raise NotImplementedError

    def should_prune(self, partition_id: int, operator: str, value: Any) -> bool:
        """Determine if partition can be pruned based on predicate.

        Args:
            partition_id: Partition ID
            operator: Comparison operator
            value: Predicate value

        Returns:
            True if partition should be pruned (skipped)
        """
        raise NotImplementedError


class RangePartitioner(PartitionScheme):
    """Range partitioning: partition by value ranges.

    Partitions data into contiguous ranges (e.g., dates by month, numbers by range).
    """

    def __init__(self, boundaries: list[Any]) -> None:
        """Initialize range partitioner.

        Args:
            boundaries: List of partition boundaries (sorted)
                       For N+1 partitions, provide N boundary values
                       Partition 0: value < boundaries[0]
                       Partition i: boundaries[i-1] <= value < boundaries[i]
                       Partition N: value >= boundaries[N-1]
        """
        self.boundaries = sorted(boundaries)
        self.num_partitions = len(boundaries) + 1

    def get_partition(self, value: Any) -> int:
        """Get partition ID for value using binary search."""
        if value is None:
            return -1  # Nulls in separate partition

        for i, boundary in enumerate(self.boundaries):
            if value < boundary:
                return i

        return len(self.boundaries)

    def should_prune(self, partition_id: int, operator: str, value: Any) -> bool:
        """Determine if partition matches predicate."""
        if partition_id == -1:
            # Null partition
            return operator != "is_null"

        # Get partition range
        if partition_id == 0:
            partition_max = self.boundaries[0]
            partition_min = None
        elif partition_id == len(self.boundaries):
            partition_min = self.boundaries[-1]
            partition_max = None
        else:
            partition_min = self.boundaries[partition_id - 1]
            partition_max = self.boundaries[partition_id]

        # Check predicate
        if operator == "==":
            if partition_min is not None and value < partition_min:
                return True
            if partition_max is not None and value >= partition_max:
                return True
            return False

        elif operator == "<":
            if partition_min is not None and partition_min >= value:
                return True
            return False

        elif operator == "<=":
            if partition_min is not None and partition_min > value:
                return True
            return False

        elif operator == ">" or operator == ">=":
            if partition_max is not None and partition_max <= value:
                return True
            return False

        elif operator == "between":
            low, high = value
            if partition_max is not None and partition_max <= low:
                return True
            if partition_min is not None and partition_min > high:
                return True
            return False

        # Keep partition for != and other operators
        return False

    def get_partition_bounds(self, partition_id: int) -> tuple[Any | None, Any | None]:
        """Get min/max bounds for partition.

        Args:
            partition_id: Partition ID

        Returns:
            (min_value, max_value) tuple
        """
        if partition_id == -1:
            return (None, None)

        if partition_id == 0:
            return (None, self.boundaries[0])

        if partition_id == len(self.boundaries):
            return (self.boundaries[-1], None)

        return (self.boundaries[partition_id - 1], self.boundaries[partition_id])


class HashPartitioner(PartitionScheme):
    """Hash partitioning: partition by hash(value) mod num_partitions.

    Provides even data distribution across partitions.
    """

    def __init__(self, num_partitions: int) -> None:
        """Initialize hash partitioner.

        Args:
            num_partitions: Number of partitions
        """
        if num_partitions <= 0:
            raise PartitionError("num_partitions must be positive")

        self.num_partitions = num_partitions

    def get_partition(self, value: Any) -> int:
        """Get partition ID for value using hash."""
        if value is None:
            return -1

        # Simple hash using Python's hash
        hash_val = hash(value)
        return abs(hash_val) % self.num_partitions

    def should_prune(self, partition_id: int, operator: str, value: Any) -> bool:
        """Hash partitioning cannot prune based on value predicates."""
        # Can only prune if we know the exact hash value
        if operator == "==":
            expected_partition = self.get_partition(value)
            return partition_id != expected_partition

        # Cannot prune for range predicates
        return False


class ListPartitioner(PartitionScheme):
    """List partitioning: partition by explicit value lists.

    Useful for categorical data (e.g., region = [US, EU, APAC]).
    """

    def __init__(self, partition_values: dict[int, list[Any]]) -> None:
        """Initialize list partitioner.

        Args:
            partition_values: Dictionary mapping partition_id -> list of values
        """
        self.partition_values = partition_values
        self.value_to_partition: dict[Any, int] = {}

        for partition_id, values in partition_values.items():
            for value in values:
                self.value_to_partition[value] = partition_id

        self.num_partitions = len(partition_values)

    def get_partition(self, value: Any) -> int:
        """Get partition ID for value."""
        if value is None:
            return -1

        return self.value_to_partition.get(value, -2)  # -2 for out-of-range

    def should_prune(self, partition_id: int, operator: str, value: Any) -> bool:
        """Determine if partition matches predicate."""
        if partition_id == -1:
            return operator != "is_null"

        partition_list = self.partition_values.get(partition_id, [])

        if operator == "==":
            return value not in partition_list

        elif operator == "!=":
            return all(v != value for v in partition_list)

        elif operator == "in":
            value_set = set(value)
            return not any(v in value_set for v in partition_list)

        # Cannot prune for other operators
        return False

    def get_partition_values(self, partition_id: int) -> list[Any]:
        """Get list of values in partition.

        Args:
            partition_id: Partition ID

        Returns:
            List of values
        """
        return self.partition_values.get(partition_id, [])


class CompositePartitioner(PartitionScheme):
    """Composite partitioning: partition by multiple columns hierarchically.

    Example: partition by (year, month) or (region, country).
    """

    def __init__(
        self,
        partitioners: list[tuple[str, PartitionScheme]],
    ) -> None:
        """Initialize composite partitioner.

        Args:
            partitioners: List of (column_name, partitioner) tuples
        """
        self.partitioners = partitioners
        self.column_names = [name for name, _ in partitioners]

    def get_partition(self, values: dict[str, Any]) -> tuple[int, ...]:
        """Get partition ID tuple for values.

        Args:
            values: Dictionary mapping column_name -> value

        Returns:
            Tuple of partition IDs
        """
        partition_ids = []

        for col_name, partitioner in self.partitioners:
            value = values.get(col_name)
            partition_ids.append(partitioner.get_partition(value))

        return tuple(partition_ids)

    def should_prune(
        self,
        partition_ids: tuple[int, ...],
        predicates: dict[str, tuple[str, Any]],
    ) -> bool:
        """Determine if partition matches multiple predicates.

        Args:
            partition_ids: Tuple of partition IDs
            predicates: Dictionary mapping column_name -> (operator, value)

        Returns:
            True if partition should be pruned
        """
        for i, (col_name, partitioner) in enumerate(self.partitioners):
            if col_name in predicates:
                operator, value = predicates[col_name]
                if partitioner.should_prune(partition_ids[i], operator, value):
                    return True

        return False


class PartitionPruner:
    """Partition pruner for query optimization."""

    def __init__(self, partitioner: PartitionScheme) -> None:
        """Initialize partition pruner.

        Args:
            partitioner: Partition scheme
        """
        self.partitioner = partitioner

    def prune_partitions(
        self,
        all_partitions: list[int],
        operator: str,
        value: Any,
    ) -> list[int]:
        """Prune partitions based on single predicate.

        Args:
            all_partitions: List of all partition IDs
            operator: Comparison operator
            value: Predicate value

        Returns:
            List of partitions to keep (pruned)
        """
        keep = []

        for partition_id in all_partitions:
            if not self.partitioner.should_prune(partition_id, operator, value):
                keep.append(partition_id)

        return keep

    def prune_with_and(
        self,
        all_partitions: list[int],
        predicates: list[tuple[str, Any]],
    ) -> list[int]:
        """Prune partitions with AND semantics (all predicates must match).

        Args:
            all_partitions: List of all partition IDs
            predicates: List of (operator, value) tuples

        Returns:
            List of partitions to keep
        """
        keep = all_partitions.copy()

        for operator, value in predicates:
            keep = self.prune_partitions(keep, operator, value)

        return keep

    def estimate_selectivity(
        self,
        all_partitions: list[int],
        operator: str,
        value: Any,
        partition_sizes: dict[int, int] | None = None,
    ) -> float:
        """Estimate selectivity of predicate after pruning.

        Args:
            all_partitions: List of all partition IDs
            operator: Comparison operator
            value: Predicate value
            partition_sizes: Optional dictionary mapping partition_id -> num_rows

        Returns:
            Estimated selectivity (0.0 to 1.0)
        """
        keep = self.prune_partitions(all_partitions, operator, value)

        if not partition_sizes:
            # Without sizes, estimate as fraction of partitions kept
            return len(keep) / len(all_partitions) if all_partitions else 0.0

        # Calculate fraction of rows in kept partitions
        total_rows = sum(partition_sizes.get(p, 0) for p in all_partitions)
        kept_rows = sum(partition_sizes.get(p, 0) for p in keep)

        return kept_rows / total_rows if total_rows > 0 else 0.0


class PartitionStatistics:
    """Statistics and metadata for partitions."""

    def __init__(self, partition_id: int) -> None:
        """Initialize partition statistics.

        Args:
            partition_id: Partition ID
        """
        self.partition_id = partition_id
        self.num_rows = 0
        self.column_stats: dict[str, Statistics] = {}
        self.compressed_size = 0
        self.uncompressed_size = 0

    def update(
        self,
        column_name: str,
        stats: Statistics,
        compressed_size: int,
        uncompressed_size: int,
    ) -> None:
        """Update statistics for column.

        Args:
            column_name: Column name
            stats: Column statistics
            compressed_size: Compressed size in bytes
            uncompressed_size: Uncompressed size in bytes
        """
        self.column_stats[column_name] = stats
        self.num_rows = stats.total_value_count
        self.compressed_size = compressed_size
        self.uncompressed_size = uncompressed_size

    def get_compression_ratio(self) -> float:
        """Get compression ratio."""
        if self.uncompressed_size == 0:
            return 1.0
        return self.uncompressed_size / self.compressed_size if self.compressed_size > 0 else 1.0

    def get_column_stats(self, column_name: str) -> Statistics | None:
        """Get statistics for column.

        Args:
            column_name: Column name

        Returns:
            Statistics or None if not found
        """
        return self.column_stats.get(column_name)
