"""
Loot and item generation with modifiers, rarity tiers, and balanced stats.
"""

import random
from dataclasses import dataclass, field
from enum import Enum, auto

from thomas.procgen._exceptions import InvalidConfigError


class ItemRarity(Enum):
    """Enumeration of item rarity tiers."""

    COMMON = auto()
    UNCOMMON = auto()
    RARE = auto()
    EPIC = auto()
    LEGENDARY = auto()


class ItemType(Enum):
    """Enumeration of item types."""

    WEAPON = auto()
    ARMOR = auto()
    ACCESSORY = auto()
    CONSUMABLE = auto()
    QUEST_ITEM = auto()


@dataclass
class ItemModifier:
    """Represents a prefix/suffix modifier for items."""

    name: str
    item_type: ItemType
    stat_bonuses: dict[str, int] = field(default_factory=dict)
    value_multiplier: float = 1.0
    rarity_weight: float = 1.0  # Higher = more common


@dataclass
class Item:
    """Represents a generated item."""

    name: str
    item_type: ItemType
    rarity: ItemRarity
    base_value: int
    level_requirement: int
    stats: dict[str, float] = field(default_factory=dict)
    prefixes: list[str] = field(default_factory=list)
    suffixes: list[str] = field(default_factory=list)
    is_set_item: bool = False
    set_name: str = ""
    enchantment_level: int = 0

    @property
    def display_name(self) -> str:
        """Get the full display name with modifiers."""
        parts = self.prefixes + [self.name] + self.suffixes
        return " ".join(parts)

    @property
    def total_value(self) -> int:
        """Calculate total value including rarity and enchantments."""
        multiplier = {
            ItemRarity.COMMON: 1.0,
            ItemRarity.UNCOMMON: 1.5,
            ItemRarity.RARE: 2.5,
            ItemRarity.EPIC: 5.0,
            ItemRarity.LEGENDARY: 10.0,
        }[self.rarity]

        enchant_bonus = (self.enchantment_level**2) * 50

        return int(self.base_value * multiplier + enchant_bonus)


