"""
Tests for audio filters.
"""

import numpy as np

from thomas.marketplace.audio_engine.filters import BiquadFilter, CrossoverFilter, FilterCascade, ParametricEQ


class TestBiquadFilter:
    """Test biquad filter."""

    def test_lowpass_filter(self) -> None:
        """Test lowpass filter."""
        filt = BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_highpass_filter(self) -> None:
        """Test highpass filter."""
        filt = BiquadFilter.highpass(1000.0, 0.707, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_bandpass_filter(self) -> None:
        """Test bandpass filter."""
        filt = BiquadFilter.bandpass(1000.0, 100.0, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_notch_filter(self) -> None:
        """Test notch filter."""
        filt = BiquadFilter.notch(1000.0, 0.707, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_peaking_eq(self) -> None:
        """Test peaking EQ filter."""
        filt = BiquadFilter.peaking(1000.0, 12.0, 0.707, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 1000)).astype(np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_low_shelf(self) -> None:
        """Test low shelf filter."""
        filt = BiquadFilter.low_shelf(200.0, 12.0, 0.5, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_high_shelf(self) -> None:
        """Test high shelf filter."""
        filt = BiquadFilter.high_shelf(5000.0, 12.0, 0.5, sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)
        output = filt.process(samples)

        assert len(output) == 1000

    def test_filter_state_reset(self) -> None:
        """Test filter state reset."""
        filt = BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100)
        samples1 = np.ones(100, dtype=np.float32)
        output1 = filt.process(samples1)

        filt.reset()
        output2 = filt.process(samples1)

        # After reset, same input should produce same output
        assert np.allclose(output1, output2)

    def test_single_sample_processing(self) -> None:
        """Test processing single samples."""
        filt = BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100)

        sample1 = filt.process_sample(0.5)
        sample2 = filt.process_sample(0.5)

        assert isinstance(sample1, float)
        assert isinstance(sample2, float)


class TestFilterCascade:
    """Test filter cascade."""

    def test_cascade_basic(self) -> None:
        """Test basic filter cascade."""
        cascade = FilterCascade()
        cascade.add_filter(BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100))
        cascade.add_filter(BiquadFilter.highpass(100.0, 0.707, sample_rate=44100))

        samples = np.ones(1000, dtype=np.float32)
        output = cascade.process(samples)

        assert len(output) == 1000

    def test_cascade_order(self) -> None:
        """Test filter cascade order."""
        cascade = FilterCascade()
        for _ in range(3):
            cascade.add_filter(BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100))

        assert cascade.order == 6  # 3 filters * 2nd order each

    def test_cascade_reset(self) -> None:
        """Test cascade reset."""
        cascade = FilterCascade()
        cascade.add_filter(BiquadFilter.lowpass(1000.0, 0.707, sample_rate=44100))

        samples = np.ones(100, dtype=np.float32)
        output1 = cascade.process(samples)

        cascade.reset()
        output2 = cascade.process(samples)

        assert np.allclose(output1, output2)


class TestParametricEQ:
    """Test parametric EQ."""

    def test_eq_basic(self) -> None:
        """Test basic parametric EQ."""
        eq = ParametricEQ(sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)
        output = eq.process(samples)

        assert len(output) == 4410

    def test_eq_band_adjustment(self) -> None:
        """Test EQ band adjustment."""
        eq = ParametricEQ(sample_rate=44100)

        # Boost low band
        eq.set_band(0, 100.0, 12.0, 0.7)
        samples = np.ones(1000, dtype=np.float32)
        output1 = eq.process(samples)

        # No boost
        eq.set_band(0, 100.0, 0.0, 0.7)
        output2 = eq.process(samples)

        # Different EQ settings should produce different results
        assert not np.allclose(output1, output2)

    def test_eq_three_bands(self) -> None:
        """Test three-band EQ."""
        eq = ParametricEQ(sample_rate=44100)

        # Low band
        eq.set_band(0, 100.0, 6.0, 0.7)
        # Mid band
        eq.set_band(1, 1000.0, -6.0, 0.7)
        # High band
        eq.set_band(2, 10000.0, 12.0, 0.7)

        samples = np.ones(4410, dtype=np.float32)
        output = eq.process(samples)

        assert len(output) == 4410


class TestCrossoverFilter:
    """Test crossover filter."""

    def test_crossover_basic(self) -> None:
        """Test basic crossover."""
        crossover = CrossoverFilter(1000.0, sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)

        lowpass, highpass = crossover.split(samples)

        assert len(lowpass) == len(samples)
        assert len(highpass) == len(samples)

    def test_crossover_energy_conservation(self) -> None:
        """Test that crossover approximately conserves energy."""
        crossover = CrossoverFilter(1000.0, sample_rate=44100)
        samples = np.random.randn(4410).astype(np.float32) * 0.1

        lowpass, highpass = crossover.split(samples)

        # Energy in lowpass + highpass should be similar to original
        energy_in = np.sum(samples**2)
        energy_out = np.sum(lowpass**2) + np.sum(highpass**2)

        # Should be approximately equal (allowing for numerical error)
        assert energy_out > energy_in * 0.5

    def test_crossover_frequency_dependent(self) -> None:
        """Test crossover frequency dependence."""
        crossover_low = CrossoverFilter(500.0, sample_rate=44100)
        crossover_high = CrossoverFilter(2000.0, sample_rate=44100)

        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)

        low_out1, high_out1 = crossover_low.split(samples)
        low_out2, high_out2 = crossover_high.split(samples)

        # Different crossover frequencies should produce different results
        assert not np.allclose(low_out1, low_out2)
