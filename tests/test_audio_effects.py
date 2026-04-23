"""
Tests for audio effects.
"""

import numpy as np

from thomas.marketplace.audio_engine.effects import (
    Chorus,
    Compressor,
    Delay,
    Distortion,
    Flanger,
    Limiter,
    Reverb,
    Tremolo,
)


class TestDelay:
    """Test delay effect."""

    def test_delay_basic(self) -> None:
        """Test basic delay effect."""
        delay = Delay(delay_time=0.1, feedback=0.3, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32)
        output = delay.process(samples)

        assert output.shape == samples.shape
        assert np.all(np.abs(output) <= 2.0)

    def test_delay_disabled(self) -> None:
        """Test disabled delay."""
        delay = Delay(delay_time=0.1, sample_rate=44100)
        delay.enabled = False
        samples = np.ones((100, 2), dtype=np.float32)
        output = delay.process(samples)

        assert np.allclose(output, samples)

    def test_delay_wet_dry_mix(self) -> None:
        """Test wet/dry mix."""
        delay = Delay(sample_rate=44100)
        delay.dry = 1.0
        delay.wet = 0.0
        samples = np.ones((100, 2), dtype=np.float32)
        output = delay.process(samples)

        assert np.allclose(output, samples)


class TestReverb:
    """Test reverb effect."""

    def test_reverb_basic(self) -> None:
        """Test basic reverb."""
        reverb = Reverb(room_size=0.5, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32)
        output = reverb.process(samples)

        assert output.shape == samples.shape

    def test_reverb_parameters(self) -> None:
        """Test reverb parameter effects."""
        reverb1 = Reverb(room_size=0.2, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)
        samples = np.column_stack([samples, samples])
        output1 = reverb1.process(samples)

        reverb2 = Reverb(room_size=0.8, sample_rate=44100)
        output2 = reverb2.process(samples)

        # Different parameters should produce different results
        assert not np.allclose(output1, output2)


class TestChorus:
    """Test chorus effect."""

    def test_chorus_basic(self) -> None:
        """Test basic chorus."""
        chorus = Chorus(rate=1.5, depth=3.0, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32)
        output = chorus.process(samples)

        assert output.shape == samples.shape

    def test_chorus_modulation(self) -> None:
        """Test chorus LFO modulation."""
        chorus = Chorus(rate=1.0, depth=5.0, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)
        samples = np.column_stack([samples, samples])
        output = chorus.process(samples)

        # Output should be different from input
        assert not np.allclose(output, samples)


class TestFlanger:
    """Test flanger effect."""

    def test_flanger_basic(self) -> None:
        """Test basic flanger."""
        flanger = Flanger(rate=0.5, depth=5.0, feedback=0.5, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32)
        output = flanger.process(samples)

        assert output.shape == samples.shape

    def test_flanger_feedback(self) -> None:
        """Test flanger feedback parameter."""
        flanger1 = Flanger(feedback=0.0, sample_rate=44100)
        samples = np.ones((1000, 2), dtype=np.float32)
        output1 = flanger1.process(samples)

        flanger2 = Flanger(feedback=0.8, sample_rate=44100)
        output2 = flanger2.process(samples)

        # Different feedback values should produce different results
        assert not np.allclose(output1, output2)


class TestDistortion:
    """Test distortion effect."""

    def test_distortion_soft_clipping(self) -> None:
        """Test soft clipping distortion."""
        distortion = Distortion(drive=5.0, distortion_type="soft")
        samples = np.ones((100, 2), dtype=np.float32) * 0.5
        output = distortion.process(samples)

        assert output.shape == samples.shape
        assert np.all(np.abs(output) <= 1.0)

    def test_distortion_hard_clipping(self) -> None:
        """Test hard clipping distortion."""
        distortion = Distortion(drive=5.0, distortion_type="hard")
        samples = np.ones((100, 2), dtype=np.float32) * 0.5
        output = distortion.process(samples)

        assert output.shape == samples.shape
        assert np.all(np.abs(output) <= 1.0)

    def test_distortion_waveshaper(self) -> None:
        """Test waveshaper distortion."""
        distortion = Distortion(drive=2.0, distortion_type="waveshaper")
        samples = np.ones((100, 2), dtype=np.float32) * 0.5
        output = distortion.process(samples)

        assert output.shape == samples.shape

    def test_distortion_drive(self) -> None:
        """Test distortion drive parameter."""
        distortion1 = Distortion(drive=1.0)
        samples = np.ones((100, 2), dtype=np.float32) * 0.5
        output1 = distortion1.process(samples)

        distortion2 = Distortion(drive=10.0)
        output2 = distortion2.process(samples)

        # More drive should produce more distortion
        assert np.std(output2) > np.std(output1)


class TestCompressor:
    """Test compressor effect."""

    def test_compressor_basic(self) -> None:
        """Test basic compression."""
        compressor = Compressor(threshold=-20.0, ratio=4.0, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)
        samples = np.column_stack([samples, samples])
        output = compressor.process(samples)

        assert output.shape == samples.shape

    def test_compressor_reduces_peaks(self) -> None:
        """Test that compressor reduces peaks."""
        compressor = Compressor(threshold=-10.0, ratio=4.0, sample_rate=44100)
        samples = np.array([0.1, 0.5, 0.9, 0.5, 0.1], dtype=np.float32)
        samples = np.column_stack([samples, samples])
        output = compressor.process(samples)

        # Peak should be reduced
        assert np.max(output) < np.max(samples)


class TestLimiter:
    """Test limiter effect."""

    def test_limiter_basic(self) -> None:
        """Test basic limiting."""
        limiter = Limiter(threshold=0.0, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32) * 2.0
        output = limiter.process(samples)

        assert output.shape == samples.shape

    def test_limiter_prevents_clipping(self) -> None:
        """Test that limiter prevents clipping."""
        limiter = Limiter(threshold=-3.0, sample_rate=44100)
        samples = np.ones((100, 2), dtype=np.float32)
        output = limiter.process(samples)

        # Should prevent loudest samples from exceeding threshold
        assert np.max(np.abs(output)) < 1.0


class TestTremolo:
    """Test tremolo effect."""

    def test_tremolo_basic(self) -> None:
        """Test basic tremolo."""
        tremolo = Tremolo(rate=5.0, depth=0.5, sample_rate=44100)
        samples = np.ones((4410, 2), dtype=np.float32)
        output = tremolo.process(samples)

        assert output.shape == samples.shape

    def test_tremolo_modulation(self) -> None:
        """Test tremolo amplitude modulation."""
        tremolo = Tremolo(rate=1.0, depth=1.0, sample_rate=44100)
        samples = np.ones((44100, 2), dtype=np.float32) * 0.5
        output = tremolo.process(samples)

        # Output should vary due to modulation
        assert np.std(output[:, 0]) > 0.1

    def test_tremolo_rate(self) -> None:
        """Test tremolo rate parameter."""
        tremolo1 = Tremolo(rate=1.0, sample_rate=44100)
        samples = np.ones((44100, 2), dtype=np.float32) * 0.5
        output1 = tremolo1.process(samples)

        tremolo2 = Tremolo(rate=10.0, sample_rate=44100)
        output2 = tremolo2.process(samples)

        # Different rates should produce different modulation patterns
        assert not np.allclose(output1, output2)
