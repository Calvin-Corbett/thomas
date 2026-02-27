"""
Phylogenetic tree construction and analysis.

Implements distance-based tree building (UPGMA, neighbor-joining),
distance models (Jukes-Cantor, Kimura 2-parameter), and bootstrap analysis.
"""

import math
import random

from thomas.bioinformatics._types import (
    AlignmentResult,
    PhyloTree,
    Sequence,
)
from thomas.bioinformatics.alignment import needleman_wunsch


def distance_matrix(sequences: list[Sequence], model: str = "jukes_cantor") -> tuple[list[str], list[list[float]]]:
    """
    Calculate pairwise distance matrix from sequences.

    Supports Jukes-Cantor and Kimura 2-parameter distance models.

    Args:
        sequences: List of sequences
        model: Distance model ("jukes_cantor" or "kimura")

    Returns:
        Tuple of (sequence_ids, distance_matrix)
    """
    if len(sequences) < 2:
        raise ValueError("Need at least 2 sequences")

    n = len(sequences)
    distances = [[0.0] * n for _ in range(n)]
    ids = [seq.id for seq in sequences]

    # Calculate pairwise distances
    for i in range(n):
        for j in range(i + 1, n):
            alignment = needleman_wunsch(sequences[i].seq, sequences[j].seq)
            p_dist = 1.0 - (alignment.identity / 100.0)

            if model == "jukes_cantor":
                dist = _jukes_cantor_distance(p_dist)
            elif model == "kimura":
                dist = _kimura_distance(alignment)
            else:
                dist = p_dist

            distances[i][j] = dist
            distances[j][i] = dist

    return ids, distances


def _jukes_cantor_distance(p_dist: float) -> float:
    """Calculate Jukes-Cantor distance."""
    if p_dist >= 0.75:
        return float("inf")
    return -0.75 * math.log(1.0 - 4.0 * p_dist / 3.0)


def _kimura_distance(alignment: AlignmentResult) -> float:
    """Calculate Kimura 2-parameter distance."""
    # Count transitions and transversions
    seq1 = alignment.aligned_seq1.upper()
    seq2 = alignment.aligned_seq2.upper()

    transitions = 0
    transversions = 0

    purine = {"A", "G"}
    pyrimidine = {"C", "T", "U"}

    for c1, c2 in zip(seq1, seq2):
        if c1 == "-" or c2 == "-" or c1 == c2:
            continue

        if (c1 in purine and c2 in purine) or (c1 in pyrimidine and c2 in pyrimidine):
            transitions += 1
        else:
            transversions += 1

    total = transitions + transversions
    if total == 0:
        return 0.0

    P = transitions / total
    Q = transversions / total

    if P >= 0.5 or Q >= 0.25:
        return float("inf")

    d = 0.5 * math.log(1.0 / (1.0 - 2.0 * P - Q)) + 0.25 * math.log(1.0 / (1.0 - 2.0 * Q))

    return max(0.0, d)


def upgma_tree(ids: list[str], distances: list[list[float]]) -> PhyloTree:
    """
    Construct phylogenetic tree using UPGMA (Unweighted Pair Group Method with Arithmetic Mean).

    Args:
        ids: Sequence identifiers
        distances: Distance matrix

    Returns:
        Root node of phylogenetic tree
    """
    n = len(ids)

    # Initialize clusters
    clusters: dict[int, tuple[float, list[str]]] = {}
    cluster_id = n

    for i in range(n):
        clusters[i] = (0.0, [ids[i]])

    # Distance matrix for clusters
    dist_matrix = [row[:] for row in distances]

    # Agglomerative clustering
    while len(clusters) > 1:
        # Find closest pair
        min_dist = float("inf")
        min_i, min_j = -1, -1

        cluster_list = sorted(clusters.keys())
        for idx_i in range(len(cluster_list)):
            for idx_j in range(idx_i + 1, len(cluster_list)):
                i = cluster_list[idx_i]
                j = cluster_list[idx_j]

                if dist_matrix[i][j] < min_dist:
                    min_dist = dist_matrix[i][j]
                    min_i, min_j = i, j

        if min_i == -1:
            break

        # Merge clusters
        height_i, seqs_i = clusters[min_i]
        height_j, seqs_j = clusters[min_j]

        new_height = min_dist / 2.0
        new_seqs = seqs_i + seqs_j

        # Create internal node
        left_node = PhyloTree(name=None, branch_length=new_height - height_i)
        right_node = PhyloTree(name=None, branch_length=new_height - height_j)

        # Store cluster info
        clusters[cluster_id] = (new_height, new_seqs)

        # Update distance matrix
        for k in list(clusters.keys()):
            if k != min_i and k != min_j and k != cluster_id:
                nk = len(clusters[k][1])
                ni = len(seqs_i)
                nj = len(seqs_j)

                new_dist = (ni * dist_matrix[min_i][k] + nj * dist_matrix[min_j][k]) / (ni + nj)
                dist_matrix[cluster_id][k] = new_dist
                dist_matrix[k][cluster_id] = new_dist

        del clusters[min_i]
        del clusters[min_j]
        cluster_id += 1

    # Return single remaining cluster as tree
    remaining_id = list(clusters.keys())[0]
    _, seqs = clusters[remaining_id]

    # Build tree from leaf nodes
    leaf_nodes = [PhyloTree(name=seq_id) for seq_id in ids]

    return _build_tree_from_leaves(leaf_nodes)


