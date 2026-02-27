"""Tests for compression algorithms.

Verifies delta-delta encoding, XOR compression, and roundtrip correctness.
"""

import random

import pytest

from . import (
    CompressionStats,
    DeltaOfDeltaEncoder,
    RunLengthEncoder,
    XORFloatCompressor,
)


class TestDeltaOfDeltaEncoding:
    """Tests for delta-of-delta timestamp encoding."""

    def test_encode_single_timestamp(self):
        """Test encoding single timestamp."""
        data = DeltaOfDeltaEncoder.encode([1000])
        assert len(data) > 0

    def test_encode_two_timestamps(self):
        """Test encoding two timestamps."""
        data = DeltaOfDeltaEncoder.encode([1000, 2000])
        assert len(data) > 0

    def test_encode_uniform_intervals(self):
        """Test encoding timestamps with uniform intervals."""
        timestamps = [1000, 2000, 3000, 4000, 5000]
        data = DeltaOfDeltaEncoder.encode(timestamps)
        decoded = DeltaOfDeltaEncoder.decode(data)
        assert decoded == timestamps

    def test_encode_variable_intervals(self):
        """Test encoding timestamps with variable intervals."""
        timestamps = [1000, 2000, 2500, 4000, 4100, 10000]
        data = DeltaOfDeltaEncoder.encode(timestamps)
        decoded = DeltaOfDeltaEncoder.decode(data)
        assert decoded == timestamps

    def test_compression_ratio(self):
        """Test that encoding compresses well for uniform intervals."""
        timestamps = list(range(1000, 101000, 1000))
        data = DeltaOfDeltaEncoder.encode(timestamps)

        # Original size: 100 timestamps * 8 bytes = 800 bytes
        # Compressed should be much smaller
        original_size = len(timestamps) * 8
        assert len(data) < original_size / 2

    def test_large_timestamps(self):
        """Test with large timestamp values."""
        timestamps = [
            int(1.7e12),
            int(1.7e12) + 1000,
            int(1.7e12) + 2000,
        ]
        data = DeltaOfDeltaEncoder.encode(timestamps)
        decoded = DeltaOfDeltaEncoder.decode(data)
        assert decoded == timestamps

    def test_empty_list_raises_error(self):
        """Test that empty list raises error."""
        with pytest.raises(ValueError):
            DeltaOfDeltaEncoder.encode([])

    def test_round_trip_random(self):
        """Test round-trip with random timestamps."""
        random.seed(42)
        timestamps = []
        t = 1000000
        for _ in range(100):
            t += random.randint(100, 10000)
            timestamps.append(t)

        data = DeltaOfDeltaEncoder.encode(timestamps)
        decoded = DeltaOfDeltaEncoder.decode(data)
        assert decoded == timestamps


class TestXORFloatCompression:
    """Tests for XOR-based floating-point compression."""

    def test_encode_single_value(self):
        """Test encoding single float value."""
        data = XORFloatCompressor.encode([45.5])
        assert len(data) > 0

    def test_encode_identical_values(self):
        """Test encoding identical values."""
        values = [45.5, 45.5, 45.5, 45.5, 45.5]
        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        assert len(decoded) == len(values)
        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10

    def test_encode_varying_values(self):
        """Test encoding varying float values."""
        values = [10.5, 20.3, 15.7, 18.9, 22.1]
        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        assert len(decoded) == len(values)
        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10

    def test_compression_ratio(self):
        """Test compression ratio."""
        # Generate 1000 values
        values = [45.0 + i * 0.1 for i in range(1000)]
        data = XORFloatCompressor.encode(values)

        # Original: 1000 * 8 bytes = 8000 bytes
        # Compressed should be smaller
        original_size = len(values) * 8
        assert len(data) < original_size

    def test_encode_integers_as_floats(self):
        """Test encoding integers represented as floats."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10

    def test_encode_negative_values(self):
        """Test encoding negative float values."""
        values = [-10.5, -5.3, 0.0, 5.7, 10.9]
        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10

    def test_encode_very_small_values(self):
        """Test encoding very small values."""
        values = [1e-10, 2e-10, 3e-10, 4e-10]
        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-15

    def test_empty_list_raises_error(self):
        """Test that empty list raises error."""
        with pytest.raises(ValueError):
            XORFloatCompressor.encode([])

    def test_round_trip_random(self):
        """Test round-trip with random values."""
        random.seed(42)
        values = [random.uniform(-1000, 1000) for _ in range(500)]

        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        assert len(decoded) == len(values)
        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10


class TestRunLengthEncoding:
    """Tests for run-length encoding."""

    def test_encode_single_value(self):
        """Test encoding single value."""
        data = RunLengthEncoder.encode([45.5])
        assert len(data) > 0

    def test_encode_repeated_values(self):
        """Test encoding many repeated values."""
        values = [45.5] * 100
        data = RunLengthEncoder.encode(values)
        decoded = RunLengthEncoder.decode(data)

        assert decoded == values

    def test_encode_no_repetition(self):
        """Test encoding values with no repetition."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        data = RunLengthEncoder.encode(values)
        decoded = RunLengthEncoder.decode(data)

        assert decoded == values

    def test_encode_mixed_repetition(self):
        """Test encoding with mixed repetition."""
        values = [10.0, 10.0, 20.0, 20.0, 20.0, 30.0]
        data = RunLengthEncoder.encode(values)
        decoded = RunLengthEncoder.decode(data)

        assert decoded == values

    def test_compression_ratio_high_repetition(self):
        """Test compression ratio with high repetition."""
        values = [45.5] * 1000
        data = RunLengthEncoder.encode(values)

        # Original: 1000 * 8 = 8000 bytes
        # Compressed: ~10 bytes (1 value + run length)
        assert len(data) < 100

    def test_empty_list_raises_error(self):
        """Test that empty list raises error."""
        with pytest.raises(ValueError):
            RunLengthEncoder.encode([])


