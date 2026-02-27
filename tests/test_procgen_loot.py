"""
Tests for loot and item generation.
"""

import pytest

from thomas.procgen._exceptions import InvalidConfigError
from thomas.procgen.loot import (
    Item,
    ItemModifier,
    ItemRarity,
    ItemType,
    LootGenerator,
)


class TestItemModifier:
    """Test item modifiers."""

    def test_item_modifier_creation(self):
        """Test modifier creation."""
        mod = ItemModifier(
            name="Sharp",
            item_type=ItemType.WEAPON,
            stat_bonuses={"damage": 2},
            value_multiplier=1.2,
        )
        assert mod.name == "Sharp"
        assert mod.item_type == ItemType.WEAPON
        assert mod.stat_bonuses["damage"] == 2


class TestItem:
    """Test item class."""

    def test_item_creation(self):
        """Test item creation."""
        item = Item(
            name="Sword",
            item_type=ItemType.WEAPON,
            rarity=ItemRarity.COMMON,
            base_value=50,
            level_requirement=1,
        )
        assert item.name == "Sword"
        assert item.rarity == ItemRarity.COMMON

    def test_item_display_name(self):
        """Test item display name with modifiers."""
        item = Item(
            name="Sword",
            item_type=ItemType.WEAPON,
            rarity=ItemRarity.RARE,
            base_value=50,
            level_requirement=1,
            prefixes=["Flaming"],
            suffixes=["of Power"],
        )
        display_name = item.display_name
        assert "Flaming" in display_name
        assert "Sword" in display_name
        assert "Power" in display_name

    def test_item_total_value(self):
        """Test item value calculation."""
        item = Item(
            name="Sword",
            item_type=ItemType.WEAPON,
            rarity=ItemRarity.COMMON,
            base_value=100,
            level_requirement=1,
        )
        value = item.total_value
        assert value >= 100

    def test_item_value_rarity_scaling(self):
        """Test value scales with rarity."""
        common_item = Item(
            name="Sword",
            item_type=ItemType.WEAPON,
            rarity=ItemRarity.COMMON,
            base_value=100,
            level_requirement=1,
        )
        rare_item = Item(
            name="Sword",
            item_type=ItemType.WEAPON,
            rarity=ItemRarity.RARE,
            base_value=100,
            level_requirement=1,
        )
        assert rare_item.total_value > common_item.total_value


class TestLootGenerator:
    """Test loot generation."""

    def test_loot_generator_initialization(self):
        """Test loot generator initializes."""
        gen = LootGenerator(seed=42)
        assert gen.seed == 42
        assert gen._modifiers is not None

    def test_create_modifier_tables(self):
        """Test modifier tables are created."""
        gen = LootGenerator(seed=42)
        assert ItemType.WEAPON in gen._modifiers
        assert ItemType.ARMOR in gen._modifiers
        assert ItemType.ACCESSORY in gen._modifiers

    def test_select_rarity(self):
        """Test rarity selection."""
        gen = LootGenerator(seed=42)
        for _ in range(10):
            rarity = gen._select_rarity()
            assert isinstance(rarity, ItemRarity)

    def test_get_base_item_name(self):
        """Test base item name selection."""
        gen = LootGenerator(seed=42)

        for item_type in [ItemType.WEAPON, ItemType.ARMOR, ItemType.ACCESSORY]:
            name = gen._get_base_item_name(item_type)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_select_modifiers_common(self):
        """Test modifier selection for common items."""
        gen = LootGenerator(seed=42)
        prefixes, suffixes = gen._select_modifiers(ItemType.WEAPON, ItemRarity.COMMON)
        assert len(prefixes) + len(suffixes) == 0

    def test_select_modifiers_rare(self):
        """Test modifier selection for rare items."""
        gen = LootGenerator(seed=42)
        prefixes, suffixes = gen._select_modifiers(ItemType.WEAPON, ItemRarity.RARE)
        assert len(prefixes) + len(suffixes) == 2

    def test_select_modifiers_legendary(self):
        """Test modifier selection for legendary items."""
        gen = LootGenerator(seed=42)
        prefixes, suffixes = gen._select_modifiers(ItemType.WEAPON, ItemRarity.LEGENDARY)
        assert len(prefixes) + len(suffixes) == 4

    def test_generate_stats_weapon(self):
        """Test stat generation for weapons."""
        gen = LootGenerator(seed=42)
        stats = gen._generate_stats(ItemType.WEAPON, level=5, rarity=ItemRarity.RARE)

        assert "damage" in stats
        assert stats["damage"] > 0

    def test_generate_stats_armor(self):
        """Test stat generation for armor."""
        gen = LootGenerator(seed=42)
        stats = gen._generate_stats(ItemType.ARMOR, level=5, rarity=ItemRarity.RARE)

        assert "defense" in stats
        assert stats["defense"] > 0

    def test_generate_stats_scales_with_level(self):
        """Test stats scale with character level."""
        gen = LootGenerator(seed=42)
        stats1 = gen._generate_stats(ItemType.WEAPON, level=1, rarity=ItemRarity.COMMON)
        stats5 = gen._generate_stats(ItemType.WEAPON, level=5, rarity=ItemRarity.COMMON)

        assert stats5["damage"] > stats1["damage"]

    def test_generate_item(self):
        """Test item generation."""
        gen = LootGenerator(seed=42)
        item = gen.generate_item(ItemType.WEAPON, level=5)

        assert isinstance(item, Item)
        assert item.item_type == ItemType.WEAPON
        assert item.level_requirement <= 5

    def test_generate_item_all_types(self):
        """Test generation for all item types."""
        gen = LootGenerator(seed=42)

        for item_type in [ItemType.WEAPON, ItemType.ARMOR, ItemType.ACCESSORY]:
            item = gen.generate_item(item_type, level=5)
            assert item.item_type == item_type

    def test_generate_item_all_rarities(self):
        """Test generation for all rarity levels."""
        gen = LootGenerator(seed=42)

        for rarity in ItemRarity:
            item = gen.generate_item(ItemType.WEAPON, level=5, rarity=rarity)
            assert item.rarity == rarity

    def test_generate_loot_table(self):
        """Test loot table generation."""
        gen = LootGenerator(seed=42)
        items = gen.generate_loot_table(num_items=5, average_level=5)

        assert len(items) == 5
        assert all(isinstance(item, Item) for item in items)

    def test_generate_treasure_hoard(self):
        """Test treasure hoard generation."""
        gen = LootGenerator(seed=42)
        hoard = gen.generate_treasure_hoard(cr=5)

        assert "gold" in hoard
        assert "items" in hoard
        assert "value" in hoard
        assert hoard["gold"] > 0
        assert len(hoard["items"]) > 0

    def test_generate_treasure_hoard_scales_with_cr(self):
        """Test treasure scales with challenge rating."""
        gen = LootGenerator(seed=42)
        hoard1 = gen.generate_treasure_hoard(cr=1)
        hoard5 = gen.generate_treasure_hoard(cr=5)

        assert hoard5["gold"] >= hoard1["gold"]
        assert hoard5["value"] >= hoard1["value"]

    def test_generate_treasure_hoard_invalid_cr(self):
        """Test invalid CR raises error."""
        gen = LootGenerator(seed=42)
        with pytest.raises(InvalidConfigError):
            gen.generate_treasure_hoard(cr=0)

    def test_calculate_enchantment_level(self):
        """Test enchantment level calculation."""
        gen = LootGenerator(seed=42)

        for rarity in ItemRarity:
            enchant = gen._calculate_enchantment_level(rarity, level=10)
            assert enchant >= 0
