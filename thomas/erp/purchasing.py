"""
Purchasing management.

Handles purchase orders, requisitions, vendor selection,
and PO approval workflows.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from thomas.erp._exceptions import POError, VendorError
from thomas.erp._types import (
    LineItem,
    POStatus,
    PurchaseOrder,
    Vendor,
)


class PurchaseRequisition:
    """Purchase requisition (request to purchase)."""

    def __init__(
        self,
        requisition_id: str,
        requested_by: str,
        items: list[dict[str, any]],
        request_date: date,
        needed_by_date: date,
    ) -> None:
        """Initialize requisition."""
        self.requisition_id = requisition_id
        self.requested_by = requested_by
        self.items = items  # [{sku, quantity, estimated_cost}, ...]
        self.request_date = request_date
        self.needed_by_date = needed_by_date
        self.status = "PENDING"
        self.approved_by: str | None = None
        self.created_at = datetime.now()


class PurchasingManager:
    """
    Purchasing management with PO workflow and vendor management.
    """

    def __init__(self) -> None:
        """Initialize purchasing manager."""
        self.purchase_orders: dict[str, PurchaseOrder] = {}
        self.requisitions: dict[str, PurchaseRequisition] = {}
        self.vendors: dict[str, Vendor] = {}
        self.preferred_vendors: dict[str, str] = {}  # item_sku -> vendor_id
        self.po_approvals: dict[str, list[tuple[str, datetime]]] = {}
        self.goods_receipts: list[dict[str, any]] = []
        self.blanket_pos: dict[str, dict[str, any]] = {}
        self.vendor_performance: dict[str, dict[str, any]] = {}

    def create_purchase_requisition(
        self,
        requisition_id: str,
        requested_by: str,
        items: list[dict[str, any]],
        needed_by_date: date,
    ) -> PurchaseRequisition:
        """
        Create a purchase requisition.

        Args:
            requisition_id: Unique requisition ID
            requested_by: Requestor user ID
            items: List of {sku, quantity, estimated_cost}
            needed_by_date: Date items are needed

        Returns:
            Created PurchaseRequisition
        """
        requisition = PurchaseRequisition(
            requisition_id=requisition_id,
            requested_by=requested_by,
            items=items,
            request_date=date.today(),
            needed_by_date=needed_by_date,
        )
        self.requisitions[requisition_id] = requisition
        return requisition

    def convert_requisition_to_po(
        self,
        requisition_id: str,
        vendor_id: str,
        po_id: str,
    ) -> PurchaseOrder:
        """
        Convert an approved requisition to a purchase order.

        Args:
            requisition_id: Requisition ID
            vendor_id: Selected vendor
            po_id: New PO number

        Returns:
            Created PurchaseOrder

        Raises:
            POError: If requisition not found or invalid
            VendorError: If vendor not found
        """
        if requisition_id not in self.requisitions:
            raise POError(f"Requisition {requisition_id} not found")

        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        requisition = self.requisitions[requisition_id]

        lines: list[LineItem] = []
        total = Decimal("0.00")

        for item in requisition.items:
            line = LineItem(
                account_id="",
                description=f"SKU: {item['sku']}",
                quantity=item.get("quantity", Decimal("0.00")),
                unit_price=item.get("estimated_cost", Decimal("0.00")),
            )
            lines.append(line)
            total += item.get("quantity", Decimal("0.00")) * item.get("estimated_cost", Decimal("0.00"))

        po = PurchaseOrder(
            id=po_id,
            vendor_id=vendor_id,
            po_date=date.today(),
            expected_delivery_date=requisition.needed_by_date,
            lines=lines,
            total=total,
        )

        self.purchase_orders[po_id] = po
        requisition.status = "CONVERTED"

        return po

    def create_purchase_order(
        self,
        po_id: str,
        vendor_id: str,
        po_date: date,
        expected_delivery_date: date,
        lines: list[LineItem],
    ) -> PurchaseOrder:
        """
        Create a purchase order directly.

        Args:
            po_id: Unique PO number
            vendor_id: Vendor ID
            po_date: Order date
            expected_delivery_date: Expected delivery
            lines: Line items with quantities and prices

        Returns:
            Created PurchaseOrder

        Raises:
            POError: If PO already exists
            VendorError: If vendor not found
        """
        if po_id in self.purchase_orders:
            raise POError(f"PO {po_id} already exists")

        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        total = Decimal("0.00")
        for line in lines:
            total += line.get_amount()

        po = PurchaseOrder(
            id=po_id,
            vendor_id=vendor_id,
            po_date=po_date,
            expected_delivery_date=expected_delivery_date,
            lines=lines,
            total=total,
        )

        self.purchase_orders[po_id] = po
        self.po_approvals[po_id] = []
        self._initialize_vendor_performance(vendor_id)

        return po

    def approve_po(
        self,
        po_id: str,
        approver_id: str,
        approval_level: int = 1,
    ) -> None:
        """
        Approve a purchase order.

        Args:
            po_id: PO ID
            approver_id: Approver user ID
            approval_level: Approval level/tier

        Raises:
            POError: If PO not found
        """
        if po_id not in self.purchase_orders:
            raise POError(f"PO {po_id} not found")

        po = self.purchase_orders[po_id]

        if po_id not in self.po_approvals:
            self.po_approvals[po_id] = []

        self.po_approvals[po_id].append((approver_id, datetime.now()))

        if len(self.po_approvals[po_id]) >= approval_level:
            po.status = POStatus.APPROVED

    def record_goods_receipt(
        self,
        po_id: str,
        lines_received: dict[int, Decimal],
        receipt_date: date,
        receipt_reference: str = "",
    ) -> dict[str, any]:
        """
        Record goods receipt against a PO.

        Supports partial receipts.

        Args:
            po_id: PO ID
            lines_received: Map of line index to quantity received
            receipt_date: Receipt date
            receipt_reference: Receiving document reference

        Returns:
            Receipt details

        Raises:
            POError: If PO not found
        """
        if po_id not in self.purchase_orders:
            raise POError(f"PO {po_id} not found")

        po = self.purchase_orders[po_id]

        receipt_id = f"RCT_{uuid4().hex[:8]}"
        total_received = Decimal("0.00")

        for line_idx, qty_received in lines_received.items():
            if line_idx < len(po.lines):
                line = po.lines[line_idx]
                amount = (line.unit_price or Decimal("0.00")) * qty_received
                po.received_amount += amount
                total_received += qty_received

        if po.received_amount >= po.total:
            po.status = POStatus.RECEIVED
        elif po.received_amount > Decimal("0.00"):
            po.status = POStatus.PARTIALLY_RECEIVED

        receipt = {
            "receipt_id": receipt_id,
            "po_id": po_id,
            "receipt_date": receipt_date,
            "reference": receipt_reference,
            "lines_received": lines_received,
            "total_received": total_received,
            "created_at": datetime.now(),
        }

        self.goods_receipts.append(receipt)

        vendor_id = po.vendor_id
        if vendor_id in self.vendor_performance:
            if receipt_date <= po.expected_delivery_date:
                self.vendor_performance[vendor_id]["on_time_count"] += 1
            else:
                self.vendor_performance[vendor_id]["late_count"] += 1
            self.vendor_performance[vendor_id]["total_receipts"] += 1

        return receipt

    def create_blanket_po(
        self,
        blanket_po_id: str,
        vendor_id: str,
        items: dict[str, dict[str, Decimal]],
        expiration_date: date,
        total_budget: Decimal,
    ) -> dict[str, any]:
        """
        Create a blanket PO (framework agreement).

        Allows multiple deliveries against pre-negotiated terms.

        Args:
            blanket_po_id: Blanket PO identifier
            vendor_id: Vendor ID
            items: Map of SKU to {unit_price, min_quantity, max_quantity}
            expiration_date: Agreement expiration
            total_budget: Total budget allocation

        Returns:
            Blanket PO details

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        blanket_po = {
            "blanket_po_id": blanket_po_id,
            "vendor_id": vendor_id,
            "items": items,
            "expiration_date": expiration_date,
            "total_budget": total_budget,
            "amount_used": Decimal("0.00"),
            "releases": [],
            "created_at": datetime.now(),
        }

        self.blanket_pos[blanket_po_id] = blanket_po
        return blanket_po

    def release_from_blanket_po(
        self,
        blanket_po_id: str,
        release_items: dict[str, Decimal],
        delivery_date: date,
    ) -> str:
        """
        Create a release (delivery schedule) from blanket PO.

        Args:
            blanket_po_id: Blanket PO ID
            release_items: Map of SKU to quantity
            delivery_date: Requested delivery date

        Returns:
            Release ID

        Raises:
            POError: If blanket PO not found or insufficient budget
        """
        if blanket_po_id not in self.blanket_pos:
            raise POError(f"Blanket PO {blanket_po_id} not found")

        blanket = self.blanket_pos[blanket_po_id]

        release_amount = Decimal("0.00")
        for sku, qty in release_items.items():
            if sku in blanket["items"]:
                unit_price = blanket["items"][sku]["unit_price"]
                release_amount += qty * unit_price

        if blanket["amount_used"] + release_amount > blanket["total_budget"]:
            raise POError("Release would exceed blanket PO budget")

        release_id = f"REL_{uuid4().hex[:8]}"
        blanket["amount_used"] += release_amount
        blanket["releases"].append(
            {
                "release_id": release_id,
                "items": release_items,
                "delivery_date": delivery_date,
                "amount": release_amount,
                "created_at": datetime.now(),
            }
        )

        return release_id

    def set_preferred_vendor(self, sku: str, vendor_id: str) -> None:
        """
        Set preferred vendor for an item.

        Args:
            sku: Item SKU
            vendor_id: Vendor ID

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        self.preferred_vendors[sku] = vendor_id

    def get_preferred_vendor(self, sku: str) -> str | None:
        """
        Get preferred vendor for an item.

        Args:
            sku: Item SKU

        Returns:
            Vendor ID or None
        """
        return self.preferred_vendors.get(sku)

    def compare_vendor_prices(
        self,
        sku: str,
        vendors: list[str],
    ) -> dict[str, Decimal]:
        """
        Compare prices from multiple vendors for an item.

        Args:
            sku: Item SKU
            vendors: List of vendor IDs to compare

        Returns:
            Map of vendor ID to price
        """
        prices: dict[str, Decimal] = {}

        for vendor_id in vendors:
            if vendor_id in self.vendors:
                prices[vendor_id] = Decimal("0.00")

        return prices

    def get_vendor_performance(self, vendor_id: str) -> dict[str, any] | None:
        """
        Get vendor performance metrics.

        Args:
            vendor_id: Vendor ID

        Returns:
            Performance metrics (on-time delivery, etc.)

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        return self.vendor_performance.get(vendor_id)

    def _initialize_vendor_performance(self, vendor_id: str) -> None:
        """Initialize vendor performance tracking."""
        if vendor_id not in self.vendor_performance:
            self.vendor_performance[vendor_id] = {
                "total_pos": 0,
                "total_receipts": 0,
                "on_time_count": 0,
                "late_count": 0,
                "quality_issues": 0,
            }
        self.vendor_performance[vendor_id]["total_pos"] += 1

    def calculate_on_time_delivery_rate(self, vendor_id: str) -> Decimal:
        """
        Calculate on-time delivery percentage.

        Args:
            vendor_id: Vendor ID

        Returns:
            On-time delivery rate (0-100)

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        if vendor_id not in self.vendor_performance:
            return Decimal("0.00")

        perf = self.vendor_performance[vendor_id]
        total = perf["on_time_count"] + perf["late_count"]

        if total == 0:
            return Decimal("0.00")

        return (Decimal(perf["on_time_count"]) / Decimal(total)) * Decimal("100.00")

    def record_quality_issue(self, vendor_id: str) -> None:
        """
        Record a quality issue with vendor.

        Args:
            vendor_id: Vendor ID

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        if vendor_id in self.vendor_performance:
            self.vendor_performance[vendor_id]["quality_issues"] += 1
