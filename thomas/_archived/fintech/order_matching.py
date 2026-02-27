"""
Order matching engine with limit order book.

Implements a high-performance order matching system with support for:
- Limit, market, and stop orders
- Price-time priority matching
- Partial fills
- Fill-or-kill and immediate-or-cancel orders
- Trade generation and execution
- Order cancellation and tracking
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from ._exceptions import OrderError
from ._types import (
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    Trade,
)


class LimitOrderBook:
    """
    Limit order book with bid/ask sides and price-time priority.

    Maintains separate bid and ask sides sorted by price (best first).
    Supports adding, removing, and matching orders with full trade generation.
    """

    def __init__(self, symbol: str) -> None:
        """
        Initialize limit order book.

        Args:
            symbol: Trading symbol for this book
        """
        self.symbol = symbol
        self.bids: dict[Decimal, list[Order]] = defaultdict(list)
        self.asks: dict[Decimal, list[Order]] = defaultdict(list)
        self.order_map: dict[str, Order] = {}
        self.trades: list[Trade] = []
        self._trade_counter = 0

    def add_order(self, order: Order) -> list[Trade]:
        """
        Add order to book and attempt matching.

        Args:
            order: Order to add

        Returns:
            List of trades generated from matching
        """
        if order.symbol != self.symbol:
            raise ValueError(f"Order symbol {order.symbol} != book symbol {self.symbol}")

        self.order_map[order.id] = order
        trades: list[Trade] = []

        # Market orders execute immediately at best available price
        if order.order_type == OrderType.MARKET:
            trades = self._match_market_order(order)
        # Limit orders match against opposite side, rest goes to book
        elif order.order_type == OrderType.LIMIT:
            trades = self._match_limit_order(order)
            if order.remaining_quantity > 0:
                self._add_to_book(order)
        # Stop orders converted to market when triggered
        elif order.order_type == OrderType.STOP:
            self._add_to_book(order)

        return trades

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if order was cancelled, False if not found
        """
        if order_id not in self.order_map:
            return False

        order = self.order_map[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False

        # Remove from book
        if order.side == OrderSide.BUY:
            if order.price in self.bids:
                self.bids[order.price] = [o for o in self.bids[order.price] if o.id != order_id]
                if not self.bids[order.price]:
                    del self.bids[order.price]
        else:
            if order.price in self.asks:
                self.asks[order.price] = [o for o in self.asks[order.price] if o.id != order_id]
                if not self.asks[order.price]:
                    del self.asks[order.price]

        order.status = OrderStatus.CANCELLED
        return True

    def get_order(self, order_id: str) -> Order | None:
        """Retrieve an order by ID."""
        return self.order_map.get(order_id)

    def get_book_snapshot(self) -> OrderBook:
        """Get current order book snapshot."""
        bids = [
            (price, sum(o.remaining_quantity for o in orders))
            for price in sorted(self.bids.keys(), reverse=True)
            for orders in [self.bids[price]]
        ]
        asks = [
            (price, sum(o.remaining_quantity for o in orders))
            for price in sorted(self.asks.keys())
            for orders in [self.asks[price]]
        ]
        return OrderBook(
            symbol=self.symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.utcnow(),
        )

    def _match_market_order(self, order: Order) -> list[Trade]:
        """Match market order against book immediately."""
        trades: list[Trade] = []

        if order.side == OrderSide.BUY:
            opposite_side = self.asks
            opposite_order_side = OrderSide.SELL
        else:
            opposite_side = self.bids
            opposite_order_side = OrderSide.BUY

        # Match against all available prices until order filled or book empty
        for price in sorted(opposite_side.keys()):
            if order.remaining_quantity == 0:
                break

            orders_at_price = opposite_side[price]
            while orders_at_price and order.remaining_quantity > 0:
                matched_order = orders_at_price[0]
                match_qty = min(
                    order.remaining_quantity,
                    matched_order.remaining_quantity,
                )

                trade = self._execute_match(order, matched_order, price, match_qty)
                trades.append(trade)

                if matched_order.remaining_quantity == 0:
                    orders_at_price.pop(0)

            if not orders_at_price:
                del opposite_side[price]

        # Market order fills what it can
        order.status = OrderStatus.FILLED
        order.fill_price = trades[0].price if trades else Decimal("0")

        return trades

    def _match_limit_order(self, order: Order) -> list[Trade]:
        """Match limit order against opposite side."""
        trades: list[Trade] = []

        if order.side == OrderSide.BUY:
            opposite_side = self.asks
            best_first_desc = False
        else:
            opposite_side = self.bids
            best_first_desc = True

        # Check if order can match at its limit price or better
        for price in sorted(opposite_side.keys(), reverse=best_first_desc):
            if order.remaining_quantity == 0:
                break

            # Limit order won't match worse than limit price
            if order.side == OrderSide.BUY and price > order.price:
                break
            if order.side == OrderSide.SELL and price < order.price:
                break

            orders_at_price = opposite_side[price]
            while orders_at_price and order.remaining_quantity > 0:
                matched_order = orders_at_price[0]
                match_qty = min(
                    order.remaining_quantity,
                    matched_order.remaining_quantity,
                )

                trade = self._execute_match(order, matched_order, price, match_qty)
                trades.append(trade)

                if matched_order.remaining_quantity == 0:
                    orders_at_price.pop(0)

            if not orders_at_price:
                del opposite_side[price]

        # Update order status
        if order.remaining_quantity == 0:
            order.status = OrderStatus.FILLED
        elif order.fill_quantity > 0:
            order.status = OrderStatus.PARTIALLY_FILLED

        if trades:
            order.fill_price = sum(t.price * t.quantity for t in trades) / order.fill_quantity

        return trades

    def _execute_match(
        self,
        taker: Order,
        maker: Order,
        price: Decimal,
        quantity: Decimal,
    ) -> Trade:
        """Execute a match between two orders."""
        self._trade_counter += 1
        trade_id = f"TRADE-{self._trade_counter:09d}"

        # Update quantities
        taker.fill_quantity += quantity
        taker.remaining_quantity -= quantity
        maker.fill_quantity += quantity
        maker.remaining_quantity -= quantity

        # Create trade record
        trade = Trade(
            id=trade_id,
            buy_order_id=taker.id if taker.side == OrderSide.BUY else maker.id,
            sell_order_id=taker.id if taker.side == OrderSide.SELL else maker.id,
            symbol=self.symbol,
            price=price,
            quantity=quantity,
            timestamp=datetime.utcnow(),
        )

        # Update maker status
        if maker.remaining_quantity == 0:
            maker.status = OrderStatus.FILLED
        else:
            maker.status = OrderStatus.PARTIALLY_FILLED

        if maker.fill_quantity == quantity:
            maker.fill_price = price
        else:
            maker.fill_price = (
                maker.fill_price * (maker.fill_quantity - quantity) + price * quantity
            ) / maker.fill_quantity

        self.trades.append(trade)
        return trade

    def _add_to_book(self, order: Order) -> None:
        """Add order to appropriate side of book."""
        if order.side == OrderSide.BUY:
            self.bids[order.price].append(order)
        else:
            self.asks[order.price].append(order)

        order.status = OrderStatus.OPEN

    def apply_tif(self, order: Order, trades: list[Trade]) -> list[Trade]:
        """Apply time-in-force rules to order."""
        if order.tif == TimeInForce.FOK:
            # Fill-or-Kill: cancel if not fully filled
            if order.remaining_quantity > 0:
                self.cancel_order(order.id)
                return []

        elif order.tif == TimeInForce.IOC:
            # Immediate-or-Cancel: cancel remaining
            if order.remaining_quantity > 0:
                self.cancel_order(order.id)

        return trades


class OrderMatcher:
    """
    Central order matching engine managing multiple order books.

    Handles order routing to appropriate books, trade execution, and
    coordination across different trading symbols.
    """

    def __init__(self) -> None:
        """Initialize order matcher."""
        self.books: dict[str, LimitOrderBook] = {}
        self.trades: list[Trade] = []
        self.order_map: dict[str, Order] = {}

    def submit_order(self, order: Order) -> list[Trade]:
        """
        Submit order for matching.

        Args:
            order: Order to submit

        Returns:
            List of trades generated

        Raises:
            OrderError: If order is invalid
        """
        # Validate order
        if order.symbol in self.order_map and order.id in self.order_map.values():
            raise OrderError(order.id, "Order already submitted")

        # Get or create book for symbol
        if order.symbol not in self.books:
            self.books[order.symbol] = LimitOrderBook(order.symbol)

        book = self.books[order.symbol]
        self.order_map[order.id] = order

        # Add order to book and get trades
        trades = book.add_order(order)

        # Apply time-in-force rules
        trades = book.apply_tif(order, trades)

        # Track trades
        self.trades.extend(trades)

        return trades

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a submitted order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if cancelled, False if not found
        """
        if order_id not in self.order_map:
            return False

        order = self.order_map[order_id]
        book = self.books.get(order.symbol)

        if book is None:
            return False

        return book.cancel_order(order_id)

    def get_order(self, order_id: str) -> Order | None:
        """Retrieve an order by ID."""
        return self.order_map.get(order_id)

    def get_book(self, symbol: str) -> OrderBook | None:
        """Get current order book snapshot for a symbol."""
        if symbol not in self.books:
            return None
        return self.books[symbol].get_book_snapshot()

    def get_trades(self, symbol: str | None = None) -> list[Trade]:
        """
        Get trades, optionally filtered by symbol.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of trades
        """
        if symbol is None:
            return self.trades
        return [t for t in self.trades if t.symbol == symbol]

    def get_order_book_depth(
        self,
        symbol: str,
        levels: int = 10,
    ) -> tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]:
        """
        Get market depth for a symbol.

        Args:
            symbol: Trading symbol
            levels: Number of price levels to return

        Returns:
            Tuple of (bids, asks) as (price, quantity) pairs
        """
        book = self.get_book(symbol)
        if book is None:
            return [], []

        return (
            book.get_depth_at_price(OrderSide.BUY, levels),
            book.get_depth_at_price(OrderSide.SELL, levels),
        )
