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

from thomas.erp._exceptions import (
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
from thomas.erp._types import (
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
from thomas.erp.accounts_payable import AccountsPayable
from thomas.erp.accounts_receivable import AccountsReceivable
from thomas.erp.financial_reports import FinancialReporter
from thomas.erp.general_ledger import GeneralLedger
from thomas.erp.inventory import InventoryManager
from thomas.erp.manufacturing import ManufacturingManager
from thomas.erp.purchasing import PurchasingManager
from thomas.erp.sales import SalesManager
from thomas.erp.tax import TaxManager

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
