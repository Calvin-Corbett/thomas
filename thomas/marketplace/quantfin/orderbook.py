"""Limit order book and matching engine."""

from __future__ import annotations

from datetime import datetime

from thomas.marketplace.quantfin._exceptions import OrderError
from thomas.marketplace.quantfin._types import Asset, Order, OrderBook, OrderSide, OrderStatus, Trade


class LimitOrderBook:
    """Limit order book with efficient price level management.

    Maintains buy and sell orders sorted by price level with FIFO queue
    at each price. Supports market order matching, limit order placement,
    and order cancellation.
    """

    def __init__(self, asset: Asset) -> None:
        """Initialize order book for asset.

        Args:
            asset: Asset for this order book
        """
        self.asset = asset
        self.bid_levels: dict[float, list[Order]] = {}
        self.ask_levels: dict[float, list[Order]] = {}
        self.order_id_map: dict[str, tuple[float, OrderSide]] = {}
        self.timestamp = datetime.now()

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
    def mid_price(self) -> float | None:
        """Get mid price."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float | None:
        """Get bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def add_limit_order(self, order: Order) -> None:
        """Add limit order to book.

        Args:
            order: Limit order to add

        Raises:
            OrderError: If order is invalid
        """
        if order.price is None:
            raise OrderError("Limit order must have price")

        if order.side == OrderSide.BUY:
            if order.price not in self.bid_levels:
                self.bid_levels[order.price] = []
            self.bid_levels[order.price].append(order)
        else:  # SELL
            if order.price not in self.ask_levels:
                self.ask_levels[order.price] = []
            self.ask_levels[order.price].append(order)

        self.order_id_map[order.order_id] = (order.price, order.side)
        self.timestamp = datetime.now()

    def match_market_order(self, order: Order) -> list[Trade]:
        """Match market order against order book.

        Sweeps through price levels from best price until order is fully filled.

        Args:
            order: Market order to match

        Returns:
            List of trades executed

        Raises:
            OrderError: If order book is empty
        """
        if order.price is not None:
            raise OrderError("Market order should not have price")

        trades: list[Trade] = []
        remaining_qty = order.quantity

        if order.side == OrderSide.BUY:
            # Match against asks (lowest first)
            ask_prices = sorted(self.ask_levels.keys())
            for price in ask_prices:
                if remaining_qty == 0:
                    break

                queue = self.ask_levels[price]
                while remaining_qty > 0 and queue:
                    seller_order = queue[0]
                    fill_qty = min(remaining_qty, seller_order.remaining_quantity)

                    # Execute trade
                    seller_order.fill(fill_qty, price)
                    order.fill(fill_qty, price)
                    remaining_qty -= fill_qty

                    # Record trade
                    trades.append(
                        Trade(
                            asset=self.asset,
                            side=order.side,
                            quantity=fill_qty,
                            price=price,
                            timestamp=self.timestamp,
                        )
                    )

                    # Remove filled orders
                    if seller_order.is_filled:
                        queue.pop(0)
                        if seller_order.order_id in self.order_id_map:
                            del self.order_id_map[seller_order.order_id]

                # Clean up empty level
                if not queue:
                    del self.ask_levels[price]
        else:  # SELL
            # Match against bids (highest first)
            bid_prices = sorted(self.bid_levels.keys(), reverse=True)
            for price in bid_prices:
                if remaining_qty == 0:
                    break

                queue = self.bid_levels[price]
                while remaining_qty > 0 and queue:
                    buyer_order = queue[0]
                    fill_qty = min(remaining_qty, buyer_order.remaining_quantity)

                    # Execute trade
                    buyer_order.fill(fill_qty, price)
                    order.fill(fill_qty, price)
                    remaining_qty -= fill_qty

                    # Record trade
                    trades.append(
                        Trade(
                            asset=self.asset,
                            side=order.side,
                            quantity=fill_qty,
                            price=price,
                            timestamp=self.timestamp,
                        )
                    )

                    # Remove filled orders
                    if buyer_order.is_filled:
                        queue.pop(0)
                        if buyer_order.order_id in self.order_id_map:
                            del self.order_id_map[buyer_order.order_id]

                # Clean up empty level
                if not queue:
                    del self.bid_levels[price]

        self.timestamp = datetime.now()

        if remaining_qty > 0 and order.side == OrderSide.BUY or remaining_qty > 0 and order.side == OrderSide.SELL:
            raise OrderError(f"Insufficient liquidity: {remaining_qty} unfilled")

        return trades

    def cancel_order(self, order_id: str) -> Order | None:
        """Cancel order by ID.

        Args:
            order_id: Order ID to cancel

        Returns:
            Cancelled order if found, None otherwise
        """
        if order_id not in self.order_id_map:
            return None

        price, side = self.order_id_map[order_id]

        if side == OrderSide.BUY:
            queue = self.bid_levels.get(price)
        else:
            queue = self.ask_levels.get(price)

        if queue:
            for i, order in enumerate(queue):
                if order.order_id == order_id:
                    order.status = OrderStatus.CANCELLED
                    queue.pop(i)
                    del self.order_id_map[order_id]

                    if not queue:
                        if side == OrderSide.BUY:
                            del self.bid_levels[price]
                        else:
                            del self.ask_levels[price]

                    self.timestamp = datetime.now()
                    return order

        return None

    def modify_order(self, order_id: str, new_quantity: float, new_price: float | None = None) -> bool:
        """Modify existing order.

        Args:
            order_id: Order ID to modify
            new_quantity: New quantity
            new_price: New price (for limit orders)

        Returns:
            True if modification succeeded
        """
        cancelled = self.cancel_order(order_id)
        if not cancelled:
            return False

        # Create new order with updated parameters
        new_order = Order(
            order_id=order_id,
            asset=self.asset,
            side=cancelled.side,
            order_type=cancelled.order_type,
            quantity=new_quantity,
            price=new_price if new_price is not None else cancelled.price,
            created_at=datetime.now(),
        )

        self.add_limit_order(new_order)
        return True

    def get_depth(self, num_levels: int = 10) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Get order book depth.

        Args:
            num_levels: Number of levels to return

        Returns:
            Tuple of (bids, asks) with (price, quantity) tuples
        """
        bids = []
        for price in sorted(self.bid_levels.keys(), reverse=True)[:num_levels]:
            total_qty = sum(o.remaining_quantity for o in self.bid_levels[price])
            bids.append((price, total_qty))

        asks = []
        for price in sorted(self.ask_levels.keys())[:num_levels]:
            total_qty = sum(o.remaining_quantity for o in self.ask_levels[price])
            asks.append((price, total_qty))

        return bids, asks

    def calculate_price_impact(self, side: OrderSide, quantity: float) -> float:
        """Estimate price impact of market order.

        Simple model: average price weighted by quantity available.

        Args:
            side: Order side
            quantity: Order quantity

        Returns:
            Estimated execution price
        """
        remaining = quantity
        total_cost = 0.0

        if side == OrderSide.BUY:
            ask_prices = sorted(self.ask_levels.keys())
            for price in ask_prices:
                if remaining == 0:
                    break
                available = sum(o.remaining_quantity for o in self.ask_levels[price])
                fill_qty = min(remaining, available)
                total_cost += fill_qty * price
                remaining -= fill_qty
        else:  # SELL
            bid_prices = sorted(self.bid_levels.keys(), reverse=True)
            for price in bid_prices:
                if remaining == 0:
                    break
                available = sum(o.remaining_quantity for o in self.bid_levels[price])
                fill_qty = min(remaining, available)
                total_cost += fill_qty * price
                remaining -= fill_qty

        if quantity - remaining == 0:
            return 0.0

        return total_cost / (quantity - remaining)

    def twap_execution(
        self,
        side: OrderSide,
        quantity: float,
        num_slices: int = 10,
    ) -> list[tuple[float, float]]:
        """Time-Weighted Average Price execution algorithm.

        Divides order into equal slices executed over time.

        Args:
            side: Order side
            quantity: Total quantity
            num_slices: Number of slices

        Returns:
            List of (price, quantity) tuples for each slice
        """
        slice_qty = quantity / num_slices
        executions = []

        for _ in range(num_slices):
            price = self.calculate_price_impact(side, slice_qty)
            executions.append((price, slice_qty))

        return executions

    def vwap_execution(
        self,
        side: OrderSide,
        quantity: float,
        volume_profile: list[float],
    ) -> list[tuple[float, float]]:
        """Volume-Weighted Average Price execution algorithm.

        Executes order weighted by expected volume profile.

        Args:
            side: Order side
            quantity: Total quantity
            volume_profile: Expected volume for each time period

        Returns:
            List of (price, quantity) tuples
        """
        total_volume = sum(volume_profile)
        if total_volume == 0:
            return [(self.mid_price or 0.0, quantity)]

        executions = []
        for vol in volume_profile:
            slice_qty = quantity * (vol / total_volume)
            price = self.calculate_price_impact(side, slice_qty)
            executions.append((price, slice_qty))

        return executions

    def iceberg_order(
        self,
        order: Order,
        visible_qty: float,
    ) -> None:
        """Add iceberg order (partially hidden).

        Iceberg orders show only visible_qty at a time, with rest hidden.
        Not fully implemented here - simplified model.

        Args:
            order: Limit order
            visible_qty: Visible quantity
        """
        order.metadata["iceberg_visible"] = visible_qty
        order.metadata["iceberg_total"] = order.quantity
        self.add_limit_order(order)

    def get_order_book_snapshot(self) -> OrderBook:
        """Create snapshot of current order book state.

        Returns:
            OrderBook snapshot
        """
        snapshot = OrderBook(asset=self.asset, timestamp=self.timestamp)

        for price, orders in self.bid_levels.items():
            total_qty = sum(o.remaining_quantity for o in orders)
            if total_qty > 0:
                snapshot.bid_levels[price] = type(
                    "PriceLevel",
                    (),
                    {
                        "price": price,
                        "total_quantity": total_qty,
                    },
                )()

        for price, orders in self.ask_levels.items():
            total_qty = sum(o.remaining_quantity for o in orders)
            if total_qty > 0:
                snapshot.ask_levels[price] = type(
                    "PriceLevel",
                    (),
                    {
                        "price": price,
                        "total_quantity": total_qty,
                    },
                )()

        return snapshot
