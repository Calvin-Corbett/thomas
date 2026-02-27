"""Style control: text readability and stylistic adjustment.

Implements style control including:
- Readability scoring (multiple metrics)
- Sentence length targeting
- Vocabulary level control
- Passive voice detection and rewriting
- Hedging and boosting language
- Formality adjustment
- Jargon simplification
"""

import re

from thomas.nlg._exceptions import NLGException


class StyleError(NLGException):
    """Raised when style adjustment fails."""

    pass


class StyleController:
    """Controls text style and readability.

    Adjusts text style for readability level, formality, vocabulary,
    and other stylistic properties.
    """

    def __init__(self) -> None:
        """Initialize style controller."""
        self.target_flesch_kincaid = 60  # 60 = high school level
        self.target_sentence_length = 15  # words per sentence
        self.basic_vocabulary: set = self._load_basic_vocabulary()
        self.advanced_vocabulary: set = self._load_advanced_vocabulary()
        self.formal_markers: dict[str, str] = {
            "gonna": "going to",
            "wanna": "want to",
            "gotta": "got to",
            "ain't": "am not",
        }
        self.hedging_words = [
            "perhaps",
            "possibly",
            "might",
            "could",
            "seem",
            "appear",
        ]
        self.boosting_words = ["certainly", "definitely", "clearly", "obviously"]

    def _load_basic_vocabulary(self) -> set:
        """Load basic vocabulary list."""
        return {
            "the",
            "a",
            "is",
            "are",
            "good",
            "bad",
            "big",
            "small",
            "go",
            "come",
            "make",
            "take",
            "know",
            "think",
            "see",
            "say",
            "get",
            "give",
            "find",
            "work",
            "want",
            "use",
            "tell",
            "ask",
            "need",
            "feel",
            "try",
            "leave",
            "put",
        }

    def _load_advanced_vocabulary(self) -> set:
        """Load advanced vocabulary list."""
        return {
            "ameliorate",
            "benevolent",
            "perspicacious",
            "obfuscate",
            "ephemeral",
            "recalcitrant",
            "requisite",
            "precipitate",
            "obtuse",
            "profligate",
            "perfunctory",
            "egregious",
            "moribund",
            "pellucid",
            "propitious",
        }

    def calculate_flesch_kincaid(self, text: str) -> float:
        """Calculate Flesch-Kincaid Grade Level.

        Args:
            text: Text to analyze

        Returns:
            Grade level (0-18)
        """
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return 0.0

        words = text.split()
        syllables = sum(self._count_syllables(word) for word in words)

        if not words or not sentences:
            return 0.0

        grade = 0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59

        return max(0, grade)

    def calculate_flesch_reading_ease(self, text: str) -> float:
        """Calculate Flesch Reading Ease score.

        Args:
            text: Text to analyze

        Returns:
            Score 0-100 (90-100=very easy, 0-30=very difficult)
        """
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        words = text.split()
        syllables = sum(self._count_syllables(word) for word in words)

        if not words or not sentences:
            return 0.0

        score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))

        return max(0, min(100, score))

    def calculate_gunning_fog(self, text: str) -> float:
        """Calculate Gunning Fog Index.

        Args:
            text: Text to analyze

        Returns:
            Grade level
        """
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        words = text.split()
        complex_words = sum(1 for word in words if self._count_syllables(word) >= 3)

        if not words or not sentences:
            return 0.0

        index = 0.4 * ((len(words) / len(sentences)) + 100 * (complex_words / len(words)))

        return max(0, index)

    def calculate_coleman_liau(self, text: str) -> float:
        """Calculate Coleman-Liau Index.

        Args:
            text: Text to analyze

        Returns:
            Grade level
        """
        letters = sum(1 for c in text if c.isalpha())
        sentences = len(re.split(r"[.!?]+", text))
        words = len(text.split())

        if words == 0:
            return 0.0

        index = 0.0588 * letters / words * 100 - 0.296 * sentences / words * 100 - 15.8

        return max(0, index)

    def calculate_smog(self, text: str) -> float:
        """Calculate SMOG Index.

        Args:
            text: Text to analyze

        Returns:
            Grade level
        """
        sentences = len(re.split(r"[.!?]+", text))
        words = text.split()
        complex_words = sum(1 for word in words if self._count_syllables(word) >= 3)

        if sentences == 0:
            return 0.0

        smog = 1.0430 * (complex_words * (30 / sentences)) ** 0.5 + 3.1291

        return max(0, smog)

    def _count_syllables(self, word: str) -> int:
        """Estimate syllable count in word.

        Args:
            word: Word to count

        Returns:
            Estimated syllable count
        """
        word = word.lower()

        # Simple heuristic
        vowels = "aeiouy"
        syllable_count = 0
        previous_was_vowel = False

        for char in word:
            is_vowel = char in vowels
            if is_vowel and not previous_was_vowel:
                syllable_count += 1
            previous_was_vowel = is_vowel

        # Adjust for silent e
        if word.endswith("e"):
            syllable_count -= 1

        # Adjust for ed ending
        if word.endswith("ed") and not word.endswith("ted"):
            syllable_count -= 1

        return max(1, syllable_count)

    def target_sentence_length_range(self, text: str, target: int = 15, tolerance: int = 5) -> list[str]:
        """Split text to target sentence length.

        Args:
            text: Text to process
            target: Target sentence length (words)
            tolerance: Allowed variance

        Returns:
            Sentences close to target length
        """
        sentences = re.split(r"[.!?]+", text)
        result = []

        for sent in sentences:
            words = sent.split()
            if not words:
                continue

            if len(words) <= target + tolerance:
                result.append(sent.strip())
            else:
                # Split long sentence
                parts = self._split_long_sentence(sent, target)
                result.extend(parts)

        return result

    def _split_long_sentence(self, sentence: str, target_length: int) -> list[str]:
        """Split long sentence into shorter ones.

        Args:
            sentence: Sentence to split
            target_length: Target length

        Returns:
            List of shorter sentences
        """
        # Split at conjunctions
        for conj in ["and", "but", "or", ";", ":"]:
            if conj in sentence:
                parts = sentence.split(conj)
                if len(parts) > 1:
                    return [p.strip() for p in parts if p.strip()]

        # Otherwise return as-is
        return [sentence]

    def control_vocabulary_level(self, text: str, level: str = "intermediate") -> str:
        """Adjust vocabulary complexity.

        Args:
            text: Text to adjust
            level: "basic", "intermediate", or "advanced"

        Returns:
            Adjusted text

        Raises:
            StyleError: If adjustment fails
        """
        if level not in ("basic", "intermediate", "advanced"):
            raise StyleError(f"Unknown vocabulary level: {level}")

        words = text.split()
        adjusted = []

        for word in words:
            adjusted_word = self._simplify_word(word, level)
            adjusted.append(adjusted_word)

        return " ".join(adjusted)

    def _simplify_word(self, word: str, level: str) -> str:
        """Simplify a word for target level.

        Args:
            word: Word to simplify
            level: Target level

        Returns:
            Simplified word
        """
        clean_word = word.lower().rstrip(".,!?;:")

        if level == "basic":
            if clean_word in self.advanced_vocabulary:
                # Very simplified
                simple_map = {
                    "ameliorate": "improve",
                    "benevolent": "kind",
                    "perspicacious": "smart",
                    "obfuscate": "hide",
                    "ephemeral": "temporary",
                    "recalcitrant": "stubborn",
                }
                return simple_map.get(clean_word, word)

        return word

    def detect_passive_voice(self, sentence: str) -> bool:
        """Detect if sentence is passive voice.

        Args:
            sentence: Sentence to analyze

        Returns:
            True if passive
        """
        # Look for "was/were/be + past participle"
        passive_markers = [
            r"\bwas\s+\w+ed\b",
            r"\bwere\s+\w+ed\b",
            r"\bbeen\s+\w+ed\b",
            r"\bis\s+\w+ed\b",
            r"\bare\s+\w+ed\b",
            r"\bby\s+\w+",  # agent phrase
        ]

        for marker in passive_markers:
            if re.search(marker, sentence, re.IGNORECASE):
                return True

        return False

    def rewrite_to_active(self, sentence: str) -> str:
        """Rewrite passive sentence to active.

        Args:
            sentence: Passive sentence

        Returns:
            Active sentence (simplified rewrite)
        """
        # Simple heuristic: remove "by X" and move agent to subject
        sentence = re.sub(r"\s+by\s+\w+", "", sentence)

        # Remove auxiliary forms
        sentence = re.sub(r"\b(was|were|is|are|been)\s+", "", sentence)

        return sentence

    def add_hedging(self, text: str, level: float = 0.5) -> str:
        """Add hedging language.

        Args:
            text: Text to hedge
            level: Hedging strength (0-1)

        Returns:
            Hedged text
        """
        if level <= 0:
            return text

        # Add hedging to main clauses
        sentences = re.split(r"[.!?]+", text)
        hedged = []

        for sent in sentences:
            if sent.strip():
                hedge = self.hedging_words[int(len(self.hedging_words) * min(level, 1.0)) - 1]
                hedged.append(f"{hedge} {sent.strip()}")

        return ". ".join(hedged) + "."

    def add_boosting(self, text: str, level: float = 0.5) -> str:
        """Add boosting/emphasis language.

        Args:
            text: Text to boost
            level: Boosting strength (0-1)

        Returns:
            Boosted text
        """
        if level <= 0:
            return text

        # Add boosting to assertions
        sentences = re.split(r"[.!?]+", text)
        boosted = []

        for sent in sentences:
            if sent.strip():
                boost = self.boosting_words[int(len(self.boosting_words) * min(level, 1.0)) - 1]
                boosted.append(f"{boost}, {sent.strip()}")

        return ". ".join(boosted) + "."

    def adjust_formality(self, text: str, formality: str = "neutral") -> str:
        """Adjust text formality level.

        Args:
            text: Text to adjust
            formality: "informal", "neutral", or "formal"

        Returns:
            Adjusted text
        """
        if formality == "formal":
            # Replace contractions and informal markers
            for informal, formal in self.formal_markers.items():
                text = re.sub(rf"\b{informal}\b", formal, text, flags=re.IGNORECASE)
        elif formality == "informal":
            # Add contractions
            text = re.sub(r"\bdo not\b", "don't", text, flags=re.IGNORECASE)
            text = re.sub(r"\bwill not\b", "won't", text, flags=re.IGNORECASE)

        return text

    def simplify_jargon(self, text: str) -> str:
        """Simplify technical jargon.

        Args:
            text: Text with potential jargon

        Returns:
            Simplified text
        """
        jargon_map = {
            "optimize": "improve",
            "leverage": "use",
            "synergy": "teamwork",
            "paradigm shift": "major change",
            "utilize": "use",
            "facilitate": "help",
            "stakeholder": "interested party",
            "bandwidth": "capacity",
            "touch base": "talk",
        }

        for jargon, replacement in jargon_map.items():
            text = re.sub(rf"\b{re.escape(jargon)}\b", replacement, text, flags=re.IGNORECASE)

        return text
