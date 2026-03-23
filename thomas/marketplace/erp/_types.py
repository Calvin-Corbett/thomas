"""
Data types for the Thomas ERP system.

This module defines all core data structures used throughout the ERP,
including accounts, transactions, and business entities.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class AccountType(Enum):
    """Chart of accounts classification."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"
    COGS = "COGS"
    CONTRA_ASSET = "CONTRA_ASSET"


class Currency(Enum):
    """Supported currencies."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CAD = "CAD"


class InvoiceType(Enum):
    """Invoice classification."""

    SALES_INVOICE = "SALES_INVOICE"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    CREDIT_MEMO = "CREDIT_MEMO"
    DEBIT_MEMO = "DEBIT_MEMO"


class InvoiceStatus(Enum):
    """Invoice workflow status."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    OVERDUE = "OVERDUE"


class POStatus(Enum):
    """Purchase order workflow status."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SOStatus(Enum):
    """Sales order workflow status."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PRStatus(Enum):
    """Production order workflow status."""

    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class UnitOfMeasure(Enum):
    """Standard units of measure."""

    PIECE = "PIECE"
    BOX = "BOX"
    CASE = "CASE"
    CARTON = "CARTON"
    PALLET = "PALLET"
    UNIT = "UNIT"
    KG = "KG"
    LB = "LB"
    L = "L"
    GAL = "GAL"
    M = "M"
    FT = "FT"


@dataclass
class Account:
    """
    General ledger account with hierarchical structure.

    Attributes:
        id: Unique account identifier (e.g., "1000", "1010")
        name: Account name
        account_type: Classification (ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE, COGS)
        parent_id: Parent account for hierarchical reporting (None for root)
        balance: Current account balance
        currency: Account currency
        is_active: Whether account is in use
        description: Account description
        created_date: Account creation date
        last_modified: Last modification timestamp
    """

    id: str
    name: str
    account_type: AccountType
    parent_id: str | None = None
    balance: Decimal = Decimal("0.00")
    currency: Currency = Currency.USD
    is_active: bool = True
    description: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def is_debit_account(self) -> bool:
        """Return True if this is a debit-balance account."""
        return self.account_type in (
            AccountType.ASSET,
            AccountType.EXPENSE,
            AccountType.COGS,
            AccountType.CONTRA_LIABILITY,
        )


@dataclass
class LineItem:
    """
    Single line in a journal entry, purchase order, or sales order.

    Attributes:
        account_id: Account to post to
        debit: Debit amount (None if credit)
        credit: Credit amount (None if debit)
        description: Line description
        reference: External reference (PO/SO/Invoice number)
        quantity: Quantity (for physical items)
        unit_price: Price per unit
    """

    account_id: str
    debit: Decimal | None = None
    credit: Decimal | None = None
    description: str = ""
    reference: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None

    def get_amount(self) -> Decimal:
        """Get the absolute amount of this line."""
        if self.debit is not None:
            return self.debit
        return self.credit or Decimal("0.00")


@dataclass
class JournalEntry:
    """
    Double-entry accounting transaction.

    Attributes:
        id: Unique entry identifier
        entry_date: Transaction date
        description: Entry description
        lines: List of line items (must balance)
        posted: Whether entry is posted to ledger
        reference: External reference (invoice/PO/check number)
        memo: Additional notes
    """

    id: str
    entry_date: date
    description: str
    lines: list[LineItem]
    posted: bool = False
    reference: str = ""
    memo: str = ""

    def total_debits(self) -> Decimal:
        """Calculate total debits."""
        return sum(line.debit or Decimal("0.00") for line in self.lines)

    def total_credits(self) -> Decimal:
        """Calculate total credits."""
        return sum(line.credit or Decimal("0.00") for line in self.lines)

    def is_balanced(self) -> bool:
        """Check if debits equal credits."""
        return self.total_debits() == self.total_credits()


@dataclass
class Vendor:
    """
    Supplier entity for purchase transactions.

    Attributes:
        id: Unique vendor identifier
        name: Vendor name
        contact_name: Primary contact
        email: Contact email
        phone: Contact phone
        address: Street address
        city: City
        state: State/province
        zip_code: Postal code
        country: Country
        tax_id: Tax identification number
        payment_terms: Default payment terms
        is_active: Whether vendor is active
        created_date: Record creation date
    """

    id: str
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""
    tax_id: str = ""
    payment_terms: Optional["PaymentTerm"] = None
    is_active: bool = True
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class Customer:
    """
    Buyer entity for sales transactions.

    Attributes:
        id: Unique customer identifier
        name: Customer name
        contact_name: Primary contact
        email: Contact email
        phone: Contact phone
        address: Street address
        city: City
        state: State/province
        zip_code: Postal code
        country: Country
        tax_id: Tax identification number
        payment_terms: Default payment terms
        credit_limit: Maximum allowed outstanding balance
        is_active: Whether customer is active
        created_date: Record creation date
    """

    id: str
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = ""
    tax_id: str = ""
    payment_terms: Optional["PaymentTerm"] = None
    credit_limit: Decimal = Decimal("0.00")
    is_active: bool = True
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class PaymentTerm:
    """
    Payment terms definition.

    Attributes:
        id: Term identifier
        name: Display name (e.g., "Net 30")
        days: Number of days until due
        discount_percent: Early payment discount percentage
        discount_days: Days to qualify for discount
    """

    id: str
    name: str
    days: int
    discount_percent: Decimal = Decimal("0.00")
    discount_days: int = 0


