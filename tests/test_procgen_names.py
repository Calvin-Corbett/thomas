"""
Tests for name generation.
"""

from thomas.marketplace.procgen.names import (
    MarkovChain,
    NameGenerator,
    PhonotacticRules,
)


class TestMarkovChain:
    """Test Markov chain text generation."""

    def test_markov_chain_initialization(self):
        """Test Markov chain initializes."""
        chain = MarkovChain(order=2)
        assert chain.order == 2
        assert len(chain.chains) == 0

    def test_markov_chain_training(self):
        """Test Markov chain training."""
        chain = MarkovChain(order=2)
        training_data = ["hello", "hallo", "hillo"]
        chain.train(training_data)

        assert len(chain.chains) > 0

    def test_markov_chain_generate(self):
        """Test Markov chain generation."""
        chain = MarkovChain(order=2)
        training_data = ["apple", "ample", "apply", "apparel"]
        chain.train(training_data)

        result = chain.generate(max_length=10)
        assert isinstance(result, str)

    def test_markov_chain_deterministic(self):
        """Test Markov chain with seed."""
        import random

        chain1 = MarkovChain(order=2)
        chain2 = MarkovChain(order=2)
        training = ["test", "text", "tent"]

        random.seed(42)
        chain1.train(training)
        val1 = chain1.generate()

        random.seed(42)
        chain2.train(training)
        val2 = chain2.generate()

        # Should generate same output with same seed
        assert val1 == val2

    def test_markov_chain_empty(self):
        """Test Markov chain with no training data."""
        chain = MarkovChain(order=2)
        result = chain.generate()
        assert result == ""


class TestPhonotacticRules:
    """Test phonotactic rules."""

    def test_phonotactic_initialization(self):
        """Test phonotactic rules initialize."""
        rules = PhonotacticRules()
        assert rules.consonants is not None
        assert rules.vowels is not None

    def test_is_valid_cluster(self):
        """Test consonant cluster validation."""
        rules = PhonotacticRules()
        assert rules.is_valid_cluster("br")
        assert rules.is_valid_cluster("tr")
        assert not rules.is_valid_cluster("xz")

    def test_is_valid_onset(self):
        """Test word onset validation."""
        rules = PhonotacticRules()
        assert rules.is_valid_onset("b")
        assert rules.is_valid_onset("br")
        assert rules.is_valid_onset("")
        assert not rules.is_valid_onset("bbbbb")

    def test_is_valid_coda(self):
        """Test word coda validation."""
        rules = PhonotacticRules()
        assert rules.is_valid_coda("t")
        assert rules.is_valid_coda("")
        assert rules.is_valid_coda("nd")


class TestNameGenerator:
    """Test name generation."""

    def test_name_generator_initialization(self):
        """Test name generator initializes."""
        gen = NameGenerator(seed=42)
        assert gen.seed == 42
        assert gen.markov_chain is not None

    def test_name_generator_train(self):
        """Test training name generator."""
        gen = NameGenerator(seed=42)
        names = ["Alice", "Bob", "Charlie", "Diana"]
        gen.train_on_names(names)

        assert len(gen.markov_chain.chains) > 0

    def test_generate_character_name_generic(self):
        """Test generic character name generation."""
        gen = NameGenerator(seed=42)
        name = gen.generate_character_name(culture="generic")

        assert isinstance(name, str)
        assert len(name) > 0

    def test_generate_character_name_cultures(self):
        """Test different culture name styles."""
        gen = NameGenerator(seed=42)

        for culture in ["generic", "elvish", "dwarven", "human"]:
            name = gen.generate_character_name(culture=culture)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_generate_place_name(self):
        """Test place name generation."""
        gen = NameGenerator(seed=42)

        name = gen.generate_place_name(location_type="city")
        assert isinstance(name, str)
        assert len(name) > 0

    def test_generate_place_name_types(self):
        """Test different place name types."""
        gen = NameGenerator(seed=42)

        for location_type in ["city", "village", "forest", "mountain", "river"]:
            name = gen.generate_place_name(location_type=location_type)
            assert isinstance(name, str)

    def test_generate_tavern_name(self):
        """Test tavern name generation."""
        gen = NameGenerator(seed=42)

        for _ in range(5):
            name = gen.generate_tavern_name()
            assert isinstance(name, str)
            assert len(name) > 0

    def test_generate_shop_name(self):
        """Test shop name generation."""
        gen = NameGenerator(seed=42)

        for _ in range(5):
            name = gen.generate_shop_name()
            assert isinstance(name, str)
            assert len(name) > 0

    def test_generate_generic_name_format(self):
        """Test generic name is capitalized."""
        gen = NameGenerator(seed=42)

        for _ in range(10):
            name = gen._generate_generic_name()
            assert name[0].isupper()

    def test_generate_elvish_name_format(self):
        """Test elvish name has typical structure."""
        gen = NameGenerator(seed=42)

        for _ in range(10):
            name = gen._generate_elvish_name()
            assert isinstance(name, str)
            assert len(name) >= 3

    def test_generate_dwarven_name_format(self):
        """Test dwarven name has typical structure."""
        gen = NameGenerator(seed=42)

        for _ in range(10):
            name = gen._generate_dwarven_name()
            assert isinstance(name, str)
            assert len(name) >= 3

    def test_generate_human_name_format(self):
        """Test human name has typical structure."""
        gen = NameGenerator(seed=42)

        for _ in range(10):
            name = gen._generate_human_name()
            assert isinstance(name, str)
            assert len(name) >= 3

    def test_generate_spell_name(self):
        """Test spell name generation."""
        gen = NameGenerator(seed=42)

        for _ in range(5):
            name = gen.generate_spell_name()
            assert isinstance(name, str)
            assert len(name) > 0
            assert name[0].isupper()

    def test_name_deterministic(self):
        """Test names are deterministic with same seed."""
        gen1 = NameGenerator(seed=42)
        gen2 = NameGenerator(seed=42)

        # Generic names use random, so seed it
        import random

        random.seed(42)
        name1 = gen1.generate_character_name()

        random.seed(42)
        name2 = gen2.generate_character_name()

        assert name1 == name2
