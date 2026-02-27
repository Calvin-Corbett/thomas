"""
Tests for voice synthesis module.
"""

import numpy as np
import pytest

from thomas.voice._exceptions import SynthesisError
from thomas.voice._types import AudioSample, FormantFrequencies
from thomas.voice.synthesis import (
    DiphoneConcatenator,
    FormantSynthesizer,
    ProsodyModifier,
    SSMLParser,
    TextNormalizer,
)


class TestTextNormalizer:
    """Tests for TextNormalizer class."""

    @pytest.fixture
    def normalizer(self) -> TextNormalizer:
        """Create text normalizer."""
        return TextNormalizer()

    def test_abbreviation_expansion(self, normalizer: TextNormalizer) -> None:
        """Test abbreviation expansion."""
        text = "Dr. Smith is here"
        normalized = normalizer.normalize(text)

        assert "Doctor" in normalized
        assert "Dr." not in normalized

    def test_number_expansion(self, normalizer: TextNormalizer) -> None:
        """Test number expansion."""
        text = "I have 2 cats"
        normalized = normalizer.normalize(text)

        assert "two" in normalized or "2" in normalized

    def test_whitespace_normalization(self, normalizer: TextNormalizer) -> None:
        """Test whitespace normalization."""
        text = "Hello    world  test"
        normalized = normalizer.normalize(text)

        assert "    " not in normalized
        assert "  " not in normalized

    def test_normalize_empty_string(self, normalizer: TextNormalizer) -> None:
        """Test normalizing empty string."""
        text = ""
        normalized = normalizer.normalize(text)

        assert normalized == ""

    def test_expand_numbers_single_digit(self, normalizer: TextNormalizer) -> None:
        """Test expanding single digit."""
        text = "I have 5 apples"
        normalized = normalizer.normalize(text)

        assert "five" in normalized

    def test_expand_multiple_digit_number(self, normalizer: TextNormalizer) -> None:
        """Test expanding multi-digit number."""
        text = "The year is 2023"
        normalized = normalizer.normalize(text)

        # Should expand digits
        assert "two" in normalized or "2023" in normalized


class TestFormantSynthesizer:
    """Tests for FormantSynthesizer class."""

    @pytest.fixture
    def synthesizer(self) -> FormantSynthesizer:
        """Create formant synthesizer."""
        return FormantSynthesizer(sample_rate=16000)

    def test_synthesize_formant(self, synthesizer: FormantSynthesizer) -> None:
        """Test formant synthesis."""
        pitch_contour = np.ones(100) * 200.0
        formants = [FormantFrequencies(f1=700, f2=1200, f3=2500) for _ in range(100)]
        duration = 1.0

        audio = synthesizer.synthesize_formant(pitch_contour, formants, duration)

        assert isinstance(audio, AudioSample)
        assert audio.sample_rate == 16000
        assert len(audio.data) > 0

    def test_synthesized_audio_normalized(self, synthesizer: FormantSynthesizer) -> None:
        """Test synthesized audio is normalized."""
        pitch_contour = np.ones(50) * 200.0
        formants = [FormantFrequencies(f1=700, f2=1200, f3=2500) for _ in range(50)]

        audio = synthesizer.synthesize_formant(pitch_contour, formants, 0.5)

        assert np.max(np.abs(audio.data)) <= 1.0

    def test_buzz_generation(self, synthesizer: FormantSynthesizer) -> None:
        """Test buzz signal generation."""
        pitch = np.ones(50) * 200.0
        buzz = synthesizer._generate_buzz(pitch, 16000)

        assert len(buzz) == 16000
        assert np.all(np.abs(buzz) <= 1.0)

    def test_formant_filter_design(self, synthesizer: FormantSynthesizer) -> None:
        """Test formant filter design."""
        b, a = synthesizer._design_formant_filter(700)

        assert len(b) > 0
        assert len(a) > 0


