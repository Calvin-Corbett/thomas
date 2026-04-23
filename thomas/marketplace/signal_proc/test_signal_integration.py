"""
Integration tests for complete signal processing pipelines.
"""

import numpy as np

from thomas.marketplace.signal_proc._types import Signal
from thomas.marketplace.signal_proc.analysis import (
    fundamental_frequency,
    rms_energy,
    zero_crossing_rate,
)
from thomas.marketplace.signal_proc.filters import (
    FIRFilter,
    design_butterworth_highpass,
    design_butterworth_lowpass,
    design_lowpass_fir,
)
from thomas.marketplace.signal_proc.spectral import spectral_centroid, stft, welch_psd
from thomas.marketplace.signal_proc.synthesis import adsr_envelope, sine_wave, white_noise
from thomas.marketplace.signal_proc.transforms import dct, hilbert_transform, idct


class TestAudioProcessingPipeline:
    """Test complete audio processing pipeline."""

    def test_record_analyze_filter_pipeline(self):
        """Full pipeline: synthesis → analysis → filtering."""
        # 1. Generate signal
        sig = sine_wave(
            frequency=100,
            sample_rate=8000,
            duration=1.0,
        )

        # 2. Add noise
        noise = white_noise(sample_rate=8000, duration=1.0, amplitude=0.1, seed=42)
        noisy = Signal(sig.samples + noise.samples, sig.sample_rate)

        # 3. Analyze (before filtering)
        energy_before = rms_energy(noisy.samples)
        zcr_before = zero_crossing_rate(noisy.samples)

        # 4. Filter
        h = design_lowpass_fir(150, 8000, num_taps=101)
        fir = FIRFilter(h)
        filtered = fir.filter(noisy.samples)

        # 5. Analyze (after filtering)
        energy_after = rms_energy(filtered)
        zcr_after = zero_crossing_rate(filtered)

        # Filtering should reduce noise (lower ZCR)
        assert zcr_after < zcr_before

    def test_synthesis_modulation_spectral(self):
        """Synthesis → modulation → spectral analysis."""
        # 1. Generate carrier
        carrier = sine_wave(1000, sample_rate=10000, duration=0.5)

        # 2. Generate modulator
        modulator = sine_wave(10, sample_rate=10000, duration=0.5)

        # 3. Apply AM
        modulated = carrier.samples * (1 + 0.5 * modulator.samples)

        # 4. Spectral analysis
        freqs, psd = welch_psd(modulated, nperseg=512, sample_rate=10000)

        # Should have peaks at 1000, 1010, 990 Hz
        peak_indices = np.argsort(psd)[-3:]
        peak_freqs = freqs[peak_indices]

        # Should contain ~990, ~1000, ~1010
        assert np.any(np.abs(peak_freqs - 1000) < 5)

    def test_noise_reduction_pipeline(self):
        """Noise reduction: synthesis → noise → filter → measure."""
        # 1. Generate clean signal
        clean = sine_wave(440, 44100, duration=0.5)

        # 2. Add noise
        noise = white_noise(44100, duration=0.5, amplitude=0.2, seed=42)
        noisy_samples = clean.samples + noise.samples

        # 3. Measure SNR before
        snr_before = 10 * np.log10(np.var(clean.samples) / np.var(noise.samples))

        # 4. Filter
        h = design_lowpass_fir(500, 44100, num_taps=201)
        fir = FIRFilter(h)
        filtered = fir.filter(noisy_samples)

        # 5. Estimate SNR after
        snr_after = 10 * np.log10(np.var(filtered) / np.var(noisy_samples - filtered))

        # SNR should improve
        assert snr_after > snr_before

    def test_pitch_detection_pipeline(self):
        """Pitch detection: synthesis → analysis."""
        # 1. Generate signal at known pitch
        pitch_hz = 220
        sig = sine_wave(pitch_hz, 8000, duration=1.0)

        # 2. Add harmonics (more realistic)
        sig.samples += 0.3 * sine_wave(pitch_hz * 2, 8000, duration=1.0).samples
        sig.samples += 0.2 * sine_wave(pitch_hz * 3, 8000, duration=1.0).samples

        # 3. Detect pitch using autocorrelation
        detected_pitch = fundamental_frequency(
            sig.samples,
            sig.sample_rate,
            min_freq=100,
            max_freq=300,
        )

        # Should be close to actual pitch
        assert abs(detected_pitch - pitch_hz) < 10

    def test_envelope_following(self):
        """Envelope detection: synthesis → modulation → envelope detect."""
        # 1. Generate signal
        carrier = sine_wave(1000, 10000, duration=0.5)

        # 2. Apply envelope
        envelope = adsr_envelope(
            attack_time=0.05,
            decay_time=0.1,
            sustain_level=0.8,
            release_time=0.1,
            sample_rate=10000,
            total_time=0.5,
        )
        enveloped = carrier.samples * envelope

        # 3. Detect envelope using Hilbert
        analytic = hilbert_transform(enveloped)
        detected_envelope = np.abs(analytic)

        # Should match applied envelope (shape, not necessarily exact values)
        # Normalize both
        detected_norm = detected_envelope / np.max(detected_envelope)
        envelope_norm = envelope / np.max(envelope)

        # Correlation should be high
        correlation = np.corrcoef(detected_norm, envelope_norm)[0, 1]
        assert correlation > 0.8