class TestCompressionStats:
    """Tests for compression statistics."""

    def test_compression_stats_creation(self):
        """Test creating compression statistics."""
        stats = CompressionStats(
            original_size=1000,
            compressed_size=300,
            algorithm="xor",
        )

        assert stats.compression_ratio == pytest.approx(0.3)
        assert stats.space_saved_percent == pytest.approx(70.0)

    def test_compression_stats_no_compression(self):
        """Test compression stats with no compression."""
        stats = CompressionStats(
            original_size=1000,
            compressed_size=1000,
            algorithm="none",
        )

        assert stats.compression_ratio == 1.0
        assert stats.space_saved_percent == 0.0

    def test_compression_stats_perfect_compression(self):
        """Test compression stats with perfect compression."""
        stats = CompressionStats(
            original_size=1000,
            compressed_size=100,
            algorithm="perfect",
        )

        assert stats.compression_ratio == 0.1
        assert stats.space_saved_percent == 90.0

    def test_compression_stats_string_representation(self):
        """Test string representation of stats."""
        stats = CompressionStats(
            original_size=1000,
            compressed_size=300,
            algorithm="xor",
        )

        str_repr = str(stats)
        assert "xor" in str_repr
        assert "0.3" in str_repr

    def test_zero_original_size(self):
        """Test stats with zero original size."""
        stats = CompressionStats(
            original_size=0,
            compressed_size=0,
            algorithm="test",
        )

        assert stats.compression_ratio == 1.0
        assert stats.space_saved_percent == 0.0


class TestCompressionIntegration:
    """Integration tests for compression algorithms."""

    def test_timestamp_value_compression_roundtrip(self):
        """Test compressing both timestamps and values."""
        timestamps = [1000 + i * 1000 for i in range(100)]
        values = [45.0 + i * 0.1 for i in range(100)]

        # Compress both
        ts_data = DeltaOfDeltaEncoder.encode(timestamps)
        val_data = XORFloatCompressor.encode(values)

        # Decompress both
        ts_decoded = DeltaOfDeltaEncoder.decode(ts_data)
        val_decoded = XORFloatCompressor.decode(val_data)

        assert ts_decoded == timestamps
        assert len(val_decoded) == len(values)

    def test_compression_with_outliers(self):
        """Test compression handles outliers gracefully."""
        # Normal values with occasional outliers
        values = [45.0] * 90 + [500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]

        data = XORFloatCompressor.encode(values)
        decoded = XORFloatCompressor.decode(data)

        for orig, decoded_val in zip(values, decoded):
            assert abs(orig - decoded_val) < 1e-10

    def test_time_series_compression_efficiency(self):
        """Test compression efficiency on realistic time series."""
        import math

        # Simulate CPU usage over time (smooth trend with small variations)
        timestamps = []
        values = []
        t = 1000000

        for i in range(1000):
            t += 60000  # 1 minute intervals
            base_usage = 30 + 20 * math.sin(i / 100.0)  # Oscillating trend
            noise = random.uniform(-2, 2)
            value = base_usage + noise

            timestamps.append(t)
            values.append(value)

        # Compress
        ts_data = DeltaOfDeltaEncoder.encode(timestamps)
        val_data = XORFloatCompressor.encode(values)

        # Calculate compression ratios
        ts_original = len(timestamps) * 8
        val_original = len(values) * 8
        total_original = ts_original + val_original
        total_compressed = len(ts_data) + len(val_data)

        ratio = total_compressed / total_original

        # Should achieve good compression on realistic data
        assert ratio < 0.6  # At least 40% reduction

        # Verify correctness
        ts_decoded = DeltaOfDeltaEncoder.decode(ts_data)
        val_decoded = XORFloatCompressor.decode(val_data)

        assert ts_decoded == timestamps
        for orig, dec in zip(values, val_decoded):
            assert abs(orig - dec) < 1e-10
