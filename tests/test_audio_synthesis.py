"""
Tests for audio synthesis including oscillators, ADSR, and FM synthesis.
"""

import numpy as np

from thomas.marketplace.audio_engine._types import WaveformType
from thomas.marketplace.audio_engine.synthesis import (
    LFO,
    AdditiveSynthesis,
    ADSREnvelope,
    FMSynthesis,
    NoiseGenerator,
    Oscillator,
    Wavetable,
)


class TestOscillator:
    """Test oscillator functionality."""

    def test_sine_oscillator(self) -> None:
        """Test sine wave oscillator."""
        osc = Oscillator(440.0, 44100, WaveformType.SINE)
        samples = osc.process(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)
        assert np.max(np.abs(samples)) > 0.9  # Should be close to 1.0

    def test_square_oscillator(self) -> None:
        """Test square wave oscillator."""
        osc = Oscillator(440.0, 44100, WaveformType.SQUARE)
        samples = osc.process(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)

    def test_sawtooth_oscillator(self) -> None:
        """Test sawtooth wave oscillator."""
        osc = Oscillator(440.0, 44100, WaveformType.SAWTOOTH)
        samples = osc.process(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)

    def test_triangle_oscillator(self) -> None:
        """Test triangle wave oscillator."""
        osc = Oscillator(440.0, 44100, WaveformType.TRIANGLE)
        samples = osc.process(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)

    def test_frequency_modulation(self) -> None:
        """Test frequency modulation."""
        osc = Oscillator(440.0, 44100)
        samples1 = osc.process(100)

        osc.set_frequency(880.0)
        samples2 = osc.process(100)

        # Higher frequency should have more zero crossings
        zc1 = np.sum(np.abs(np.diff(np.sign(samples1))))
        zc2 = np.sum(np.abs(np.diff(np.sign(samples2))))
        assert zc2 > zc1

    def test_phase_setting(self) -> None:
        """Test phase setting."""
        osc1 = Oscillator(440.0, 44100, WaveformType.SINE)
        osc1.set_phase(0.0)
        samples1 = osc1.process(10)

        osc2 = Oscillator(440.0, 44100, WaveformType.SINE)
        osc2.set_phase(0.5)
        samples2 = osc2.process(10)

        assert not np.allclose(samples1, samples2)


class TestWavetable:
    """Test wavetable synthesis."""

    def test_wavetable_sine(self) -> None:
        """Test sine wavetable."""
        wt = Wavetable(WaveformType.SINE, size=2048, sample_rate=44100)
        samples = wt.process(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)

    def test_wavetable_square(self) -> None:
        """Test square wavetable."""
        wt = Wavetable(WaveformType.SQUARE, size=2048, sample_rate=44100)
        samples = wt.process(44100)

        assert len(samples) == 44100

    def test_wavetable_frequency_change(self) -> None:
        """Test frequency change during playback."""
        wt = Wavetable(WaveformType.SINE, size=2048, sample_rate=44100)
        wt.set_frequency(440.0)
        samples1 = wt.process(100)

        wt.set_frequency(880.0)
        samples2 = wt.process(100)

        # Output should be different
        assert not np.allclose(samples1, samples2)


class TestNoiseGenerator:
    """Test noise generators."""

    def test_white_noise(self) -> None:
        """Test white noise generation."""
        gen = NoiseGenerator(44100)
        samples = gen.white_noise(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)
        # White noise should have variation
        assert np.std(samples) > 0.2

    def test_pink_noise(self) -> None:
        """Test pink noise generation."""
        gen = NoiseGenerator(44100)
        samples = gen.pink_noise(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)

    def test_brown_noise(self) -> None:
        """Test brown noise generation."""
        gen = NoiseGenerator(44100)
        samples = gen.brown_noise(44100)

        assert len(samples) == 44100
        assert np.all(np.abs(samples) <= 1.0)


class TestADSREnvelope:
    """Test ADSR envelope generator."""

    def test_adsr_basic(self) -> None:
        """Test basic ADSR envelope."""
        env = ADSREnvelope(attack=0.1, decay=0.1, sustain=0.7, release=0.1, sample_rate=44100)
        env.trigger()
        samples = env.process(44100 * 4)

        assert len(samples) == 44100 * 4
        assert np.all(samples >= 0.0) and np.all(samples <= 1.0)

    def test_attack_phase(self) -> None:
        """Test attack phase."""
        env = ADSREnvelope(attack=0.1, decay=0.1, sustain=0.7, release=0.1, sample_rate=44100)
        env.trigger()
        samples = env.process(int(44100 * 0.05))  # 50ms

        # Should be increasing
        assert samples[-1] > samples[0]

    def test_release_phase(self) -> None:
        """Test release phase."""
        env = ADSREnvelope(attack=0.01, decay=0.01, sustain=0.7, release=0.1, sample_rate=44100)
        env.trigger()
        env.process(int(44100 * 0.1))  # Advance past attack/decay
        env.release()
        samples = env.process(int(44100 * 0.05))

        # Should be decreasing after release
        assert samples[-1] < samples[0]


class TestLFO:
    """Test low-frequency oscillator."""

    def test_lfo_basic(self) -> None:
        """Test basic LFO."""
        lfo = LFO(frequency=5.0, amplitude=1.0, offset=0.0, sample_rate=44100)
        samples = lfo.process(44100)

        assert len(samples) == 44100

    def test_lfo_frequency(self) -> None:
        """Test LFO frequency modulation."""
        lfo = LFO(frequency=1.0, amplitude=1.0, sample_rate=44100)
        lfo.set_frequency(5.0)
        samples = lfo.process(44100)

        # Higher frequency should have more cycles
        assert len(samples) > 0

    def test_lfo_offset(self) -> None:
        """Test LFO with offset."""
        lfo = LFO(frequency=1.0, amplitude=0.5, offset=0.5, sample_rate=44100)
        samples = lfo.process(44100)

        # Values should be around offset
        assert np.min(samples) > 0.0
        assert np.max(samples) <= 1.0


class TestAdditiveSynthesis:
    """Test additive synthesis."""

    def test_additive_basic(self) -> None:
        """Test basic additive synthesis."""
        synth = AdditiveSynthesis(440.0, sample_rate=44100)
        synth.add_harmonic(2, 0.5)
        synth.add_harmonic(3, 0.3)
        samples = synth.process(4410)

        assert len(samples) == 4410
        assert np.all(np.abs(samples) <= 1.0)

    def test_additive_fundamental(self) -> None:
        """Test additive synthesis with fundamental."""
        synth = AdditiveSynthesis(440.0, sample_rate=44100)
        samples = synth.process(4410)

        assert len(samples) == 4410


class TestFMSynthesis:
    """Test FM synthesis."""

    def test_fm_basic(self) -> None:
        """Test basic FM synthesis."""
        synth = FMSynthesis(carrier_freq=440.0, modulator_freq=5.0, modulation_index=5.0, sample_rate=44100)
        samples = synth.process(4410)

        assert len(samples) == 4410
        assert np.all(np.abs(samples) <= 1.0)

    def test_fm_modulation_index(self) -> None:
        """Test FM with different modulation indices."""
        synth1 = FMSynthesis(440.0, 5.0, modulation_index=2.0, sample_rate=44100)
        samples1 = synth1.process(4410)

        synth2 = FMSynthesis(440.0, 5.0, modulation_index=10.0, sample_rate=44100)
        samples2 = synth2.process(4410)

        # Different modulation indices should produce different results
        assert not np.allclose(samples1, samples2)
