"""
Tests for digital filter design and implementation.
"""

import numpy as np
import pytest

from thomas.marketplace.signal_proc._exceptions import FilterError
from thomas.marketplace.signal_proc.filters import (
    FIRFilter,
    IIRFilter,
    MedianFilter,
    MovingAverageFilter,
    design_bandpass_fir,
    design_bandstop_fir,
    design_butterworth_highpass,
    design_butterworth_lowpass,
    design_highpass_fir,
    design_lowpass_fir,
)


class TestFIRFilterDesign:
    """Test FIR filter design."""

    def test_lowpass_fir_design(self):
        """Lowpass FIR filter should be designable."""
        h = design_lowpass_fir(
            cutoff=100,
            sample_rate=1000,
            num_taps=51,
        )

        assert len(h) == 51
        assert np.isfinite(h).all()

    def test_highpass_fir_design(self):
        """Highpass FIR filter should be designable."""
        h = design_highpass_fir(
            cutoff=100,
            sample_rate=1000,
            num_taps=51,
        )

        assert len(h) == 51
        assert np.isfinite(h).all()

    def test_bandpass_fir_design(self):
        """Bandpass FIR filter should be designable."""
        h = design_bandpass_fir(
            low_freq=100,
            high_freq=200,
            sample_rate=1000,
            num_taps=51,
        )

        assert len(h) == 51
        assert np.isfinite(h).all()

    def test_bandstop_fir_design(self):
        """Bandstop (notch) FIR filter should be designable."""
        h = design_bandstop_fir(
            low_freq=100,
            high_freq=200,
            sample_rate=1000,
            num_taps=51,
        )

        assert len(h) == 51
        assert np.isfinite(h).all()

    def test_fir_invalid_cutoff(self):
        """Invalid cutoff frequency should raise error."""
        with pytest.raises(FilterError):
            design_lowpass_fir(cutoff=600, sample_rate=1000)  # Cutoff > Nyquist

    def test_fir_invalid_band(self):
        """Invalid band frequencies should raise error."""
        with pytest.raises(FilterError):
            design_bandpass_fir(100, 50, 1000)  # low > high


class TestFIRFilterApplication:
    """Test FIR filter application."""

    def test_fir_filter_creation(self):
        """FIR filter should be creatable from coefficients."""
        h = np.array([0.25, 0.5, 0.25])
        fir = FIRFilter(h)

        assert len(fir.coefficients) == 3

    def test_fir_filter_output_length(self):
        """FIR filter output should match input length."""
        h = design_lowpass_fir(100, 1000, num_taps=51)
        fir = FIRFilter(h)

        x = np.random.randn(1000)
        y = fir.filter(x)

        assert len(y) == len(x)

    def test_fir_filter_impulse_response(self):
        """FIR filter should preserve impulse response shape."""
        h = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
        fir = FIRFilter(h)

        x = np.zeros(100)
        x[0] = 1.0

        y = fir.filter(x)

        # Should see impulse response
        assert np.allclose(y[:5], h, atol=1e-10)

    def test_fir_filter_frequency_response(self):
        """FIR lowpass filter should attenuate high frequencies."""
        h = design_lowpass_fir(100, 1000, num_taps=101)
        fir = FIRFilter(h)

        # Test frequencies
        freqs = np.array([10, 50, 100, 200, 400])
        mag, phase = fir.frequency_response(freqs, 1000)

        # Magnitude should decrease with frequency
        assert mag[0] > mag[-1]  # 10 Hz > 400 Hz


class TestIIRFilterDesign:
    """Test IIR filter design."""

    def test_butterworth_lowpass_design(self):
        """Butterworth lowpass IIR should be designable."""
        iir = design_butterworth_lowpass(
            cutoff=100,
            sample_rate=1000,
            order=4,
        )

        assert len(iir.sections) == 2  # Two biquad sections for order 4

    def test_butterworth_highpass_design(self):
        """Butterworth highpass IIR should be designable."""
        iir = design_butterworth_highpass(
            cutoff=100,
            sample_rate=1000,
            order=4,
        )

        assert len(iir.sections) == 2

    def test_butterworth_stability(self):
        """Butterworth filter should be stable."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        assert iir.is_stable()

    def test_iir_invalid_cutoff(self):
        """Invalid cutoff should raise error."""
        with pytest.raises(FilterError):
            design_butterworth_lowpass(600, 1000)  # Cutoff > Nyquist

    def test_iir_invalid_order(self):
        """Invalid order should raise error."""
        with pytest.raises(FilterError):
            design_butterworth_lowpass(100, 1000, order=0)


class TestIIRFilterApplication:
    """Test IIR filter application."""

    def test_iir_filter_output_length(self):
        """IIR filter output should match input length."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        x = np.random.randn(1000)
        y = iir.filter(x)

        assert len(y) == len(x)

    def test_iir_filter_stability_check(self):
        """IIR filter stability check should work."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        assert iir.is_stable()

    def test_iir_frequency_response(self):
        """IIR lowpass should attenuate high frequencies."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        freqs = np.array([10, 50, 100, 200, 400])
        mag, phase = iir.frequency_response(freqs, 1000)

        # Magnitude should generally decrease with frequency
        assert mag[0] > mag[-1] * 0.5


