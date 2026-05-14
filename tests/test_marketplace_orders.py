"""Tests for order management module."""

from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import (
    InvalidOrderState,
    OrderNotFoundError,
)
from thomas.marketplace._types import OrderStatus
from thomas.marketplace.orders import (
    CartItem,
    OrderProcessor,
    ShoppingCart,
    VendorCart,
)


class TestShoppingCart:
    """Test shopping cart operations."""

    def test_add_item(self) -> None:
        """Test adding item to cart."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item(
            listing_id="listing_1",
            vendor_id="vendor_1",
            quantity=2,
            unit_price=Decimal("99.99"),
            title="Laptop",
        )

        vendor_carts = cart.get_vendor_carts()
        assert len(vendor_carts) == 1
        assert len(vendor_carts[0].items) == 1
        assert vendor_carts[0].items[0].quantity == 2

    def test_add_same_item_increments_quantity(self) -> None:
        """Test adding same item increments quantity."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 2, Decimal("99.99"), "Laptop")
        cart.add_item("listing_1", "vendor_1", 3, Decimal("99.99"), "Laptop")

        vendor_carts = cart.get_vendor_carts()
        assert vendor_carts[0].items[0].quantity == 5

    def test_add_items_from_multiple_vendors(self) -> None:
        """Test adding items from multiple vendors."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 1, Decimal("99.99"), "Laptop")
        cart.add_item("listing_2", "vendor_2", 2, Decimal("29.99"), "Mouse")

        vendor_carts = cart.get_vendor_carts()
        assert len(vendor_carts) == 2

    def test_remove_item(self) -> None:
        """Test removing item from cart."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 1, Decimal("99.99"), "Laptop")
        cart.add_item("listing_2", "vendor_1", 2, Decimal("29.99"), "Mouse")

        cart.remove_item("listing_1", "vendor_1")

        vendor_carts = cart.get_vendor_carts()
        assert len(vendor_carts[0].items) == 1

    def test_remove_last_item_removes_vendor_cart(self) -> None:
        """Test removing last item removes vendor cart."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 1, Decimal("99.99"), "Laptop")
        cart.remove_item("listing_1", "vendor_1")

        vendor_carts = cart.get_vendor_carts()
        assert len(vendor_carts) == 0

    def test_get_total(self) -> None:
        """Test getting cart total."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 1, Decimal("100.00"), "Item1")
        cart.add_item("listing_2", "vendor_2", 2, Decimal("50.00"), "Item2")

        total = cart.get_total()
        assert total == Decimal("200.00")

    def test_clear_cart(self) -> None:
        """Test clearing cart."""
        cart = ShoppingCart(buyer_id="buyer_1")

        cart.add_item("listing_1", "vendor_1", 1, Decimal("100.00"), "Item1")
        cart.clear()

        assert len(cart.get_vendor_carts()) == 0


class TestOrderProcessor:
    """Test order processing."""

    def test_create_orders_from_cart(self) -> None:
        """Test creating orders from cart."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
            VendorCart(
                vendor_id="vendor_2",
                items=[
                    CartItem(
                        listing_id="listing_2",
                        vendor_id="vendor_2",
                        quantity=2,
                        unit_price=Decimal("29.99"),
                        title="Mouse",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        assert len(orders) == 2
        assert orders[0].status == OrderStatus.PLACED
        assert orders[1].status == OrderStatus.PLACED

    def test_get_order(self) -> None:
        """Test retrieving order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        retrieved = processor.get_order(orders[0].id)
        assert retrieved.id == orders[0].id
        assert retrieved.buyer_id == "buyer_1"

    def test_get_nonexistent_order(self) -> None:
        """Test getting nonexistent order."""
        processor = OrderProcessor()

        with pytest.raises(OrderNotFoundError):
            processor.get_order("order_nonexistent")

    def test_confirm_order(self) -> None:
        """Test confirming order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        confirmed = processor.confirm_order(orders[0].id)
        assert confirmed.status == OrderStatus.CONFIRMED

    def test_confirm_non_placed_order_fails(self) -> None:
        """Test confirming non-placed order fails."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        processor.confirm_order(orders[0].id)

        with pytest.raises(InvalidOrderState):
            processor.confirm_order(orders[0].id)

    def test_ship_order(self) -> None:
        """Test shipping order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        confirmed = processor.confirm_order(orders[0].id)
        shipped = processor.ship_order(confirmed.id, "TRACK123", "vendor_1")

        assert shipped.status == OrderStatus.SHIPPED
        assert "vendor_1" in shipped.tracking_numbers

    def test_deliver_order(self) -> None:
        """Test delivering order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        confirmed = processor.confirm_order(orders[0].id)
        shipped = processor.ship_order(confirmed.id, "TRACK123", "vendor_1")
        delivered = processor.deliver_order(shipped.id)

        assert delivered.status == OrderStatus.DELIVERED

    def test_complete_order(self) -> None:
        """Test completing order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        confirmed = processor.confirm_order(orders[0].id)
        shipped = processor.ship_order(confirmed.id, "TRACK123", "vendor_1")
        delivered = processor.deliver_order(shipped.id)
        completed = processor.complete_order(delivered.id)

        assert completed.status == OrderStatus.COMPLETED

    def test_cancel_order(self) -> None:
        """Test cancelling order."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        orders = processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        cancelled = processor.cancel_order(orders[0].id, "Changed mind")
        assert cancelled.status == OrderStatus.CANCELLED

    def test_list_buyer_orders(self) -> None:
        """Test listing buyer's orders."""
        processor = OrderProcessor()

        vendor_carts = [
            VendorCart(
                vendor_id="vendor_1",
                items=[
                    CartItem(
                        listing_id="listing_1",
                        vendor_id="vendor_1",
                        quantity=1,
                        unit_price=Decimal("99.99"),
                        title="Laptop",
                    ),
                ],
            ),
        ]

        processor.create_orders_from_cart(
            buyer_id="buyer_1",
            vendor_carts=vendor_carts,
            shipping_address="123 Main St",
            billing_address="456 Oak Ave",
            shipping_method="standard",
        )

        buyer_orders = processor.list_buyer_orders("buyer_1")
        assert len(buyer_orders) == 1

        other_orders = processor.list_buyer_orders("buyer_2")
        assert len(other_orders) == 0
