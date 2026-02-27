"""
Phonetics module.

Phoneme analysis and phonetic processing:
- ARPAbet phoneme set (39 phonemes)
- Phoneme classification
- Grapheme-to-phoneme conversion
- Phoneme duration modeling
- Syllabification
- Stress assignment
- Pronunciation dictionary
"""

from thomas.voice._exceptions import PhoneticsError
from thomas.voice._types import (
    Phoneme,
    PhonemeType,
    StressLevel,
)


class PhonemeSet:
    """Manages phoneme inventory."""

    # ARPAbet phoneme set (39 phonemes)
    PHONEMES = {
        # Vowels (14)
        "AA": {"type": PhonemeType.VOWEL, "ipa": "ɑ"},  # hot, father
        "AE": {"type": PhonemeType.VOWEL, "ipa": "æ"},  # trap, bad
        "AH": {"type": PhonemeType.VOWEL, "ipa": "ʌ"},  # strut, cup
        "AO": {"type": PhonemeType.VOWEL, "ipa": "ɔ"},  # lot, thought
        "AW": {"type": PhonemeType.VOWEL, "ipa": "aʊ"},  # mouth, now
        "AY": {"type": PhonemeType.VOWEL, "ipa": "aɪ"},  # price, fly
        "EH": {"type": PhonemeType.VOWEL, "ipa": "ɛ"},  # dress, bed
        "ER": {"type": PhonemeType.VOWEL, "ipa": "ɚ"},  # nurse, bird
        "EY": {"type": PhonemeType.VOWEL, "ipa": "eɪ"},  # face, day
        "IH": {"type": PhonemeType.VOWEL, "ipa": "ɪ"},  # kit, bid
        "IY": {"type": PhonemeType.VOWEL, "ipa": "i"},  # fleece, see
        "OW": {"type": PhonemeType.VOWEL, "ipa": "oʊ"},  # goat, no
        "OY": {"type": PhonemeType.VOWEL, "ipa": "ɔɪ"},  # choice, boy
        "UH": {"type": PhonemeType.VOWEL, "ipa": "ʊ"},  # foot, good
        "UW": {"type": PhonemeType.VOWEL, "ipa": "u"},  # goose, shoe
        # Consonants (24)
        "B": {"type": PhonemeType.CONSONANT, "ipa": "b", "voiced": True},  # bath
        "CH": {"type": PhonemeType.CONSONANT, "ipa": "tʃ", "voiced": False},  # choice
        "D": {"type": PhonemeType.CONSONANT, "ipa": "d", "voiced": True},  # day
        "DH": {"type": PhonemeType.CONSONANT, "ipa": "ð", "voiced": True},  # that
        "F": {"type": PhonemeType.CONSONANT, "ipa": "f", "voiced": False},  # face
        "G": {"type": PhonemeType.CONSONANT, "ipa": "g", "voiced": True},  # give
        "HH": {"type": PhonemeType.CONSONANT, "ipa": "h", "voiced": False},  # help
        "JH": {"type": PhonemeType.CONSONANT, "ipa": "dʒ", "voiced": True},  # judge
        "K": {"type": PhonemeType.CONSONANT, "ipa": "k", "voiced": False},  # keep
        "L": {"type": PhonemeType.CONSONANT, "ipa": "l", "voiced": True},  # light
        "M": {"type": PhonemeType.CONSONANT, "ipa": "m", "voiced": True},  # make
        "N": {"type": PhonemeType.CONSONANT, "ipa": "n", "voiced": True},  # new
        "NG": {"type": PhonemeType.CONSONANT, "ipa": "ŋ", "voiced": True},  # sing
        "P": {"type": PhonemeType.CONSONANT, "ipa": "p", "voiced": False},  # path
        "R": {"type": PhonemeType.CONSONANT, "ipa": "ɹ", "voiced": True},  # red
        "S": {"type": PhonemeType.CONSONANT, "ipa": "s", "voiced": False},  # see
        "SH": {"type": PhonemeType.CONSONANT, "ipa": "ʃ", "voiced": False},  # she
        "T": {"type": PhonemeType.CONSONANT, "ipa": "t", "voiced": False},  # talk
        "TH": {"type": PhonemeType.CONSONANT, "ipa": "θ", "voiced": False},  # think
        "V": {"type": PhonemeType.CONSONANT, "ipa": "v", "voiced": True},  # voice
        "W": {"type": PhonemeType.CONSONANT, "ipa": "w", "voiced": True},  # with
        "Y": {"type": PhonemeType.CONSONANT, "ipa": "j", "voiced": True},  # yes
        "Z": {"type": PhonemeType.CONSONANT, "ipa": "z", "voiced": True},  # zoo
        "ZH": {"type": PhonemeType.CONSONANT, "ipa": "ʒ", "voiced": True},  # vision
    }

    # Pronunciation dictionary (example entries)
    DICTIONARY = {
        "hello": ["HH", "EH", "L", "OW"],
        "world": ["W", "ER", "L", "D"],
        "the": ["DH", "AH"],
        "cat": ["K", "AE", "T"],
        "dog": ["D", "AO", "G"],
        "phone": ["F", "OW", "N"],
        "speech": ["S", "P", "IY", "CH"],
        "recognize": ["R", "EH", "K", "AH", "G", "N", "AY", "Z"],
        "python": ["P", "AY", "TH", "AH", "N"],
    }

    # Typical phoneme durations (in seconds)
    DURATION_STATISTICS = {
        "AA": {"mean": 0.150, "std": 0.040},
        "AE": {"mean": 0.100, "std": 0.030},
        "AH": {"mean": 0.100, "std": 0.030},
        "B": {"mean": 0.060, "std": 0.020},
        "CH": {"mean": 0.070, "std": 0.020},
        "D": {"mean": 0.050, "std": 0.015},
        "T": {"mean": 0.060, "std": 0.020},
    }

    @classmethod
    def get_phoneme_properties(cls, phoneme: str) -> dict:
        """
        Get properties for a phoneme.

        Args:
            phoneme: ARPAbet phoneme symbol.

        Returns:
            Dictionary of phoneme properties.

        Raises:
            PhoneticsError: If phoneme not found.
        """
        if phoneme not in cls.PHONEMES:
            raise PhoneticsError(f"Unknown phoneme: {phoneme}")

        return cls.PHONEMES[phoneme]

    @classmethod
    def is_vowel(cls, phoneme: str) -> bool:
        """Check if phoneme is a vowel."""
        if phoneme not in cls.PHONEMES:
            return False
        return cls.PHONEMES[phoneme]["type"] == PhonemeType.VOWEL

    @classmethod
    def is_consonant(cls, phoneme: str) -> bool:
        """Check if phoneme is a consonant."""
        if phoneme not in cls.PHONEMES:
            return False
        return cls.PHONEMES[phoneme]["type"] == PhonemeType.CONSONANT


