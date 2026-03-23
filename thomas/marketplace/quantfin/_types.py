"""Core data types and classes for quantitative finance.

Provides fundamental types for assets, portfolios, positions, trades,
orders, quotes, time series data, and derivatives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np


class OrderSide(Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order type enumeration."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OptionType(Enum):
    """Option type enumeration."""

    CALL = "CALL"
    PUT = "PUT"


@dataclass
class Asset:
    """Represents a financial asset.

    Attributes:
        symbol: Ticker symbol (e.g., 'AAPL')
        name: Full asset name
        asset_type: Type of asset (e.g., 'EQUITY', 'OPTION', 'BOND')
        currency: Trading currency (default: 'USD')
        exchange: Trading exchange
        multiplier: Contract multiplier (default: 1.0)
    """

    symbol: str
    name: str
    asset_type: str
    currency: str = "USD"
    exchange: str = ""
    multiplier: float = 1.0

    def __hash__(self) -> int:
        return hash(self.symbol)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Asset):
            return False
        return self.symbol == other.symbol


@dataclass
class Quote:
    """Market quote for an asset.

    Attributes:
        asset: Asset being quoted
        bid: Bid price
        ask: Ask price
        last: Last traded price
        timestamp: Quote timestamp
        bid_size: Bid size (volume available)
        ask_size: Ask size (volume available)
    """

    asset: Asset
    bid: float
    ask: float
    last: float
    timestamp: datetime
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float:
        """Calculate mid-price."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid


@dataclass
class OHLCV:
    """Open-High-Low-Close-Volume bar.

    Attributes:
        timestamp: Bar timestamp
        open: Opening price
        high: Highest price
        low: Lowest price
        close: Closing price
        volume: Trading volume
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def typical_price(self) -> float:
        """Calculate typical price (H+L+C)/3."""
        return (self.high + self.low + self.close) / 3.0

    @property
    def hl_ratio(self) -> float:
        """Calculate high-low ratio."""
        if self.low == 0:
            return 0.0
        return self.high / self.low


@dataclass
class TimeSeries:
    """Financial time series data.

    Attributes:
        timestamps: Array of timestamps
        values: Array of values
        name: Series name
        metadata: Additional metadata
    """

    timestamps: np.ndarray
    values: np.ndarray
    name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, idx: int) -> float:
        return self.values[idx]

    @property
    def returns(self) -> np.ndarray:
        """Calculate log returns."""
        return np.diff(np.log(self.values))

    @property
    def mean(self) -> float:
        """Calculate mean of values."""
        return float(np.mean(self.values))

    @property
    def std(self) -> float:
        """Calculate standard deviation."""
        return float(np.std(self.values))


@dataclass
class Position:
    """Trading position in an asset.

    Attributes:
        asset: Underlying asset
        quantity: Number of units held (positive=long, negative=short)
        entry_price: Average entry price
        entry_timestamp: Entry time
        metadata: Additional position metadata
    """

    asset: Asset
    quantity: float
    entry_price: float
    entry_timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        """Check if position is flat."""
        return self.quantity == 0

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL.

        Args:
            current_price: Current market price

        Returns:
            Unrealized profit/loss
        """
        return self.quantity * (current_price - self.entry_price)


@dataclass
class Trade:
    """Executed trade record.

    Attributes:
        asset: Asset traded
        side: Buy or Sell
        quantity: Number of units
        price: Execution price
        timestamp: Execution time
        commission: Trading commission
        slippage: Price slippage
    """

    asset: Asset
    side: OrderSide
    quantity: float
    price: float
    timestamp: datetime
    commission: float = 0.0
    slippage: float = 0.0

    @property
    def gross_value(self) -> float:
        """Calculate gross trade value."""
        return self.quantity * self.price

    @property
    def net_value(self) -> float:
        """Calculate net trade value after commission."""
        return self.gross_value - self.commission


@dataclass
class Order:
    """Trading order.

    Attributes:
        order_id: Unique order ID
        asset: Asset to trade
        side: Buy or Sell
        order_type: Order type (Market, Limit, etc.)
        quantity: Order quantity
        price: Limit price (if applicable)
        status: Current status
        created_at: Creation timestamp
        filled_quantity: Quantity filled
        avg_fill_price: Average fill price
        metadata: Additional metadata
    """

    order_id: str
    asset: Asset
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime | None = None
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == OrderStatus.FILLED

    @property
    def remaining_quantity(self) -> float:
        """Get remaining quantity to fill."""
        return self.quantity - self.filled_quantity

    def fill(self, quantity: float, price: float) -> None:
        """Record a partial or full fill.

        Args:
            quantity: Quantity filled in this execution
            price: Fill price
        """
        self.filled_quantity += quantity
        if self.avg_fill_price == 0:
            self.avg_fill_price = price
        else:
            self.avg_fill_price = (
                (self.avg_fill_price * (self.filled_quantity - quantity)) + (price * quantity)
            ) / self.filled_quantity

        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIALLY_FILLED


@dataclass
class PriceLevel:
    """Price level in order book.

    Attributes:
        price: Price level
        orders: FIFO queue of orders at this price
    """

    price: float
    orders: list[Order] = field(default_factory=list)

    @property
    def total_quantity(self) -> float:
        """Get total quantity at this price level."""
        return sum(o.remaining_quantity for o in self.orders)


