"""Tests for checkout flow."""

from decimal import Decimal

import pytest

from thomas.ecommerce._exceptions import OrderError
from thomas.ecommerce._types import (
    Address,
    Cart,
    CartItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    Product,
    ProductStatus,
    ShippingMethod,
)
from thomas.ecommerce.checkout import CheckoutProcessor


class TestCheckoutProcessor:
    """Test checkout flow processing."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.processor = CheckoutProcessor()
        self.product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("1000.00"),
            cost=Decimal("600.00"),
            category="electronics",
            status=ProductStatus.ACTIVE,
        )

    def create_cart_with_items(self) -> Cart:
        """Create cart with sample items."""
        cart = Cart(id="cart1", user_id="user1", items=[])
        cart.items.append(
            CartItem(
                product_id="p1",
                variant_id=None,
                quantity=1,
                unit_price=self.product.price,
            )
        )
        return cart

    def test_start_checkout(self) -> None:
        """Test starting checkout."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        assert session.cart == cart
        assert session.step == "shipping"

    def test_start_checkout_empty_cart(self) -> None:
        """Test starting checkout with empty cart."""
        cart = Cart(id="cart1", user_id="user1", items=[])

        with pytest.raises(OrderError):
            self.processor.start_checkout(cart)

    def test_set_shipping_address(self) -> None:
        """Test setting shipping address."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)

        assert session.shipping_address == address

    def test_set_shipping_address_invalid(self) -> None:
        """Test setting invalid shipping address."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )

        with pytest.raises(OrderError):
            self.processor.set_shipping_address(session.session_id, address)

    def test_set_billing_address_same_as_shipping(self) -> None:
        """Test setting billing address same as shipping."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)

        assert session.billing_address == address

    def test_set_billing_address_different(self) -> None:
        """Test setting different billing address."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        shipping_address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        billing_address = Address(
            street_line_1="456 Oak Ave",
            street_line_2=None,
            city="Chicago",
            state="IL",
            postal_code="60601",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, shipping_address)
        self.processor.set_billing_address(session.session_id, billing_address, same_as_shipping=False)

        assert session.billing_address == billing_address
        assert session.shipping_address != session.billing_address

    def test_set_shipping_method(self) -> None:
        """Test selecting shipping method."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        self.processor.set_shipping_method(session.session_id, ShippingMethod.EXPRESS)

        assert session.shipping_method == ShippingMethod.EXPRESS

    def test_set_payment_method(self) -> None:
        """Test selecting payment method."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        assert session.payment_method == PaymentMethod.CREDIT_CARD

    def test_validate_checkout_incomplete(self) -> None:
        """Test validation fails for incomplete checkout."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        with pytest.raises(OrderError):
            self.processor.validate_checkout(session.session_id)

    def test_validate_checkout_complete(self) -> None:
        """Test validation passes for complete checkout."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        assert self.processor.validate_checkout(session.session_id) is True

    def test_create_order(self) -> None:
        """Test creating order from checkout."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")

        assert order.status == OrderStatus.PENDING
        assert len(order.items) == 1
        assert order.items[0].product_id == "p1"

    def test_calculate_order_totals(self) -> None:
        """Test calculating order totals."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")

        updated_order = self.processor.calculate_order_totals(
            order,
            shipping_cost=Decimal("10.00"),
            tax_cost=Decimal("100.00"),
            discount=Decimal("50.00"),
        )

        assert updated_order.subtotal == Decimal("1000.00")
        assert updated_order.shipping == Decimal("10.00")
        assert updated_order.tax == Decimal("100.00")
        assert updated_order.discount == Decimal("50.00")
        assert updated_order.total == Decimal("1060.00")

    def test_process_payment(self) -> None:
        """Test processing payment."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")

        payment_details = {
            "amount": Decimal("1000.00"),
            "card_number": "4111111111111111",
        }
        success = self.processor.process_payment(order, payment_details)

        assert success is True
        assert order.payment_status == PaymentStatus.COMPLETED
        assert order.status == OrderStatus.PROCESSING

    def test_update_order_status(self) -> None:
        """Test updating order status."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")

        updated = self.processor.update_order_status(order.id, OrderStatus.SHIPPED)

        assert updated.status == OrderStatus.SHIPPED

    def test_cancel_order(self) -> None:
        """Test cancelling order."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")

        cancelled = self.processor.cancel_order(order.id, "Customer request")

        assert cancelled.status == OrderStatus.CANCELLED

    def test_refund_order(self) -> None:
        """Test refunding order."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")
        order.payment_status = PaymentStatus.COMPLETED

        refunded = self.processor.refund_order(order.id, "Customer request")

        assert refunded.payment_status == PaymentStatus.REFUNDED
        assert refunded.status == OrderStatus.REFUNDED

    def test_get_order_confirmation(self) -> None:
        """Test getting order confirmation."""
        cart = self.create_cart_with_items()
        session = self.processor.start_checkout(cart)

        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        )
        self.processor.set_shipping_address(session.session_id, address)
        self.processor.set_billing_address(session.session_id, same_as_shipping=True)
        self.processor.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.processor.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.processor.create_order(session.session_id, "user1")
        self.processor.calculate_order_totals(order, Decimal("10.00"), Decimal("100.00"))

        confirmation = self.processor.get_order_confirmation(order.id)

        assert confirmation["order_id"] == order.id
        assert confirmation["status"] == "pending"
        assert len(confirmation["items"]) == 1