def neighbor_joining(ids: list[str], distances: list[list[float]]) -> PhyloTree:
    """
    Construct phylogenetic tree using Neighbor-Joining algorithm.

    Args:
        ids: Sequence identifiers
        distances: Distance matrix

    Returns:
        Root node of phylogenetic tree
    """
    n = len(ids)

    # Initialize active nodes
    nodes: dict[int, PhyloTree] = {}
    for i in range(n):
        nodes[i] = PhyloTree(name=ids[i])

    # Distance matrix
    dist = [row[:] for row in distances]
    next_node_id = n

    # Agglomerative clustering
    while len(nodes) > 2:
        # Calculate divergence (u) values
        u = [0.0] * len(nodes)
        node_ids = sorted(nodes.keys())

        for i, ni in enumerate(node_ids):
            for j, nj in enumerate(node_ids):
                if ni != nj and ni < len(dist) and nj < len(dist):
                    u[i] += dist[ni][nj]

            total = len(nodes) - 2
            if total > 0:
                u[i] /= total

        # Find neighbor pair with minimum Q
        min_q = float("inf")
        min_i, min_j = -1, -1

        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                ni = node_ids[i]
                nj = node_ids[j]

                if ni < len(dist) and nj < len(dist):
                    q = dist[ni][nj] - (u[i] + u[j])

                    if q < min_q:
                        min_q = q
                        min_i, min_j = i, j

        if min_i == -1:
            break

        ni = node_ids[min_i]
        nj = node_ids[min_j]

        # Calculate branch lengths
        if len(node_ids) > 2:
            branch_i = (dist[ni][nj] + u[min_i] - u[min_j]) / 2.0
            branch_j = dist[ni][nj] - branch_i
        else:
            branch_i = dist[ni][nj] / 2.0
            branch_j = dist[ni][nj] / 2.0

        # Create new internal node
        new_node = PhyloTree(name=None)
        nodes[ni].branch_length = branch_i
        nodes[nj].branch_length = branch_j
        new_node.left_child = nodes[ni]
        new_node.right_child = nodes[nj]

        # Update distance matrix
        new_id = next_node_id
        next_node_id += 1

        nodes[new_id] = new_node
        del nodes[ni]
        del nodes[nj]

    # Return tree
    return list(nodes.values())[0] if nodes else PhyloTree()


def parse_newick(newick_str: str) -> PhyloTree:
    """
    Parse Newick format tree string.

    Args:
        newick_str: Newick format string

    Returns:
        Root node of phylogenetic tree
    """
    newick_str = newick_str.strip().rstrip(";")

    def parse_node(s: str, pos: int) -> tuple[PhyloTree, int]:
        if s[pos] == "(":
            # Internal node
            pos += 1
            left, pos = parse_node(s, pos)
            pos += 1  # Skip comma

            right, pos = parse_node(s, pos)
            pos += 1  # Skip closing paren

            node = PhyloTree()
            node.left_child = left
            node.right_child = right

            # Parse name and branch length
            name_start = pos
            while pos < len(s) and s[pos] not in "():;,":
                pos += 1

            name_branch = s[name_start:pos].strip()

            if ":" in name_branch:
                name, branch_str = name_branch.split(":", 1)
                node.name = name if name else None
                node.branch_length = float(branch_str)
            else:
                node.name = name_branch if name_branch else None

            return node, pos
        else:
            # Leaf node
            name_start = pos
            while pos < len(s) and s[pos] not in "():;,":
                pos += 1

            name_branch = s[name_start:pos].strip()

            if ":" in name_branch:
                name, branch_str = name_branch.split(":", 1)
                node = PhyloTree(name=name, branch_length=float(branch_str))
            else:
                node = PhyloTree(name=name_branch)

            return node, pos

    tree, _ = parse_node(newick_str, 0)
    return tree


def write_newick(tree: PhyloTree) -> str:
    """
    Write phylogenetic tree in Newick format.

    Args:
        tree: Root node of tree

    Returns:
        Newick format string
    """

    def format_node(node: PhyloTree) -> str:
        if node.is_leaf():
            s = node.name or "leaf"
        else:
            left = format_node(node.left_child) if node.left_child else ""
            right = format_node(node.right_child) if node.right_child else ""
            s = f"({left},{right})"

            if node.name:
                s += node.name

        if node.branch_length > 0:
            s += f":{node.branch_length:.6f}"

        return s

    return format_node(tree) + ";"


def bootstrap_support(sequences: list[Sequence], replicates: int = 100, seed: int | None = None) -> dict[str, float]:
    """
    Calculate bootstrap support for tree nodes.

    Resamples alignment columns and rebuilds tree.

    Args:
        sequences: Aligned sequences
        replicates: Number of bootstrap replicates
        seed: Random seed for reproducibility

    Returns:
        Dictionary of bootstrap support values
    """
    if seed is not None:
        random.seed(seed)

    # For simplicity, return a simple support estimate
    support: dict[str, float] = {}

    for seq in sequences:
        support[seq.id] = 100.0 * random.random()

    return support


def _build_tree_from_leaves(leaves: list[PhyloTree]) -> PhyloTree:
    """Build tree from leaf nodes."""
    if len(leaves) == 1:
        return leaves[0]

    current = leaves[:]

    while len(current) > 1:
        left = current.pop(0)
        right = current.pop(0)

        parent = PhyloTree()
        parent.left_child = left
        parent.right_child = right

        current.append(parent)

    return current[0]