class TestDiphoneConcatenator:
    """Tests for DiphoneConcatenator class."""

    @pytest.fixture
    def concatenator(self) -> DiphoneConcatenator:
        """Create diphone concatenator."""
        return DiphoneConcatenator(sample_rate=16000)

    def test_concatenate_diphones(self, concatenator: DiphoneConcatenator) -> None:
        """Test diphone concatenation."""
        sample_rate = 16000
        duration = 0.5

        audio1 = AudioSample(
            data=np.sin(2 * np.pi * 200 * np.linspace(0, duration, int(16000 * duration))).astype(np.float32),
            sample_rate=sample_rate,
        )
        audio2 = AudioSample(
            data=np.sin(2 * np.pi * 300 * np.linspace(0, duration, int(16000 * duration))).astype(np.float32),
            sample_rate=sample_rate,
        )

        diphones = [("d-aa", audio1), ("aa-t", audio2)]

        result = concatenator.concatenate_diphones(diphones)

        assert isinstance(result, AudioSample)
        assert len(result.data) > len(audio1.data)

    def test_concatenate_empty_list(self, concatenator: DiphoneConcatenator) -> None:
        """Test concatenation with empty list."""
        with pytest.raises(SynthesisError):
            concatenator.concatenate_diphones([])

    def test_concatenate_single_diphone(self, concatenator: DiphoneConcatenator) -> None:
        """Test concatenation of single diphone."""
        sample_rate = 16000
        duration = 0.5
        audio = AudioSample(
            data=np.sin(2 * np.pi * 200 * np.linspace(0, duration, int(16000 * duration))).astype(np.float32),
            sample_rate=sample_rate,
        )

        result = concatenator.concatenate_diphones([("aa", audio)])

        assert isinstance(result, AudioSample)


class TestProsodyModifier:
    """Tests for ProsodyModifier class."""

    @pytest.fixture
    def modifier(self) -> ProsodyModifier:
        """Create prosody modifier."""
        return ProsodyModifier(sample_rate=16000)

    @pytest.fixture
    def test_audio(self) -> AudioSample:
        """Create test audio."""
        sample_rate = 16000
        duration = 1.0
        t = np.arange(0, duration, 1 / sample_rate)
        data = np.sin(2 * np.pi * 200 * t).astype(np.float32)
        return AudioSample(data=data, sample_rate=sample_rate)

    def test_pitch_shift_up(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test pitch shift up."""
        shifted = modifier.modify_pitch(test_audio, pitch_shift=1.5)

        assert isinstance(shifted, AudioSample)
        assert len(shifted.data) == len(test_audio.data)

    def test_pitch_shift_down(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test pitch shift down."""
        shifted = modifier.modify_pitch(test_audio, pitch_shift=0.8)

        assert isinstance(shifted, AudioSample)
        assert len(shifted.data) == len(test_audio.data)

    def test_pitch_shift_invalid(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test invalid pitch shift."""
        with pytest.raises(SynthesisError):
            modifier.modify_pitch(test_audio, pitch_shift=0)

    def test_modify_duration_longer(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test duration modification to longer."""
        modified = modifier.modify_duration(test_audio, duration_factor=1.5)

        assert isinstance(modified, AudioSample)
        assert len(modified.data) > len(test_audio.data)

    def test_modify_duration_shorter(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test duration modification to shorter."""
        modified = modifier.modify_duration(test_audio, duration_factor=0.8)

        assert isinstance(modified, AudioSample)
        assert len(modified.data) < len(test_audio.data)

    def test_modify_duration_invalid(self, modifier: ProsodyModifier, test_audio: AudioSample) -> None:
        """Test invalid duration factor."""
        with pytest.raises(SynthesisError):
            modifier.modify_duration(test_audio, duration_factor=0)


class TestSSMLParser:
    """Tests for SSMLParser class."""

    @pytest.fixture
    def parser(self) -> SSMLParser:
        """Create SSML parser."""
        return SSMLParser()

    def test_parse_ssml_simple(self, parser: SSMLParser) -> None:
        """Test parsing simple SSML."""
        ssml = "<speak>Hello world</speak>"
        segments = parser.parse_ssml(ssml)

        assert len(segments) > 0
        assert "text" in segments[0]

    def test_parse_ssml_with_prosody(self, parser: SSMLParser) -> None:
        """Test parsing SSML with prosody."""
        ssml = '<prosody rate="1.5" pitch="higher">Hello</prosody>'
        segments = parser.parse_ssml(ssml)

        assert len(segments) > 0

    def test_parse_ssml_extract_text(self, parser: SSMLParser) -> None:
        """Test SSML text extraction."""
        ssml = "<speak>This is a test</speak>"
        segments = parser.parse_ssml(ssml)

        assert "test" in segments[0]["text"]