@dataclass
class OrderBook:
    """Limit order book for an asset.

    Attributes:
        asset: Asset for this order book
        bid_levels: Buy order price levels (sorted descending)
        ask_levels: Sell order price levels (sorted ascending)
        timestamp: Book timestamp
    """

    asset: Asset
    bid_levels: dict[float, PriceLevel] = field(default_factory=dict)
    ask_levels: dict[float, PriceLevel] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def best_bid(self) -> float | None:
        """Get best bid price."""
        if not self.bid_levels:
            return None
        return max(self.bid_levels.keys())

    @property
    def best_ask(self) -> float | None:
        """Get best ask price."""
        if not self.ask_levels:
            return None
        return min(self.ask_levels.keys())

    @property
    def bid_ask_spread(self) -> float | None:
        """Calculate bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def mid_price(self) -> float | None:
        """Calculate mid-price."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    def get_depth(self, num_levels: int = 10) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Get market depth.

        Args:
            num_levels: Number of levels to return

        Returns:
            Tuple of (bids, asks) with (price, quantity) tuples
        """
        bids = sorted(self.bid_levels.keys(), reverse=True)[:num_levels]
        asks = sorted(self.ask_levels.keys())[:num_levels]

        bid_depths = [(p, self.bid_levels[p].total_quantity) for p in bids]
        ask_depths = [(p, self.ask_levels[p].total_quantity) for p in asks]

        return bid_depths, ask_depths


@dataclass
class Greeks:
    """Option Greeks (sensitivity measures).

    Attributes:
        delta: Price sensitivity (∂V/∂S)
        gamma: Delta sensitivity (∂Δ/∂S)
        theta: Time decay (∂V/∂t)
        vega: Volatility sensitivity (∂V/∂σ)
        rho: Rate sensitivity (∂V/∂r)
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass
class OptionContract:
    """Option contract specification.

    Attributes:
        symbol: Underlying symbol
        option_type: Call or Put
        strike: Strike price
        expiration: Expiration date
        underlying_price: Current underlying price
        volatility: Implied volatility
        risk_free_rate: Risk-free rate
        dividend_yield: Dividend yield
    """

    symbol: str
    option_type: OptionType
    strike: float
    expiration: datetime
    underlying_price: float
    volatility: float
    risk_free_rate: float = 0.05
    dividend_yield: float = 0.0


@dataclass
class Portfolio:
    """Investment portfolio.

    Attributes:
        name: Portfolio name
        positions: Dictionary of positions keyed by asset symbol
        cash: Available cash
        benchmark_symbol: Benchmark asset symbol for tracking
        metadata: Additional metadata
    """

    name: str
    positions: dict[str, Position] = field(default_factory=dict)
    cash: float = 0.0
    benchmark_symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_position(self, position: Position) -> None:
        """Add or update position.

        Args:
            position: Position to add
        """
        self.positions[position.asset.symbol] = position

    def get_position(self, symbol: str) -> Position | None:
        """Get position by symbol.

        Args:
            symbol: Asset symbol

        Returns:
            Position if exists, None otherwise
        """
        return self.positions.get(symbol)

    def gross_value(self, price_dict: dict[str, float]) -> float:
        """Calculate gross portfolio value.

        Args:
            price_dict: Dictionary of symbol -> price

        Returns:
            Total gross value of all positions
        """
        total = 0.0
        for symbol, position in self.positions.items():
            if symbol in price_dict:
                total += position.quantity * price_dict[symbol]
        return total

    def net_value(self, price_dict: dict[str, float]) -> float:
        """Calculate net portfolio value.

        Args:
            price_dict: Dictionary of symbol -> price

        Returns:
            Gross value plus cash
        """
        return self.gross_value(price_dict) + self.cash


@dataclass
class Signal:
    """Trading signal.

    Attributes:
        timestamp: Signal generation time
        asset: Asset the signal is for
        signal_type: Type of signal ('BUY', 'SELL', 'HOLD')
        strength: Signal strength (0.0 to 1.0)
        metadata: Additional signal metadata
    """

    timestamp: datetime
    asset: Asset
    signal_type: str
    strength: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Indicator:
    """Technical indicator value.

    Attributes:
        name: Indicator name
        timestamp: Calculation timestamp
        value: Indicator value
        signal_line: Optional signal line value
        metadata: Additional metadata
    """

    name: str
    timestamp: datetime
    value: float
    signal_line: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskMetric:
    """Risk metric calculation result.

    Attributes:
        name: Metric name (e.g., 'VaR', 'CVaR', 'MaxDD')
        value: Metric value
        confidence_level: Confidence level (if applicable)
        holding_period: Holding period in days
        timestamp: Calculation timestamp
        metadata: Additional metadata
    """

    name: str
    value: float
    confidence_level: float | None = None
    holding_period: int = 1
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Strategy:
    """Trading strategy specification.

    Attributes:
        name: Strategy name
        description: Strategy description
        indicators: List of required indicators
        parameters: Strategy parameters
        rules: Entry/exit rules
    """

    name: str
    description: str = ""
    indicators: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class YieldCurve:
    """Yield curve representation.

    Attributes:
        maturities: Array of maturity times (in years)
        yields: Array of yields at each maturity
        timestamp: Yield curve timestamp
        curve_type: Type of curve (e.g., 'Par', 'Spot', 'Forward')
    """

    maturities: np.ndarray
    yields: np.ndarray
    timestamp: datetime
    curve_type: str = "Spot"

    def __len__(self) -> int:
        return len(self.maturities)

    def interpolate(self, maturity: float) -> float:
        """Linearly interpolate yield at given maturity.

        Args:
            maturity: Time to maturity in years

        Returns:
            Interpolated yield
        """
        return float(np.interp(maturity, self.maturities, self.yields))
