"""
Graph partitioning algorithms.

Implements spectral partitioning, Kernighan-Lin heuristic, and balanced partitioning.
"""

import math
import random


def spectral_partitioning(adjacency_matrix: list[list[float]], num_partitions: int = 2, seed: int = 42) -> list[int]:
    """
    Partition graph using spectral method (Fiedler vector).

    Uses power iteration to compute Laplacian eigenvector and thresholds to partition.

    Args:
        adjacency_matrix: Adjacency matrix (list of lists).
        num_partitions: Number of partitions (typically 2).
        seed: Random seed.

    Returns:
        List of partition assignments (indices 0 to num_partitions-1).
    """
    random.seed(seed)
    n = len(adjacency_matrix)

    if n == 0:
        return []

    # Compute degree matrix
    degrees = [sum(row) for row in adjacency_matrix]

    # Compute Laplacian: L = D - A
    laplacian = [[0.0] * n for _ in range(n)]
    for i in range(n):
        laplacian[i][i] = degrees[i]
        for j in range(n):
            laplacian[i][j] -= adjacency_matrix[i][j]

    # Power iteration for second smallest eigenvector
    x = [1.0 / math.sqrt(n)] * n

    for iteration in range(100):
        # Matrix-vector product
        x_new = [0.0] * n
        for i in range(n):
            for j in range(n):
                x_new[i] += laplacian[i][j] * x[j]

        # Normalize
        norm = math.sqrt(sum(val**2 for val in x_new))
        if norm == 0:
            break

        x_new = [val / norm for val in x_new]

        # Check convergence
        diff = sum(abs(x_new[i] - x[i]) for i in range(n))
        x = x_new

        if diff < 1e-6:
            break

    # Threshold to partition
    median = sorted(x)[n // 2]
    partitions = [0 if val < median else 1 for val in x]

    return partitions


def kernighan_lin_partitioning(
    adjacency_matrix: list[list[float]], initial_partition: list[int], max_iterations: int = 100
) -> list[int]:
    """
    Improve partition using Kernighan-Lin heuristic.

    Iteratively swaps pairs of nodes if it reduces edge cut.

    Args:
        adjacency_matrix: Adjacency matrix.
        initial_partition: Initial partition assignment.
        max_iterations: Maximum iterations.

    Returns:
        Improved partition assignment.
    """
    n = len(adjacency_matrix)
    partition = initial_partition.copy()

    for iteration in range(max_iterations):
        moved = False

        # Try swapping each pair
        for i in range(n):
            for j in range(i + 1, n):
                if partition[i] == partition[j]:
                    continue

                # Calculate cost of swap
                cost_i = sum(adjacency_matrix[i][k] for k in range(n) if partition[k] != partition[i])
                cost_j = sum(adjacency_matrix[j][k] for k in range(n) if partition[k] != partition[j])

                cost_ij = adjacency_matrix[i][j] if adjacency_matrix[i][j] > 0 else 0

                # Gain from swapping
                gain = cost_i + cost_j - 2 * cost_ij

                if gain > 0:
                    # Perform swap
                    partition[i], partition[j] = partition[j], partition[i]
                    moved = True

        if not moved:
            break

    return partition


def min_cut_partitioning(adjacency_matrix: list[list[float]], num_partitions: int = 2) -> list[int]:
    """
    Partition graph to minimize edge cut.

    Uses recursive spectral partitioning.

    Args:
        adjacency_matrix: Adjacency matrix.
        num_partitions: Number of partitions.

    Returns:
        Partition assignment.
    """
    n = len(adjacency_matrix)

    if n == 0 or num_partitions <= 1:
        return [0] * n

    # Use spectral partitioning for initial cut
    partition = spectral_partitioning(adjacency_matrix, num_partitions=2)

    # Recursively partition if needed
    if num_partitions > 2:
        partition_0 = [i for i in range(n) if partition[i] == 0]
        partition_1 = [i for i in range(n) if partition[i] == 1]

        if partition_0:
            sub_adj_0 = [[adjacency_matrix[i][j] for j in partition_0] for i in partition_0]
            sub_partition_0 = spectral_partitioning(sub_adj_0, num_partitions // 2)
            for idx, orig_idx in enumerate(partition_0):
                partition[orig_idx] = sub_partition_0[idx]

        if partition_1:
            sub_adj_1 = [[adjacency_matrix[i][j] for j in partition_1] for i in partition_1]
            sub_partition_1 = spectral_partitioning(sub_adj_1, num_partitions - num_partitions // 2)
            for idx, orig_idx in enumerate(partition_1):
                partition[orig_idx] = sub_partition_1[idx] + num_partitions // 2

    return partition


def balanced_partitioning(
    adjacency_matrix: list[list[float]], num_partitions: int = 2, balance_factor: float = 0.1
) -> list[int]:
    """
    Partition graph with size balance constraint.

    Partitions should have sizes within balance_factor of ideal size.

    Args:
        adjacency_matrix: Adjacency matrix.
        num_partitions: Number of partitions.
        balance_factor: Acceptable deviation from ideal partition size.

    Returns:
        Balanced partition assignment.
    """
    n = len(adjacency_matrix)

    if n == 0 or num_partitions <= 1:
        return [0] * n

    # Get initial partition
    partition = spectral_partitioning(adjacency_matrix, num_partitions)

    # Check balance
    partition_sizes = [partition.count(p) for p in range(num_partitions)]
    ideal_size = n / num_partitions
    tolerance = int(ideal_size * balance_factor)

    # Try to balance by moving nodes
    for iteration in range(100):
        unbalanced = False

        for p in range(num_partitions):
            current_size = partition.count(p)

            if abs(current_size - ideal_size) > tolerance:
                unbalanced = True

                # Find nodes to move
                for i in range(n):
                    if partition[i] == p:
                        # Try moving to better partition
                        best_new_p = p
                        best_cost = abs(current_size - ideal_size)

                        for new_p in range(num_partitions):
                            if new_p != p:
                                cost = abs(current_size - 1 - ideal_size)
                                if cost < best_cost:
                                    best_cost = cost
                                    best_new_p = new_p

                        if best_new_p != p:
                            partition[i] = best_new_p
                            break

        if not unbalanced:
            break

    return partition


def partition_quality(adjacency_matrix: list[list[float]], partition: list[int]) -> dict[str, float]:
    """
    Calculate quality metrics for a partition.

    Computes edge cut, conductance, and other measures.

    Args:
        adjacency_matrix: Adjacency matrix.
        partition: Partition assignment.

    Returns:
        Dictionary of quality metrics.
    """
    n = len(adjacency_matrix)
    num_partitions = max(partition) + 1 if partition else 0

    # Count edges
    internal_edges = 0
    cut_edges = 0

    for i in range(n):
        for j in range(i + 1, n):
            if adjacency_matrix[i][j] > 0:
                if partition[i] == partition[j]:
                    internal_edges += 1
                else:
                    cut_edges += 1

    # Partition sizes
    partition_sizes = [partition.count(p) for p in range(num_partitions)]

    # Conductance
    total_edges = internal_edges + cut_edges
    conductance = cut_edges / (2 * total_edges) if total_edges > 0 else 0

    # Edge expansion
    expansion = cut_edges / min(partition_sizes) if min(partition_sizes) > 0 else float("inf")

    # Balance
    avg_size = n / num_partitions if num_partitions > 0 else 0
    imbalance = max(abs(size - avg_size) for size in partition_sizes) / avg_size if avg_size > 0 else 0

    return {
        "edge_cut": cut_edges,
        "internal_edges": internal_edges,
        "conductance": conductance,
        "edge_expansion": expansion,
        "imbalance": imbalance,
        "num_partitions": num_partitions,
    }


def multi_way_partitioning(
    adjacency_matrix: list[list[float]], num_partitions: int, num_runs: int = 5, seed: int = 42
) -> list[int]:
    """
    Find good multi-way partition using multiple random starts.

    Args:
        adjacency_matrix: Adjacency matrix.
        num_partitions: Number of partitions.
        num_runs: Number of different runs to try.
        seed: Random seed.

    Returns:
        Best partition found.
    """
    random.seed(seed)
    best_partition = None
    best_cost = float("inf")

    for run in range(num_runs):
        partition = spectral_partitioning(adjacency_matrix, num_partitions, seed=seed + run)

        # Improve with Kernighan-Lin
        partition = kernighan_lin_partitioning(adjacency_matrix, partition)

        # Evaluate
        quality = partition_quality(adjacency_matrix, partition)
        cost = quality["conductance"]

        if cost < best_cost:
            best_cost = cost
            best_partition = partition

    return best_partition if best_partition is not None else [0] * len(adjacency_matrix)
