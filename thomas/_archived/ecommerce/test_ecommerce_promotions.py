"""Tests for promotions and coupons."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.ecommerce._exceptions import InvalidCouponError
from thomas.ecommerce._types import Cart, CartItem, Coupon, Product, ProductStatus
from thomas.ecommerce.promotions import PromotionEngine


class TestPromotionEngine:
    """Test promotion and coupon engine."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.engine = PromotionEngine()
        self.product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("1000.00"),
            cost=Decimal("600.00"),
            category="electronics",
            status=ProductStatus.ACTIVE,
        )

    def test_add_coupon(self) -> None:
        """Test adding coupon."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
        )
        self.engine.add_coupon(coupon)

        retrieved = self.engine.get_coupon("SUMMER20")
        assert retrieved is not None
        assert retrieved.code == "SUMMER20"

    def test_validate_coupon_valid(self) -> None:
        """Test validating valid coupon."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
            active=True,
        )
        self.engine.add_coupon(coupon)

        validated = self.engine.validate_coupon("SUMMER20")
        assert validated.code == "SUMMER20"

    def test_validate_coupon_not_found(self) -> None:
        """Test validating non-existent coupon."""
        with pytest.raises(InvalidCouponError):
            self.engine.validate_coupon("NONEXISTENT")

    def test_validate_coupon_expired(self) -> None:
        """Test validating expired coupon."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
            expires_at=datetime.utcnow() - timedelta(days=1),
            active=True,
        )
        self.engine.add_coupon(coupon)

        with pytest.raises(InvalidCouponError):
            self.engine.validate_coupon("SUMMER20")

    def test_validate_coupon_inactive(self) -> None:
        """Test validating inactive coupon."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
            active=False,
        )
        self.engine.add_coupon(coupon)

        with pytest.raises(InvalidCouponError):
            self.engine.validate_coupon("SUMMER20")

    def test_coupon_minimum_order(self) -> None:
        """Test coupon minimum order threshold."""
        coupon = Coupon(
            code="MIN100",
            coupon_type="flat",
            value=Decimal("10"),
            minimum_order_total=Decimal("100.00"),
            active=True,
        )
        self.engine.add_coupon(coupon)

        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("50.00"),
            )
        )

        with pytest.raises(InvalidCouponError):
            self.engine.apply_coupon("MIN100", cart)

    def test_apply_coupon_percentage(self) -> None:
        """Test applying percentage coupon."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
            active=True,
        )
        self.engine.add_coupon(coupon)

        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("100.00"),
            )
        )

        discount = self.engine.apply_coupon("SUMMER20", cart)
        assert discount == Decimal("20.00")

    def test_apply_coupon_flat(self) -> None:
        """Test applying flat discount coupon."""
        coupon = Coupon(
            code="FLAT20",
            coupon_type="flat",
            value=Decimal("20.00"),
            active=True,
        )
        self.engine.add_coupon(coupon)

        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("100.00"),
            )
        )

        discount = self.engine.apply_coupon("FLAT20", cart)
        assert discount == Decimal("20.00")

    def test_record_coupon_usage(self) -> None:
        """Test recording coupon usage."""
        coupon = Coupon(
            code="SUMMER20",
            coupon_type="percentage",
            value=Decimal("20"),
        )
        self.engine.add_coupon(coupon)

        self.engine.record_coupon_usage("SUMMER20", "user1")

        retrieved = self.engine.get_coupon("SUMMER20")
        assert retrieved.usage_count == 1

    def test_coupon_usage_limit_per_user(self) -> None:
        """Test coupon usage limit per user."""
        coupon = Coupon(
            code="LIMITED",
            coupon_type="flat",
            value=Decimal("10.00"),
            usage_limit_per_user=1,
            active=True,
        )
        self.engine.add_coupon(coupon)

        self.engine.record_coupon_usage("LIMITED", "user1")

        with pytest.raises(InvalidCouponError):
            self.engine.validate_coupon("LIMITED", "user1")

    def test_add_bogo(self) -> None:
        """Test adding buy-one-get-one promotion."""
        self.engine.add_bogo(
            "bogo1",
            trigger_product_id="p1",
            reward_product_id="p2",
            reward_type="free",
        )

        assert "bogo1" in self.engine.bogo_rules

    def test_apply_bogo_free(self) -> None:
        """Test applying BOGO free reward."""
        self.engine.add_bogo(
            "bogo1",
            trigger_product_id="p1",
            reward_product_id="p2",
            reward_type="free",
            min_quantity=1,
        )

        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("100.00"),
            )
        )
        cart.items.append(
            CartItem(
                product_id="p2",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("50.00"),
            )
        )

        discount = self.engine.apply_bogo("bogo1", cart)
        assert discount == Decimal("50.00")

    def test_add_cart_rule(self) -> None:
        """Test adding automatic cart rule."""
        condition = {"min_cart_total": Decimal("100.00")}
        action = {"type": "discount_percentage", "value": Decimal("5")}

        self.engine.add_cart_rule("rule1", condition, action)

        assert len(self.engine.cart_rules) == 1

    def test_apply_cart_rules(self) -> None:
        """Test applying automatic cart rules."""
        condition = {"min_cart_total": Decimal("100.00")}
        action = {"type": "discount_percentage", "value": Decimal("5")}
        self.engine.add_cart_rule("rule1", condition, action)

        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=Decimal("150.00"),
            )
        )

        discount = self.engine.apply_cart_rules(cart)
        expected = Decimal("150.00") * Decimal("5") / Decimal("100")
        assert discount == expected

    def test_loyalty_points_earn(self) -> None:
        """Test earning loyalty points."""
        self.engine.add_loyalty_points("user1", 100)

        balance = self.engine.get_loyalty_balance("user1")
        assert balance == 100

    def test_loyalty_points_redeem(self) -> None:
        """Test redeeming loyalty points."""
        self.engine.add_loyalty_points("user1", 100)

        success = self.engine.redeem_loyalty_points("user1", 50)

        assert success is True
        assert self.engine.get_loyalty_balance("user1") == 50

    def test_loyalty_points_redeem_insufficient(self) -> None:
        """Test redeeming with insufficient points."""
        self.engine.add_loyalty_points("user1", 50)

        success = self.engine.redeem_loyalty_points("user1", 100)

        assert success is False

    def test_calculate_loyalty_points_earned(self) -> None:
        """Test calculating loyalty points earned."""
        points = self.engine.calculate_loyalty_points_earned(Decimal("100.00"))
        assert points == 100

    def test_loyalty_points_to_discount(self) -> None:
        """Test converting loyalty points to discount."""
        discount = self.engine.loyalty_points_to_discount(100)
        assert discount == Decimal("1.00")
