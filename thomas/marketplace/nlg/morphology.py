"""Morphological generation: word form inflection.

Implements English morphological generation including:
- Pluralization with irregular forms
- Verb conjugation for all tenses and persons
- Comparative and superlative adjectives
- Morphophonological rules
- Contraction generation
- Number-to-word conversion
- Ordinal generation
"""

from thomas.marketplace.nlg._exceptions import MorphologyError
from thomas.marketplace.nlg._types import (
    Aspect,
    MorphologicalForm,
    Number,
    Person,
    Tense,
)


class MorphologyEngine:
    """Generates inflected word forms.

    Implements English morphological rules for inflection of nouns,
    verbs, adjectives, and other word classes.
    """

    def __init__(self) -> None:
        """Initialize morphology engine."""
        self.irregular_plurals: dict[str, str] = {
            "man": "men",
            "woman": "women",
            "child": "children",
            "tooth": "teeth",
            "foot": "feet",
            "mouse": "mice",
            "goose": "geese",
            "ox": "oxen",
            "person": "people",
        }

        self.irregular_verbs: dict[str, dict[str, str]] = {
            "be": {
                "1sg_present": "am",
                "2sg_present": "are",
                "3sg_present": "is",
                "pl_present": "are",
                "past": "was",
                "past_pl": "were",
            },
            "have": {
                "3sg_present": "has",
                "other_present": "have",
                "past": "had",
            },
            "do": {
                "3sg_present": "does",
                "other_present": "do",
                "past": "did",
            },
            "go": {
                "3sg_present": "goes",
                "other_present": "go",
                "past": "went",
            },
            "say": {
                "3sg_present": "says",
                "other_present": "say",
                "past": "said",
            },
        }

        self.number_words = {
            0: "zero",
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine",
            10: "ten",
            11: "eleven",
            12: "twelve",
            13: "thirteen",
            14: "fourteen",
            15: "fifteen",
            16: "sixteen",
            17: "seventeen",
            18: "eighteen",
            19: "nineteen",
            20: "twenty",
            30: "thirty",
            40: "forty",
            50: "fifty",
            60: "sixty",
            70: "seventy",
            80: "eighty",
            90: "ninety",
            100: "hundred",
            1000: "thousand",
            1000000: "million",
        }

        self.ordinals = {
            1: "first",
            2: "second",
            3: "third",
            4: "fourth",
            5: "fifth",
            6: "sixth",
            7: "seventh",
            8: "eighth",
            9: "ninth",
            10: "tenth",
            11: "eleventh",
            12: "twelfth",
            13: "thirteenth",
            20: "twentieth",
            21: "twenty-first",
            30: "thirtieth",
        }

    def pluralize(self, word: str) -> str:
        """Generate plural form of noun.

        Applies English pluralization rules with support for irregular forms.

        Args:
            word: Singular noun lemma

        Returns:
            Plural form

        Raises:
            MorphologyError: If pluralization fails
        """
        if not word:
            raise MorphologyError("Empty word for pluralization")

        # Check irregular plurals
        if word.lower() in self.irregular_plurals:
            return self.irregular_plurals[word.lower()]

        # Apply regular pluralization rules
        word_lower = word.lower()

        # Words ending in s, x, z, ch, sh -> add -es
        if word_lower.endswith(("s", "x", "z")) or word_lower.endswith(("ch", "sh")):
            return word + "es"

        # Words ending in consonant + y -> change y to ies
        if len(word) > 1 and word_lower.endswith("y"):
            if word_lower[-2] not in "aeiou":
                return word[:-1] + "ies"

        # Words ending in consonant + o -> add -es
        if word_lower.endswith("o"):
            if len(word) > 1 and word_lower[-2] not in "aeiou":
                return word + "es"

        # Words ending in f or fe -> change to ves
        if word_lower.endswith("f"):
            return word[:-1] + "ves"
        if word_lower.endswith("fe"):
            return word[:-2] + "ves"

        # Default: add -s
        return word + "s"

    def conjugate_verb(
        self,
        lemma: str,
        tense: Tense = Tense.PRESENT,
        aspect: Aspect = Aspect.SIMPLE,
        person: Person = Person.THIRD,
        number: Number = Number.SINGULAR,
    ) -> str:
        """Generate conjugated verb form.

        Args:
            lemma: Verb lemma
            tense: Tense
            aspect: Aspect
            person: Person
            number: Number

        Returns:
            Conjugated form

        Raises:
            MorphologyError: If conjugation fails
        """
        if not lemma:
            raise MorphologyError("Empty lemma for conjugation")

        # Check irregular verbs
        if lemma.lower() in self.irregular_verbs:
            return self._conjugate_irregular(lemma, tense, person, number)

        return self._conjugate_regular(lemma, tense, aspect, person, number)

    def _conjugate_regular(
        self,
        lemma: str,
        tense: Tense,
        aspect: Aspect,
        person: Person,
        number: Number,
    ) -> str:
        """Conjugate regular verb.

        Args:
            lemma: Verb lemma
            tense: Tense
            aspect: Aspect
            person: Person
            number: Number

        Returns:
            Conjugated form
        """
        lemma_lower = lemma.lower()

        # Check aspect first (takes priority)
        # Progressive aspect -> add -ing
        if aspect == Aspect.PROGRESSIVE:
            if lemma_lower.endswith("e"):
                return lemma[:-1] + "ing"
            # Doubling rule for -ing
            if (
                len(lemma) >= 2
                and lemma_lower[-1] not in "aeiou"
                and lemma_lower[-2] in "aeiou"
                and lemma_lower[-3] not in "aeiou"
            ):
                return lemma + lemma[-1] + "ing"
            return lemma + "ing"

        # Present tense
        if tense == Tense.PRESENT:
            if number == Number.SINGULAR and person == Person.THIRD:
                # Add -s
                if lemma_lower.endswith(("s", "x", "z")) or lemma_lower.endswith(("ch", "sh")):
                    return lemma + "es"
                if lemma_lower.endswith("y") and lemma_lower[-2] not in "aeiou":
                    return lemma[:-1] + "ies"
                return lemma + "s"
            else:
                return lemma

        # Past tense
        elif tense == Tense.PAST:
            # Add -ed
            if lemma_lower.endswith("e"):
                return lemma + "d"
            # Doubling: consonant doubling (CVC -> CVVC)
            if (
                len(lemma) >= 2
                and lemma_lower[-1] not in "aeiou"
                and lemma_lower[-2] in "aeiou"
                and lemma_lower[-3] not in "aeiou"
            ):
                return lemma + lemma[-1] + "ed"
            # y -> ied
            if lemma_lower.endswith("y") and lemma_lower[-2] not in "aeiou":
                return lemma[:-1] + "ied"
            return lemma + "ed"

        # Future tense -> handled as modal + verb
        elif tense == Tense.FUTURE:
            return lemma

        return lemma

    def _conjugate_irregular(self, lemma: str, tense: Tense, person: Person, number: Number) -> str:
        """Conjugate irregular verb.

        Args:
            lemma: Verb lemma
            tense: Tense
            person: Person
            number: Number

        Returns:
            Conjugated form
        """
        forms = self.irregular_verbs.get(lemma.lower(), {})

        if tense == Tense.PRESENT:
            if number == Number.SINGULAR and person == Person.THIRD:
                key = "3sg_present"
            else:
                key = "present" if lemma.lower() == "be" else "other_present"
            return forms.get(key, lemma)

        elif tense == Tense.PAST:
            key = "past"
            return forms.get(key, lemma)

        return lemma

    def generate_comparative(self, adjective: str) -> str:
        """Generate comparative form of adjective.

        Args:
            adjective: Adjective lemma

        Returns:
            Comparative form

        Raises:
            MorphologyError: If generation fails
        """
        if not adjective:
            raise MorphologyError("Empty adjective for comparative")

        adj_lower = adjective.lower()

        # Short adjectives: add -er
        if len(adj_lower) <= 3:
            if adj_lower.endswith("y"):
                return adjective[:-1] + "ier"
            if adj_lower.endswith("e"):
                return adjective + "r"
            # Doubling rule
            if len(adj_lower) == 3 and adj_lower[1] in "aeiou" and adj_lower[2] not in "aeiou":
                return adjective + adj_lower[-1] + "er"
            return adjective + "er"

        # Long adjectives: use "more"
        return "more " + adjective

    def generate_superlative(self, adjective: str) -> str:
        """Generate superlative form of adjective.

        Args:
            adjective: Adjective lemma

        Returns:
            Superlative form

        Raises:
            MorphologyError: If generation fails
        """
        if not adjective:
            raise MorphologyError("Empty adjective for superlative")

        adj_lower = adjective.lower()

        # Short adjectives: add -est
        if len(adj_lower) <= 3:
            if adj_lower.endswith("y"):
                return adjective[:-1] + "iest"
            if adj_lower.endswith("e"):
                return adjective + "st"
            # Doubling rule
            if len(adj_lower) == 3 and adj_lower[1] in "aeiou" and adj_lower[2] not in "aeiou":
                return adjective + adj_lower[-1] + "est"
            return adjective + "est"

        # Long adjectives: use "most"
        return "most " + adjective

    def number_to_words(self, num: int) -> str:
        """Convert number to word form.

        Args:
            num: Number to convert

        Returns:
            Word form of number

        Raises:
            MorphologyError: If conversion fails
        """
        if num < 0:
            return "negative " + self.number_to_words(-num)

        if num in self.number_words:
            return self.number_words[num]

        if num < 20:
            return self.number_words.get(num, str(num))

        if num < 100:
            tens = (num // 10) * 10
            ones = num % 10
            result = self.number_words[tens]
            if ones > 0:
                result += "-" + self.number_words[ones]
            return result

        if num < 1000:
            hundreds = num // 100
            remainder = num % 100
            result = self.number_words[hundreds] + " hundred"
            if remainder > 0:
                result += " " + self.number_to_words(remainder)
            return result

        if num < 1000000:
            thousands = num // 1000
            remainder = num % 1000
            result = self.number_to_words(thousands) + " thousand"
            if remainder > 0:
                result += " " + self.number_to_words(remainder)
            return result

        if num < 1000000000:
            millions = num // 1000000
            remainder = num % 1000000
            result = self.number_to_words(millions) + " million"
            if remainder > 0:
                result += " " + self.number_to_words(remainder)
            return result

        return str(num)

    def number_to_ordinal(self, num: int) -> str:
        """Convert number to ordinal form.

        Args:
            num: Number to convert

        Returns:
            Ordinal form

        Raises:
            MorphologyError: If conversion fails
        """
        if num in self.ordinals:
            return self.ordinals[num]

        if num % 10 == 1 and num != 11:
            return self.number_to_words(num) + "st"
        elif num % 10 == 2 and num != 12:
            return self.number_to_words(num) + "nd"
        elif num % 10 == 3 and num != 13:
            return self.number_to_words(num) + "rd"
        else:
            return self.number_to_words(num) + "th"

    def generate_contraction(self, word1: str, word2: str) -> str | None:
        """Generate contraction form.

        Args:
            word1: First word
            word2: Second word (typically auxiliary/negative)

        Returns:
            Contraction or None

        Raises:
            MorphologyError: If generation fails
        """
        contractions = {
            ("do", "not"): "don't",
            ("does", "not"): "doesn't",
            ("did", "not"): "didn't",
            ("will", "not"): "won't",
            ("would", "not"): "wouldn't",
            ("can", "not"): "can't",
            ("could", "not"): "couldn't",
            ("should", "not"): "shouldn't",
            ("is", "not"): "isn't",
            ("are", "not"): "aren't",
            ("was", "not"): "wasn't",
            ("were", "not"): "weren't",
            ("have", "not"): "haven't",
            ("has", "not"): "hasn't",
            ("had", "not"): "hadn't",
        }

        key = (word1.lower(), word2.lower())
        return contractions.get(key)

    def get_indefinite_article(self, word: str) -> str:
        """Get appropriate indefinite article (a/an).

        Args:
            word: Word following the article

        Returns:
            "a" or "an"
        """
        if not word:
            return "a"

        word_lower = word.lower()

        # Words starting with vowel sounds
        vowel_sounds = ["a", "e", "i", "o", "u"]
        # Special cases: h-words
        h_vowel = word_lower.startswith("h") and word_lower[1] in vowel_sounds

        if word_lower[0] in vowel_sounds or h_vowel:
            return "an"

        return "a"

    def apply_morphology(self, lemma: str, morphology: MorphologicalForm) -> str:
        """Apply morphological features to generate surface form.

        Args:
            lemma: Lemma to inflect
            morphology: Morphological features

        Returns:
            Surface form

        Raises:
            MorphologyError: If application fails
        """
        form = lemma

        # Apply tense/aspect for verbs
        if morphology.tense or morphology.aspect:
            form = self.conjugate_verb(
                lemma,
                morphology.tense or Tense.PRESENT,
                morphology.aspect or Aspect.SIMPLE,
                morphology.person or Person.THIRD,
                morphology.number or Number.SINGULAR,
            )

        # Apply number for nouns
        if morphology.number == Number.PLURAL:
            form = self.pluralize(lemma)

        return form
