"""
Tests for order matching engine.

Comprehensive tests for limit order book, market orders, limit orders,
partial fills, cancellation, and trade generation.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from _types import Order, OrderSide, OrderStatus, OrderType, TimeInForce
from order_matching import LimitOrderBook, OrderMatcher


class TestLimitOrderBook:
    """Test limit order book functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.book = LimitOrderBook("AAPL")

    def test_create_order_book(self):
        """Test order book creation."""
        assert self.book.symbol == "AAPL"
        assert len(self.book.bids) == 0
        assert len(self.book.asks) == 0

    def test_add_limit_order_no_match(self):
        """Test adding limit order with no match."""
        order = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        trades = self.book.add_order(order)

        assert len(trades) == 0
        assert order.status == OrderStatus.OPEN
        assert Decimal("150.00") in self.book.bids

    def test_limit_order_match_exact(self):
        """Test limit order match at exact price."""
        buy_order = Order(
            id="BUY1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell_order = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.book.add_order(buy_order)
        trades = self.book.add_order(sell_order)

        assert len(trades) == 1
        assert trades[0].price == Decimal("150.00")
        assert trades[0].quantity == Decimal("100")
        assert buy_order.status == OrderStatus.FILLED
        assert sell_order.status == OrderStatus.FILLED

    def test_partial_fill(self):
        """Test partial fill of order."""
        buy_order = Order(
            id="BUY1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("200"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell_order = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.book.add_order(buy_order)
        trades = self.book.add_order(sell_order)

        assert len(trades) == 1
        assert buy_order.status == OrderStatus.PARTIALLY_FILLED
        assert sell_order.status == OrderStatus.FILLED
        assert buy_order.remaining_quantity == Decimal("100")

    def test_market_order_execution(self):
        """Test market order immediate execution."""
        # Add liquidity
        sell_order = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )
        self.book.add_order(sell_order)

        # Market order
        buy_order = Order(
            id="BUY1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=None,
            timestamp=datetime.utcnow(),
        )

        trades = self.book.add_order(buy_order)

        assert len(trades) == 1
        assert buy_order.status == OrderStatus.FILLED
        assert buy_order.fill_price == Decimal("150.00")

    def test_cancel_order(self):
        """Test order cancellation."""
        order = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.book.add_order(order)
        assert order.status == OrderStatus.OPEN

        cancelled = self.book.cancel_order("O1")
        assert cancelled is True
        assert order.status == OrderStatus.CANCELLED

    def test_multiple_price_levels(self):
        """Test matching across multiple price levels."""
        # Add asks at different prices
        for price in [Decimal("150.00"), Decimal("150.50"), Decimal("151.00")]:
            sell_order = Order(
                id=f"SELL-{price}",
                symbol="AAPL",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("50"),
                price=price,
                timestamp=datetime.utcnow(),
            )
            self.book.add_order(sell_order)

        # Market buy that should consume all
        buy_order = Order(
            id="BUY1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("150"),
            price=None,
            timestamp=datetime.utcnow(),
        )

        trades = self.book.add_order(buy_order)

        assert len(trades) == 3
        assert buy_order.fill_quantity == Decimal("150")
        assert buy_order.status == OrderStatus.FILLED

    def test_price_time_priority(self):
        """Test price-time priority matching."""
        # Add buy orders at same price
        order1 = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )
        order2 = Order(
            id="O2",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.book.add_order(order1)
        self.book.add_order(order2)

        # Sell that matches first order
        sell_order = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        trades = self.book.add_order(sell_order)

        assert len(trades) == 1
        assert trades[0].buy_order_id == "O1"  # First order matched


class TestOrderMatcher:
    """Test central order matching engine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = OrderMatcher()

    def test_submit_order(self):
        """Test order submission."""
        order = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        trades = self.matcher.submit_order(order)

        assert len(trades) == 0
        assert self.matcher.get_order("O1") == order

    def test_cancel_order(self):
        """Test order cancellation through matcher."""
        order = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(order)
        cancelled = self.matcher.cancel_order("O1")

        assert cancelled is True
        assert self.matcher.get_order("O1").status == OrderStatus.CANCELLED

    def test_multiple_symbols(self):
        """Test matching with multiple symbols."""
        aapl_buy = Order(
            id="AAPL_BUY",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        msft_buy = Order(
            id="MSFT_BUY",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("50"),
            price=Decimal("300.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(aapl_buy)
        self.matcher.submit_order(msft_buy)

        assert len(self.matcher.books) == 2
        assert "AAPL" in self.matcher.books
        assert "MSFT" in self.matcher.books

    def test_get_book_snapshot(self):
        """Test getting order book snapshot."""
        order = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(order)
        book = self.matcher.get_book("AAPL")

        assert book is not None
        assert book.get_best_bid() == Decimal("150.00")

    def test_fill_or_kill_order(self):
        """Test fill-or-kill order."""
        # Add some liquidity
        sell_order = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("50"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )
        self.matcher.submit_order(sell_order)

        # FOK order wanting more than available
        fok_order = Order(
            id="FOK1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
            tif=TimeInForce.FOK,
        )

        trades = self.matcher.submit_order(fok_order)

        # Should cancel unfilled
        assert fok_order.status == OrderStatus.CANCELLED

    def test_get_trades(self):
        """Test retrieving trades."""
        # Execute a trade
        buy = Order(
            id="BUY1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell = Order(
            id="SELL1",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(buy)
        self.matcher.submit_order(sell)

        trades = self.matcher.get_trades()
        assert len(trades) > 0

        aapl_trades = self.matcher.get_trades("AAPL")
        assert len(aapl_trades) == len(trades)

    def test_get_order_book_depth(self):
        """Test getting order book depth."""
        # Add multiple orders at different prices
        for i, price in enumerate([Decimal("150.00"), Decimal("149.50"), Decimal("149.00")]):
            buy = Order(
                id=f"BUY{i}",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("100"),
                price=price,
                timestamp=datetime.utcnow(),
            )
            self.matcher.submit_order(buy)

        bids, asks = self.matcher.get_order_book_depth("AAPL", 5)

        assert len(bids) == 3
        assert bids[0][0] == Decimal("150.00")  # Best bid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
