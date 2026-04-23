"""Order management with multi-vendor cart, checkout, and fulfillment."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from thomas.marketplace._exceptions import (
    InvalidOrderState,
    OrderNotFoundError,
)
from thomas.marketplace._types import (
    Order,
    OrderStatus,
)


@dataclass
class CartItem:
    """Item in shopping cart."""

    listing_id: str
    vendor_id: str
    quantity: int
    unit_price: Decimal
    title: str

    @property
    def total_price(self) -> Decimal:
        """Get item total price."""
        return self.unit_price * Decimal(str(self.quantity))


@dataclass
class VendorCart:
    """Cart items grouped by vendor."""

    vendor_id: str
    items: list[CartItem] = field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        """Get vendor cart subtotal."""
        return sum(item.total_price for item in self.items)

    @property
    def item_count(self) -> int:
        """Get total items in vendor cart."""
        return sum(item.quantity for item in self.items)


class ShoppingCart:
    """Multi-vendor shopping cart with vendor-level separation."""

    def __init__(self, buyer_id: str) -> None:
        """Initialize shopping cart.

        Args:
            buyer_id: Buyer identifier.
        """
        self.buyer_id = buyer_id
        self._carts: dict[str, VendorCart] = {}

    def add_item(
        self,
        listing_id: str,
        vendor_id: str,
        quantity: int,
        unit_price: Decimal,
        title: str,
    ) -> None:
        """Add item to cart, grouped by vendor.

        Args:
            listing_id: Listing identifier.
            vendor_id: Vendor identifier.
            quantity: Quantity to add.
            unit_price: Price per unit.
            title: Product title.
        """
        if vendor_id not in self._carts:
            self._carts[vendor_id] = VendorCart(vendor_id=vendor_id)

        vendor_cart = self._carts[vendor_id]

        # Check if item already in cart
        for item in vendor_cart.items:
            if item.listing_id == listing_id:
                item.quantity += quantity
                return

        # Add new item
        item = CartItem(
            listing_id=listing_id,
            vendor_id=vendor_id,
            quantity=quantity,
            unit_price=unit_price,
            title=title,
        )
        vendor_cart.items.append(item)

    def remove_item(self, listing_id: str, vendor_id: str) -> None:
        """Remove item from cart.

        Args:
            listing_id: Listing identifier.
            vendor_id: Vendor identifier.
        """
        if vendor_id not in self._carts:
            return

        vendor_cart = self._carts[vendor_id]
        vendor_cart.items = [item for item in vendor_cart.items if item.listing_id != listing_id]

        if not vendor_cart.items:
            del self._carts[vendor_id]

    def get_vendor_carts(self) -> list[VendorCart]:
        """Get all vendor carts.

        Returns:
            List of vendor carts.
        """
        return list(self._carts.values())

    def get_total(self) -> Decimal:
        """Get total cart value.

        Returns:
            Cart total.
        """
        return sum(vc.subtotal for vc in self._carts.values())

    def clear(self) -> None:
        """Clear all items from cart."""
        self._carts.clear()


class OrderProcessor:
    """Process checkout and split orders by vendor."""

    def __init__(self) -> None:
        """Initialize order processor."""
        self._orders: dict[str, Order] = {}

    def create_orders_from_cart(
        self,
        buyer_id: str,
        vendor_carts: list[VendorCart],
        shipping_address: str,
        billing_address: str,
        shipping_method: str,
    ) -> list[Order]:
        """Create separate orders for each vendor from cart.

        Args:
            buyer_id: Buyer identifier.
            vendor_carts: List of vendor carts from shopping cart.
            shipping_address: Shipping address.
            billing_address: Billing address.
            shipping_method: Shipping method.

        Returns:
            List of created orders.
        """
        orders: list[Order] = []

        for vendor_cart in vendor_carts:
            order = self._create_single_vendor_order(
                buyer_id=buyer_id,
                vendor_id=vendor_cart.vendor_id,
                items=vendor_cart.items,
                shipping_address=shipping_address,
                billing_address=billing_address,
                shipping_method=shipping_method,
            )
            orders.append(order)
            self._orders[order.id] = order

        return orders

    def _create_single_vendor_order(
        self,
        buyer_id: str,
        vendor_id: str,
        items: list[CartItem],
        shipping_address: str,
        billing_address: str,
        shipping_method: str,
    ) -> Order:
        """Create single vendor order.

        Args:
            buyer_id: Buyer identifier.
            vendor_id: Vendor identifier.
            items: Order items.
            shipping_address: Shipping address.
            billing_address: Billing address.
            shipping_method: Shipping method.

        Returns:
            Created order.
        """
        order_id = f"order_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        # Convert cart items to order items
        order_items = [
            {
                "listing_id": item.listing_id,
                "vendor_id": vendor_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "title": item.title,
                "status": "pending",
            }
            for item in items
        ]

        # Calculate totals
        subtotal = sum(item.total_price for item in items)
        shipping_cost = Decimal("10.00")  # Simplified
        tax_amount = subtotal * Decimal("0.08")  # 8% tax
        total = subtotal + shipping_cost + tax_amount

        order = Order(
            id=order_id,
            buyer_id=buyer_id,
            status=OrderStatus.PLACED,
            created_at=now,
            updated_at=now,
            items=order_items,
            shipping_address=shipping_address,
            billing_address=billing_address,
            shipping_method=shipping_method,
            subtotal=subtotal,
            shipping_cost=shipping_cost,
            tax_amount=tax_amount,
            total_amount=total,
            currency="USD",
        )

        return order

    def get_order(self, order_id: str) -> Order:
        """Get order by ID.

        Args:
            order_id: Order identifier.

        Returns:
            Order object.

        Raises:
            OrderNotFoundError: If order not found.
        """
        order = self._orders.get(order_id)
        if not order:
            raise OrderNotFoundError(order_id)
        return order

    def confirm_order(self, order_id: str) -> Order:
        """Confirm order (transition from PLACED to CONFIRMED).

        Args:
            order_id: Order identifier.

        Returns:
            Confirmed order.

        Raises:
            OrderNotFoundError: If order not found.
            InvalidOrderState: If cannot transition.
        """
        order = self.get_order(order_id)

        if order.status != OrderStatus.PLACED:
            raise InvalidOrderState(order_id, order.status.value)

        order.status = OrderStatus.CONFIRMED
        order.updated_at = datetime.utcnow()

        # Mark items as confirmed
        for item in order.items:
            item["status"] = "confirmed"

        return order

    def ship_order(self, order_id: str, tracking_number: str, vendor_id: str) -> Order:
        """Mark order as shipped.

        Args:
            order_id: Order identifier.
            tracking_number: Shipment tracking number.
            vendor_id: Vendor identifier.

        Returns:
            Shipped order.

        Raises:
            OrderNotFoundError: If order not found.
            InvalidOrderState: If cannot transition.
        """
        order = self.get_order(order_id)

        if order.status not in (OrderStatus.CONFIRMED, OrderStatus.SHIPPED):
            raise InvalidOrderState(order_id, order.status.value)

        order.tracking_numbers[vendor_id] = tracking_number

        # Mark vendor items as shipped
        for item in order.items:
            if item.get("vendor_id") == vendor_id:
                item["status"] = "shipped"

        # Check if all items shipped
        if all(item["status"] == "shipped" for item in order.items):
            order.status = OrderStatus.SHIPPED
        else:
            # Partial shipment - keep in confirmed for now
            pass

        order.updated_at = datetime.utcnow()
        return order

    def deliver_order(self, order_id: str) -> Order:
        """Mark order as delivered.

        Args:
            order_id: Order identifier.

        Returns:
            Delivered order.

        Raises:
            OrderNotFoundError: If order not found.
            InvalidOrderState: If cannot transition.
        """
        order = self.get_order(order_id)

        if order.status != OrderStatus.SHIPPED:
            raise InvalidOrderState(order_id, order.status.value)

        order.status = OrderStatus.DELIVERED
        order.updated_at = datetime.utcnow()

        for item in order.items:
            item["status"] = "delivered"

        return order

    def complete_order(self, order_id: str) -> Order:
        """Mark order as completed (after delivery confirmation window).

        Args:
            order_id: Order identifier.

        Returns:
            Completed order.

        Raises:
            OrderNotFoundError: If order not found.
            InvalidOrderState: If cannot transition.
        """
        order = self.get_order(order_id)

        if order.status != OrderStatus.DELIVERED:
            raise InvalidOrderState(order_id, order.status.value)

        order.status = OrderStatus.COMPLETED
        order.updated_at = datetime.utcnow()

        for item in order.items:
            item["status"] = "completed"

        return order

    def cancel_order(self, order_id: str, reason: str = "") -> Order:
        """Cancel order and issue refund.

        Args:
            order_id: Order identifier.
            reason: Cancellation reason.

        Returns:
            Cancelled order.

        Raises:
            OrderNotFoundError: If order not found.
            InvalidOrderState: If cannot cancel in current state.
        """
        order = self.get_order(order_id)

        # Can cancel if placed or confirmed
        if order.status not in (OrderStatus.PLACED, OrderStatus.CONFIRMED):
            raise InvalidOrderState(order_id, order.status.value)

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()
        order.notes = f"Cancelled: {reason}"

        for item in order.items:
            item["status"] = "cancelled"

        return order

    def partial_refund(self, order_id: str, item_listing_ids: list[str], reason: str = "") -> Order:
        """Issue partial refund for specific items.

        Args:
            order_id: Order identifier.
            item_listing_ids: Listing IDs to refund.
            reason: Refund reason.

        Returns:
            Updated order.

        Raises:
            OrderNotFoundError: If order not found.
        """
        order = self.get_order(order_id)

        refund_amount = Decimal("0")

        for item in order.items:
            if item["listing_id"] in item_listing_ids:
                item_total = Decimal(str(item["unit_price"])) * Decimal(str(item["quantity"]))
                refund_amount += item_total
                item["refunded"] = True

        # Update order totals
        order.total_amount -= refund_amount
        order.updated_at = datetime.utcnow()

        return order

    def list_buyer_orders(self, buyer_id: str) -> list[Order]:
        """List all orders for a buyer.

        Args:
            buyer_id: Buyer identifier.

        Returns:
            List of buyer's orders.
        """
        return [order for order in self._orders.values() if order.buyer_id == buyer_id]

    def list_vendor_orders(self, vendor_id: str) -> list[Order]:
        """List all orders containing vendor's items.

        Args:
            vendor_id: Vendor identifier.

        Returns:
            List of orders with vendor items.
        """
        vendor_orders = []
        for order in self._orders.values():
            if any(item.get("vendor_id") == vendor_id for item in order.items):
                vendor_orders.append(order)
        return vendor_orders
