"""
Similarity computation functions for recommendation algorithms.
"""

import math


def cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute cosine similarity between two feature vectors.

    Cosine similarity measures the cosine of the angle between two vectors.
    Returns a value between -1 and 1, typically used on non-negative vectors (0 to 1).

    Args:
        vec1: First feature vector as dictionary.
        vec2: Second feature vector as dictionary.

    Returns:
        Cosine similarity score between -1 and 1.
    """
    if not vec1 or not vec2:
        return 0.0

    # Compute dot product
    dot_product = sum(vec1.get(key, 0.0) * vec2.get(key, 0.0) for key in set(vec1.keys()) | set(vec2.keys()))

    # Compute magnitudes
    mag1 = math.sqrt(sum(v**2 for v in vec1.values()))
    mag2 = math.sqrt(sum(v**2 for v in vec2.values()))

    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


def pearson_correlation(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute Pearson correlation coefficient between vectors.

    Pearson correlation measures linear correlation between vectors.
    Ranges from -1 (perfect negative) to 1 (perfect positive).

    Args:
        vec1: First feature vector as dictionary.
        vec2: Second feature vector as dictionary.

    Returns:
        Pearson correlation coefficient between -1 and 1.
    """
    # Get common keys
    common_keys = set(vec1.keys()) & set(vec2.keys())
    if len(common_keys) < 2:
        return 0.0

    # Extract values
    vals1 = [vec1[k] for k in common_keys]
    vals2 = [vec2[k] for k in common_keys]

    # Compute means
    mean1 = sum(vals1) / len(vals1)
    mean2 = sum(vals2) / len(vals2)

    # Compute Pearson correlation
    numerator = sum((vals1[i] - mean1) * (vals2[i] - mean2) for i in range(len(vals1)))
    denom1 = math.sqrt(sum((v - mean1) ** 2 for v in vals1))
    denom2 = math.sqrt(sum((v - mean2) ** 2 for v in vals2))

    if denom1 == 0 or denom2 == 0:
        return 0.0

    return numerator / (denom1 * denom2)


def jaccard_similarity(set1: set, set2: set) -> float:
    """Compute Jaccard similarity between two sets.

    Jaccard similarity = |intersection| / |union|.
    Useful for comparing sets of items (tags, categories, etc).

    Args:
        set1: First set.
        set2: Second set.

    Returns:
        Jaccard similarity between 0 and 1.
    """
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union


def euclidean_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Convert Euclidean distance to similarity (1 / (1 + distance)).

    Euclidean distance measures straight-line distance between points.
    Converted to similarity where closer points have higher similarity.

    Args:
        vec1: First feature vector as dictionary.
        vec2: Second feature vector as dictionary.

    Returns:
        Similarity score between 0 and 1.
    """
    if not vec1 or not vec2:
        return 0.0

    # All keys
    all_keys = set(vec1.keys()) | set(vec2.keys())

    # Compute sum of squared differences
    sum_sq_diff = sum((vec1.get(key, 0.0) - vec2.get(key, 0.0)) ** 2 for key in all_keys)

    distance = math.sqrt(sum_sq_diff)
    return 1.0 / (1.0 + distance)


def adjusted_cosine_similarity(
    vec1: dict[str, float], vec2: dict[str, float], mean1: float = 0.0, mean2: float = 0.0
) -> float:
    """Compute adjusted cosine similarity (subtract user/item mean).

    Used in collaborative filtering to account for rating biases.
    Each rating is adjusted by subtracting the user's mean rating.

    Args:
        vec1: First rating vector.
        vec2: Second rating vector.
        mean1: Mean to subtract from vec1.
        mean2: Mean to subtract from vec2.

    Returns:
        Adjusted cosine similarity.
    """
    common_keys = set(vec1.keys()) & set(vec2.keys())
    if not common_keys:
        return 0.0

    # Subtract means
    adj_vec1 = {k: vec1[k] - mean1 for k in common_keys}
    adj_vec2 = {k: vec2[k] - mean2 for k in common_keys}

    return cosine_similarity(adj_vec1, adj_vec2)


def hamming_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Compute similarity based on Hamming distance for binary vectors.

    Hamming distance counts positions where vectors differ.
    Converted to similarity as (n - distance) / n.

    Args:
        vec1: First binary vector (values 0 or 1).
        vec2: Second binary vector (values 0 or 1).

    Returns:
        Hamming similarity between 0 and 1.
    """
    all_keys = set(vec1.keys()) | set(vec2.keys())
    if not all_keys:
        return 1.0

    distance = sum(1 for key in all_keys if vec1.get(key, 0.0) != vec2.get(key, 0.0))

    return 1.0 - (distance / len(all_keys))


