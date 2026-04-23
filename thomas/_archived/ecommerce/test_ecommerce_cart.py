"""Tests for shopping cart management."""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.ecommerce._exceptions import EcommerceError, OutOfStockError
from thomas.ecommerce._types import Product, ProductStatus
from thomas.ecommerce.cart import ShoppingCart


class TestShoppingCart:
    """Test shopping cart operations."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.cart_manager = ShoppingCart()
        self.product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            inventory_count=10,
            status=ProductStatus.ACTIVE,
        )

    def test_create_cart(self) -> None:
        """Test creating cart."""
        cart = self.cart_manager.create_cart("cart1", "user1")

        assert cart.id == "cart1"
        assert cart.user_id == "user1"
        assert len(cart.items) == 0

    def test_create_duplicate_cart(self) -> None:
        """Test creating cart with duplicate ID."""
        self.cart_manager.create_cart("cart1", "user1")

        with pytest.raises(EcommerceError):
            self.cart_manager.create_cart("cart1", "user1")

    def test_add_item(self) -> None:
        """Test adding item to cart."""
        cart = self.cart_manager.create_cart("cart1", "user1")
        item = self.cart_manager.add_item("cart1", self.product, 2)

        assert item.product_id == "p1"
        assert item.quantity == 2
        assert item.unit_price == Decimal("999.99")

    def test_add_item_to_nonexistent_cart(self) -> None:
        """Test adding item to non-existent cart."""
        with pytest.raises(EcommerceError):
            self.cart_manager.add_item("nonexistent", self.product, 1)

    def test_add_item_out_of_stock(self) -> None:
        """Test adding more items than available."""
        self.cart_manager.create_cart("cart1")

        with pytest.raises(OutOfStockError):
            self.cart_manager.add_item("cart1", self.product, 20)

    def test_add_same_item_twice(self) -> None:
        """Test adding same item updates quantity."""
        cart = self.cart_manager.create_cart("cart1")

        self.cart_manager.add_item("cart1", self.product, 2)
        item = self.cart_manager.add_item("cart1", self.product, 3)

        assert item.quantity == 5
        assert len(cart.items) == 1

    def test_remove_item(self) -> None:
        """Test removing item from cart."""
        cart = self.cart_manager.create_cart("cart1")
        self.cart_manager.add_item("cart1", self.product, 2)

        self.cart_manager.remove_item("cart1", "p1")

        assert len(cart.items) == 0

    def test_update_item_quantity(self) -> None:
        """Test updating item quantity."""
        self.cart_manager.create_cart("cart1")
        self.cart_manager.add_item("cart1", self.product, 2)

        self.cart_manager.update_item_quantity("cart1", "p1", 5)

        cart = self.cart_manager.get_cart("cart1")
        assert cart.items[0].quantity == 5

    def test_update_item_to_zero(self) -> None:
        """Test updating item quantity to zero removes it."""
        self.cart_manager.create_cart("cart1")
        self.cart_manager.add_item("cart1", self.product, 2)

        self.cart_manager.update_item_quantity("cart1", "p1", 0)

        cart = self.cart_manager.get_cart("cart1")
        assert len(cart.items) == 0

    def test_get_subtotal(self) -> None:
        """Test calculating cart subtotal."""
        self.cart_manager.create_cart("cart1")

        p1 = Product(
            id="p1",
            name="Product 1",
            sku="P001",
            price=Decimal("100.00"),
            cost=Decimal("50.00"),
            category="cat1",
            inventory_count=10,
        )
        p2 = Product(
            id="p2",
            name="Product 2",
            sku="P002",
            price=Decimal("50.00"),
            cost=Decimal("25.00"),
            category="cat1",
            inventory_count=10,
        )

        self.cart_manager.add_item("cart1", p1, 2)
        self.cart_manager.add_item("cart1", p2, 3)

        subtotal = self.cart_manager.get_subtotal("cart1")
        expected = (Decimal("100.00") * 2) + (Decimal("50.00") * 3)
        assert subtotal == expected

    def test_get_item_count(self) -> None:
        """Test getting total item count."""
        self.cart_manager.create_cart("cart1")

        p1 = Product(
            id="p1",
            name="Product 1",
            sku="P001",
            price=Decimal("100.00"),
            cost=Decimal("50.00"),
            category="cat1",
            inventory_count=10,
        )
        p2 = Product(
            id="p2",
            name="Product 2",
            sku="P002",
            price=Decimal("50.00"),
            cost=Decimal("25.00"),
            category="cat1",
            inventory_count=10,
        )

        self.cart_manager.add_item("cart1", p1, 2)
        self.cart_manager.add_item("cart1", p2, 3)

        count = self.cart_manager.get_item_count("cart1")
        assert count == 5

    def test_clear_cart(self) -> None:
        """Test clearing cart."""
        self.cart_manager.create_cart("cart1")
        self.cart_manager.add_item("cart1", self.product, 2)

        self.cart_manager.clear_cart("cart1")

        cart = self.cart_manager.get_cart("cart1")
        assert len(cart.items) == 0

    def test_apply_coupon(self) -> None:
        """Test applying coupon code."""
        cart = self.cart_manager.create_cart("cart1")

        self.cart_manager.apply_coupon("cart1", "SUMMER20")

        assert cart.coupon_code == "SUMMER20"

    def test_remove_coupon(self) -> None:
        """Test removing coupon."""
        cart = self.cart_manager.create_cart("cart1")
        self.cart_manager.apply_coupon("cart1", "SUMMER20")

        self.cart_manager.remove_coupon("cart1")

        assert cart.coupon_code is None

    def test_save_for_later(self) -> None:
        """Test saving item for later."""
        self.cart_manager.create_cart("cart1")

        self.cart_manager.save_for_later("cart1", "p1")

        saved = self.cart_manager.get_saved_items("cart1")
        assert "p1" in saved

    def test_remove_saved_item(self) -> None:
        """Test removing saved item."""
        self.cart_manager.create_cart("cart1")
        self.cart_manager.save_for_later("cart1", "p1")

        self.cart_manager.remove_saved_item("cart1", "p1")

        saved = self.cart_manager.get_saved_items("cart1")
        assert "p1" not in saved

    def test_merge_carts(self) -> None:
        """Test merging guest and user carts."""
        guest_cart = self.cart_manager.create_cart("guest_cart")
        user_cart = self.cart_manager.create_cart("user_cart", "user1")

        p1 = Product(
            id="p1",
            name="Product 1",
            sku="P001",
            price=Decimal("100.00"),
            cost=Decimal("50.00"),
            category="cat1",
            inventory_count=20,
        )

        self.cart_manager.add_item("guest_cart", p1, 2)
        self.cart_manager.add_item("user_cart", p1, 3)

        merged = self.cart_manager.merge_carts("guest_cart", "user_cart", "user1")

        assert merged.user_id == "user1"
        assert merged.items[0].quantity == 5

    def test_cart_expiry(self) -> None:
        """Test cart expiration."""
        cart = self.cart_manager.create_cart("cart1")
        original_expires = cart.expires_at

        assert original_expires is not None

    def test_cleanup_expired_carts(self) -> None:
        """Test cleaning up expired carts."""
        from datetime import timedelta

        cart1 = self.cart_manager.create_cart("cart1")
        cart1.expires_at = datetime.utcnow() - timedelta(minutes=1)

        cart2 = self.cart_manager.create_cart("cart2")

        cleaned = self.cart_manager.cleanup_expired_carts()

        assert cleaned == 1
        assert self.cart_manager.get_cart("cart1") is None
        assert self.cart_manager.get_cart("cart2") is not None

    def test_export_cart(self) -> None:
        """Test exporting cart as dictionary."""
        self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.product, 2)

        exported = self.cart_manager.export_cart("cart1")

        assert exported["id"] == "cart1"
        assert exported["user_id"] == "user1"
        assert len(exported["items"]) == 1