@dataclass
class Invoice:
    """
    Sales or purchase invoice.

    Attributes:
        id: Unique invoice number
        invoice_type: SALES_INVOICE or PURCHASE_INVOICE
        invoice_date: Transaction date
        due_date: Payment due date
        customer_id: Customer ID (for sales invoices)
        vendor_id: Vendor ID (for purchase invoices)
        lines: Invoice line items
        status: Invoice workflow status
        total: Invoice total amount
        paid_amount: Amount paid to date
        currency: Invoice currency
        memo: Additional notes
        created_date: Record creation date
    """

    id: str
    invoice_type: InvoiceType
    invoice_date: date
    due_date: date
    lines: list[LineItem] = field(default_factory=list)
    customer_id: str | None = None
    vendor_id: str | None = None
    status: InvoiceStatus = InvoiceStatus.DRAFT
    total: Decimal = Decimal("0.00")
    paid_amount: Decimal = Decimal("0.00")
    currency: Currency = Currency.USD
    memo: str = ""
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class PurchaseOrder:
    """
    Purchase requisition and order document.

    Attributes:
        id: Unique PO number
        vendor_id: Vendor identifier
        po_date: Order date
        expected_delivery_date: Expected receipt date
        lines: Line items with quantities and prices
        status: PO workflow status
        total: Total PO amount
        received_amount: Amount received to date
        currency: PO currency
        created_date: Record creation date
    """

    id: str
    vendor_id: str
    po_date: date
    expected_delivery_date: date
    lines: list[LineItem] = field(default_factory=list)
    status: POStatus = POStatus.DRAFT
    total: Decimal = Decimal("0.00")
    received_amount: Decimal = Decimal("0.00")
    currency: Currency = Currency.USD
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class SalesOrder:
    """
    Customer order for products/services.

    Attributes:
        id: Unique SO number
        customer_id: Customer identifier
        order_date: Order date
        promised_date: Promised delivery date
        lines: Line items with quantities and prices
        status: SO workflow status
        total: Total SO amount
        shipped_amount: Amount shipped to date
        currency: SO currency
        created_date: Record creation date
    """

    id: str
    customer_id: str
    order_date: date
    promised_date: date
    lines: list[LineItem] = field(default_factory=list)
    status: SOStatus = SOStatus.DRAFT
    total: Decimal = Decimal("0.00")
    shipped_amount: Decimal = Decimal("0.00")
    currency: Currency = Currency.USD
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class InventoryItem:
    """
    Inventory master record.

    Attributes:
        sku: Stock keeping unit
        description: Item description
        uom: Unit of measure
        cost_method: Valuation method (FIFO, LIFO, Weighted Average)
        standard_cost: Standard unit cost
        quantity_on_hand: Current stock level
        quantity_reserved: Quantity reserved for orders
        quantity_available: Available for sale
        min_quantity: Minimum reorder point
        max_quantity: Maximum stock level
        reorder_quantity: Preferred order quantity
        locations: Stock by location/warehouse
        lot_tracking: Whether lot/batch numbers are required
        serial_tracking: Whether serial numbers are required
        is_active: Whether item is in use
        created_date: Record creation date
    """

    sku: str
    description: str
    uom: UnitOfMeasure
    cost_method: str  # FIFO, LIFO, WEIGHTED_AVERAGE
    standard_cost: Decimal = Decimal("0.00")
    quantity_on_hand: Decimal = Decimal("0.00")
    quantity_reserved: Decimal = Decimal("0.00")
    quantity_available: Decimal = Decimal("0.00")
    min_quantity: Decimal = Decimal("0.00")
    max_quantity: Decimal = Decimal("0.00")
    reorder_quantity: Decimal = Decimal("0.00")
    locations: dict[str, Decimal] = field(default_factory=dict)
    lot_tracking: bool = False
    serial_tracking: bool = False
    is_active: bool = True
    created_date: datetime = field(default_factory=datetime.now)


@dataclass
class BOMLine:
    """Single line in a bill of materials."""

    sku: str
    quantity: Decimal
    unit_cost: Decimal
    scrap_percent: Decimal = Decimal("0.00")


@dataclass
class BOM:
    """
    Bill of materials (recipe for manufactured product).

    Attributes:
        id: BOM identifier
        finished_sku: SKU of finished product
        lines: Component lines
        effective_date: When BOM becomes active
        revision: BOM version number
        is_active: Whether BOM is current
    """

    id: str
    finished_sku: str
    lines: list[BOMLine] = field(default_factory=list)
    effective_date: date = field(default_factory=date.today)
    revision: str = "1.0"
    is_active: bool = True


@dataclass
class ProductionOrder:
    """
    Manufacturing work order.

    Attributes:
        id: Production order number
        bom_id: Bill of materials reference
        finished_sku: Product being manufactured
        quantity_ordered: Quantity to produce
        quantity_completed: Quantity completed
        start_date: Scheduled start date
        due_date: Completion target date
        status: Production status
        planned_materials: Exploded material requirements
        created_date: Record creation date
    """

    id: str
    bom_id: str
    finished_sku: str
    quantity_ordered: Decimal
    quantity_completed: Decimal = Decimal("0.00")
    start_date: date = field(default_factory=date.today)
    due_date: date | None = None
    status: PRStatus = PRStatus.DRAFT
    planned_materials: dict[str, Decimal] = field(default_factory=dict)
    created_date: datetime = field(default_factory=datetime.now)
