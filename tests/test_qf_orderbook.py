"""Tests for limit order book and matching engine."""

import pytest

from thomas.marketplace.quantfin._types import Asset, Order, OrderSide, OrderStatus, OrderType
from thomas.marketplace.quantfin.orderbook import LimitOrderBook


class TestOrderBook:
    """Order book tests."""

    @pytest.fixture
    def asset(self) -> Asset:
        """Create test asset."""
        return Asset(symbol="AAPL", name="Apple", asset_type="EQUITY")

    @pytest.fixture
    def order_book(self, asset: Asset) -> LimitOrderBook:
        """Create test order book."""
        return LimitOrderBook(asset)

    def test_best_bid_ask(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test best bid and ask price tracking."""
        order1 = Order(
            order_id="1",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=100.0,
        )
        order_book.add_limit_order(order1)

        order2 = Order(
            order_id="2",
            asset=asset,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=101.0,
        )
        order_book.add_limit_order(order2)

        assert order_book.best_bid == 100.0
        assert order_book.best_ask == 101.0

    def test_mid_price(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test mid-price calculation."""
        order_book.add_limit_order(
            Order(
                order_id="1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=100.0,
            )
        )
        order_book.add_limit_order(
            Order(
                order_id="2",
                asset=asset,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=102.0,
            )
        )

        assert order_book.mid_price == 101.0

    def test_spread(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test bid-ask spread calculation."""
        order_book.add_limit_order(
            Order(
                order_id="1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=100.0,
            )
        )
        order_book.add_limit_order(
            Order(
                order_id="2",
                asset=asset,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=105.0,
            )
        )

        assert order_book.spread == 5.0

    def test_market_order_buy(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test market order buy execution."""
        # Add sell orders
        order_book.add_limit_order(
            Order(
                order_id="1",
                asset=asset,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=101.0,
            )
        )

        # Execute market buy
        buy_order = Order(
            order_id="2",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=50,
        )

        trades = order_book.match_market_order(buy_order)

        assert len(trades) == 1
        assert trades[0].price == 101.0
        assert trades[0].quantity == 50
        assert buy_order.is_filled

    def test_market_order_sell(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test market order sell execution."""
        # Add buy orders
        order_book.add_limit_order(
            Order(
                order_id="1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=99.0,
            )
        )

        # Execute market sell
        sell_order = Order(
            order_id="2",
            asset=asset,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=50,
        )

        trades = order_book.match_market_order(sell_order)

        assert len(trades) == 1
        assert trades[0].price == 99.0
        assert trades[0].quantity == 50

    def test_order_cancellation(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test order cancellation."""
        order = Order(
            order_id="1",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=100.0,
        )
        order_book.add_limit_order(order)

        assert order_book.best_bid == 100.0

        cancelled = order_book.cancel_order("1")
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED
        assert order_book.best_bid is None

    def test_order_modification(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test order modification."""
        order = Order(
            order_id="1",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=100.0,
        )
        order_book.add_limit_order(order)

        # Modify quantity and price
        success = order_book.modify_order("1", new_quantity=150, new_price=99.0)

        assert success
        assert order_book.best_bid == 99.0

    def test_order_book_depth(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test order book depth retrieval."""
        for i in range(5):
            order_book.add_limit_order(
                Order(
                    order_id=f"buy_{i}",
                    asset=asset,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=100.0 - i,
                )
            )
            order_book.add_limit_order(
                Order(
                    order_id=f"sell_{i}",
                    asset=asset,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=101.0 + i,
                )
            )

        bids, asks = order_book.get_depth(num_levels=3)

        assert len(bids) == 3
        assert len(asks) == 3
        assert bids[0][0] > bids[1][0] > bids[2][0]  # Bids descending
        assert asks[0][0] < asks[1][0] < asks[2][0]  # Asks ascending

    def test_price_impact(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test price impact estimation."""
        for i in range(3):
            order_book.add_limit_order(
                Order(
                    order_id=f"sell_{i}",
                    asset=asset,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=101.0 + i,
                )
            )

        impact = order_book.calculate_price_impact(OrderSide.BUY, 150)

        # Should be weighted average between 101.0 and 102.0
        assert 101.0 < impact < 102.0

    def test_twap_execution(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test TWAP execution algorithm."""
        # Add deep liquidity
        for price in range(100, 110):
            order_book.add_limit_order(
                Order(
                    order_id=f"sell_{price}",
                    asset=asset,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1000,
                    price=float(price),
                )
            )

        executions = order_book.twap_execution(OrderSide.BUY, quantity=500, num_slices=5)

        assert len(executions) == 5
        assert sum(qty for _, qty in executions) == 500
        assert all(qty == 100 for _, qty in executions)  # Equal slices

    def test_vwap_execution(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test VWAP execution algorithm."""
        for price in range(100, 110):
            order_book.add_limit_order(
                Order(
                    order_id=f"sell_{price}",
                    asset=asset,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1000,
                    price=float(price),
                )
            )

        volume_profile = [100, 200, 300, 200, 100]  # Higher volume in middle
        executions = order_book.vwap_execution(OrderSide.BUY, quantity=900, volume_profile=volume_profile)

        assert len(executions) == 5
        # Total should sum to 900
        total_qty = sum(qty for _, qty in executions)
        assert abs(total_qty - 900) < 1.0

    def test_multiple_price_levels(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test order book with multiple price levels."""
        # Add orders at different prices
        order_book.add_limit_order(
            Order(
                order_id="1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=99.0,
            )
        )
        order_book.add_limit_order(
            Order(
                order_id="2",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=200,
                price=98.0,
            )
        )

        # Execute market sell that sweeps both levels
        sell_order = Order(
            order_id="3",
            asset=asset,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=250,
        )

        trades = order_book.match_market_order(sell_order)

        # Should have 2 trades
        assert len(trades) == 2
        # First trade at 99.0 for 100
        assert trades[0].price == 99.0
        assert trades[0].quantity == 100
        # Second trade at 98.0 for 150
        assert trades[1].price == 98.0
        assert trades[1].quantity == 150

    def test_fifo_queue_at_price_level(self, order_book: LimitOrderBook, asset: Asset) -> None:
        """Test FIFO queue ordering at same price level."""
        order1 = Order(
            order_id="1",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=100.0,
        )
        order2 = Order(
            order_id="2",
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=100.0,
        )

        order_book.add_limit_order(order1)
        order_book.add_limit_order(order2)

        # Execute market sell - should fill order1 first (FIFO)
        sell_order = Order(
            order_id="3",
            asset=asset,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
        )

        trades = order_book.match_market_order(sell_order)

        assert len(trades) == 1
        assert order1.is_filled
        assert not order2.is_filled
