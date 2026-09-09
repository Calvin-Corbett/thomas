"""Pricing engine with dynamic pricing rules."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ._exceptions import PricingError
from ._types import PriceRule, Product, ProductVariant


class PricingEngine:
    """Dynamic pricing engine with rules and bundling."""

    def __init__(self) -> None:
        """Initialize pricing engine."""
        self.price_rules: dict[str, PriceRule] = {}
        self.bundle_rules: dict[str, dict[str, Any]] = {}

    def add_price_rule(self, rule: PriceRule) -> None:
        """Add pricing rule.

        Args:
            rule: Price rule to add
        """
        self.price_rules[rule.id] = rule

    def remove_price_rule(self, rule_id: str) -> None:
        """Remove pricing rule.

        Args:
            rule_id: Rule ID to remove
        """
        if rule_id in self.price_rules:
            del self.price_rules[rule_id]

    def get_product_price(
        self,
        product: Product,
        variant: ProductVariant | None = None,
        quantity: int = 1,
    ) -> Decimal:
        """Get effective product price with rules applied.

        Args:
            product: Product to price
            variant: Optional product variant
            quantity: Quantity for tiered pricing

        Returns:
            Effective price
        """
        base_price = product.price
        if variant:
            base_price += variant.price_delta

        # Apply price rules
        applicable_rules = [
            rule
            for rule in self.price_rules.values()
            if rule.is_applicable() and self._rule_matches(rule, product, quantity)
        ]

        # Sort by priority
        applicable_rules.sort(key=lambda r: r.priority, reverse=True)

        final_price = base_price
        for rule in applicable_rules:
            final_price = self._apply_price_rule(final_price, rule)

        return max(final_price, Decimal("0"))

    def _rule_matches(self, rule: PriceRule, product: Product, quantity: int) -> bool:
        """Check if rule matches product and quantity.

        Args:
            rule: Price rule
            product: Product to match
            quantity: Quantity

        Returns:
            True if rule applies
        """
        conditions = rule.conditions

        # Product ID condition
        if "product_ids" in conditions:
            if product.id not in conditions["product_ids"]:
                return False

        # Category condition
        if "categories" in conditions:
            if product.category not in conditions["categories"]:
                return False

        # Min quantity condition
        if "min_quantity" in conditions:
            if quantity < conditions["min_quantity"]:
                return False

        # Max quantity condition
        if "max_quantity" in conditions:
            if quantity > conditions["max_quantity"]:
                return False

        return True

    def _apply_price_rule(self, price: Decimal, rule: PriceRule) -> Decimal:
        """Apply single price rule.

        Args:
            price: Current price
            rule: Rule to apply

        Returns:
            Adjusted price
        """
        if rule.action == "discount_percentage":
            discount = price * (rule.action_value / Decimal("100"))
            return price - discount
        elif rule.action == "discount_fixed":
            return max(price - rule.action_value, Decimal("0"))
        elif rule.action == "set_price":
            return rule.action_value

        return price

    def get_quantity_discount(
        self,
        base_price: Decimal,
        quantity: int,
        tiers: list[tuple[int, Decimal]] | None = None,
    ) -> Decimal:
        """Calculate price with quantity discounts.

        Args:
            base_price: Base unit price
            quantity: Quantity ordered
            tiers: List of (min_qty, discount_percentage) tuples

        Returns:
            Unit price after quantity discount
        """
        if not tiers or quantity <= 0:
            return base_price

        # Sort tiers by quantity
        sorted_tiers = sorted(tiers, key=lambda x: x[0])

        applicable_tier = None
        for min_qty, discount_pct in sorted_tiers:
            if quantity >= min_qty:
                applicable_tier = discount_pct
            else:
                break

        if applicable_tier is not None:
            discount = base_price * (applicable_tier / Decimal("100"))
            return base_price - discount

        return base_price

    def get_tiered_price(
        self,
        quantity: int,
        tier_prices: dict[int, Decimal],
    ) -> Decimal:
        """Get tiered pricing based on quantity.

        Args:
            quantity: Quantity ordered
            tier_prices: Dict of {min_qty: price_per_unit}

        Returns:
            Unit price for quantity tier
        """
        applicable_price = None
        for min_qty in sorted(tier_prices.keys(), reverse=True):
            if quantity >= min_qty:
                applicable_price = tier_prices[min_qty]
                break

        return applicable_price if applicable_price is not None else Decimal("0")

    def add_bundle(
        self,
        bundle_id: str,
        name: str,
        items: dict[str, int],
        bundle_price: Decimal,
    ) -> None:
        """Add product bundle.

        Args:
            bundle_id: Unique bundle ID
            name: Bundle name
            items: Dict of {product_id: quantity}
            bundle_price: Total price for bundle
        """
        self.bundle_rules[bundle_id] = {
            "name": name,
            "items": items,
            "price": bundle_price,
        }

    def get_bundle_price(self, bundle_id: str) -> Decimal | None:
        """Get bundle price.

        Args:
            bundle_id: Bundle ID

        Returns:
            Bundle price or None if not found
        """
        bundle = self.bundle_rules.get(bundle_id)
        return bundle["price"] if bundle else None

    def calculate_bundle_savings(
        self,
        bundle_id: str,
        individual_prices: dict[str, Decimal],
    ) -> Decimal:
        """Calculate savings with bundle.

        Args:
            bundle_id: Bundle ID
            individual_prices: Dict of {product_id: price}

        Returns:
            Total savings
        """
        bundle = self.bundle_rules.get(bundle_id)
        if not bundle:
            return Decimal("0")

        individual_total = sum(individual_prices.get(pid, Decimal("0")) * qty for pid, qty in bundle["items"].items())

        return max(individual_total - bundle["price"], Decimal("0"))

    def get_member_price(
        self,
        base_price: Decimal,
        member_tier: str,
        tier_discounts: dict[str, Decimal],
    ) -> Decimal:
        """Get price for member tier.

        Args:
            base_price: Base price
            member_tier: Member tier name
            tier_discounts: Dict of {tier_name: discount_percentage}

        Returns:
            Member price
        """
        discount_pct = tier_discounts.get(member_tier, Decimal("0"))
        discount = base_price * (discount_pct / Decimal("100"))
        return base_price - discount

    def get_sale_price(
        self,
        base_price: Decimal,
        sale_discount: Decimal,
    ) -> Decimal:
        """Calculate sale price with discount.

        Args:
            base_price: Base price
            sale_discount: Discount percentage or amount

        Returns:
            Sale price
        """
        if sale_discount >= Decimal("1"):
            # Fixed amount discount
            return max(base_price - sale_discount, Decimal("0"))
        else:
            # Percentage discount
            discount = base_price * sale_discount
            return max(base_price - discount, Decimal("0"))

    def format_currency(self, amount: Decimal, currency: str = "USD") -> str:
        """Format amount as currency.

        Args:
            amount: Amount to format
            currency: Currency code

        Returns:
            Formatted currency string
        """
        symbols = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "JPY": "¥",
        }
        symbol = symbols.get(currency, currency)
        return f"{symbol}{amount:.2f}"

    def parse_currency_string(self, currency_str: str) -> Decimal:
        """Parse currency string to Decimal.

        Args:
            currency_str: Currency string like "$19.99"

        Returns:
            Decimal value

        Raises:
            PricingError: If parsing fails
        """
        # Remove currency symbols and whitespace
        cleaned = currency_str.strip()
        for symbol in ["$", "€", "£", "¥"]:
            cleaned = cleaned.replace(symbol, "")

        try:
            return Decimal(cleaned)
        except Exception as e:
            raise PricingError(f"Cannot parse currency string: {currency_str}") from e

    def round_price(self, price: Decimal, decimals: int = 2) -> Decimal:
        """Round price to decimal places.

        Args:
            price: Price to round
            decimals: Number of decimals

        Returns:
            Rounded price
        """
        quantize_exp = Decimal(10) ** -decimals
        return price.quantize(quantize_exp, rounding=ROUND_HALF_UP)

    def get_price_comparison(self, current_price: Decimal, original_price: Decimal) -> dict[str, Any]:
        """Calculate price comparison metrics.

        Args:
            current_price: Current price
            original_price: Original/list price

        Returns:
            Dict with comparison data
        """
        if original_price <= 0:
            return {"discount_amount": Decimal("0"), "discount_percentage": Decimal("0")}

        discount_amount = original_price - current_price
        discount_percentage = (discount_amount / original_price) * Decimal("100")

        return {
            "current_price": current_price,
            "original_price": original_price,
            "discount_amount": self.round_price(discount_amount),
            "discount_percentage": self.round_price(discount_percentage),
            "savings": self.format_currency(discount_amount),
        }

    def apply_dynamic_pricing(
        self,
        base_price: Decimal,
        demand_level: str,
        time_of_day: str,
    ) -> Decimal:
        """Apply dynamic pricing based on demand and time.

        Args:
            base_price: Base product price
            demand_level: "low", "medium", "high"
            time_of_day: "morning", "afternoon", "evening", "night"

        Returns:
            Dynamically priced amount
        """
        demand_multipliers = {
            "low": Decimal("0.95"),
            "medium": Decimal("1.00"),
            "high": Decimal("1.10"),
        }

        time_multipliers = {
            "morning": Decimal("0.98"),
            "afternoon": Decimal("1.00"),
            "evening": Decimal("1.05"),
            "night": Decimal("1.02"),
        }

        demand_mult = demand_multipliers.get(demand_level, Decimal("1.00"))
        time_mult = time_multipliers.get(time_of_day, Decimal("1.00"))

        return self.round_price(base_price * demand_mult * time_mult)
