"""Checkout flow management."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from ._exceptions import EcommerceError, OrderError, PaymentError
from ._types import (
    Address,
    Cart,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    ShippingMethod,
)


class CheckoutSession:
    """Checkout session for order creation."""

    def __init__(self, session_id: str, cart: Cart) -> None:
        """Initialize checkout session.

        Args:
            session_id: Unique session ID
            cart: Shopping cart
        """
        self.session_id = session_id
        self.cart = cart
        self.step = "shipping"  # shipping -> payment -> review -> confirm
        self.shipping_address: Address | None = None
        self.billing_address: Address | None = None
        self.shipping_method: ShippingMethod | None = None
        self.payment_method: PaymentMethod | None = None
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(minutes=30)

    def is_expired(self) -> bool:
        """Check if session expired.

        Returns:
            True if expired
        """
        return datetime.utcnow() > self.expires_at


class CheckoutProcessor:
    """Multi-step checkout flow processor."""

    def __init__(self) -> None:
        """Initialize checkout processor."""
        self.sessions: dict[str, CheckoutSession] = {}
        self.orders: dict[str, Order] = {}

    def start_checkout(self, cart: Cart) -> CheckoutSession:
        """Start new checkout session.

        Args:
            cart: Shopping cart

        Returns:
            Checkout session

        Raises:
            EcommerceError: If cart is empty
        """
        if not cart.items:
            raise EcommerceError("Cannot checkout with empty cart")

        session_id = str(uuid4())
        session = CheckoutSession(session_id, cart)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> CheckoutSession | None:
        """Get checkout session.

        Args:
            session_id: Session ID

        Returns:
            Session or None if expired/not found
        """
        session = self.sessions.get(session_id)
        if session and session.is_expired():
            del self.sessions[session_id]
            return None
        return session

    def set_shipping_address(
        self,
        session_id: str,
        address: Address,
    ) -> None:
        """Set shipping address.

        Args:
            session_id: Session ID
            address: Shipping address

        Raises:
            OrderError: If address invalid or session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise OrderError("Checkout session not found or expired")

        if not address.is_valid():
            raise OrderError("Invalid address: missing required fields")

        session.shipping_address = address

    def set_billing_address(
        self,
        session_id: str,
        address: Address | None = None,
        same_as_shipping: bool = True,
    ) -> None:
        """Set billing address.

        Args:
            session_id: Session ID
            address: Billing address
            same_as_shipping: Use shipping address for billing

        Raises:
            OrderError: If address invalid or session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise OrderError("Checkout session not found or expired")

        if same_as_shipping:
            session.billing_address = session.shipping_address
        else:
            if not address or not address.is_valid():
                raise OrderError("Invalid address: missing required fields")
            session.billing_address = address

    def set_shipping_method(
        self,
        session_id: str,
        method: ShippingMethod,
    ) -> None:
        """Select shipping method.

        Args:
            session_id: Session ID
            method: Shipping method

        Raises:
            OrderError: If session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise OrderError("Checkout session not found or expired")

        session.shipping_method = method

    def set_payment_method(
        self,
        session_id: str,
        method: PaymentMethod,
    ) -> None:
        """Select payment method.

        Args:
            session_id: Session ID
            method: Payment method

        Raises:
            OrderError: If session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise OrderError("Checkout session not found or expired")

        session.payment_method = method

    def validate_checkout(self, session_id: str) -> bool:
        """Validate all checkout steps completed.

        Args:
            session_id: Session ID

        Returns:
            True if valid

        Raises:
            OrderError: If validation fails
        """
        session = self.get_session(session_id)
        if not session:
            raise OrderError("Checkout session not found or expired")

        if not session.shipping_address:
            raise OrderError("Shipping address required")

        if not session.billing_address:
            raise OrderError("Billing address required")

        if not session.shipping_method:
            raise OrderError("Shipping method required")

        if not session.payment_method:
            raise OrderError("Payment method required")

        return True

    def create_order(
        self,
        session_id: str,
        user_id: str | None = None,
    ) -> Order:
        """Create order from checkout session.

        Args:
            session_id: Session ID
            user_id: User ID

        Returns:
            Created order

        Raises:
            OrderError: If checkout invalid
        """
        self.validate_checkout(session_id)
        session = self.get_session(session_id)

        order_id = str(uuid4())
        order_items: list[OrderItem] = []

        # Convert cart items to order items
        for cart_item in session.cart.items:
            order_item = OrderItem(
                product_id=cart_item.product_id,
                variant_id=cart_item.variant_id,
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
                subtotal=cart_item.subtotal(),
            )
            order_items.append(order_item)

        # Create order
        order = Order(
            id=order_id,
            user_id=user_id or session.cart.user_id,
            items=order_items,
            status=OrderStatus.PENDING,
            payment_method=session.payment_method,
            shipping_method=session.shipping_method,
            shipping_address=session.shipping_address,
            billing_address=session.billing_address,
            coupon_code=session.cart.coupon_code,
        )

        self.orders[order_id] = order
        del self.sessions[session_id]

        return order

    def calculate_order_totals(
        self,
        order: Order,
        shipping_cost: Decimal = Decimal("0"),
        tax_cost: Decimal = Decimal("0"),
        discount: Decimal = Decimal("0"),
    ) -> Order:
        """Calculate and set order totals.

        Args:
            order: Order to calculate
            shipping_cost: Shipping amount
            tax_cost: Tax amount
            discount: Discount amount

        Returns:
            Updated order
        """
        subtotal = sum(item.subtotal for item in order.items)

        order.subtotal = subtotal
        order.tax = tax_cost
        order.shipping = shipping_cost
        order.discount = discount
        order.total = subtotal + shipping_cost + tax_cost - discount

        # Calculate loyalty points earned
        order.loyalty_points_earned = int(order.total)

        return order

    def process_payment(
        self,
        order: Order,
        payment_details: dict[str, Any],
    ) -> bool:
        """Process payment for order.

        Args:
            order: Order to pay for
            payment_details: Payment information

        Returns:
            True if payment successful

        Raises:
            PaymentError: If payment fails
        """
        # Simulate payment processing
        if not payment_details.get("amount"):
            raise PaymentError("Payment amount required")

        if order.payment_method == PaymentMethod.CREDIT_CARD:
            if not payment_details.get("card_number"):
                raise PaymentError("Card number required")

        if order.payment_method == PaymentMethod.BANK_TRANSFER:
            if not payment_details.get("account_number"):
                raise PaymentError("Account number required")

        # Update order payment status
        order.payment_status = PaymentStatus.COMPLETED
        order.status = OrderStatus.PROCESSING
        order.updated_at = datetime.utcnow()

        return True

    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order or None
        """
        return self.orders.get(order_id)

    def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
    ) -> Order:
        """Update order status.

        Args:
            order_id: Order ID
            status: New status

        Returns:
            Updated order

        Raises:
            OrderError: If order not found
        """
        order = self.orders.get(order_id)
        if not order:
            raise OrderError(f"Order {order_id} not found")

        order.status = status
        order.updated_at = datetime.utcnow()
        return order

    def cancel_order(self, order_id: str, reason: str = "") -> Order:
        """Cancel order.

        Args:
            order_id: Order ID
            reason: Cancellation reason

        Returns:
            Cancelled order

        Raises:
            OrderError: If order not found or already shipped
        """
        order = self.orders.get(order_id)
        if not order:
            raise OrderError(f"Order {order_id} not found")

        if order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            raise OrderError("Cannot cancel shipped order")

        order.status = OrderStatus.CANCELLED
        order.payment_status = PaymentStatus.REFUNDED
        order.notes = reason
        order.updated_at = datetime.utcnow()

        return order

    def refund_order(self, order_id: str, reason: str = "") -> Order:
        """Refund order.

        Args:
            order_id: Order ID
            reason: Refund reason

        Returns:
            Refunded order

        Raises:
            OrderError: If order not found or not paid
        """
        order = self.orders.get(order_id)
        if not order:
            raise OrderError(f"Order {order_id} not found")

        if order.payment_status != PaymentStatus.COMPLETED:
            raise OrderError("Only completed payments can be refunded")

        order.payment_status = PaymentStatus.REFUNDED
        order.status = OrderStatus.REFUNDED
        order.notes = reason
        order.updated_at = datetime.utcnow()

        return order

    def cleanup_expired_sessions(self) -> int:
        """Remove expired checkout sessions.

        Returns:
            Number of sessions removed
        """
        expired = [sid for sid, session in self.sessions.items() if session.is_expired()]
        for sid in expired:
            del self.sessions[sid]
        return len(expired)

    def get_order_confirmation(self, order_id: str) -> dict[str, Any]:
        """Get order confirmation data.

        Args:
            order_id: Order ID

        Returns:
            Order confirmation dictionary

        Raises:
            OrderError: If order not found
        """
        order = self.orders.get(order_id)
        if not order:
            raise OrderError(f"Order {order_id} not found")

        return {
            "order_id": order.id,
            "order_date": order.created_at.isoformat(),
            "status": order.status.value,
            "items": [
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "subtotal": str(item.subtotal),
                }
                for item in order.items
            ],
            "subtotal": str(order.subtotal),
            "tax": str(order.tax),
            "shipping": str(order.shipping),
            "discount": str(order.discount),
            "total": str(order.total),
            "payment_method": order.payment_method.value if order.payment_method else None,
            "shipping_method": order.shipping_method.value,
            "shipping_address": order.shipping_address.to_dict() if order.shipping_address else None,
            "loyalty_points_earned": order.loyalty_points_earned,
        }
