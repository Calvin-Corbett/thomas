"""
Tests for data partitioning: range, hash, list, and composite partitioning.
"""

import pytest

from thomas.columnar._types import Statistics
from thomas.columnar.partitioning import (
    CompositePartitioner,
    HashPartitioner,
    ListPartitioner,
    PartitionPruner,
    PartitionStatistics,
    RangePartitioner,
)


class TestRangePartitioner:
    """Tests for range partitioning."""

    def test_get_partition(self) -> None:
        """Test getting partition for values."""
        partitioner = RangePartitioner([10, 20, 30])

        assert partitioner.get_partition(5) == 0
        assert partitioner.get_partition(15) == 1
        assert partitioner.get_partition(25) == 2
        assert partitioner.get_partition(35) == 3

    def test_null_handling(self) -> None:
        """Test null value partitioning."""
        partitioner = RangePartitioner([10, 20])

        assert partitioner.get_partition(None) == -1

    def test_boundary_values(self) -> None:
        """Test boundary value partitioning."""
        partitioner = RangePartitioner([10, 20, 30])

        assert partitioner.get_partition(10) == 1
        assert partitioner.get_partition(20) == 2
        assert partitioner.get_partition(30) == 3

    def test_should_prune_equal(self) -> None:
        """Test pruning with equality predicate."""
        partitioner = RangePartitioner([10, 20, 30])

        assert not partitioner.should_prune(1, "==", 15)
        assert partitioner.should_prune(1, "==", 5)
        assert partitioner.should_prune(1, "==", 25)

    def test_should_prune_range(self) -> None:
        """Test pruning with range predicates."""
        partitioner = RangePartitioner([10, 20, 30])

        assert partitioner.should_prune(3, "<", 30)
        assert not partitioner.should_prune(0, "<", 10)

    def test_get_partition_bounds(self) -> None:
        """Test getting partition bounds."""
        partitioner = RangePartitioner([10, 20, 30])

        bounds = partitioner.get_partition_bounds(1)
        assert bounds[0] == 10
        assert bounds[1] == 20


class TestHashPartitioner:
    """Tests for hash partitioning."""

    def test_get_partition(self) -> None:
        """Test getting partition for values."""
        partitioner = HashPartitioner(num_partitions=4)

        partition = partitioner.get_partition("apple")
        assert 0 <= partition < 4

    def test_consistent_partitioning(self) -> None:
        """Test that same value always gets same partition."""
        partitioner = HashPartitioner(num_partitions=4)

        p1 = partitioner.get_partition("apple")
        p2 = partitioner.get_partition("apple")

        assert p1 == p2

    def test_null_value(self) -> None:
        """Test null value partitioning."""
        partitioner = HashPartitioner(num_partitions=4)

        assert partitioner.get_partition(None) == -1

    def test_distribution(self) -> None:
        """Test even distribution across partitions."""
        partitioner = HashPartitioner(num_partitions=10)

        partitions = {}
        for i in range(1000):
            p = partitioner.get_partition(i)
            partitions[p] = partitions.get(p, 0) + 1

        # Check that all partitions are used
        assert len(partitions) == 10


class TestListPartitioner:
    """Tests for list partitioning."""

    def test_get_partition(self) -> None:
        """Test getting partition for categorical values."""
        partitioner = ListPartitioner(
            {
                0: ["US", "CA"],
                1: ["EU", "UK"],
                2: ["APAC", "AU"],
            }
        )

        assert partitioner.get_partition("US") == 0
        assert partitioner.get_partition("EU") == 1
        assert partitioner.get_partition("APAC") == 2

    def test_out_of_range_value(self) -> None:
        """Test out-of-range value."""
        partitioner = ListPartitioner({0: ["a", "b"], 1: ["c", "d"]})

        assert partitioner.get_partition("z") == -2

    def test_should_prune_equal(self) -> None:
        """Test pruning with equality predicate."""
        partitioner = ListPartitioner({0: ["a", "b"], 1: ["c", "d"]})

        assert not partitioner.should_prune(0, "==", "a")
        assert partitioner.should_prune(0, "==", "c")

    def test_should_prune_in_list(self) -> None:
        """Test pruning with in-list predicate."""
        partitioner = ListPartitioner({0: ["a", "b"], 1: ["c", "d"]})

        assert not partitioner.should_prune(0, "in", ["a", "x"])
        assert partitioner.should_prune(0, "in", ["c", "d"])

    def test_get_partition_values(self) -> None:
        """Test getting values for partition."""
        partitioner = ListPartitioner({0: ["a", "b"], 1: ["c", "d"]})

        values = partitioner.get_partition_values(0)

        assert "a" in values
        assert "b" in values


