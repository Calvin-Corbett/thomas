"""
Data types and models for fintech operations.

Provides core financial data structures for orders, trading, portfolio management,
and risk metrics. All types use full type annotations and support serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    """Side of an order: BUY or SELL."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Type of order: MARKET, LIMIT, or STOP."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class TimeInForce(str, Enum):
    """Order time-in-force: GTC, IOC, FOK."""

    GTC = "GTC"  # Good-Till-Cancelled
    IOC = "IOC"  # Immediate-Or-Cancel
    FOK = "FOK"  # Fill-Or-Kill


class OrderStatus(str, Enum):
    """Status of an order in the system."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TransactionType(str, Enum):
    """Type of transaction for ledger entries."""

    TRADE = "TRADE"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


class Currency(str, Enum):
    """ISO 4217 currency codes."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CHF = "CHF"
    CAD = "CAD"
    AUD = "AUD"
    NZD = "NZD"
    CNY = "CNY"
    INR = "INR"


@dataclass
class Order:
    """
    Represents a single order in the market.

    Attributes:
        id: Unique order identifier
        symbol: Trading symbol (e.g., "AAPL", "BTC/USD")
        side: BUY or SELL
        order_type: MARKET, LIMIT, or STOP
        quantity: Amount to trade
        price: Price per unit (None for market orders)
        timestamp: Order creation time
        status: Current order status
        tif: Time-in-force (GTC, IOC, FOK)
        stop_price: Trigger price for STOP orders
        fill_price: Average fill price
        fill_quantity: Amount filled
        remaining_quantity: Amount still open
    """

    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    timestamp: datetime
    status: OrderStatus = OrderStatus.PENDING
    price: Decimal | None = None
    tif: TimeInForce = TimeInForce.GTC
    stop_price: Decimal | None = None
    fill_price: Decimal = Decimal("0")
    fill_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        """Validate order on creation."""
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT orders must have a price")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("STOP orders must have a stop_price")
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if self.price is not None and self.price <= 0:
            raise ValueError("Price must be positive")
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity

    def is_buy(self) -> bool:
        """Check if this is a buy order."""
        return self.side == OrderSide.BUY

    def is_sell(self) -> bool:
        """Check if this is a sell order."""
        return self.side == OrderSide.SELL

    def is_open(self) -> bool:
        """Check if order has remaining quantity."""
        return self.remaining_quantity > 0

    def get_notional_value(self) -> Decimal:
        """Calculate order notional value (quantity * price)."""
        if self.price is None:
            return Decimal("0")
        return self.quantity * self.price


@dataclass
class Trade:
    """
    Represents a single trade execution (match between buyer and seller).

    Attributes:
        id: Unique trade identifier
        buy_order_id: ID of the buying order
        sell_order_id: ID of the selling order
        symbol: Trading symbol
        price: Execution price
        quantity: Executed quantity
        timestamp: Trade execution time
        buyer_id: ID of buyer account
        seller_id: ID of seller account
    """

    id: str
    buy_order_id: str
    sell_order_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    buyer_id: str | None = None
    seller_id: str | None = None

    def __post_init__(self) -> None:
        """Validate trade on creation."""
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("Price and quantity must be positive")

    def get_notional_value(self) -> Decimal:
        """Calculate trade notional value."""
        return self.price * self.quantity


@dataclass
class Position:
    """
    Represents a position in a security.

    Attributes:
        symbol: Trading symbol
        quantity: Amount held
        avg_price: Average acquisition price
        current_price: Current market price
        realized_pnl: Realized profit/loss
        unrealized_pnl: Unrealized profit/loss
        last_updated: Timestamp of last update
    """

    symbol: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def get_market_value(self) -> Decimal:
        """Get current market value of position."""
        return self.quantity * self.current_price

    def get_cost_basis(self) -> Decimal:
        """Get original cost basis."""
        return self.quantity * self.avg_price

    def update_price(self, new_price: Decimal) -> None:
        """Update current price and recalculate unrealized P&L."""
        if new_price < 0:
            raise ValueError("Price cannot be negative")
        self.current_price = new_price
        self.unrealized_pnl = self.get_market_value() - self.get_cost_basis()
        self.last_updated = datetime.utcnow()

    def is_long(self) -> bool:
        """Check if position is long (positive quantity)."""
        return self.quantity > 0

    def is_short(self) -> bool:
        """Check if position is short (negative quantity)."""
        return self.quantity < 0


