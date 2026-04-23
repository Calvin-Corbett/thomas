"""
Thomas ERP Module

A comprehensive enterprise resource planning system with support for:
- General ledger and financial accounting
- Accounts payable and receivable
- Inventory management
- Purchasing and sales
- Manufacturing and production planning
- Financial reporting and analysis
- Tax management
"""

from thomas.marketplace.erp._exceptions import (
    CustomerError,
    ERPException,
    InsufficientInventoryError,
    InvalidAccountError,
    InvoiceError,
    JournalEntryError,
    ManufacturingError,
    POError,
    SOError,
    TaxError,
    VendorError,
)
from thomas.marketplace.erp._types import (
    BOM,
    Account,
    AccountType,
    BOMLine,
    Currency,
    Customer,
    InventoryItem,
    Invoice,
    InvoiceStatus,
    InvoiceType,
    JournalEntry,
    LineItem,
    PaymentTerm,
    POStatus,
    ProductionOrder,
    PRStatus,
    PurchaseOrder,
    SalesOrder,
    SOStatus,
    UnitOfMeasure,
    Vendor,
)
from thomas.marketplace.erp.accounts_payable import AccountsPayable
from thomas.marketplace.erp.accounts_receivable import AccountsReceivable
from thomas.marketplace.erp.financial_reports import FinancialReporter
from thomas.marketplace.erp.general_ledger import GeneralLedger
from thomas.marketplace.erp.inventory import InventoryManager
from thomas.marketplace.erp.manufacturing import ManufacturingManager
from thomas.marketplace.erp.purchasing import PurchasingManager
from thomas.marketplace.erp.sales import SalesManager
from thomas.marketplace.erp.tax import TaxManager

__all__ = [
    # Types
    "Account",
    "AccountType",
    "JournalEntry",
    "LineItem",
    "Vendor",
    "Customer",
    "Invoice",
    "InvoiceType",
    "InvoiceStatus",
    "PurchaseOrder",
    "POStatus",
    "SalesOrder",
    "SOStatus",
    "InventoryItem",
    "UnitOfMeasure",
    "BOM",
    "BOMLine",
    "ProductionOrder",
    "PRStatus",
    "PaymentTerm",
    "Currency",
    # Exceptions
    "ERPException",
    "InvalidAccountError",
    "JournalEntryError",
    "InsufficientInventoryError",
    "VendorError",
    "CustomerError",
    "InvoiceError",
    "POError",
    "SOError",
    "ManufacturingError",
    "TaxError",
    # Managers
    "GeneralLedger",
    "AccountsPayable",
    "AccountsReceivable",
    "InventoryManager",
    "PurchasingManager",
    "SalesManager",
    "ManufacturingManager",
    "FinancialReporter",
    "TaxManager",
]

__version__ = "1.0.0"
