"""
Sales management.

Handles sales orders, quotes, order fulfillment,
and sales analytics.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from thomas.erp._exceptions import SOError
from thomas.erp._types import (
    LineItem,
    SalesOrder,
    SOStatus,
)


class Quote:
    """Sales quote/estimate."""

    def __init__(
        self,
        quote_id: str,
        customer_id: str,
        quote_date: date,
        valid_until: date,
        lines: list[LineItem],
    ) -> None:
        """Initialize quote."""
        self.quote_id = quote_id
        self.customer_id = customer_id
        self.quote_date = quote_date
        self.valid_until = valid_until
        self.lines = lines
        self.total = sum(line.get_amount() for line in lines)
        self.status = "DRAFT"
        self.converted_to_so: str | None = None
        self.created_at = datetime.now()


class SalesManager:
    """
    Sales management with order processing and fulfillment.
    """

    def __init__(self) -> None:
        """Initialize sales manager."""
        self.quotes: dict[str, Quote] = {}
        self.sales_orders: dict[str, SalesOrder] = {}
        self.shipments: list[dict[str, any]] = []
        self.price_lists: dict[str, dict[str, Decimal]] = {}  # list_id -> {sku: price}
        self.customer_pricing: dict[str, dict[str, Decimal]] = {}  # customer_id -> {sku: price}
        self.back_orders: list[dict[str, any]] = []
        self.sales_commission: dict[str, dict[str, Decimal]] = {}  # rep_id -> {metric: value}
        self.sales_analytics: dict[str, dict[str, any]] = {}

    def create_quote(
        self,
        quote_id: str,
        customer_id: str,
        valid_until: date,
        lines: list[LineItem],
    ) -> Quote:
        """
        Create a sales quote.

        Args:
            quote_id: Unique quote number
            customer_id: Customer ID
            valid_until: Quote expiration date
            lines: Line items with descriptions and prices

        Returns:
            Created Quote

        Raises:
            CustomerError: If customer not found
        """
        quote = Quote(
            quote_id=quote_id,
            customer_id=customer_id,
            quote_date=date.today(),
            valid_until=valid_until,
            lines=lines,
        )
        self.quotes[quote_id] = quote
        return quote

    def convert_quote_to_order(
        self,
        quote_id: str,
        so_id: str,
        promised_date: date,
    ) -> SalesOrder:
        """
        Convert an accepted quote to a sales order.

        Args:
            quote_id: Quote ID
            so_id: New sales order number
            promised_date: Promised delivery date

        Returns:
            Created SalesOrder

        Raises:
            SOError: If quote not found
        """
        if quote_id not in self.quotes:
            raise SOError(f"Quote {quote_id} not found")

        quote = self.quotes[quote_id]

        so = SalesOrder(
            id=so_id,
            customer_id=quote.customer_id,
            order_date=date.today(),
            promised_date=promised_date,
            lines=quote.lines,
            total=quote.total,
        )

        self.sales_orders[so_id] = so
        quote.converted_to_so = so_id
        quote.status = "CONVERTED"

        return so

    def create_sales_order(
        self,
        so_id: str,
        customer_id: str,
        promised_date: date,
        lines: list[LineItem],
    ) -> SalesOrder:
        """
        Create a sales order directly.

        Args:
            so_id: Unique SO number
            customer_id: Customer ID
            promised_date: Promised delivery date
            lines: Line items with quantities and prices

        Returns:
            Created SalesOrder

        Raises:
            SOError: If SO already exists
        """
        if so_id in self.sales_orders:
            raise SOError(f"Sales order {so_id} already exists")

        total = Decimal("0.00")
        for line in lines:
            total += line.get_amount()

        so = SalesOrder(
            id=so_id,
            customer_id=customer_id,
            order_date=date.today(),
            promised_date=promised_date,
            lines=lines,
            total=total,
        )

        self.sales_orders[so_id] = so
        return so

    def fulfill_order(
        self,
        so_id: str,
        lines_shipped: dict[int, Decimal],
        shipment_date: date,
        shipment_reference: str = "",
        partial: bool = False,
    ) -> dict[str, any]:
        """
        Record fulfillment/shipment of a sales order.

        Supports partial shipments.

        Args:
            so_id: Sales order ID
            lines_shipped: Map of line index to quantity shipped
            shipment_date: Shipment date
            shipment_reference: Tracking number, etc.
            partial: Whether this is a partial shipment

        Returns:
            Shipment details

        Raises:
            SOError: If SO not found
        """
        if so_id not in self.sales_orders:
            raise SOError(f"Sales order {so_id} not found")

        so = self.sales_orders[so_id]
        shipment_id = f"SHP_{uuid4().hex[:8]}"
        total_shipped = Decimal("0.00")

        for line_idx, qty_shipped in lines_shipped.items():
            if line_idx < len(so.lines):
                line = so.lines[line_idx]
                amount = (line.unit_price or Decimal("0.00")) * qty_shipped
                so.shipped_amount += amount
                total_shipped += qty_shipped

        if not partial:
            if so.shipped_amount >= so.total:
                so.status = SOStatus.SHIPPED
            elif so.shipped_amount > Decimal("0.00"):
                so.status = SOStatus.PARTIALLY_SHIPPED
        else:
            so.status = SOStatus.PARTIALLY_SHIPPED

        shipment = {
            "shipment_id": shipment_id,
            "so_id": so_id,
            "shipment_date": shipment_date,
            "reference": shipment_reference,
            "lines_shipped": lines_shipped,
            "total_shipped": total_shipped,
            "partial": partial,
            "created_at": datetime.now(),
        }

        self.shipments.append(shipment)
        return shipment

    def create_back_order(
        self,
        so_id: str,
        lines_backordered: dict[int, Decimal],
        expected_availability: date,
    ) -> dict[str, any]:
        """
        Create a back order for items not currently in stock.

        Args:
            so_id: Sales order ID
            lines_backordered: Map of line index to quantity backordered
            expected_availability: Expected availability date

        Returns:
            Back order details

        Raises:
            SOError: If SO not found
        """
        if so_id not in self.sales_orders:
            raise SOError(f"Sales order {so_id} not found")

        back_order_id = f"BO_{uuid4().hex[:8]}"

        back_order = {
            "back_order_id": back_order_id,
            "so_id": so_id,
            "lines": lines_backordered,
            "expected_availability": expected_availability,
            "status": "OPEN",
            "created_at": datetime.now(),
        }

        self.back_orders.append(back_order)
        return back_order

    def create_price_list(
        self,
        price_list_id: str,
        name: str,
        prices: dict[str, Decimal],
        effective_from: date,
        effective_to: date | None = None,
    ) -> dict[str, any]:
        """
        Create a price list for standard pricing.

        Args:
            price_list_id: Price list identifier
            name: Display name
            prices: Map of SKU to price
            effective_from: Effective date
            effective_to: End date (None for ongoing)

        Returns:
            Price list details
        """
        price_list = {
            "price_list_id": price_list_id,
            "name": name,
            "prices": prices,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "created_at": datetime.now(),
        }
        self.price_lists[price_list_id] = prices
        return price_list

    def set_customer_pricing(
        self,
        customer_id: str,
        prices: dict[str, Decimal],
    ) -> None:
        """
        Set customer-specific pricing.

        Args:
            customer_id: Customer ID
            prices: Map of SKU to price
        """
        self.customer_pricing[customer_id] = prices

    def get_price(self, customer_id: str, sku: str) -> Decimal:
        """
        Get price for customer/item combination.

        Uses customer-specific pricing if available, otherwise list price.

        Args:
            customer_id: Customer ID
            sku: Item SKU

        Returns:
            Unit price
        """
        if customer_id in self.customer_pricing:
            return self.customer_pricing[customer_id].get(sku, Decimal("0.00"))

        for prices in self.price_lists.values():
            if sku in prices:
                return prices[sku]

        return Decimal("0.00")

    def calculate_commission(
        self,
        sales_rep_id: str,
        sales_amount: Decimal,
        commission_rate: Decimal,
    ) -> Decimal:
        """
        Calculate sales commission.

        Args:
            sales_rep_id: Sales representative ID
            sales_amount: Total sales amount
            commission_rate: Commission percentage (0-100)

        Returns:
            Commission amount
        """
        commission = sales_amount * (commission_rate / Decimal("100.00"))

        if sales_rep_id not in self.sales_commission:
            self.sales_commission[sales_rep_id] = {}

        if "total_commission" not in self.sales_commission[sales_rep_id]:
            self.sales_commission[sales_rep_id]["total_commission"] = Decimal("0.00")
            self.sales_commission[sales_rep_id]["total_sales"] = Decimal("0.00")

        self.sales_commission[sales_rep_id]["total_commission"] += commission
        self.sales_commission[sales_rep_id]["total_sales"] += sales_amount

        return commission

    def get_sales_by_customer(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Decimal]:
        """
        Get total sales by customer.

        Args:
            start_date: Filter start date
            end_date: Filter end date

        Returns:
            Map of customer ID to total sales
        """
        by_customer: dict[str, Decimal] = {}

        for so in self.sales_orders.values():
            if start_date and so.order_date < start_date:
                continue
            if end_date and so.order_date > end_date:
                continue

            if so.customer_id not in by_customer:
                by_customer[so.customer_id] = Decimal("0.00")
            by_customer[so.customer_id] += so.total

        return by_customer

    def get_sales_by_product(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, dict[str, Decimal]]:
        """
        Get sales by product (SKU).

        Args:
            start_date: Filter start date
            end_date: Filter end date

        Returns:
            Map of SKU to {quantity, amount}
        """
        by_product: dict[str, dict[str, Decimal]] = {}

        for so in self.sales_orders.values():
            if start_date and so.order_date < start_date:
                continue
            if end_date and so.order_date > end_date:
                continue

            for line in so.lines:
                sku = line.description.split("SKU: ")[-1] if "SKU: " in line.description else ""
                if not sku:
                    continue

                if sku not in by_product:
                    by_product[sku] = {
                        "quantity": Decimal("0.00"),
                        "amount": Decimal("0.00"),
                    }

                qty = line.quantity or Decimal("0.00")
                amount = line.get_amount()

                by_product[sku]["quantity"] += qty
                by_product[sku]["amount"] += amount

        return by_product

    def get_sales_by_rep(
        self,
        rep_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Decimal]:
        """
        Get sales metrics for a sales representative.

        Args:
            rep_id: Sales rep ID
            start_date: Filter start date
            end_date: Filter end date

        Returns:
            Dictionary with sales metrics
        """
        if rep_id not in self.sales_commission:
            return {
                "total_sales": Decimal("0.00"),
                "total_commission": Decimal("0.00"),
            }

        return self.sales_commission[rep_id]

    def get_all_sales_analytics(self) -> dict[str, any]:
        """
        Get comprehensive sales analytics.

        Returns:
            Sales metrics and trends
        """
        return {
            "total_sales": sum(so.total for so in self.sales_orders.values()),
            "by_customer": self.get_sales_by_customer(),
            "by_product": self.get_sales_by_product(),
            "pending_orders": [
                so.id
                for so in self.sales_orders.values()
                if so.status not in (SOStatus.SHIPPED, SOStatus.DELIVERED, SOStatus.CLOSED)
            ],
            "back_orders": len(self.back_orders),
        }
