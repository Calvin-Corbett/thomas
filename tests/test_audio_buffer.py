"""
Tests for audio buffer management and sample conversion.
"""

import numpy as np
import pytest

from thomas.marketplace.audio_engine._exceptions import BufferOverflowError, BufferUnderflowError
from thomas.marketplace.audio_engine.buffer import (
    AudioBufferPool,
    BitDepthConverter,
    ChannelConverter,
    RingBuffer,
    SampleConverter,
    SampleRateConverter,
)


class TestRingBuffer:
    """Test ring buffer functionality."""

    def test_write_read_basic(self) -> None:
        """Test basic write and read."""
        buf = RingBuffer(100, 2)
        samples = np.ones((10, 2), dtype=np.float32)
        assert buf.write(samples) == 10
        assert buf.available_read == 10

    def test_write_overflow(self) -> None:
        """Test write overflow detection."""
        buf = RingBuffer(10, 2)
        samples = np.ones((20, 2), dtype=np.float32)
        with pytest.raises(BufferOverflowError):
            buf.write(samples)

    def test_read_underflow(self) -> None:
        """Test read underflow detection."""
        buf = RingBuffer(100, 2)
        with pytest.raises(BufferUnderflowError):
            buf.read(10)

    def test_wraparound(self) -> None:
        """Test buffer wrap-around."""
        buf = RingBuffer(20, 1)
        samples1 = np.arange(15, dtype=np.float32).reshape(15, 1)
        samples2 = np.arange(10, dtype=np.float32).reshape(10, 1)

        buf.write(samples1)
        buf.read(10)
        buf.write(samples2)
        result = buf.read(15)

        assert len(result) == 15

    def test_flush(self) -> None:
        """Test buffer flush."""
        buf = RingBuffer(100, 2)
        samples = np.ones((10, 2), dtype=np.float32)
        buf.write(samples)
        buf.flush()
        assert buf.available_read == 0


class TestSampleConverter:
    """Test sample format conversion."""

    def test_int16_to_float32(self) -> None:
        """Test int16 to float32 conversion."""
        int_samples = np.array([0, 16384, 32767, -32768], dtype=np.int16)
        float_samples = SampleConverter.int16_to_float32(int_samples)

        assert float_samples.dtype == np.float32
        assert float_samples[0] == pytest.approx(0.0)
        assert float_samples[1] == pytest.approx(0.5, abs=0.01)
        assert float_samples[2] == pytest.approx(1.0, abs=0.01)
        assert float_samples[3] == pytest.approx(-1.0, abs=0.01)

    def test_float32_to_int16(self) -> None:
        """Test float32 to int16 conversion."""
        float_samples = np.array([0.0, 0.5, 1.0, -1.0], dtype=np.float32)
        int_samples = SampleConverter.float32_to_int16(float_samples)

        assert int_samples.dtype == np.int16
        assert np.all(np.abs(int_samples) <= 32767)

    def test_int32_to_float32(self) -> None:
        """Test int32 to float32 conversion."""
        int_samples = np.array([0, 1073741824, 2147483647], dtype=np.int32)
        float_samples = SampleConverter.int32_to_float32(int_samples)

        assert float_samples.dtype == np.float32
        assert float_samples[0] == pytest.approx(0.0)

    def test_dither(self) -> None:
        """Test dithering."""
        samples = np.ones(1000, dtype=np.float32) * 0.5
        dithered = SampleConverter.with_dither(samples, bit_depth=16)

        assert dithered.dtype == np.float32
        assert np.std(dithered) > 0  # Should have variation from dither


class TestChannelConverter:
    """Test channel format conversion."""

    def test_mono_to_stereo(self) -> None:
        """Test mono to stereo conversion."""
        mono = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        stereo = ChannelConverter.mono_to_stereo(mono)

        assert stereo.shape == (3, 2)
        assert np.allclose(stereo[:, 0], stereo[:, 1])

    def test_stereo_to_mono(self) -> None:
        """Test stereo to mono conversion."""
        stereo = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        mono = ChannelConverter.stereo_to_mono(stereo)

        assert mono.shape == (2,)
        assert mono[0] == pytest.approx(0.15)
        assert mono[1] == pytest.approx(0.35)

    def test_interleave(self) -> None:
        """Test channel interleaving."""
        left = np.array([0.1, 0.2], dtype=np.float32)
        right = np.array([0.3, 0.4], dtype=np.float32)
        interleaved = ChannelConverter.interleave([left, right])

        assert interleaved.shape == (2, 2)
        assert interleaved[0, 0] == 0.1
        assert interleaved[0, 1] == 0.3

    def test_deinterleave(self) -> None:
        """Test channel deinterleaving."""
        interleaved = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        channels = ChannelConverter.deinterleave(interleaved)

        assert len(channels) == 2
        assert np.allclose(channels[0], [0.1, 0.3])
        assert np.allclose(channels[1], [0.2, 0.4])


class TestAudioBufferPool:
    """Test buffer pooling."""

    def test_acquire_release(self) -> None:
        """Test acquiring and releasing buffers."""
        pool = AudioBufferPool(1024, 2, 4)

        buf1 = pool.acquire()
        assert buf1.shape == (1024, 2)
        assert pool.available_count == 3

        buf2 = pool.acquire()
        assert pool.available_count == 2

        pool.release(buf1)
        assert pool.available_count == 3

    def test_pool_exhaustion(self) -> None:
        """Test pool exhaustion."""
        pool = AudioBufferPool(100, 1, 2)
        pool.acquire()
        pool.acquire()

        with pytest.raises(BufferOverflowError):
            pool.acquire()


class TestSampleRateConverter:
    """Test sample rate conversion."""

    def test_upsample_linear(self) -> None:
        """Test upsampling with linear interpolation."""
        converter = SampleRateConverter(44100, 88200)
        samples = np.array([0.0, 0.5, 1.0], dtype=np.float32)
        upsampled = converter.process_linear(samples)

        assert len(upsampled) > len(samples)

    def test_downsample_cubic(self) -> None:
        """Test downsampling with cubic interpolation."""
        converter = SampleRateConverter(44100, 22050)
        samples = np.sin(2 * np.pi * np.linspace(0, 1, 1000)).astype(np.float32)
        downsampled = converter.process_cubic(samples)

        assert len(downsampled) < len(samples)

    def test_same_rate(self) -> None:
        """Test when input and output rates are the same."""
        converter = SampleRateConverter(44100, 44100)
        samples = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        result = converter.process_linear(samples)

        assert len(result) == len(samples)


class TestBitDepthConverter:
    """Test bit depth conversion."""

    def test_16_to_32_conversion(self) -> None:
        """Test 16-bit to 32-bit conversion."""
        samples = np.array([0.0, 0.5, 1.0, -1.0], dtype=np.float32)
        converted = BitDepthConverter.convert(samples, 16, 32)

        assert converted.dtype == np.float32
        assert np.all(converted >= -1.0) and np.all(converted <= 1.0)

    def test_32_to_16_conversion(self) -> None:
        """Test 32-bit to 16-bit conversion."""
        samples = np.array([0.0, 0.5, 1.0, -1.0], dtype=np.float32)
        converted = BitDepthConverter.convert(samples, 32, 16)

        assert np.all(converted >= -1.0) and np.all(converted <= 1.0)

    def test_same_depth(self) -> None:
        """Test when bit depths are the same."""
        samples = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        converted = BitDepthConverter.convert(samples, 16, 16)

        assert np.allclose(converted, samples)
