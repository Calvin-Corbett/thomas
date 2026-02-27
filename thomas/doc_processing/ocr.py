"""Optical Character Recognition (OCR) simulation and framework.

Implements character recognition using template matching, connected component
extraction, feature extraction, k-NN classification, and post-processing.
"""

import math
from collections import Counter

import numpy as np

from thomas.doc_processing._exceptions import OCRError


class ConnectedComponentExtractor:
    """Extract connected components for character segmentation."""

    def __init__(self, threshold: float = 0.5):
        """Initialize extractor.

        Args:
            threshold: Binarization threshold (0-1).
        """
        self.threshold = threshold

    def extract(self, image_array: np.ndarray) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
        """Extract connected components from image.

        Args:
            image_array: 2D numpy array (grayscale).

        Returns:
            List of (component_array, bounding_box) tuples.

        Raises:
            OCRError: If extraction fails.
        """
        try:
            # Binarize
            binary = (image_array > self.threshold * 255).astype(np.uint8)

            components: list[tuple[np.ndarray, tuple[int, int, int, int]]] = []
            visited = np.zeros_like(binary, dtype=bool)

            for i in range(binary.shape[0]):
                for j in range(binary.shape[1]):
                    if binary[i, j] > 0 and not visited[i, j]:
                        component, bbox = self._bfs(binary, visited, i, j)
                        if component.size > 10:  # Minimum size
                            components.append((component, bbox))

            return components

        except Exception as e:
            raise OCRError(f"Connected component extraction failed: {e}")

    @staticmethod
    def _bfs(
        binary: np.ndarray,
        visited: np.ndarray,
        start_i: int,
        start_j: int,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """BFS to extract single component.

        Args:
            binary: Binary image.
            visited: Visited mask.
            start_i: Starting row.
            start_j: Starting column.

        Returns:
            Component array and bounding box (row0, col0, row1, col1).
        """
        queue = [(start_i, start_j)]
        visited[start_i, start_j] = True
        pixels = [(start_i, start_j)]

        min_row, max_row = start_i, start_i
        min_col, max_col = start_j, start_j

        while queue:
            i, j = queue.pop(0)

            # Check 8-connected neighbors
            for di in [-1, 0, 1]:
                for dj in [-1, 0, 1]:
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj

                    if (
                        0 <= ni < binary.shape[0]
                        and 0 <= nj < binary.shape[1]
                        and binary[ni, nj] > 0
                        and not visited[ni, nj]
                    ):
                        visited[ni, nj] = True
                        queue.append((ni, nj))
                        pixels.append((ni, nj))

                        min_row = min(min_row, ni)
                        max_row = max(max_row, ni)
                        min_col = min(min_col, nj)
                        max_col = max(max_col, nj)

        component = binary[min_row : max_row + 1, min_col : max_col + 1]

        return component, (min_row, min_col, max_row, max_col)


class CharacterFeatureExtractor:
    """Extract features from character images."""

    @staticmethod
    def extract_features(image: np.ndarray) -> dict[str, float]:
        """Extract feature vector from character image.

        Args:
            image: Binary character image.

        Returns:
            Dictionary of feature_name -> value.

        Raises:
            OCRError: If extraction fails.
        """
        try:
            features: dict[str, float] = {}

            # Shape features
            features["aspect_ratio"] = image.shape[1] / image.shape[0] if image.shape[0] > 0 else 0.0
            features["solidity"] = CharacterFeatureExtractor._solidity(image)
            features["eccentricity"] = CharacterFeatureExtractor._eccentricity(image)

            # Projection profiles
            h_proj = np.sum(image, axis=1)
            v_proj = np.sum(image, axis=0)

            features["horizontal_variance"] = float(np.var(h_proj))
            features["vertical_variance"] = float(np.var(v_proj))

            # Zoning features (divide image into 3x3 grid)
            zone_features = CharacterFeatureExtractor._zone_features(image)
            features.update(zone_features)

            # Moments
            moments = CharacterFeatureExtractor._moments(image)
            features.update(moments)

            return features

        except Exception as e:
            raise OCRError(f"Feature extraction failed: {e}")

    @staticmethod
    def _solidity(image: np.ndarray) -> float:
        """Calculate solidity (fill ratio).

        Args:
            image: Binary image.

        Returns:
            Solidity value (0-1).
        """
        area = np.sum(image > 0)
        if area == 0:
            return 0.0
        return area / image.size

    @staticmethod
    def _eccentricity(image: np.ndarray) -> float:
        """Calculate eccentricity of shape.

        Args:
            image: Binary image.

        Returns:
            Eccentricity value (0-1).
        """
        # Simple approximation using variance
        rows, cols = np.where(image > 0)
        if len(rows) == 0:
            return 0.0

        row_var = np.var(rows)
        col_var = np.var(cols)

        if col_var == 0:
            return 0.0

        return row_var / (row_var + col_var)

    @staticmethod
    def _zone_features(image: np.ndarray) -> dict[str, float]:
        """Extract 3x3 zoning features.

        Args:
            image: Binary image.

        Returns:
            Dictionary of zone_0_0 through zone_2_2 features.
        """
        features: dict[str, float] = {}
        h, w = image.shape

        for i in range(3):
            for j in range(3):
                row_start = (i * h) // 3
                row_end = ((i + 1) * h) // 3
                col_start = (j * w) // 3
                col_end = ((j + 1) * w) // 3

                zone = image[row_start:row_end, col_start:col_end]
                zone_sum = np.sum(zone)

                features[f"zone_{i}_{j}"] = float(zone_sum) / image.size

        return features

    @staticmethod
    def _moments(image: np.ndarray) -> dict[str, float]:
        """Calculate image moments.

        Args:
            image: Binary image.

        Returns:
            Dictionary with moment features.
        """
        features: dict[str, float] = {}
        h, w = image.shape

        m00 = np.sum(image)
        if m00 == 0:
            return {"m10": 0.0, "m01": 0.0}

        y_coords, x_coords = np.where(image > 0)

        m10 = np.sum(x_coords)
        m01 = np.sum(y_coords)

        features["m10"] = m10 / m00 if m00 > 0 else 0.0
        features["m01"] = m01 / m00 if m00 > 0 else 0.0

        return features


class KNNCharacterClassifier:
    """k-NN character classifier."""

    def __init__(self, k: int = 3):
        """Initialize classifier.

        Args:
            k: Number of neighbors.
        """
        self.k = k
        self.training_features: list[dict[str, float]] = []
        self.training_labels: list[str] = []

    def train(
        self,
        training_features: list[dict[str, float]],
        training_labels: list[str],
    ) -> None:
        """Train classifier.

        Args:
            training_features: List of feature dictionaries.
            training_labels: List of character labels.
        """
        self.training_features = training_features
        self.training_labels = training_labels

    def predict(self, features: dict[str, float]) -> str:
        """Classify character.

        Args:
            features: Feature vector.

        Returns:
            Predicted character.
        """
        if not self.training_features:
            return "?"

        distances = [
            (self._euclidean_distance(features, train_feat), label)
            for train_feat, label in zip(self.training_features, self.training_labels)
        ]

        distances.sort(key=lambda x: x[0])

        neighbors = distances[: self.k]
        labels = [label for _, label in neighbors]

        label_counts = Counter(labels)
        return label_counts.most_common(1)[0][0]

    @staticmethod
    def _euclidean_distance(vec1: dict[str, float], vec2: dict[str, float]) -> float:
        """Calculate Euclidean distance between feature vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Distance.
        """
        all_keys = set(vec1.keys()) | set(vec2.keys())

        sum_sq = sum((vec1.get(key, 0.0) - vec2.get(key, 0.0)) ** 2 for key in all_keys)

        return math.sqrt(sum_sq)


class WordSegmenter:
    """Segment characters into words."""

    @staticmethod
    def segment(
        components: list[tuple[np.ndarray, tuple[int, int, int, int]]],
    ) -> list[list[tuple[np.ndarray, tuple[int, int, int, int]]]]:
        """Segment characters into words based on gaps.

        Args:
            components: List of character components with bboxes.

        Returns:
            List of words (each word is a list of components).
        """
        if not components:
            return []

        # Sort by x-coordinate
        components.sort(key=lambda x: x[1][1])  # Sort by col0

        words: list[list[tuple[np.ndarray, tuple[int, int, int, int]]]] = []
        current_word: list[tuple[np.ndarray, tuple[int, int, int, int]]] = [components[0]]

        for i in range(1, len(components)):
            prev_bbox = components[i - 1][1]
            curr_bbox = components[i][1]

            # Gap between components
            gap = curr_bbox[1] - prev_bbox[3]

            # If gap is large, start new word
            if gap > 5:
                words.append(current_word)
                current_word = [components[i]]
            else:
                current_word.append(components[i])

        if current_word:
            words.append(current_word)

        return words


class LineDetector:
    """Detect text lines in document images."""

    @staticmethod
    def detect_lines(
        components: list[tuple[np.ndarray, tuple[int, int, int, int]]],
    ) -> list[list[tuple[np.ndarray, tuple[int, int, int, int]]]]:
        """Detect text lines using horizontal projection.

        Args:
            components: Character components with bboxes.

        Returns:
            List of lines (each line is a list of components).
        """
        if not components:
            return []

        # Get max dimensions
        max_row = max(bbox[2] for _, bbox in components)

        # Horizontal projection
        projection = np.zeros(max_row + 1)
        for _, bbox in components:
            for row in range(bbox[0], bbox[2] + 1):
                projection[row] += 1

        # Find valleys (gaps) in projection
        threshold = np.mean(projection) * 0.3
        lines: list[list[tuple[np.ndarray, tuple[int, int, int, int]]]] = []
        current_line: list[tuple[np.ndarray, tuple[int, int, int, int]]] = []

        for row in range(len(projection)):
            if projection[row] > threshold:
                # In a line
                current_line.extend([(comp, bbox) for comp, bbox in components if bbox[0] <= row <= bbox[2]])
            else:
                # Gap
                if current_line:
                    lines.append(current_line)
                    current_line = []

        if current_line:
            lines.append(current_line)

        # Remove duplicates and sort by row
        unique_lines: list[list[tuple[np.ndarray, tuple[int, int, int, int]]]] = []
        for line in lines:
            if line and line not in unique_lines:
                line.sort(key=lambda x: x[1][1])  # Sort by col0
                unique_lines.append(line)

        return unique_lines


class SpellCorrector:
    """Simple dictionary-based spell correction."""

    def __init__(self) -> None:
        """Initialize spell corrector."""
        self.vocabulary: dict[str, int] = {}

    def build_vocabulary(self, words: list[str]) -> None:
        """Build vocabulary from words.

        Args:
            words: List of correctly spelled words.
        """
        self.vocabulary = Counter(words)

    def correct(self, word: str) -> str:
        """Correct spelling of word.

        Args:
            word: Word to correct.

        Returns:
            Corrected word.
        """
        if word in self.vocabulary:
            return word

        # Find closest match in vocabulary
        candidates = [(w, self._edit_distance(word, w)) for w in self.vocabulary.keys()]

        candidates.sort(key=lambda x: x[1])

        if candidates and candidates[0][1] <= 2:
            return candidates[0][0]

        return word

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """Calculate edit distance.

        Args:
            s1: First string.
            s2: Second string.

        Returns:
            Edit distance.
        """
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

        return dp[m][n]


class LanguageModel:
    """Simple n-gram language model for OCR post-processing."""

    def __init__(self, n: int = 2) -> None:
        """Initialize language model.

        Args:
            n: N-gram size.
        """
        self.n = n
        self.ngrams: dict[tuple, int] = Counter()

    def fit(self, text: str) -> None:
        """Fit language model on text.

        Args:
            text: Training text.
        """
        words = text.split()

        for i in range(len(words) - self.n + 1):
            ngram = tuple(words[i : i + self.n])
            self.ngrams[ngram] += 1

    def score_sequence(self, words: list[str]) -> float:
        """Score a sequence of words.

        Args:
            words: Word sequence.

        Returns:
            Score (higher = better).
        """
        score = 0.0

        for i in range(len(words) - self.n + 1):
            ngram = tuple(words[i : i + self.n])
            if ngram in self.ngrams:
                score += math.log(self.ngrams[ngram] + 1)

        return score
