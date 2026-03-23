"""
Name generation using Markov chains and phonotactic rules.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class MarkovChain:
    """Markov chain text generator."""

    order: int = 2
    training_data: list[str] = field(default_factory=list)
    chains: dict[str, list[str]] = field(default_factory=dict)

    def train(self, texts: list[str]) -> None:
        """
        Train the Markov chain on a list of texts.

        Args:
            texts: List of training text strings
        """
        self.chains = defaultdict(list)

        for text in texts:
            # Convert to lowercase
            text = text.lower()

            # Generate chains
            for i in range(len(text) - self.order):
                key = text[i : i + self.order]
                value = text[i + self.order]
                self.chains[key].append(value)

    def generate(self, max_length: int = 10) -> str:
        """
        Generate a new text from the trained chains.

        Args:
            max_length: Maximum length of generated text

        Returns:
            Generated string
        """
        if not self.chains:
            return ""

        # Start with random key
        current = random.choice(list(self.chains.keys()))
        result = current

        for _ in range(max_length):
            if current not in self.chains or not self.chains[current]:
                break

            next_char = random.choice(self.chains[current])
            result += next_char
            current = result[-self.order :]

        return result


@dataclass
class PhonotacticRules:
    """Rules for phonotactically valid names."""

    consonants: str = "bcdfghjklmnprstvwxyz"
    vowels: str = "aeiou"
    consonant_clusters: list[str] = field(
        default_factory=lambda: ["br", "cl", "cr", "dr", "fr", "gr", "pr", "tr", "str"]
    )
    allowed_final: str = "bcdgmnprst"  # Allowed final consonants
    vowel_harmony: bool = False

    def is_valid_cluster(self, cluster: str) -> bool:
        """Check if consonant cluster is valid."""
        return cluster in self.consonant_clusters or len(cluster) == 1

    def is_valid_onset(self, onset: str) -> bool:
        """Check if word onset (start) is phonotactically valid."""
        if not onset:
            return True
        if len(onset) > 3:
            return False
        if onset[0] not in self.consonants and onset[0] not in self.vowels:
            return False
        return True

    def is_valid_coda(self, coda: str) -> bool:
        """Check if word coda (end) is phonotactically valid."""
        if not coda:
            return True
        for char in coda:
            if len(coda) > 2 and char == coda[-1]:
                return False
            if char not in self.consonants:
                return False
        return True


@dataclass
class NameGenerator:
    """Generate names using Markov chains and phonotactic rules."""

    seed: int = 42
    markov_order: int = 2
    markov_chain: MarkovChain = None
    phonotactic: PhonotacticRules = field(default_factory=PhonotacticRules)

    def __post_init__(self) -> None:
        """Initialize Markov chain."""
        self.markov_chain = MarkovChain(order=self.markov_order)
        random.seed(self.seed)

    def train_on_names(self, names: list[str]) -> None:
        """
        Train the generator on a list of example names.

        Args:
            names: List of name strings to train on
        """
        self.markov_chain.train(names)

    def generate_character_name(self, culture: str = "generic") -> str:
        """
        Generate a character name.

        Args:
            culture: Cultural name style (generic, elvish, dwarven, human)

        Returns:
            Generated character name
        """
        if culture == "elvish":
            return self._generate_elvish_name()
        elif culture == "dwarven":
            return self._generate_dwarven_name()
        elif culture == "human":
            return self._generate_human_name()
        else:
            return self._generate_generic_name()

    def generate_place_name(self, location_type: str = "city") -> str:
        """
        Generate a place name.

        Args:
            location_type: Type of location (city, village, forest, mountain, river)

        Returns:
            Generated place name
        """
        prefixes = {
            "city": ["North", "South", "East", "West", "New", "Old"],
            "village": ["White", "Green", "Clear", "Stone", "Tall"],
            "forest": ["Dark", "Old", "Silent", "Deep", "Ancient"],
            "mountain": ["High", "Blue", "White", "Sharp", "Misty"],
            "river": ["Clear", "Silver", "Swift", "Deep", "Crystal"],
        }

        suffixes = {
            "city": ["haven", "shire", "port", "ford", "ham", "bury"],
            "village": ["field", "stead", "town", "dale", "vale", "spring"],
            "forest": ["wood", "shaw", "thicket", "copse", "grove", "mere"],
            "mountain": ["peak", "horn", "top", "ridge", "fang", "spire"],
            "river": ["waters", "stream", "burn", "brook", "ford", "mouth"],
        }

        prefix_list = prefixes.get(location_type, prefixes["city"])
        suffix_list = suffixes.get(location_type, suffixes["city"])

        prefix = random.choice(prefix_list)
        suffix = random.choice(suffix_list)

        return f"{prefix}{suffix}"

    def generate_tavern_name(self) -> str:
        """
        Generate a tavern/inn name.

        Returns:
            Generated tavern name
        """
        adjectives = [
            "The Drunken",
            "The Wandering",
            "The Wise",
            "The Red",
            "The Black",
            "The Golden",
            "The Silver",
            "The Royal",
        ]

        animals = [
            "Dragon",
            "Griffin",
            "Raven",
            "Stag",
            "Bear",
            "Eagle",
            "Serpent",
            "Lion",
        ]

        objects = [
            "Apple",
            "Crown",
            "Sword",
            "Shield",
            "Thorn",
            "Horn",
            "Star",
            "Oak",
        ]

        pattern = random.choice(
            [
                lambda: f"{random.choice(adjectives)} {random.choice(animals)}",
                lambda: f"The {random.choice(objects)} and {random.choice(animals)}",
                lambda: f"The {random.choice(adjectives)} {random.choice(objects)}",
            ]
        )

        return pattern()

    def generate_shop_name(self) -> str:
        """
        Generate a shop name.

        Returns:
            Generated shop name
        """
        shop_types = [
            "Armory",
            "Smithy",
            "Weaver's",
            "Alchemist's",
            "Bakery",
            "Market",
            "Emporium",
            "Boutique",
        ]

        qualifiers = [
            "The Fine",
            "The Grand",
            "The Master's",
            "The Old",
            "The New",
            "The Fair",
            "The Golden",
        ]

        if random.choice([True, False]):
            return f"{random.choice(qualifiers)} {random.choice(shop_types)}"
        else:
            return f"{random.choice(shop_types)}"

    def _generate_generic_name(self) -> str:
        """Generate a generic phonotactically valid name."""
        name = ""
        length = random.randint(4, 10)

        # Build syllables
        num_syllables = random.randint(2, 4)

        for _ in range(num_syllables):
            # Onset (initial consonant or cluster)
            if random.choice([True, False, False]):  # 1/3 chance consonant
                if random.choice([True, False]):
                    onset = random.choice(self.phonotactic.consonants)
                else:
                    onset = random.choice(self.phonotactic.consonant_clusters)
            else:
                onset = ""

            # Nucleus (vowel)
            nucleus = random.choice(self.phonotactic.vowels)

            # Coda (final consonant)
            if random.choice([True, False, False]):  # 1/3 chance consonant
                coda = random.choice(self.phonotactic.allowed_final)
            else:
                coda = ""

            name += onset + nucleus + coda

        return name.capitalize()

    def _generate_elvish_name(self) -> str:
        """Generate an elvish-style name."""
        consonants = "bcdfghjklmnprstvwy"
        vowels = "aeiou"

        name = ""
        num_syllables = random.randint(2, 4)

        for i in range(num_syllables):
            if i == 0:
                # Start with consonant
                name += random.choice(consonants)
            name += random.choice(vowels)
            if random.choice([True, False]):
                name += random.choice("lr")

        return name.capitalize()

    def _generate_dwarven_name(self) -> str:
        """Generate a dwarven-style name."""
        consonants = "bdfghjkmnprstvwz"
        vowels = "ao"

        name = ""
        num_syllables = random.randint(2, 3)

        for _ in range(num_syllables):
            name += random.choice(consonants)
            name += random.choice(vowels)
            if random.choice([True, False]):
                name += random.choice("rn")

        return name.capitalize()

    def _generate_human_name(self) -> str:
        """Generate a human-style name."""
        # Simple syllable-based approach
        consonants = "bcdfghjklmnprstvwxyz"
        vowels = "aeiou"

        name = ""
        num_syllables = random.randint(2, 3)

        for i in range(num_syllables):
            name += random.choice(consonants)
            name += random.choice(vowels)
            if i < num_syllables - 1 and random.choice([True, False]):
                name += random.choice(consonants)

        return name.capitalize()

    def generate_spell_name(self) -> str:
        """
        Generate a magic spell name.

        Returns:
            Generated spell name
        """
        prefixes = ["Ar", "Mor", "Atha", "Vel", "Kaz", "Xan", "Tar"]
        roots = ["morph", "blast", "ward", "bolt", "shield", "strike", "bind"]
        suffixes = ["us", "or", "ia", "eth", "yx", "an"]

        name = random.choice(prefixes) + random.choice(roots) + random.choice(suffixes)
        return name.capitalize()
