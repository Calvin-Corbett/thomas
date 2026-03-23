"""
Tests for audio mixer functionality.
"""

import numpy as np

from thomas.marketplace.audio_engine._types import PanLaw
from thomas.marketplace.audio_engine.mixer import Mixer, MixerAutomation, VUMeter


class TestMixer:
    """Test audio mixer."""

    def test_mixer_initialization(self) -> None:
        """Test mixer initialization."""
        mixer = Mixer(num_channels=8, sample_rate=44100)

        assert len(mixer.channels) == 8
        assert mixer.sample_rate == 44100

    def test_mixer_input_output(self) -> None:
        """Test mixer input and output."""
        mixer = Mixer(num_channels=2, sample_rate=44100)
        samples = np.ones((1000, 2), dtype=np.float32) * 0.1

        mixer.input_samples(0, samples)
        mixer.input_samples(1, samples)

        output = mixer.mix(1000)
        assert output.shape == (1000, 2)

    def test_mixer_channel_volume(self) -> None:
        """Test channel volume control."""
        mixer = Mixer(num_channels=2, sample_rate=44100)
        samples = np.ones((100, 2), dtype=np.float32) * 0.5

        mixer.set_channel_volume(0, 0.5)
        mixer.input_samples(0, samples)
        output1 = mixer.mix(100)

        mixer.set_channel_volume(0, 2.0)
        mixer.input_samples(0, samples)
        output2 = mixer.mix(100)

        # Higher volume should produce louder output
        assert np.mean(np.abs(output2)) > np.mean(np.abs(output1))

    def test_mixer_channel_mute(self) -> None:
        """Test channel mute."""
        mixer = Mixer(num_channels=2, sample_rate=44100)
        samples = np.ones((100, 2), dtype=np.float32) * 0.5

        mixer.input_samples(0, samples)
        mixer.set_channel_mute(0, True)
        output = mixer.mix(100)

        # Muted channel should produce silent output
        assert np.allclose(output, 0, atol=0.01)

    def test_mixer_panning(self) -> None:
        """Test stereo panning."""
        mixer = Mixer(num_channels=1, sample_rate=44100)
        samples = np.ones((100, 2), dtype=np.float32) * 0.5

        # Pan left
        mixer.set_channel_pan(0, -1.0)
        mixer.input_samples(0, samples)
        output_left = mixer.mix(100)

        # Pan right
        mixer.set_channel_pan(0, 1.0)
        mixer.input_samples(0, samples)
        output_right = mixer.mix(100)

        # Different panning should produce different left/right balance
        assert not np.allclose(output_left, output_right)

    def test_mixer_solo(self) -> None:
        """Test solo function."""
        mixer = Mixer(num_channels=2, sample_rate=44100)
        samples1 = np.ones((100, 2), dtype=np.float32) * 0.5
        samples2 = np.ones((100, 2), dtype=np.float32) * 0.3

        mixer.input_samples(0, samples1)
        mixer.input_samples(1, samples2)

        mixer.set_channel_solo(0, True)
        output = mixer.mix(100)

        # With solo on channel 0, only that channel should be audible
        assert np.mean(np.abs(output)) > np.mean(np.abs(samples2))

    def test_mixer_pan_laws(self) -> None:
        """Test different pan laws."""
        for pan_law in [PanLaw.LINEAR, PanLaw.EQUAL_POWER, PanLaw.MINUS_4_5DB]:
            mixer = Mixer(num_channels=1, sample_rate=44100, pan_law=pan_law)
            samples = np.ones((100, 2), dtype=np.float32) * 0.5

            mixer.set_channel_pan(0, 0.0)  # Center
            mixer.input_samples(0, samples)
            output = mixer.mix(100)

            assert output.shape == (100, 2)


class TestVUMeter:
    """Test VU meter."""

    def test_vu_meter_basic(self) -> None:
        """Test basic VU meter operation."""
        meter = VUMeter(sample_rate=44100)
        samples = np.ones(4410, dtype=np.float32) * 0.5
        peak_db, rms_db = meter.process(samples)

        assert isinstance(peak_db, float)
        assert isinstance(rms_db, float)

    def test_vu_meter_peak_detection(self) -> None:
        """Test VU meter peak detection."""
        meter = VUMeter(sample_rate=44100)

        # Low amplitude
        samples1 = np.ones(1000, dtype=np.float32) * 0.1
        peak1, _ = meter.process(samples1)

        meter.reset()

        # High amplitude
        samples2 = np.ones(1000, dtype=np.float32) * 0.9
        peak2, _ = meter.process(samples2)

        # Higher amplitude should have higher peak level
        assert peak2 > peak1

    def test_vu_meter_rms_calculation(self) -> None:
        """Test RMS calculation."""
        meter = VUMeter(sample_rate=44100)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 4410)).astype(np.float32)
        _, rms_db = meter.process(samples)

        # RMS of sine wave should be reasonable
        assert rms_db < 0  # Should be negative in dB

    def test_vu_meter_reset(self) -> None:
        """Test VU meter reset."""
        meter = VUMeter(sample_rate=44100)
        samples = np.ones(1000, dtype=np.float32)

        peak1, _ = meter.process(samples)
        meter.reset()
        peak2, _ = meter.process(np.zeros(1000, dtype=np.float32))

        # After reset, silent signal should have low peak
        assert peak2 < peak1


class TestMixerAutomation:
    """Test mixer automation."""

    def test_automation_linear(self) -> None:
        """Test linear automation curve."""
        automation = MixerAutomation(target_value=1.0, duration=1000, curve="linear")
        samples = automation.process(1000)

        assert len(samples) == 1000
        # Should smoothly transition
        assert samples[0] < samples[-1]

    def test_automation_exponential(self) -> None:
        """Test exponential automation curve."""
        automation = MixerAutomation(target_value=1.0, duration=1000, curve="exponential")
        samples = automation.process(1000)

        assert len(samples) == 1000

    def test_automation_value_range(self) -> None:
        """Test automation value range."""
        automation = MixerAutomation(target_value=2.0, duration=1000)
        samples = automation.process(1000)

        # Should smoothly approach target
        assert samples[-1] <= 2.0
        assert samples[0] < samples[-1]