class TestMovingAverageFilter:
    """Test moving average filter."""

    def test_ma_filter_creation(self):
        """Moving average filter should be creatable."""
        ma = MovingAverageFilter(window_size=5)

        assert ma.window_size == 5

    def test_ma_filter_output_length(self):
        """MA filter output should match input length."""
        ma = MovingAverageFilter(window_size=5)

        x = np.random.randn(100)
        y = ma.filter(x)

        assert len(y) == len(x)

    def test_ma_filter_smoothing(self):
        """MA filter should smooth high-frequency noise."""
        # Create noisy signal
        t = np.arange(1000) / 1000
        x = np.sin(2 * np.pi * 5 * t) + 0.5 * np.random.randn(1000)

        ma = MovingAverageFilter(window_size=25)
        y = ma.filter(x)

        # Variance should decrease
        assert np.var(y) < np.var(x)

    def test_ma_filter_constant(self):
        """MA filter output should preserve constants."""
        x = np.ones(100) * 5.0

        ma = MovingAverageFilter(window_size=5)
        y = ma.filter(x)

        assert np.allclose(y[5:], 5.0, atol=1e-10)

    def test_ma_invalid_window_size(self):
        """Invalid window size should raise error."""
        with pytest.raises(FilterError):
            MovingAverageFilter(window_size=0)


class TestMedianFilter:
    """Test median filter."""

    def test_median_filter_creation(self):
        """Median filter should be creatable with odd window size."""
        med = MedianFilter(window_size=5)

        assert med.window_size == 5

    def test_median_filter_even_size_error(self):
        """Even window size should raise error."""
        with pytest.raises(FilterError):
            MedianFilter(window_size=4)

    def test_median_filter_output_length(self):
        """Median filter output should match input length."""
        med = MedianFilter(window_size=5)

        x = np.random.randn(100)
        y = med.filter(x)

        assert len(y) == len(x)

    def test_median_filter_impulse_rejection(self):
        """Median filter should remove impulse noise."""
        x = np.sin(2 * np.pi * np.arange(1000) / 100)

        # Add impulses
        x[250] = 100
        x[500] = -100
        x[750] = 100

        med = MedianFilter(window_size=5)
        y = med.filter(x)

        # Should remove most of impulse noise
        impulse_amplitude = np.max(np.abs(y[245:255] - np.sin(2 * np.pi * np.arange(245, 255) / 100)))
        assert impulse_amplitude < 1.0

    def test_median_filter_constant(self):
        """Median filter should preserve constants."""
        x = np.ones(100) * 3.0

        med = MedianFilter(window_size=5)
        y = med.filter(x)

        assert np.allclose(y, 3.0, atol=1e-10)


class TestFrequencyResponse:
    """Test filter frequency response computation."""

    def test_fir_frequency_response_shape(self):
        """FIR frequency response should have expected shape."""
        h = design_lowpass_fir(100, 1000, num_taps=101)
        fir = FIRFilter(h)

        freqs = np.logspace(0, 3, 100)  # 1 Hz to 1 kHz
        mag, phase = fir.frequency_response(freqs, 1000)

        assert len(mag) == 100
        assert len(phase) == 100
        assert np.all(mag >= 0)
        assert np.all(np.abs(phase) <= np.pi)

    def test_iir_frequency_response_shape(self):
        """IIR frequency response should have expected shape."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        freqs = np.logspace(0, 3, 100)
        mag, phase = iir.frequency_response(freqs, 1000)

        assert len(mag) == 100
        assert len(phase) == 100


class TestFilterSignalProcessing:
    """Test filters on actual signals."""

    def test_lowpass_sine_filtering(self):
        """Lowpass filter should pass low frequencies."""
        fs = 1000
        duration = 1.0
        t = np.arange(int(fs * duration)) / fs

        # Low frequency signal
        x_low = np.sin(2 * np.pi * 20 * t)
        # High frequency noise
        x_high = 0.1 * np.sin(2 * np.pi * 400 * t)
        x = x_low + x_high

        h = design_lowpass_fir(100, fs, num_taps=101)
        fir = FIRFilter(h)
        y = fir.filter(x)

        # Output should be mostly low frequency
        from thomas.marketplace.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        X_in = fft(x)
        X_out = fft(y)

        mag_in = magnitude_spectrum(X_in)
        mag_out = magnitude_spectrum(X_out)
        freqs = frequency_bins(len(x), fs)

        # Energy at 20 Hz should be preserved
        idx_20 = np.argmin(np.abs(freqs - 20))
        # Energy at 400 Hz should be attenuated
        idx_400 = np.argmin(np.abs(freqs - 400))

        assert mag_out[idx_20] > mag_out[idx_400]

    def test_butterworth_filtering_passband(self):
        """Butterworth filter should have flat passband."""
        iir = design_butterworth_lowpass(100, 1000, order=4)

        # Low frequencies in passband
        freqs = np.array([10, 50, 99])
        mag, _ = iir.frequency_response(freqs, 1000)

        # Should be relatively flat
        assert np.std(mag) < np.mean(mag) * 0.1


class TestFilterErrors:
    """Test error handling."""

    def test_fir_empty_coefficients(self):
        """Empty coefficients should raise error."""
        with pytest.raises(FilterError):
            FIRFilter(np.array([]))

    def test_iir_zero_denominator(self):
        """Zero denominator coefficient should raise error."""
        with pytest.raises(FilterError):
            IIRFilter([(np.array([1, 0.5]), np.array([0, 1, 0.5]))])