@dataclass
class Portfolio:
    """
    Represents a portfolio of positions.

    Attributes:
        account_id: Account identifier
        positions: Map of symbol to Position
        cash: Available cash balance
        currency: Base currency
        timestamp: Portfolio valuation time
    """

    account_id: str
    positions: dict[str, Position] = field(default_factory=dict)
    cash: Decimal = Decimal("0")
    currency: Currency = Currency.USD
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_total_market_value(self) -> Decimal:
        """Get total portfolio value (positions + cash)."""
        positions_value = sum(pos.get_market_value() for pos in self.positions.values())
        return positions_value + self.cash

    def get_total_cost_basis(self) -> Decimal:
        """Get total cost basis of all positions."""
        return sum(pos.get_cost_basis() for pos in self.positions.values())

    def get_total_realized_pnl(self) -> Decimal:
        """Get total realized P&L."""
        return sum(pos.realized_pnl for pos in self.positions.values())

    def get_total_unrealized_pnl(self) -> Decimal:
        """Get total unrealized P&L."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    def get_total_pnl(self) -> Decimal:
        """Get total P&L (realized + unrealized)."""
        return self.get_total_realized_pnl() + self.get_total_unrealized_pnl()

    def get_notional_exposure(self) -> Decimal:
        """Get total notional exposure (sum of absolute position values)."""
        return sum(abs(pos.get_market_value()) for pos in self.positions.values())

    def add_position(self, position: Position) -> None:
        """Add or update a position."""
        self.positions[position.symbol] = position

    def get_position(self, symbol: str) -> Position | None:
        """Retrieve a position by symbol."""
        return self.positions.get(symbol)


@dataclass
class RiskMetrics:
    """
    Represents risk metrics for a portfolio.

    Attributes:
        var_95: Value at Risk at 95% confidence
        var_99: Value at Risk at 99% confidence
        cvar_95: Conditional Value at Risk (Expected Shortfall)
        sharpe_ratio: Sharpe ratio
        sortino_ratio: Sortino ratio
        max_drawdown: Maximum drawdown
        volatility: Portfolio volatility
        beta: Portfolio beta
        timestamp: Calculation time
    """

    var_95: Decimal
    var_99: Decimal
    cvar_95: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    max_drawdown: Decimal
    volatility: Decimal
    beta: Decimal
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExchangeRate:
    """
    Represents a foreign exchange rate.

    Attributes:
        base: Base currency
        quote: Quote currency
        bid: Bid rate
        ask: Ask rate
        timestamp: Rate timestamp
    """

    base: Currency
    quote: Currency
    bid: Decimal
    ask: Decimal
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate rates on creation."""
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("Rates must be positive")
        if self.bid > self.ask:
            raise ValueError("Bid must be <= Ask")

    def get_mid_rate(self) -> Decimal:
        """Get mid-point rate."""
        return (self.bid + self.ask) / 2

    def get_spread(self) -> Decimal:
        """Get bid-ask spread in bps."""
        return (self.ask - self.bid) / self.mid_rate() * 10000


@dataclass
class AccountBalance:
    """
    Represents an account balance.

    Attributes:
        account_id: Account identifier
        currency: Currency of balance
        available: Available balance
        reserved: Reserved balance (in trades)
        timestamp: Balance timestamp
    """

    account_id: str
    currency: Currency
    available: Decimal
    reserved: Decimal = Decimal("0")
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_total(self) -> Decimal:
        """Get total balance (available + reserved)."""
        return self.available + self.reserved

    def can_withdraw(self, amount: Decimal) -> bool:
        """Check if amount can be withdrawn."""
        return amount <= self.available


@dataclass
class FeeSchedule:
    """
    Represents a fee schedule.

    Attributes:
        maker_rate: Fee rate for maker orders (basis points)
        taker_rate: Fee rate for taker orders (basis points)
        min_fee: Minimum fee amount
        flat_fee: Flat fee per transaction
        tiered_rates: List of (volume_threshold, fee_rate) tuples
    """

    maker_rate: Decimal
    taker_rate: Decimal
    min_fee: Decimal = Decimal("0")
    flat_fee: Decimal = Decimal("0")
    tiered_rates: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    def get_maker_fee(self, notional: Decimal) -> Decimal:
        """Calculate maker fee."""
        if self.tiered_rates:
            rate = self.taker_rate
            for threshold, tier_rate in sorted(self.tiered_rates):
                if notional >= threshold:
                    rate = tier_rate
            fee = notional * rate / 10000
        else:
            fee = notional * self.maker_rate / 10000
        return max(fee, self.min_fee) + self.flat_fee

    def get_taker_fee(self, notional: Decimal) -> Decimal:
        """Calculate taker fee."""
        if self.tiered_rates:
            rate = self.taker_rate
            for threshold, tier_rate in sorted(self.tiered_rates):
                if notional >= threshold:
                    rate = tier_rate
            fee = notional * rate / 10000
        else:
            fee = notional * self.taker_rate / 10000
        return max(fee, self.min_fee) + self.flat_fee


@dataclass
class OrderBook:
    """
    Represents an order book for a symbol.

    Attributes:
        symbol: Trading symbol
        bids: List of (price, quantity) tuples (sorted descending)
        asks: List of (price, quantity) tuples (sorted ascending)
        timestamp: Book timestamp
    """

    symbol: str
    bids: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    asks: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_best_bid(self) -> Decimal | None:
        """Get best bid price."""
        return self.bids[0][0] if self.bids else None

    def get_best_ask(self) -> Decimal | None:
        """Get best ask price."""
        return self.asks[0][0] if self.asks else None

    def get_spread(self) -> Decimal | None:
        """Get bid-ask spread."""
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid is None or ask is None:
            return None
        return ask - bid

    def get_depth_at_price(self, side: OrderSide, depth_levels: int = 5) -> list[tuple[Decimal, Decimal]]:
        """Get market depth at specified price levels."""
        levels = self.bids if side == OrderSide.BUY else self.asks
        return levels[:depth_levels]

    def get_total_bid_volume(self) -> Decimal:
        """Get total bid volume."""
        return sum(qty for _, qty in self.bids)

    def get_total_ask_volume(self) -> Decimal:
        """Get total ask volume."""
        return sum(qty for _, qty in self.asks)