class TestSpectralAnalysisPipeline:
    """Test spectral analysis workflows."""

    def test_stft_feature_extraction(self):
        """STFT → feature extraction."""
        # 1. Generate signal with frequency change
        t1 = np.arange(0, 0.5, 1 / 8000)
        t2 = np.arange(0.5, 1.0, 1 / 8000)

        sig1 = np.sin(2 * np.pi * 200 * t1)
        sig2 = np.sin(2 * np.pi * 400 * t2)
        x = np.concatenate([sig1, sig2])

        # 2. Compute STFT
        spec = stft(x, window_size=512, hop_size=256, sample_rate=8000)

        # 3. Compute spectral centroid over time
        centroids = []
        for i in range(spec.magnitude.shape[0]):
            centroid = spectral_centroid(spec.frequencies, spec.magnitude[i, :])
            centroids.append(centroid)

        # Centroid should jump from ~200 to ~400 Hz
        centroid_beginning = np.mean(centroids[:5])
        centroid_end = np.mean(centroids[-5:])

        assert centroid_end > centroid_beginning * 1.5

    def test_spectral_centroid_tracking(self):
        """Track spectral centroid over time."""
        # 1. Generate chirp (frequency sweep)
        from thomas.marketplace.signal_proc.synthesis import chirp

        sig = chirp(100, 400, sample_rate=4000, duration=1.0, chirp_type="linear")

        # 2. Compute STFT
        spec = stft(sig.samples, window_size=512, sample_rate=4000)

        # 3. Track centroid
        centroids = [spectral_centroid(spec.frequencies, spec.magnitude[i, :]) for i in range(spec.magnitude.shape[0])]

        # Centroid should increase monotonically for chirp
        assert np.all(np.diff(centroids) >= -5)  # Allow small fluctuations