class SimilarityComputer:
    """Computes and caches similarity matrices between entities."""

    def __init__(self, metric: str = "cosine") -> None:
        """Initialize similarity computer.

        Args:
            metric: Similarity metric to use ("cosine", "pearson", "jaccard", etc).
        """
        self.metric = metric
        self.cache: dict[tuple[str, str], float] = {}

    def compute(
        self,
        entity1_id: str,
        entity2_id: str,
        vec1: dict[str, float],
        vec2: dict[str, float],
    ) -> float:
        """Compute similarity with caching.

        Args:
            entity1_id: ID of first entity.
            entity2_id: ID of second entity.
            vec1: Vector for first entity.
            vec2: Vector for second entity.

        Returns:
            Similarity score.
        """
        # Check cache (both orderings)
        cache_key = tuple(sorted([entity1_id, entity2_id]))
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Compute similarity
        if self.metric == "cosine":
            sim = cosine_similarity(vec1, vec2)
        elif self.metric == "pearson":
            sim = pearson_correlation(vec1, vec2)
        elif self.metric == "euclidean":
            sim = euclidean_similarity(vec1, vec2)
        elif self.metric == "hamming":
            sim = hamming_similarity(vec1, vec2)
        else:
            sim = cosine_similarity(vec1, vec2)

        self.cache[cache_key] = sim
        return sim

    def pairwise_similarity(self, entities: dict[str, dict[str, float]]) -> dict[tuple[str, str], float]:
        """Compute pairwise similarities between all entities.

        Args:
            entities: Mapping of entity_id to feature vector.

        Returns:
            Dictionary mapping (id1, id2) pairs to similarity scores.
        """
        result: dict[tuple[str, str], float] = {}
        entity_ids = list(entities.keys())

        for i, id1 in enumerate(entity_ids):
            for id2 in entity_ids[i + 1 :]:
                sim = self.compute(id1, id2, entities[id1], entities[id2])
                result[(id1, id2)] = sim
                result[(id2, id1)] = sim  # Symmetric

        return result

    def similarity_matrix(self, entities: dict[str, dict[str, float]]) -> tuple[list[str], list[list[float]]]:
        """Compute similarity matrix as 2D array.

        Args:
            entities: Mapping of entity_id to feature vector.

        Returns:
            Tuple of (entity_ids, similarity_matrix).
        """
        entity_ids = list(entities.keys())
        n = len(entity_ids)
        matrix = [[0.0] * n for _ in range(n)]

        for i, id1 in enumerate(entity_ids):
            for j, id2 in enumerate(entity_ids):
                if i == j:
                    matrix[i][j] = 1.0
                else:
                    sim = self.compute(id1, id2, entities[id1], entities[id2])
                    matrix[i][j] = sim

        return entity_ids, matrix

    def clear_cache(self) -> None:
        """Clear the similarity cache."""
        self.cache.clear()

    def get_top_similar(
        self,
        entity_id: str,
        entities: dict[str, dict[str, float]],
        k: int = 10,
    ) -> list[tuple[str, float]]:
        """Get k most similar entities to a given entity.

        Args:
            entity_id: ID of reference entity.
            entities: All entities.
            k: Number of similar entities to return.

        Returns:
            List of (entity_id, similarity) tuples, sorted by similarity.
        """
        if entity_id not in entities:
            return []

        similarities: list[tuple[str, float]] = []
        ref_vec = entities[entity_id]

        for other_id, other_vec in entities.items():
            if other_id == entity_id:
                continue
            sim = self.compute(entity_id, other_id, ref_vec, other_vec)
            similarities.append((other_id, sim))

        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]
