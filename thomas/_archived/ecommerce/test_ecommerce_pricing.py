"""Tests for pricing engine."""

from decimal import Decimal

from thomas.ecommerce._types import PriceRule, Product, ProductStatus
from thomas.ecommerce.pricing import PricingEngine


class TestPricingEngine:
    """Test pricing engine functionality."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.engine = PricingEngine()
        self.product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("1000.00"),
            cost=Decimal("600.00"),
            category="electronics",
            status=ProductStatus.ACTIVE,
        )

    def test_base_price(self) -> None:
        """Test getting base product price."""
        price = self.engine.get_product_price(self.product)
        assert price == Decimal("1000.00")

    def test_quantity_discount_tiered(self) -> None:
        """Test quantity-based tiered discounts."""
        tiers = [
            (1, Decimal("0")),
            (3, Decimal("5")),
            (10, Decimal("10")),
        ]

        price_1 = self.engine.get_quantity_discount(Decimal("100.00"), 1, tiers)
        assert price_1 == Decimal("100.00")

        price_3 = self.engine.get_quantity_discount(Decimal("100.00"), 3, tiers)
        assert price_3 == Decimal("95.00")

        price_10 = self.engine.get_quantity_discount(Decimal("100.00"), 10, tiers)
        assert price_10 == Decimal("90.00")

    def test_tiered_pricing(self) -> None:
        """Test tiered pricing by quantity."""
        tier_prices = {
            1: Decimal("100.00"),
            10: Decimal("90.00"),
            50: Decimal("80.00"),
        }

        price_1 = self.engine.get_tiered_price(1, tier_prices)
        assert price_1 == Decimal("100.00")

        price_25 = self.engine.get_tiered_price(25, tier_prices)
        assert price_25 == Decimal("90.00")

        price_100 = self.engine.get_tiered_price(100, tier_prices)
        assert price_100 == Decimal("80.00")

    def test_add_price_rule(self) -> None:
        """Test adding price rule."""
        rule = PriceRule(
            id="rule1",
            name="Electronics Discount",
            conditions={"categories": ["electronics"]},
            action="discount_percentage",
            action_value=Decimal("10"),
        )
        self.engine.add_price_rule(rule)

        assert "rule1" in self.engine.price_rules

    def test_price_rule_discount_percentage(self) -> None:
        """Test percentage discount rule."""
        from datetime import datetime

        rule = PriceRule(
            id="rule1",
            name="Electronics Discount",
            conditions={"categories": ["electronics"]},
            action="discount_percentage",
            action_value=Decimal("10"),
            active=True,
            start_date=datetime.utcnow(),
        )

        self.engine.add_price_rule(rule)

        price = self.engine.get_product_price(self.product)
        expected = Decimal("1000.00") * (1 - Decimal("10") / Decimal("100"))
        assert price == expected

    def test_price_rule_discount_fixed(self) -> None:
        """Test fixed amount discount rule."""
        from datetime import datetime

        rule = PriceRule(
            id="rule1",
            name="Fixed Discount",
            conditions={"product_ids": ["p1"]},
            action="discount_fixed",
            action_value=Decimal("100.00"),
            active=True,
            start_date=datetime.utcnow(),
        )

        self.engine.add_price_rule(rule)

        price = self.engine.get_product_price(self.product)
        assert price == Decimal("900.00")

    def test_price_rule_quantity_condition(self) -> None:
        """Test price rule with quantity conditions."""
        from datetime import datetime

        rule = PriceRule(
            id="rule1",
            name="Bulk Discount",
            conditions={"product_ids": ["p1"], "min_quantity": 5},
            action="discount_percentage",
            action_value=Decimal("15"),
            active=True,
            start_date=datetime.utcnow(),
        )

        self.engine.add_price_rule(rule)

        price_1 = self.engine.get_product_price(self.product, quantity=1)
        assert price_1 == Decimal("1000.00")

        price_5 = self.engine.get_product_price(self.product, quantity=5)
        expected = Decimal("1000.00") * (1 - Decimal("15") / Decimal("100"))
        assert price_5 == expected

    def test_bundle_pricing(self) -> None:
        """Test bundle pricing."""
        bundle_items = {"p1": 2, "p2": 1}
        self.engine.add_bundle("bundle1", "Laptop Bundle", bundle_items, Decimal("2200.00"))

        bundle_price = self.engine.get_bundle_price("bundle1")
        assert bundle_price == Decimal("2200.00")

    def test_bundle_savings(self) -> None:
        """Test calculating bundle savings."""
        bundle_items = {"p1": 2, "p2": 1}
        self.engine.add_bundle("bundle1", "Laptop Bundle", bundle_items, Decimal("2200.00"))

        individual_prices = {"p1": Decimal("1000.00"), "p2": Decimal("500.00")}
        savings = self.engine.calculate_bundle_savings("bundle1", individual_prices)

        expected = (Decimal("1000.00") * 2 + Decimal("500.00")) - Decimal("2200.00")
        assert savings == expected

    def test_member_pricing(self) -> None:
        """Test member tier pricing."""
        tier_discounts = {
            "gold": Decimal("15"),
            "silver": Decimal("10"),
            "bronze": Decimal("5"),
        }

        price_gold = self.engine.get_member_price(Decimal("100.00"), "gold", tier_discounts)
        assert price_gold == Decimal("85.00")

        price_silver = self.engine.get_member_price(Decimal("100.00"), "silver", tier_discounts)
        assert price_silver == Decimal("90.00")

    def test_sale_pricing_percentage(self) -> None:
        """Test sale pricing with percentage discount."""
        price = self.engine.get_sale_price(Decimal("100.00"), Decimal("0.20"))
        assert price == Decimal("80.00")

    def test_sale_pricing_fixed(self) -> None:
        """Test sale pricing with fixed discount."""
        price = self.engine.get_sale_price(Decimal("100.00"), Decimal("20.00"))
        assert price == Decimal("80.00")

    def test_format_currency(self) -> None:
        """Test currency formatting."""
        formatted = self.engine.format_currency(Decimal("99.99"), "USD")
        assert "$" in formatted
        assert "99.99" in formatted

    def test_parse_currency_string(self) -> None:
        """Test parsing currency strings."""
        value = self.engine.parse_currency_string("$99.99")
        assert value == Decimal("99.99")

    def test_round_price(self) -> None:
        """Test price rounding."""
        rounded = self.engine.round_price(Decimal("99.996"), 2)
        assert rounded == Decimal("100.00")

    def test_price_comparison(self) -> None:
        """Test price comparison metrics."""
        comparison = self.engine.get_price_comparison(Decimal("80.00"), Decimal("100.00"))

        assert comparison["discount_amount"] == Decimal("20.00")
        assert comparison["discount_percentage"] == Decimal("20.00")

    def test_dynamic_pricing_demand(self) -> None:
        """Test dynamic pricing based on demand."""
        base = Decimal("100.00")

        low_demand = self.engine.apply_dynamic_pricing(base, "low", "afternoon")
        assert low_demand < base

        high_demand = self.engine.apply_dynamic_pricing(base, "high", "afternoon")
        assert high_demand > base

    def test_dynamic_pricing_time(self) -> None:
        """Test dynamic pricing based on time of day."""
        base = Decimal("100.00")

        morning = self.engine.apply_dynamic_pricing(base, "medium", "morning")
        evening = self.engine.apply_dynamic_pricing(base, "medium", "evening")

        assert morning < evening