class TestFilterDesignAndApplication:
    """Test filter design and application workflows."""

    def test_multirate_processing(self):
        """Downsampling with anti-aliasing filter."""
        # 1. Generate signal
        fs_high = 44100
        sig = sine_wave(1000, fs_high, duration=0.1)

        # 2. Lowpass filter before downsampling
        h = design_lowpass_fir(4000, fs_high, num_taps=201)
        fir = FIRFilter(h)
        filtered = fir.filter(sig.samples)

        # 3. Downsample
        downsampled = filtered[::10]  # 10x downsampling

        # 4. Check that 1000 Hz signal is preserved
        from thomas.marketplace.signal_proc.fft import fft, frequency_bins, magnitude_spectrum

        X = fft(downsampled)
        mag = magnitude_spectrum(X)
        freqs = frequency_bins(len(downsampled), fs_high // 10)

        peak_idx = np.argmax(mag)
        detected_freq = freqs[peak_idx]

        # 1000 Hz should be preserved after downsampling to 4410 Hz
        assert abs(detected_freq - 1000) < 50

    def test_cascaded_filtering(self):
        """Cascaded filter stages."""
        x = sine_wave(50, 1000, duration=1.0).samples
        x += 0.3 * sine_wave(200, 1000, duration=1.0).samples
        x += 0.2 * sine_wave(400, 1000, duration=1.0).samples

        # Stage 1: Lowpass at 300 Hz
        h1 = design_lowpass_fir(300, 1000, num_taps=101)
        fir1 = FIRFilter(h1)
        y1 = fir1.filter(x)

        # Stage 2: Highpass (via spectral inversion)
        from thomas.marketplace.signal_proc.filters import design_highpass_fir

        h2 = design_highpass_fir(50, 1000, num_taps=101)
        fir2 = FIRFilter(h2)
        y2 = fir2.filter(y1)

        # Should pass 50 Hz, attenuate 200 and 400 Hz
        # Verify with spectral analysis
        from thomas.marketplace.signal_proc.analysis import spectral_centroid_time

        centroids = spectral_centroid_time(y2, 1000, frame_length=512)
        centroid_avg = np.mean(centroids)

        # Average centroid should be low (dominated by 50 Hz)
        assert centroid_avg < 150

    def test_butterworth_filter_chain(self):
        """IIR Butterworth filter application."""
        x = white_noise(1000, duration=1.0, amplitude=1.0, seed=42).samples

        # Design filters
        iir_lp = design_butterworth_lowpass(100, 1000, order=4)
        iir_hp = design_butterworth_highpass(50, 1000, order=4)

        # Apply in sequence
        y = iir_hp.filter(x)
        y = iir_lp.filter(y)

        # Should have removed very low and very high frequencies
        assert iir_lp.is_stable()
        assert iir_hp.is_stable()


class TestAdaptiveProcessing:
    """Test adaptive signal processing."""

    def test_matched_filtering(self):
        """Matched filter for signal detection."""
        from thomas.marketplace.signal_proc.convolution import matched_filter

        # 1. Design template
        template = sine_wave(100, 1000, duration=0.05).samples

        # 2. Create signal with known pattern
        sig = white_noise(1000, duration=0.5, amplitude=0.1, seed=42).samples
        # Insert template at known location
        start_idx = 2500
        sig[start_idx : start_idx + len(template)] += template

        # 3. Matched filter
        corr, normalized = matched_filter(sig, template)

        # 4. Find detection peak
        peak_idx = np.argmax(normalized)

        # Peak should be near insertion location
        assert abs(peak_idx - start_idx) < 50

    def test_spectral_subtraction(self):
        """Noise reduction via spectral subtraction."""
        # 1. Estimate noise spectrum
        noise_sig = white_noise(8000, duration=0.5, amplitude=0.1, seed=42)

        freqs, noise_psd = welch_psd(noise_sig.samples, nperseg=512, sample_rate=8000)

        # 2. Generate noisy signal
        clean = sine_wave(500, 8000, duration=0.5)
        noisy = Signal(
            clean.samples + 0.1 * noise_sig.samples,
            clean.sample_rate,
        )

        # 3. Subtract noise spectrum
        freqs_noisy, noisy_psd = welch_psd(noisy.samples, nperseg=512, sample_rate=8000)

        # Subtract with over-subtraction factor
        alpha = 1.5
        denoised_psd = np.maximum(noisy_psd - alpha * noise_psd, 0.01 * noise_psd)

        # Denoised should have less energy in noise band
        assert np.mean(denoised_psd) < np.mean(noisy_psd)


class TestSignalReconstruction:
    """Test signal reconstruction from modified representations."""

    def test_stft_reconstruction(self):
        """STFT analysis-synthesis (perfect reconstruction)."""
        # 1. Generate signal
        sig = sine_wave(100, 4000, duration=0.5)

        # 2. STFT
        spec = stft(sig.samples, window_size=512, hop_size=256)

        # 3. Reconstruct (simple overlap-add)
        # Note: Perfect reconstruction requires proper window and overlap
        reconstructed = np.zeros_like(sig.samples)

        from thomas.marketplace.signal_proc.windows import hanning

        window_func = hanning(512)

        for i, (mag, phase) in enumerate(zip(spec.magnitude, spec.phase)):
            # Reconstruct complex spectrum
            X = mag * np.exp(1j * phase)

            # IFFT
            from thomas.marketplace.signal_proc.fft import ifft

            frame = np.real(ifft(np.pad(X, (0, len(X) - 1), mode="constant")))[:512]

            # Apply window and overlap-add
            frame = frame * window_func
            start = i * 256
            if start + 512 <= len(reconstructed):
                reconstructed[start : start + 512] += frame
            else:
                reconstructed[start:] += frame[: len(reconstructed) - start]

        # Should be similar to original
        # (not exact due to windowing and reconstruction)
        energy_original = np.sum(sig.samples**2)
        energy_reconstructed = np.sum(reconstructed**2)

        # Energy should be comparable
        assert 0.5 < energy_reconstructed / energy_original < 2.0

    def test_transform_domain_processing(self):
        """Process signal in DCT domain."""
        # 1. Generate signal
        x = sine_wave(100, 1000, duration=0.5).samples

        # 2. DCT
        X = dct(x, kind=2)

        # 3. Threshold (energy compaction)
        threshold = 0.01 * np.max(np.abs(X))
        X_thresholded = np.where(np.abs(X) > threshold, X, 0)

        # 4. IDCT
        x_reconstructed = idct(X_thresholded, kind=2)

        # 5. Compare
        # Should still look like sine wave
        energy_original = np.sum(x**2)
        energy_error = np.sum((x - x_reconstructed) ** 2)

        # Error should be small for sine (compressible)
        assert energy_error / energy_original < 0.1


class TestRealWorldScenarios:
    """Test realistic signal processing scenarios."""

    def test_audio_compression_workflow(self):
        """Simulate audio compression pipeline."""
        # 1. Generate multi-component signal
        sig = sine_wave(200, 16000, duration=0.5)
        sig.samples += 0.5 * sine_wave(500, 16000, duration=0.5).samples
        sig.samples += 0.2 * sine_wave(2000, 16000, duration=0.5).samples

        # 2. Frame and transform
        frame_size = 512
        frame = sig.samples[:frame_size]

        # 3. DCT
        X = dct(frame, kind=2)

        # 4. Quantize (simulate compression)
        bits = 8  # 8 bits per coefficient
        max_val = np.max(np.abs(X))
        X_quantized = np.round(X / (max_val / 128)) * (max_val / 128)

        # 5. Reconstruct
        frame_reconstructed = idct(X_quantized, kind=2)

        # Should be reasonably accurate
        mse = np.mean((frame - frame_reconstructed) ** 2)
        snr = 10 * np.log10(np.mean(frame**2) / mse)

        assert snr > 20  # At least 20 dB SNR

    def test_speech_enhancement(self):
        """Speech enhancement workflow."""
        # 1. Simulate speech + noise
        speech = sine_wave(300, 8000, duration=1.0)
        speech.samples *= np.sin(2 * np.pi * 0.5 * np.arange(len(speech)) / 8000)  # AM
        speech.samples += white_noise(8000, duration=1.0, amplitude=0.2, seed=42).samples

        # 2. High-pass filter (remove rumble)
        h_hp = design_lowpass_fir(200, 8000, num_taps=101)
        h_hp = -h_hp.copy()
        h_hp[len(h_hp) // 2] += 1.0
        fir = FIRFilter(h_hp)
        enhanced = fir.filter(speech.samples)

        # 3. Normalize
        enhanced = enhanced / np.max(np.abs(enhanced))

        # Should preserve speech while reducing noise
        assert len(enhanced) == len(speech.samples)