@dataclass
class LootGenerator:
    """Generate loot and items with appropriate stats and rarity."""

    seed: int = 42
    _modifiers: dict[ItemType, list[ItemModifier]] = None

    def __post_init__(self) -> None:
        """Initialize modifiers and tables."""
        random.seed(self.seed)
        self._modifiers = self._create_modifier_tables()

    @staticmethod
    def _create_modifier_tables() -> dict[ItemType, list[ItemModifier]]:
        """Create standard modifier tables."""
        return {
            ItemType.WEAPON: [
                ItemModifier(
                    name="Sharp",
                    item_type=ItemType.WEAPON,
                    stat_bonuses={"damage": 2},
                    value_multiplier=1.2,
                ),
                ItemModifier(
                    name="Keen",
                    item_type=ItemType.WEAPON,
                    stat_bonuses={"critical": 1},
                    value_multiplier=1.3,
                ),
                ItemModifier(
                    name="Flaming",
                    item_type=ItemType.WEAPON,
                    stat_bonuses={"damage": 5, "fire_resist": -1},
                    value_multiplier=1.8,
                ),
                ItemModifier(
                    name="Frozen",
                    item_type=ItemType.WEAPON,
                    stat_bonuses={"damage": 3, "cold": 2},
                    value_multiplier=1.5,
                ),
                ItemModifier(
                    name="of the Void",
                    item_type=ItemType.WEAPON,
                    stat_bonuses={"damage": 4, "magic": 2},
                    value_multiplier=2.0,
                ),
            ],
            ItemType.ARMOR: [
                ItemModifier(
                    name="Reinforced",
                    item_type=ItemType.ARMOR,
                    stat_bonuses={"defense": 2},
                    value_multiplier=1.3,
                ),
                ItemModifier(
                    name="Mithril",
                    item_type=ItemType.ARMOR,
                    stat_bonuses={"defense": 4, "weight": -1},
                    value_multiplier=2.5,
                ),
                ItemModifier(
                    name="Dragonscale",
                    item_type=ItemType.ARMOR,
                    stat_bonuses={"defense": 5, "fire_resist": 2},
                    value_multiplier=3.0,
                ),
                ItemModifier(
                    name="Shadowclad",
                    item_type=ItemType.ARMOR,
                    stat_bonuses={"defense": 3, "stealth": 2},
                    value_multiplier=2.0,
                ),
            ],
            ItemType.ACCESSORY: [
                ItemModifier(
                    name="of Wisdom",
                    item_type=ItemType.ACCESSORY,
                    stat_bonuses={"wisdom": 2},
                    value_multiplier=1.5,
                ),
                ItemModifier(
                    name="of Protection",
                    item_type=ItemType.ACCESSORY,
                    stat_bonuses={"all_resist": 1},
                    value_multiplier=1.8,
                ),
                ItemModifier(
                    name="of Power",
                    item_type=ItemType.ACCESSORY,
                    stat_bonuses={"strength": 2, "damage": 2},
                    value_multiplier=2.0,
                ),
            ],
        }

    def generate_item(
        self,
        item_type: ItemType,
        level: int = 1,
        rarity: ItemRarity | None = None,
    ) -> Item:
        """
        Generate a random item.

        Args:
            item_type: Type of item to generate
            level: Character level for stat scaling
            rarity: Specific rarity (random if None)

        Returns:
            Generated Item object
        """
        if rarity is None:
            rarity = self._select_rarity()

        base_name = self._get_base_item_name(item_type)
        prefixes, suffixes = self._select_modifiers(item_type, rarity)

        # Calculate base value
        base_values = {
            ItemType.WEAPON: 50,
            ItemType.ARMOR: 40,
            ItemType.ACCESSORY: 30,
            ItemType.CONSUMABLE: 10,
            ItemType.QUEST_ITEM: 0,
        }
        base_value = base_values.get(item_type, 20)

        # Generate stats
        stats = self._generate_stats(item_type, level, rarity)

        # Enchantment level
        enchant_level = self._calculate_enchantment_level(rarity, level)

        item = Item(
            name=base_name,
            item_type=item_type,
            rarity=rarity,
            base_value=base_value,
            level_requirement=max(1, level - 2),
            stats=stats,
            prefixes=prefixes,
            suffixes=suffixes,
            enchantment_level=enchant_level,
        )

        return item

    def generate_loot_table(self, num_items: int = 5, average_level: int = 1) -> list[Item]:
        """
        Generate a loot table with items.

        Args:
            num_items: Number of items to generate
            average_level: Average level for items

        Returns:
            List of Item objects
        """
        items = []

        for _ in range(num_items):
            item_type = random.choice(list(ItemType))
            level = max(1, average_level + random.randint(-2, 3))
            item = self.generate_item(item_type, level)
            items.append(item)

        return items

    def generate_treasure_hoard(self, cr: int = 1) -> dict:
        """
        Generate a treasure hoard by Challenge Rating.

        Args:
            cr: Challenge Rating of the encounter

        Returns:
            Dictionary with 'gold', 'items', and 'value'
        """
        if cr < 1:
            raise InvalidConfigError("CR must be >= 1", "cr")

        # Gold based on CR
        gold_min = cr * 50
        gold_max = cr * 200
        gold = random.randint(gold_min, gold_max)

        # Items based on CR
        num_items = max(1, (cr - 1) // 2 + random.randint(0, 2))
        items = self.generate_loot_table(num_items, average_level=cr)

        total_value = gold + sum(item.total_value for item in items)

        return {
            "gold": gold,
            "items": items,
            "value": total_value,
        }

    def _select_rarity(self) -> ItemRarity:
        """Select a random rarity with weighted distribution."""
        weights = {
            ItemRarity.COMMON: 0.60,
            ItemRarity.UNCOMMON: 0.25,
            ItemRarity.RARE: 0.10,
            ItemRarity.EPIC: 0.04,
            ItemRarity.LEGENDARY: 0.01,
        }

        rand = random.random()
        cumulative = 0.0

        for rarity, weight in weights.items():
            cumulative += weight
            if rand < cumulative:
                return rarity

        return ItemRarity.COMMON

    def _get_base_item_name(self, item_type: ItemType) -> str:
        """Get a base item name by type."""
        names = {
            ItemType.WEAPON: [
                "Sword",
                "Axe",
                "Bow",
                "Dagger",
                "Spear",
                "Club",
                "Staff",
            ],
            ItemType.ARMOR: [
                "Plate Armor",
                "Leather Armor",
                "Chain Mail",
                "Helm",
                "Shield",
                "Greaves",
            ],
            ItemType.ACCESSORY: [
                "Ring",
                "Amulet",
                "Bracelet",
                "Pendant",
                "Cloak",
            ],
            ItemType.CONSUMABLE: [
                "Potion",
                "Scroll",
                "Elixir",
            ],
            ItemType.QUEST_ITEM: ["Artifact"],
        }

        return random.choice(names.get(item_type, ["Item"]))

    def _select_modifiers(self, item_type: ItemType, rarity: ItemRarity) -> tuple[list[str], list[str]]:
        """Select prefix and suffix modifiers based on rarity."""
        modifiers = self._modifiers.get(item_type, [])

        # Rarity determines number of modifiers
        num_modifiers = {
            ItemRarity.COMMON: 0,
            ItemRarity.UNCOMMON: 1,
            ItemRarity.RARE: 2,
            ItemRarity.EPIC: 3,
            ItemRarity.LEGENDARY: 4,
        }[rarity]

        if not modifiers:
            return [], []

        selected = random.sample(modifiers, min(num_modifiers, len(modifiers)))

        prefixes = []
        suffixes = []

        for i, mod in enumerate(selected):
            if i % 2 == 0:
                prefixes.append(mod.name)
            else:
                suffixes.append(mod.name)

        return prefixes, suffixes

    def _generate_stats(self, item_type: ItemType, level: int, rarity: ItemRarity) -> dict[str, float]:
        """Generate appropriate stats for an item."""
        stats = {}

        if item_type == ItemType.WEAPON:
            damage = level * 2 + random.randint(1, 5)
            stats["damage"] = damage
            if random.choice([True, False]):
                stats["critical"] = random.uniform(0.05, 0.20)
        elif item_type == ItemType.ARMOR:
            defense = level + random.randint(1, 4)
            stats["defense"] = defense
            if random.choice([True, False]):
                stats["magic_resist"] = random.uniform(0.1, 0.3)
        elif item_type == ItemType.ACCESSORY:
            stat_name = random.choice(["strength", "dexterity", "wisdom", "intelligence"])
            stats[stat_name] = random.randint(1, 4)

        # Rarity bonus
        rarity_multiplier = {
            ItemRarity.COMMON: 1.0,
            ItemRarity.UNCOMMON: 1.2,
            ItemRarity.RARE: 1.5,
            ItemRarity.EPIC: 2.0,
            ItemRarity.LEGENDARY: 2.5,
        }[rarity]

        for key, value in stats.items():
            if isinstance(value, (int, float)):
                stats[key] = value * rarity_multiplier

        return stats

    def _calculate_enchantment_level(self, rarity: ItemRarity, level: int) -> int:
        """Calculate enchantment level based on rarity and character level."""
        base = {
            ItemRarity.COMMON: 0,
            ItemRarity.UNCOMMON: 1,
            ItemRarity.RARE: 2,
            ItemRarity.EPIC: 3,
            ItemRarity.LEGENDARY: 5,
        }[rarity]

        return base + level // 5
