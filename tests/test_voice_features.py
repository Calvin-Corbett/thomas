"""
Tests for voice feature extraction module.
"""

import numpy as np
import pytest

from thomas.marketplace.voice._types import AudioSample
from thomas.marketplace.voice.features import FeatureExtractor


class TestFeatureExtractor:
    """Tests for FeatureExtractor class."""

    @pytest.fixture
    def extractor(self) -> FeatureExtractor:
        """Create feature extractor."""
        return FeatureExtractor()

    @pytest.fixture
    def audio_sample(self) -> AudioSample:
        """Create test audio sample."""
        sample_rate = 16000
        duration = 1.0
        t = np.arange(0, duration, 1 / sample_rate)
        # Generate 440 Hz sine wave
        data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_pre_emphasis(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test pre-emphasis filter."""
        emphasized = extractor._apply_pre_emphasis(audio_sample.data)

        assert len(emphasized) == len(audio_sample.data)
        assert emphasized[0] == audio_sample.data[0]
        assert not np.array_equal(emphasized, audio_sample.data)

    def test_frame_blocking(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test frame blocking."""
        frames = extractor._frame_blocking(audio_sample.data, audio_sample.sample_rate)

        assert len(frames) > 0
        assert all(f.frame_data.shape[0] == extractor.frame_size for f in frames)
        assert all(f.sample_rate == audio_sample.sample_rate for f in frames)

    def test_hz_to_mel_conversion(self, extractor: FeatureExtractor) -> None:
        """Test Hz to mel conversion."""
        hz = 1000.0
        mel = extractor._hz_to_mel(hz)

        assert mel > 0
        assert mel < extractor._hz_to_mel(8000)  # 1kHz < 8kHz in mel scale

    def test_mel_to_hz_conversion(self, extractor: FeatureExtractor) -> None:
        """Test mel to Hz conversion."""
        mel = 1000.0
        hz = extractor._mel_to_hz(mel)

        assert hz > 0
        assert hz < 8000  # Should be reasonable speech frequency

    def test_mel_hz_roundtrip(self, extractor: FeatureExtractor) -> None:
        """Test Hz-mel roundtrip conversion."""
        original_hz = 1000.0
        mel = extractor._hz_to_mel(original_hz)
        recovered_hz = extractor._mel_to_hz(mel)

        assert np.isclose(original_hz, recovered_hz, rtol=0.01)

    def test_power_spectrum(self, extractor: FeatureExtractor) -> None:
        """Test power spectrum computation."""
        frame = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 512))
        power = extractor._power_spectrum(frame)

        assert len(power) == 257
        assert np.all(power >= 0)

    def test_mel_filterbank(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test mel filterbank."""
        frame = audio_sample.data[:512]
        power = extractor._power_spectrum(frame)
        mel_energies = extractor._mel_filterbank(power, audio_sample.sample_rate)

        assert len(mel_energies) == extractor.mel_filters
        assert np.all(mel_energies >= 0)

    def test_extract_mfcc(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test MFCC extraction."""
        mfcc = extractor.extract_mfcc(audio_sample)

        assert mfcc.num_frames > 0
        assert mfcc.num_coefficients == extractor.mfcc_coefficients
        assert mfcc.coefficients.shape[1] == extractor.mfcc_coefficients
        assert mfcc.delta is not None
        assert mfcc.delta_delta is not None

    def test_mfcc_delta_calculation(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test delta and delta-delta calculations."""
        mfcc = extractor.extract_mfcc(audio_sample)

        assert mfcc.delta.shape == mfcc.coefficients.shape
        assert mfcc.delta_delta.shape == mfcc.coefficients.shape

    def test_zero_crossing_rate(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test zero-crossing rate extraction."""
        zcr = extractor.extract_zero_crossing_rate(audio_sample)

        assert len(zcr) > 0
        assert np.all(zcr >= 0)
        assert np.all(zcr <= 1)

    def test_short_time_energy(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test short-time energy extraction."""
        energy = extractor.extract_short_time_energy(audio_sample)

        assert len(energy) > 0
        # Energy in dB should be negative for normalized signals
        assert np.all(energy <= 0)

    def test_formant_estimation(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test formant estimation."""
        formants = extractor.estimate_formants(audio_sample, num_formants=3)

        assert len(formants) > 0
        for formant in formants:
            assert formant.f1 >= 0
            assert formant.f2 >= 0
            assert formant.f3 >= 0

    def test_lpc_analysis(self, extractor: FeatureExtractor) -> None:
        """Test LPC analysis."""
        frame = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 512))
        lpc = extractor._lpc_analysis(frame, order=10)

        assert len(lpc) == 10

    def test_autocorrelation(self, extractor: FeatureExtractor) -> None:
        """Test autocorrelation calculation."""
        signal = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 512))
        autocorr = extractor._autocorrelation(signal, order=50)

        assert len(autocorr) == 50
        assert autocorr[0] == np.max(autocorr)  # First lag is maximum

    def test_mfcc_mean_vector(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test MFCC mean vector calculation."""
        mfcc = extractor.extract_mfcc(audio_sample)
        mean = mfcc.get_mean_vector()

        assert len(mean) == extractor.mfcc_coefficients

    def test_mfcc_covariance_matrix(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test MFCC covariance matrix calculation."""
        mfcc = extractor.extract_mfcc(audio_sample)
        cov = mfcc.get_covariance_matrix()

        assert cov.shape == (
            extractor.mfcc_coefficients,
            extractor.mfcc_coefficients,
        )
        assert np.allclose(cov, cov.T)  # Symmetric

    def test_frame_get_power(self, extractor: FeatureExtractor) -> None:
        """Test frame power calculation."""
        frame_data = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 512))

        from thomas.marketplace.voice._types import SpeechFrame

        frame = SpeechFrame(
            frame_data=frame_data,
            frame_index=0,
            timestamp=0.0,
            duration=0.032,
            sample_rate=16000,
        )

        power = frame.get_power()

        assert power >= 0

    def test_feature_extractor_different_frame_sizes(self) -> None:
        """Test feature extractor with different frame sizes."""
        for frame_size in [256, 512, 1024]:
            extractor = FeatureExtractor(frame_size=frame_size)
            assert extractor.frame_size == frame_size

    def test_mfcc_consistency(self, extractor: FeatureExtractor, audio_sample: AudioSample) -> None:
        """Test MFCC extraction consistency."""
        mfcc1 = extractor.extract_mfcc(audio_sample)
        mfcc2 = extractor.extract_mfcc(audio_sample)

        assert np.allclose(mfcc1.coefficients, mfcc2.coefficients)
