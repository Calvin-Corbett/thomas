"""
Thomas fintech module - Financial technology components for trading, settlement, and compliance.

This module provides comprehensive financial technology implementations including:
- Order matching and execution
- Risk management and measurement
- Portfolio management
- Financial instrument pricing
- Trade settlement
- Regulatory compliance
- Foreign exchange operations
- Payment processing
- Double-entry ledger accounting

Public API:
    Types: Order, Trade, Portfolio, Position, OrderBook, RiskMetrics, Currency
    Exceptions: FintechError, InsufficientFundsError, OrderError, RiskLimitError
    Order Matching: OrderMatcher, LimitOrderBook
    Risk: RiskCalculator, KellyCriterion, RiskLimitManager
    Portfolio: PortfolioManager, PerformanceCalculator
    Pricing: BlackScholesCalculator, BondCalculator, ImpliedVolatilityCalculator
    Settlement: SettlementCycle, DeliveryVsPaymentHandler, NetHandler
    Compliance: ComplianceMonitor, KycProfile, TradingLimits
    FX: FxRateManager, FxConverter, CrossRateCalculator, ForwardRateCalculator
    Payments: PaymentProcessor, RefundProcessor
    Ledger: GeneralLedger, FinancialStatementGenerator
"""

from ._exceptions import (
    ComplianceError,
    FintechError,
    InsufficientFundsError,
    OrderError,
    RiskLimitError,
    SettlementError,
)
from ._types import (
    AccountBalance,
    Currency,
    ExchangeRate,
    FeeSchedule,
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    RiskMetrics,
    TimeInForce,
    Trade,
    TransactionType,
)
from .compliance import (
    AmlRiskLevel,
    ComplianceMonitor,
    KycProfile,
    KycStatus,
    SuspiciousActivity,
    TradingLimits,
)
from .fx import (
    CrossRateCalculator,
    CurrencyBasketCalculator,
    CurrencyPair,
    ForwardRateCalculator,
    FxConverter,
    FxRateManager,
)
from .ledger import (
    Account,
    AccountReconciler,
    AccountType,
    FinancialStatementGenerator,
    GeneralLedger,
    JournalEntry,
)
from .order_matching import (
    LimitOrderBook,
    OrderMatcher,
)
from .payments import (
    FeeComponent,
    FeeType,
    PaymentMethod,
    PaymentProcessor,
    PaymentRefund,
    PaymentRequest,
    PaymentStatus,
    RefundProcessor,
)
from .portfolio import (
    PerformanceCalculator,
    PortfolioManager,
)
from .pricing import (
    BlackScholesCalculator,
    BondCalculator,
    Greeks,
    ImpliedVolatilityCalculator,
    OptionType,
    TimeValueCalculator,
)
from .risk import (
    KellyCriterion,
    RiskCalculator,
    RiskLimitManager,
)
from .settlement import (
    DeliveryVsPaymentHandler,
    NetHandler,
    NetPosition,
    NetType,
    SettlementCycle,
    SettlementInstruction,
    SettlementObligation,
    SettlementStatus,
)

__version__ = "1.0.0"
__author__ = "Thomas"
__license__ = "MIT"

__all__ = [
    # Exceptions
    "FintechError",
    "InsufficientFundsError",
    "OrderError",
    "RiskLimitError",
    "SettlementError",
    "ComplianceError",
    # Types
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "TimeInForce",
    "Trade",
    "Position",
    "Portfolio",
    "OrderBook",
    "RiskMetrics",
    "Currency",
    "ExchangeRate",
    "AccountBalance",
    "FeeSchedule",
    "TransactionType",
    # Order Matching
    "OrderMatcher",
    "LimitOrderBook",
    # Risk
    "RiskCalculator",
    "KellyCriterion",
    "RiskLimitManager",
    # Portfolio
    "PortfolioManager",
    "PerformanceCalculator",
    # Pricing
    "BlackScholesCalculator",
    "BondCalculator",
    "ImpliedVolatilityCalculator",
    "TimeValueCalculator",
    "Greeks",
    "OptionType",
    # Settlement
    "SettlementCycle",
    "SettlementInstruction",
    "SettlementObligation",
    "SettlementStatus",
    "NetHandler",
    "NetPosition",
    "NetType",
    "DeliveryVsPaymentHandler",
    # Compliance
    "ComplianceMonitor",
    "KycProfile",
    "KycStatus",
    "AmlRiskLevel",
    "SuspiciousActivity",
    "TradingLimits",
    # FX
    "FxRateManager",
    "FxConverter",
    "CrossRateCalculator",
    "ForwardRateCalculator",
    "CurrencyBasketCalculator",
    "CurrencyPair",
    # Payments
    "PaymentProcessor",
    "RefundProcessor",
    "PaymentRequest",
    "PaymentRefund",
    "PaymentStatus",
    "PaymentMethod",
    "FeeComponent",
    "FeeType",
    # Ledger
    "GeneralLedger",
    "FinancialStatementGenerator",
    "AccountReconciler",
    "Account",
    "AccountType",
    "JournalEntry",
]
