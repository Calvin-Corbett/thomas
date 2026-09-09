"""
Inventory management module for food technology platform.

Handles pantry tracking, expiry management, low stock alerts,
inventory-based recipe suggestions, and waste analysis.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from thomas.food_tech._exceptions import (
    InventoryError,
    LowStockError,
)
from thomas.food_tech._types import FoodItem, Recipe


class InventoryManager:
    """Manages kitchen inventory with FIFO and expiry tracking."""

    def __init__(self) -> None:
        """Initialize inventory manager."""
        self.inventory: dict[str, list[FoodItem]] = {}
        self.low_stock_threshold: dict[str, Decimal] = {}
        self.expiry_warnings: list[FoodItem] = []

    def add_item(
        self,
        name: str,
        quantity: Decimal,
        unit: str,
        category,
        expiry_date: datetime | None = None,
        storage_location: str = "pantry",
        cost: Decimal | None = None,
        supplier: str = "",
    ) -> FoodItem:
        """Add an item to inventory.

        Args:
            name: Item name.
            quantity: Quantity value.
            unit: Unit of measurement.
            category: Food category.
            expiry_date: Optional expiry date.
            storage_location: Storage location (pantry, fridge, freezer).
            cost: Optional item cost.
            supplier: Optional supplier name.

        Returns:
            FoodItem: Created inventory item.
        """
        item = FoodItem(
            name=name,
            category=category,
            quantity=quantity,
            unit=unit,
            expiry_date=expiry_date,
            storage_location=storage_location,
            purchase_date=datetime.now(),
            cost=cost,
            supplier=supplier,
        )

        key = name.lower()
        if key not in self.inventory:
            self.inventory[key] = []

        self.inventory[key].append(item)

        # Check for expiry warning
        if expiry_date:
            days_until_expiry = (expiry_date - datetime.now()).days
            if days_until_expiry < 7:
                self.expiry_warnings.append(item)

        return item

    def use_item(
        self,
        name: str,
        quantity: Decimal,
        unit: str,
    ) -> FoodItem | None:
        """Use an item from inventory (FIFO).

        Args:
            name: Item name.
            quantity: Quantity to use.
            unit: Unit of measurement.

        Returns:
            Optional[FoodItem]: Used item, or None if insufficient stock.

        Raises:
            InventoryError: If item not found.
        """
        key = name.lower()
        if key not in self.inventory or not self.inventory[key]:
            raise InventoryError(f"Item {name} not in inventory")

        # Sort by purchase date (FIFO)
        items = sorted(self.inventory[key], key=lambda x: x.purchase_date)

        remaining = quantity

        for item in items:
            if item.quantity <= 0:
                continue

            if item.expiry_date and item.expiry_date < datetime.now():
                continue

            use_amount = min(item.quantity, remaining)
            item.quantity -= use_amount
            remaining -= use_amount

            if remaining <= 0:
                # Clean up empty items
                self.inventory[key] = [i for i in self.inventory[key] if i.quantity > 0]
                return item

        if remaining > 0:
            raise LowStockError(f"Insufficient {name} in inventory")

        return items[0]

    def get_item_quantity(self, name: str) -> Decimal:
        """Get total quantity of an item in inventory.

        Args:
            name: Item name.

        Returns:
            Decimal: Total quantity available.
        """
        key = name.lower()
        if key not in self.inventory:
            return Decimal(0)

        total = Decimal(0)
        for item in self.inventory[key]:
            if not item.expiry_date or item.expiry_date >= datetime.now():
                total += item.quantity

        return total

    def set_low_stock_threshold(self, item_name: str, threshold: Decimal) -> None:
        """Set low stock alert threshold for an item.

        Args:
            item_name: Item name.
            threshold: Minimum quantity before alert.
        """
        self.low_stock_threshold[item_name.lower()] = threshold

    def get_low_stock_items(self) -> list[tuple[str, Decimal, Decimal]]:
        """Get items below low stock threshold.

        Returns:
            List[Tuple[str, Decimal, Decimal]]: (name, current_qty, threshold).
        """
        low_stock = []

        for item_name, threshold in self.low_stock_threshold.items():
            current = self.get_item_quantity(item_name)
            if current < threshold:
                low_stock.append((item_name, current, threshold))

        return low_stock

    def get_expiry_warnings(self, days_ahead: int = 7) -> list[FoodItem]:
        """Get items expiring within specified days.

        Args:
            days_ahead: Number of days to look ahead.

        Returns:
            List[FoodItem]: Items expiring soon.
        """
        expiring = []
        cutoff = datetime.now() + timedelta(days=days_ahead)

        for items_list in self.inventory.values():
            for item in items_list:
                if item.expiry_date and item.expiry_date <= cutoff:
                    if item.quantity > 0:
                        expiring.append(item)

        return sorted(expiring, key=lambda x: x.expiry_date or datetime.max)

    def find_recipes_with_inventory(
        self,
        recipes: list[Recipe],
        min_overlap: Decimal = Decimal("0.5"),
    ) -> list[tuple[Recipe, Decimal]]:
        """Find recipes that can be made with current inventory.

        Args:
            recipes: Available recipes.
            min_overlap: Minimum ingredient overlap (0-1).

        Returns:
            List[Tuple[Recipe, Decimal]]: (recipe, overlap_score) sorted by overlap.
        """
        available_items = {k: self.get_item_quantity(k.split()[0]) > 0 for k in self.inventory.keys()}

        makeable = []

        for recipe in recipes:
            available = 0
            for ingredient in recipe.ingredients:
                ing_name = ingredient.name.lower()
                if any(ing_name in item_name for item_name in available_items):
                    available += 1

            if recipe.ingredients:
                overlap = Decimal(available) / Decimal(len(recipe.ingredients))
                if overlap >= min_overlap:
                    makeable.append((recipe, overlap))

        return sorted(makeable, key=lambda x: x[1], reverse=True)

    def generate_shopping_list(
        self,
        recipes: list[Recipe],
    ) -> dict[str, tuple[Decimal, str]]:
        """Generate shopping list for recipes based on missing items.

        Args:
            recipes: Recipes to shop for.

        Returns:
            Dict[str, Tuple[Decimal, str]]: Items to purchase (name -> (qty, unit)).
        """
        needed: dict[str, tuple[Decimal, str]] = {}

        for recipe in recipes:
            for ingredient in recipe.ingredients:
                ing_key = ingredient.name.lower()
                in_stock = self.get_item_quantity(ing_key)

                if in_stock < ingredient.quantity:
                    to_buy = ingredient.quantity - in_stock

                    if ing_key in needed:
                        current_qty, unit = needed[ing_key]
                        needed[ing_key] = (current_qty + to_buy, unit)
                    else:
                        needed[ing_key] = (to_buy, ingredient.unit)

        return needed

    def get_waste_analysis(self) -> dict[str, Decimal]:
        """Analyze food waste from expired items.

        Returns:
            Dict[str, Decimal]: Item name to wasted quantity.
        """
        wasted = {}

        for item_name, items_list in self.inventory.items():
            for item in items_list:
                if item.expiry_date and item.expiry_date < datetime.now():
                    if item.quantity > 0:
                        wasted[item_name] = wasted.get(item_name, Decimal(0)) + item.quantity

        return wasted

    def get_waste_percentage(self) -> Decimal:
        """Calculate percentage of inventory that has expired.

        Returns:
            Decimal: Waste percentage (0-100).
        """
        total_quantity = Decimal(0)
        wasted_quantity = Decimal(0)

        for items_list in self.inventory.values():
            for item in items_list:
                total_quantity += item.quantity

                if item.expiry_date and item.expiry_date < datetime.now():
                    wasted_quantity += item.quantity

        if total_quantity == 0:
            return Decimal(0)

        return (wasted_quantity / total_quantity * 100).quantize(Decimal("0.1"))

    def get_storage_recommendations(self, item_name: str) -> str:
        """Get storage location recommendation for an item.

        Args:
            item_name: Item name.

        Returns:
            str: Recommended storage location.
        """
        # Simple heuristic-based recommendations
        name_lower = item_name.lower()

        if any(fruit in name_lower for fruit in ["banana", "apple", "orange", "berry"]):
            return "pantry"
        elif any(veg in name_lower for veg in ["lettuce", "spinach", "carrot", "celery"]):
            return "fridge"
        elif any(meat in name_lower for meat in ["chicken", "beef", "fish", "pork"]):
            return "freezer"
        elif any(dairy in name_lower for dairy in ["milk", "yogurt", "butter", "cheese"]):
            return "fridge"
        else:
            return "pantry"
