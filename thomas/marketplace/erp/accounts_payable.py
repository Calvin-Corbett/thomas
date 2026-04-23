"""
Accounts Payable management.

Handles vendor management, purchase invoices, approval workflows,
payment processing, and vendor reconciliation.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.erp._exceptions import (
    InvoiceError,
    VendorError,
)
from thomas.marketplace.erp._types import (
    Invoice,
    InvoiceStatus,
    InvoiceType,
    LineItem,
    PaymentTerm,
    PurchaseOrder,
    Vendor,
)


class AccountsPayable:
    """
    Accounts Payable management.

    Manages vendor relationships, purchase invoices, payment workflows,
    and vendor reporting.
    """

    def __init__(self) -> None:
        """Initialize accounts payable."""
        self.vendors: dict[str, Vendor] = {}
        self.invoices: dict[str, Invoice] = {}
        self.purchase_orders: dict[str, PurchaseOrder] = {}
        self.invoice_approvals: dict[str, list[tuple[str, datetime]]] = {}
        self.vendor_statements: dict[str, list[tuple[date, Decimal]]] = {}
        self.payment_batches: list[dict[str, any]] = []
        self.vendor_1099_tracking: dict[str, Decimal] = {}
        self.three_way_matches: dict[str, dict[str, any]] = {}

    def create_vendor(
        self,
        vendor_id: str,
        name: str,
        contact_name: str = "",
        email: str = "",
        phone: str = "",
        tax_id: str = "",
        payment_terms: PaymentTerm | None = None,
    ) -> Vendor:
        """
        Create a new vendor.

        Args:
            vendor_id: Unique vendor identifier
            name: Vendor name
            contact_name: Primary contact name
            email: Contact email
            phone: Contact phone
            tax_id: Tax ID (for 1099 tracking)
            payment_terms: Default payment terms

        Returns:
            Created Vendor object

        Raises:
            VendorError: If vendor already exists
        """
        if vendor_id in self.vendors:
            raise VendorError(f"Vendor {vendor_id} already exists")

        vendor = Vendor(
            id=vendor_id,
            name=name,
            contact_name=contact_name,
            email=email,
            phone=phone,
            tax_id=tax_id,
            payment_terms=payment_terms,
        )
        self.vendors[vendor_id] = vendor
        return vendor

    def get_vendor(self, vendor_id: str) -> Vendor:
        """
        Retrieve a vendor by ID.

        Args:
            vendor_id: Vendor identifier

        Returns:
            Vendor object

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")
        return self.vendors[vendor_id]

    def record_purchase_invoice(
        self,
        invoice_id: str,
        vendor_id: str,
        invoice_date: date,
        due_date: date,
        lines: list[LineItem],
        po_id: str | None = None,
    ) -> Invoice:
        """
        Record a purchase invoice (accounts payable).

        Args:
            invoice_id: Unique invoice number
            vendor_id: Vendor identifier
            invoice_date: Invoice date
            due_date: Payment due date
            lines: Invoice line items
            po_id: Related purchase order (for matching)

        Returns:
            Created Invoice

        Raises:
            VendorError: If vendor not found
            InvoiceError: If invoice is invalid
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        if invoice_id in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} already exists")

        total = Decimal("0.00")
        for line in lines:
            total += line.get_amount()

        invoice = Invoice(
            id=invoice_id,
            invoice_type=InvoiceType.PURCHASE_INVOICE,
            invoice_date=invoice_date,
            due_date=due_date,
            vendor_id=vendor_id,
            lines=lines,
            total=total,
            status=InvoiceStatus.SUBMITTED,
        )
        self.invoices[invoice_id] = invoice

        if po_id:
            self._initiate_three_way_match(invoice_id, po_id)

        return invoice

    def approve_invoice(
        self,
        invoice_id: str,
        approver_id: str,
    ) -> None:
        """
        Approve a purchase invoice.

        Tracks approvals for audit trail.

        Args:
            invoice_id: Invoice identifier
            approver_id: ID of approving user

        Raises:
            InvoiceError: If invoice not found
        """
        if invoice_id not in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.status == InvoiceStatus.DRAFT:
            invoice.status = InvoiceStatus.SUBMITTED

        if invoice_id not in self.invoice_approvals:
            self.invoice_approvals[invoice_id] = []

        self.invoice_approvals[invoice_id].append((approver_id, datetime.now()))

        if invoice.status != InvoiceStatus.APPROVED:
            invoice.status = InvoiceStatus.APPROVED

    def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: date,
        reference: str = "",
    ) -> None:
        """
        Record a payment against an invoice.

        Args:
            invoice_id: Invoice identifier
            amount: Payment amount
            payment_date: Payment date
            reference: Check/transaction reference

        Raises:
            InvoiceError: If invoice not found or cannot be paid
        """
        if invoice_id not in self.invoices:
            raise InvoiceError(f"Invoice {invoice_id} not found")

        invoice = self.invoices[invoice_id]
        if invoice.status == InvoiceStatus.CANCELLED:
            raise InvoiceError(f"Cannot pay cancelled invoice {invoice_id}")

        invoice.paid_amount += amount

        if invoice.paid_amount >= invoice.total:
            invoice.status = InvoiceStatus.PAID
        elif invoice.paid_amount > Decimal("0.00"):
            invoice.status = InvoiceStatus.PARTIALLY_PAID

    def calculate_payment_due_date(
        self,
        invoice_date: date,
        payment_terms: PaymentTerm,
    ) -> date:
        """
        Calculate due date based on payment terms.

        Args:
            invoice_date: Invoice date
            payment_terms: Payment term definition

        Returns:
            Calculated due date
        """
        return invoice_date + timedelta(days=payment_terms.days)

    def calculate_early_payment_discount(
        self,
        invoice_amount: Decimal,
        payment_terms: PaymentTerm,
        payment_date: date,
        invoice_date: date,
    ) -> Decimal:
        """
        Calculate early payment discount if applicable.

        Args:
            invoice_amount: Total invoice amount
            payment_terms: Payment term definition
            payment_date: Actual payment date
            invoice_date: Invoice date

        Returns:
            Discount amount (0 if not eligible)
        """
        discount_date = invoice_date + timedelta(days=payment_terms.discount_days)

        if payment_date <= discount_date:
            discount_rate = payment_terms.discount_percent / Decimal("100.00")
            return invoice_amount * discount_rate

        return Decimal("0.00")

    def generate_payment_batch(
        self,
        payment_date: date,
        include_overdue: bool = True,
    ) -> dict[str, list[dict[str, any]]]:
        """
        Generate payment batch for due invoices.

        Groups invoices by vendor for batch processing.

        Args:
            payment_date: Target payment date
            include_overdue: Whether to include overdue invoices

        Returns:
            Map of vendor IDs to lists of payment items
        """
        payment_batch: dict[str, list[dict[str, any]]] = {}

        for invoice_id, invoice in self.invoices.items():
            if invoice.invoice_type != InvoiceType.PURCHASE_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue

            is_due = invoice.due_date <= payment_date
            is_overdue = invoice.due_date < payment_date

            if not is_due:
                continue
            if is_overdue and not include_overdue:
                continue

            vendor_id = invoice.vendor_id
            if vendor_id not in payment_batch:
                payment_batch[vendor_id] = []

            remaining = invoice.total - invoice.paid_amount
            discount = Decimal("0.00")

            if self.vendors[vendor_id].payment_terms:
                discount = self.calculate_early_payment_discount(
                    invoice.total,
                    self.vendors[vendor_id].payment_terms,
                    payment_date,
                    invoice.invoice_date,
                )

            payment_batch[vendor_id].append(
                {
                    "invoice_id": invoice_id,
                    "amount": remaining,
                    "discount": discount,
                    "net_payment": remaining - discount,
                    "is_overdue": is_overdue,
                }
            )

        batch_id = f"BATCH_{uuid4().hex[:8]}"
        self.payment_batches.append(
            {
                "id": batch_id,
                "created_date": datetime.now(),
                "payment_date": payment_date,
                "payments": payment_batch,
            }
        )

        return payment_batch

    def aging_report(self, as_of_date: date) -> dict[str, dict[str, Decimal]]:
        """
        Generate accounts payable aging report.

        Categorizes outstanding invoices by age: current, 30, 60, 90+ days.

        Args:
            as_of_date: Reporting date

        Returns:
            Map of vendor IDs to aging buckets
        """
        aging: dict[str, dict[str, Decimal]] = {}

        for invoice_id, invoice in self.invoices.items():
            if invoice.invoice_type != InvoiceType.PURCHASE_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue

            vendor_id = invoice.vendor_id
            if vendor_id not in aging:
                aging[vendor_id] = {
                    "current": Decimal("0.00"),
                    "30_days": Decimal("0.00"),
                    "60_days": Decimal("0.00"),
                    "90_plus_days": Decimal("0.00"),
                    "total": Decimal("0.00"),
                }

            outstanding = invoice.total - invoice.paid_amount
            days_overdue = (as_of_date - invoice.due_date).days

            if days_overdue <= 0:
                aging[vendor_id]["current"] += outstanding
            elif days_overdue <= 30:
                aging[vendor_id]["30_days"] += outstanding
            elif days_overdue <= 60:
                aging[vendor_id]["60_days"] += outstanding
            else:
                aging[vendor_id]["90_plus_days"] += outstanding

            aging[vendor_id]["total"] += outstanding

        return aging

    def track_1099_vendor(self, vendor_id: str, amount: Decimal) -> None:
        """
        Track 1099 payments (U.S. tax reporting).

        Args:
            vendor_id: Vendor identifier
            amount: Payment amount for tax tracking

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        if vendor_id not in self.vendor_1099_tracking:
            self.vendor_1099_tracking[vendor_id] = Decimal("0.00")

        self.vendor_1099_tracking[vendor_id] += amount

    def get_1099_amount(self, vendor_id: str) -> Decimal:
        """
        Get cumulative 1099 tracking amount for a vendor.

        Args:
            vendor_id: Vendor identifier

        Returns:
            Cumulative amount tracked for 1099 reporting

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        return self.vendor_1099_tracking.get(vendor_id, Decimal("0.00"))

    def reconcile_vendor_statement(
        self,
        vendor_id: str,
        statement_date: date,
        statement_balance: Decimal,
    ) -> bool:
        """
        Reconcile vendor statement with AP records.

        Args:
            vendor_id: Vendor identifier
            statement_date: Statement date
            statement_balance: Balance per vendor statement

        Returns:
            True if reconciliation matches, False otherwise

        Raises:
            VendorError: If vendor not found
        """
        if vendor_id not in self.vendors:
            raise VendorError(f"Vendor {vendor_id} not found")

        calculated_balance = Decimal("0.00")

        for invoice in self.invoices.values():
            if invoice.vendor_id != vendor_id:
                continue
            if invoice.invoice_type != InvoiceType.PURCHASE_INVOICE:
                continue
            if invoice.invoice_date > statement_date:
                continue
            if invoice.status == InvoiceStatus.CANCELLED:
                continue

            calculated_balance += invoice.total - invoice.paid_amount

        if vendor_id not in self.vendor_statements:
            self.vendor_statements[vendor_id] = []

        matches = calculated_balance == statement_balance
        self.vendor_statements[vendor_id].append((statement_date, calculated_balance))

        return matches

    def _initiate_three_way_match(self, invoice_id: str, po_id: str) -> None:
        """
        Initiate three-way matching (PO, receipt, invoice).

        Args:
            invoice_id: Invoice identifier
            po_id: Purchase order identifier
        """
        self.three_way_matches[invoice_id] = {
            "po_id": po_id,
            "invoice_id": invoice_id,
            "po_verified": False,
            "receipt_verified": False,
            "invoice_verified": True,
            "created_at": datetime.now(),
        }

    def complete_three_way_match(
        self,
        invoice_id: str,
        po_verified: bool = False,
        receipt_verified: bool = False,
    ) -> bool:
        """
        Complete three-way matching verification.

        Args:
            invoice_id: Invoice identifier
            po_verified: PO matches invoice quantity/price
            receipt_verified: Receipt matches PO

        Returns:
            True if all three are verified
        """
        if invoice_id not in self.three_way_matches:
            return False

        match = self.three_way_matches[invoice_id]
        match["po_verified"] = po_verified
        match["receipt_verified"] = receipt_verified

        return match["po_verified"] and match["receipt_verified"] and match["invoice_verified"]

    def get_outstanding_invoices(self, vendor_id: str | None = None) -> list[Invoice]:
        """
        Get list of outstanding (unpaid) invoices.

        Args:
            vendor_id: Filter by vendor (None for all)

        Returns:
            List of outstanding invoices
        """
        outstanding: list[Invoice] = []

        for invoice in self.invoices.values():
            if invoice.invoice_type != InvoiceType.PURCHASE_INVOICE:
                continue
            if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue
            if vendor_id and invoice.vendor_id != vendor_id:
                continue

            outstanding.append(invoice)

        return sorted(outstanding, key=lambda i: i.due_date)