class PhoneticsProcessor:
    """Processes phonetic information."""

    def __init__(self) -> None:
        """Initialize phonetics processor."""
        self.phoneme_set = PhonemeSet()

    def grapheme_to_phoneme(self, text: str) -> list[str]:
        """
        Convert graphemes (letters) to phonemes.

        Uses dictionary lookup with rule-based fallback.

        Args:
            text: Input text (word or phrase).

        Returns:
            List of ARPAbet phonemes.

        Raises:
            PhoneticsError: If conversion fails.
        """
        try:
            text = text.lower().strip()

            # Dictionary lookup
            if text in PhonemeSet.DICTIONARY:
                return PhonemeSet.DICTIONARY[text]

            # Rule-based conversion (simplified)
            phonemes = self._rule_based_conversion(text)

            return phonemes

        except Exception as e:
            raise PhoneticsError(f"Grapheme-to-phoneme conversion failed: {str(e)}")

    def _rule_based_conversion(self, text: str) -> list[str]:
        """
        Rule-based grapheme-to-phoneme conversion.

        Args:
            text: Input text.

        Returns:
            List of phonemes.
        """
        # Simplified rules
        phonemes = []

        i = 0
        while i < len(text):
            char = text[i]

            # Simple character-to-phoneme mapping
            if char == "a":
                phonemes.append("AE")
            elif char == "e":
                phonemes.append("EH")
            elif char == "i":
                phonemes.append("IH")
            elif char == "o":
                phonemes.append("AO")
            elif char == "u":
                phonemes.append("UH")
            elif char == "b":
                phonemes.append("B")
            elif char == "c":
                phonemes.append("K")
            elif char == "d":
                phonemes.append("D")
            elif char == "f":
                phonemes.append("F")
            elif char == "g":
                phonemes.append("G")
            elif char == "h":
                phonemes.append("HH")
            elif char == "j":
                phonemes.append("JH")
            elif char == "k":
                phonemes.append("K")
            elif char == "l":
                phonemes.append("L")
            elif char == "m":
                phonemes.append("M")
            elif char == "n":
                phonemes.append("N")
            elif char == "p":
                phonemes.append("P")
            elif char == "r":
                phonemes.append("R")
            elif char == "s":
                phonemes.append("S")
            elif char == "t":
                phonemes.append("T")
            elif char == "v":
                phonemes.append("V")
            elif char == "w":
                phonemes.append("W")
            elif char == "y":
                phonemes.append("Y")
            elif char == "z":
                phonemes.append("Z")

            i += 1

        return phonemes

    def syllabify(self, phonemes: list[str]) -> list[list[str]]:
        """
        Divide phonemes into syllables.

        Onset-Nucleus-Coda decomposition.

        Args:
            phonemes: List of phonemes.

        Returns:
            List of syllables (each syllable is a list of phonemes).
        """
        syllables: list[list[str]] = []
        current_syllable: list[str] = []

        for phoneme in phonemes:
            is_vowel = PhonemeSet.is_vowel(phoneme)

            if is_vowel:
                # Nucleus
                current_syllable.append(phoneme)
            else:
                # Consonant
                if current_syllable:
                    # We have a nucleus, this is a coda
                    current_syllable.append(phoneme)
                else:
                    # No nucleus yet, this is an onset
                    current_syllable.append(phoneme)

            # Start new syllable after nucleus
            if is_vowel and len(current_syllable) > 0:
                # Check if next phoneme is a consonant
                idx = phonemes.index(phoneme)
                if idx + 1 < len(phonemes) and not PhonemeSet.is_vowel(phonemes[idx + 1]):
                    # Could be coda or onset of next syllable
                    # For simplicity, start new syllable after vowel
                    pass
                else:
                    syllables.append(current_syllable)
                    current_syllable = []

        if current_syllable:
            syllables.append(current_syllable)

        return syllables

    def assign_stress(self, phonemes: list[str]) -> list[StressLevel]:
        """
        Assign lexical stress to syllables.

        Returns stress level for each phoneme.

        Args:
            phonemes: List of phonemes.

        Returns:
            List of stress levels.
        """
        stress = [StressLevel.UNSTRESSED] * len(phonemes)

        # Simple rule: primary stress on first vowel
        for i, phoneme in enumerate(phonemes):
            if PhonemeSet.is_vowel(phoneme):
                stress[i] = StressLevel.PRIMARY
                break

        return stress

    def get_phoneme_duration(self, phoneme: str, context: str | None = None) -> tuple[float, float]:
        """
        Get estimated duration for a phoneme.

        Args:
            phoneme: ARPAbet phoneme.
            context: Phonetic context (not used in simplified version).

        Returns:
            Tuple of (mean_duration, std_deviation) in seconds.
        """
        if phoneme in PhonemeSet.DURATION_STATISTICS:
            stats = PhonemeSet.DURATION_STATISTICS[phoneme]
            return (stats["mean"], stats["std"])

        # Default durations
        if PhonemeSet.is_vowel(phoneme):
            return (0.120, 0.035)
        else:
            return (0.055, 0.020)

    def create_phoneme(
        self,
        arpabet: str,
        start_time: float,
        end_time: float,
    ) -> Phoneme:
        """
        Create a Phoneme object.

        Args:
            arpabet: ARPAbet symbol.
            start_time: Start time in seconds.
            end_time: End time in seconds.

        Returns:
            Phoneme object.

        Raises:
            PhoneticsError: If phoneme unknown.
        """
        try:
            props = PhonemeSet.get_phoneme_properties(arpabet)

            phoneme_type = props["type"]
            is_voiced = props.get("voiced", True)

            return Phoneme(
                arpabet=arpabet,
                phoneme_type=phoneme_type,
                start_time=start_time,
                end_time=end_time,
                is_voiced=is_voiced,
            )

        except PhoneticsError:
            raise
        except Exception as e:
            raise PhoneticsError(f"Failed to create phoneme: {str(e)}")

    def lookup_pronunciation(self, word: str) -> list[str] | None:
        """
        Look up pronunciation in dictionary.

        Args:
            word: Word to look up.

        Returns:
            List of phonemes or None if not found.
        """
        word = word.lower()
        return PhonemeSet.DICTIONARY.get(word)
