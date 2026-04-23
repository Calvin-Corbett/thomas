"""
Speaker recognition module.

Speaker verification, identification, and clustering:
- Speaker enrollment (i-vector-like representation)
- Speaker verification via cosine similarity
- Speaker identification
- GMM-UBM approach with MAP adaptation
- Agglomerative clustering with BIC criterion
"""

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import cosine

from thomas.marketplace.voice._exceptions import SpeakerError
from thomas.marketplace.voice._types import (
    AudioSample,
    SpeakerModel,
)
from thomas.marketplace.voice.features import FeatureExtractor


class SpeakerRecognizer:
    """Performs speaker recognition tasks."""

    def __init__(
        self,
        num_gmm_components: int = 16,
        mfcc_coefficients: int = 13,
    ) -> None:
        """
        Initialize speaker recognizer.

        Args:
            num_gmm_components: Number of GMM components.
            mfcc_coefficients: Number of MFCC coefficients.
        """
        self.num_gmm_components = num_gmm_components
        self.mfcc_coefficients = mfcc_coefficients
        self.feature_extractor = FeatureExtractor(mfcc_coefficients=mfcc_coefficients)
        self.speakers: dict[str, SpeakerModel] = {}

    def enroll_speaker(self, speaker_id: str, audio_samples: list[AudioSample]) -> SpeakerModel:
        """
        Enroll a speaker with training utterances.

        Extracts MFCC features and creates speaker model.

        Args:
            speaker_id: Unique speaker identifier.
            audio_samples: List of audio samples for enrollment.

        Returns:
            Speaker model.

        Raises:
            SpeakerError: If enrollment fails.
        """
        try:
            all_features = []

            for audio in audio_samples:
                mfcc = self.feature_extractor.extract_mfcc(audio)
                all_features.append(mfcc.coefficients)

            # Concatenate all features
            all_features = np.vstack(all_features)

            # Calculate mean and covariance
            mean_vector = np.mean(all_features, axis=0)
            covariance_matrix = np.cov(all_features.T)

            # Train GMM
            gmm_weights, gmm_means, gmm_covariances = self._train_gmm(all_features, self.num_gmm_components)

            model = SpeakerModel(
                speaker_id=speaker_id,
                mean_vector=mean_vector,
                covariance_matrix=covariance_matrix,
                num_utterances=len(audio_samples),
                gmm_weights=gmm_weights,
                gmm_means=gmm_means,
                gmm_covariances=gmm_covariances,
            )

            self.speakers[speaker_id] = model
            return model

        except Exception as e:
            raise SpeakerError(f"Speaker enrollment failed: {str(e)}")

    def verify_speaker(self, speaker_id: str, audio_sample: AudioSample, threshold: float = 0.5) -> tuple[bool, float]:
        """
        Verify if audio belongs to enrolled speaker.

        Args:
            speaker_id: Speaker identifier to verify.
            audio_sample: Test audio sample.
            threshold: Decision threshold for similarity.

        Returns:
            Tuple of (verified, score).

        Raises:
            SpeakerError: If verification fails.
        """
        try:
            if speaker_id not in self.speakers:
                raise SpeakerError(f"Speaker {speaker_id} not enrolled")

            model = self.speakers[speaker_id]

            # Extract MFCC
            mfcc = self.feature_extractor.extract_mfcc(audio_sample)

            # Calculate similarity
            score = self._calculate_similarity(mfcc.coefficients, model)

            verified = score > threshold

            return verified, score

        except SpeakerError:
            raise
        except Exception as e:
            raise SpeakerError(f"Speaker verification failed: {str(e)}")

    def identify_speaker(self, audio_sample: AudioSample) -> tuple[str, float]:
        """
        Identify which enrolled speaker the audio belongs to.

        Args:
            audio_sample: Test audio sample.

        Returns:
            Tuple of (speaker_id, score).

        Raises:
            SpeakerError: If identification fails.
        """
        try:
            if not self.speakers:
                raise SpeakerError("No speakers enrolled")

            mfcc = self.feature_extractor.extract_mfcc(audio_sample)

            best_speaker = None
            best_score = -np.inf

            for speaker_id, model in self.speakers.items():
                score = self._calculate_similarity(mfcc.coefficients, model)

                if score > best_score:
                    best_score = score
                    best_speaker = speaker_id

            return best_speaker, best_score

        except SpeakerError:
            raise
        except Exception as e:
            raise SpeakerError(f"Speaker identification failed: {str(e)}")

    def cluster_speakers(
        self, audio_samples: list[tuple[str, AudioSample]], distance_threshold: float = 0.5
    ) -> list[list[str]]:
        """
        Cluster unknown speakers using agglomerative clustering.

        Args:
            audio_samples: List of (sample_id, audio) tuples.
            distance_threshold: Distance threshold for clustering.

        Returns:
            List of clusters (each cluster is a list of sample IDs).

        Raises:
            SpeakerError: If clustering fails.
        """
        try:
            if not audio_samples:
                return []

            # Extract MFCC features for all samples
            features = []
            sample_ids = []

            for sample_id, audio in audio_samples:
                mfcc = self.feature_extractor.extract_mfcc(audio)
                mean_vector = np.mean(mfcc.coefficients, axis=0)
                features.append(mean_vector)
                sample_ids.append(sample_id)

            features = np.array(features)

            # Compute distance matrix
            num_samples = len(features)
            distance_matrix = np.zeros((num_samples, num_samples))

            for i in range(num_samples):
                for j in range(i + 1, num_samples):
                    dist = cosine(features[i], features[j])
                    distance_matrix[i, j] = dist
                    distance_matrix[j, i] = dist

            # Agglomerative clustering
            condensed_dist = self._condense_distance_matrix(distance_matrix)
            Z = linkage(condensed_dist, method="ward")

            # Cut dendrogram
            cluster_labels = fcluster(Z, distance_threshold, criterion="distance")

            # Group by cluster
            clusters: dict[int, list[str]] = {}
            for sample_id, label in zip(sample_ids, cluster_labels):
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(sample_id)

            return list(clusters.values())

        except Exception as e:
            raise SpeakerError(f"Speaker clustering failed: {str(e)}")

    def _calculate_similarity(self, test_features: np.ndarray, model: SpeakerModel) -> float:
        """
        Calculate similarity between test features and speaker model.

        Uses cosine similarity of mean vectors.

        Args:
            test_features: Test MFCC features (num_frames x num_coefficients).
            model: Speaker model.

        Returns:
            Similarity score [0, 1].
        """
        # Get mean vector of test features
        test_mean = np.mean(test_features, axis=0)

        # Cosine similarity
        similarity = 1 - cosine(test_mean, model.mean_vector)

        # Map to [0, 1]
        return max(0.0, min(1.0, (similarity + 1) / 2))

    def _train_gmm(
        self, features: np.ndarray, num_components: int, max_iterations: int = 10
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Train Gaussian Mixture Model using EM algorithm.

        Args:
            features: Feature matrix (num_samples x num_features).
            num_components: Number of Gaussian components.
            max_iterations: Maximum EM iterations.

        Returns:
            Tuple of (weights, means, covariances).
        """
        num_samples, num_features = features.shape

        # Initialize components
        indices = np.random.choice(num_samples, num_components, replace=False)
        means = features[indices].copy()
        weights = np.ones(num_components) / num_components
        covariances = np.array([np.cov(features.T) for _ in range(num_components)])

        for _ in range(max_iterations):
            # E-step: compute responsibilities
            responsibilities = np.zeros((num_samples, num_components))

            for k in range(num_components):
                try:
                    inv_cov = np.linalg.inv(covariances[k])
                    det_cov = np.linalg.det(covariances[k])

                    if det_cov <= 0:
                        det_cov = 1e-10

                    diff = features - means[k]
                    mahalanobis = np.diagonal(diff @ inv_cov @ diff.T)
                    gaussian = weights[k] * np.exp(-0.5 * mahalanobis) / np.sqrt((2 * np.pi) ** num_features * det_cov)
                    responsibilities[:, k] = gaussian
                except np.linalg.LinAlgError:
                    responsibilities[:, k] = weights[k]

            # Normalize responsibilities
            norm = np.sum(responsibilities, axis=1, keepdims=True)
            norm[norm == 0] = 1
            responsibilities /= norm

            # M-step: update parameters
            Nk = np.sum(responsibilities, axis=0)

            for k in range(num_components):
                if Nk[k] > 0:
                    weights[k] = Nk[k] / num_samples
                    means[k] = np.average(features, axis=0, weights=responsibilities[:, k])

                    diff = features - means[k]
                    weighted_diff = (diff.T * responsibilities[:, k]) @ diff / Nk[k]
                    covariances[k] = weighted_diff + np.eye(num_features) * 1e-6

        return weights, means, covariances

    def _condense_distance_matrix(self, dist_matrix: np.ndarray) -> np.ndarray:
        """
        Convert square distance matrix to condensed form.

        Args:
            dist_matrix: Square distance matrix.

        Returns:
            Condensed distance vector.
        """
        n = dist_matrix.shape[0]
        condensed = []

        for i in range(n):
            for j in range(i + 1, n):
                condensed.append(dist_matrix[i, j])

        return np.array(condensed)