class TestCompositePartitioner:
    """Tests for composite partitioning."""

    def test_get_partition_tuple(self) -> None:
        """Test getting partition tuple."""
        year_partitioner = RangePartitioner([2020, 2021, 2022])
        month_partitioner = RangePartitioner([1, 4, 7, 10])

        partitioner = CompositePartitioner([("year", year_partitioner), ("month", month_partitioner)])

        p = partitioner.get_partition({"year": 2021, "month": 6})

        assert isinstance(p, tuple)
        assert len(p) == 2

    def test_should_prune_composite(self) -> None:
        """Test pruning with composite predicate."""
        year_partitioner = RangePartitioner([2020, 2021, 2022])
        month_partitioner = RangePartitioner([1, 4, 7, 10])

        partitioner = CompositePartitioner([("year", year_partitioner), ("month", month_partitioner)])

        predicates = {"year": (">", 2021), "month": ("<", 6)}

        # Get some partition IDs
        p_ids = (1, 0)

        # Should handle pruning
        should_prune = partitioner.should_prune(p_ids, predicates)

        assert isinstance(should_prune, bool)


class TestPartitionPruner:
    """Tests for partition pruner."""

    def test_prune_partitions(self) -> None:
        """Test pruning partitions."""
        partitioner = RangePartitioner([10, 20, 30])
        pruner = PartitionPruner(partitioner)

        all_partitions = [0, 1, 2, 3]
        pruned = pruner.prune_partitions(all_partitions, ">", 20)

        assert len(pruned) < len(all_partitions)

    def test_prune_with_and(self) -> None:
        """Test pruning with AND semantics."""
        partitioner = RangePartitioner([10, 20, 30])
        pruner = PartitionPruner(partitioner)

        all_partitions = [0, 1, 2, 3]
        predicates = [("<", 25), (">", 5)]

        pruned = pruner.prune_with_and(all_partitions, predicates)

        assert isinstance(pruned, list)

    def test_estimate_selectivity(self) -> None:
        """Test selectivity estimation."""
        partitioner = RangePartitioner([10, 20, 30])
        pruner = PartitionPruner(partitioner)

        all_partitions = [0, 1, 2, 3]
        selectivity = pruner.estimate_selectivity(all_partitions, ">", 20)

        assert 0.0 <= selectivity <= 1.0

    def test_estimate_selectivity_with_sizes(self) -> None:
        """Test selectivity estimation with partition sizes."""
        partitioner = RangePartitioner([10, 20, 30])
        pruner = PartitionPruner(partitioner)

        all_partitions = [0, 1, 2, 3]
        partition_sizes = {0: 100, 1: 200, 2: 150, 3: 50}

        selectivity = pruner.estimate_selectivity(all_partitions, "<", 25, partition_sizes)

        assert 0.0 <= selectivity <= 1.0


class TestPartitionStatistics:
    """Tests for partition statistics."""

    def test_create_and_update_stats(self) -> None:
        """Test creating and updating partition statistics."""
        stats = PartitionStatistics(partition_id=0)

        col_stats = Statistics()
        col_stats.total_value_count = 1000
        col_stats.distinct_count = 500

        stats.update("id", col_stats, 5000, 10000)

        assert stats.num_rows == 1000
        assert stats.compressed_size == 5000
        assert stats.uncompressed_size == 10000

    def test_get_compression_ratio(self) -> None:
        """Test compression ratio calculation."""
        stats = PartitionStatistics(partition_id=0)

        col_stats = Statistics()
        col_stats.total_value_count = 100

        stats.update("col", col_stats, 2500, 10000)

        ratio = stats.get_compression_ratio()

        assert ratio == pytest.approx(4.0)

    def test_get_column_stats(self) -> None:
        """Test getting column statistics."""
        stats = PartitionStatistics(partition_id=0)

        col_stats = Statistics()
        col_stats.total_value_count = 1000
        col_stats.distinct_count = 100

        stats.update("id", col_stats, 1000, 2000)

        retrieved = stats.get_column_stats("id")

        assert retrieved is not None
        assert retrieved.total_value_count == 1000

    def test_missing_column_stats(self) -> None:
        """Test getting non-existent column statistics."""
        stats = PartitionStatistics(partition_id=0)

        retrieved = stats.get_column_stats("non_existent")

        assert retrieved is None


class TestPartitioningEdgeCases:
    """Tests for partitioning edge cases."""

    def test_single_boundary(self) -> None:
        """Test range partitioner with single boundary."""
        partitioner = RangePartitioner([10])

        assert partitioner.get_partition(5) == 0
        assert partitioner.get_partition(15) == 1

    def test_large_number_of_partitions(self) -> None:
        """Test hash partitioner with many partitions."""
        partitioner = HashPartitioner(num_partitions=1000)

        partition = partitioner.get_partition("value")

        assert 0 <= partition < 1000

    def test_list_partitioner_single_value(self) -> None:
        """Test list partitioner with single value per partition."""
        partitioner = ListPartitioner({0: ["a"], 1: ["b"], 2: ["c"]})

        assert partitioner.get_partition("a") == 0
        assert partitioner.get_partition("b") == 1
        assert partitioner.get_partition("c") == 2

    def test_empty_partition_list(self) -> None:
        """Test list partitioner with empty partition."""
        partitioner = ListPartitioner({0: [], 1: ["a", "b"]})

        assert partitioner.get_partition("x") == -2
