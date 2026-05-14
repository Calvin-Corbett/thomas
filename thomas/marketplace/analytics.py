"""Marketplace analytics with GMV, take rate, and performance metrics."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from thomas.marketplace._types import (
    Analytics,
    Order,
    OrderStatus,
)


@dataclass
class ConversionFunnelStep:
    """Conversion funnel step metric."""

    step: str
    count: int
    conversion_rate: Decimal


@dataclass
class CategoryPerformance:
    """Category-level performance metrics."""

    category_id: str
    category_name: str
    total_listings: int
    active_listings: int
    total_sales: Decimal
    total_items_sold: int
    avg_item_price: Decimal
    avg_rating: Decimal


@dataclass
class PricingAnalysis:
    """Pricing analytics across marketplace."""

    price_min: Decimal
    price_max: Decimal
    price_avg: Decimal
    price_median: Decimal
    price_std_dev: Decimal
    price_quartiles: dict[str, Decimal] = field(default_factory=dict)


class AnalyticsEngine:
    """Calculate marketplace analytics and metrics."""

    def __init__(self) -> None:
        """Initialize analytics engine."""
        self._orders: list[Order] = []
        self._events: list[dict] = []

    def record_order(self, order: Order) -> None:
        """Record order for analytics.

        Args:
            order: Order to record.
        """
        self._orders.append(order)

    def record_event(
        self,
        event_type: str,
        user_id: str,
        listing_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record user event for funnel analysis.

        Args:
            event_type: Type of event (view, add_to_cart, purchase).
            user_id: User identifier.
            listing_id: Listing identifier.
            metadata: Additional event data.
        """
        event = {
            "type": event_type,
            "user_id": user_id,
            "listing_id": listing_id,
            "timestamp": datetime.utcnow(),
            "metadata": metadata or {},
        }
        self._events.append(event)

    def calculate_gmv(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Decimal:
        """Calculate Gross Merchandise Value for period.

        Args:
            start_date: Period start.
            end_date: Period end.

        Returns:
            GMV total.
        """
        gmv = Decimal("0")

        for order in self._orders:
            if start_date <= order.created_at <= end_date:
                if order.status != OrderStatus.CANCELLED:
                    gmv += order.total_amount

        return gmv

    def calculate_take_rate(
        self,
        start_date: datetime,
        end_date: datetime,
        platform_revenue: Decimal,
    ) -> Decimal:
        """Calculate platform take rate (revenue / GMV).

        Args:
            start_date: Period start.
            end_date: Period end.
            platform_revenue: Platform revenue for period.

        Returns:
            Take rate percentage.
        """
        gmv = self.calculate_gmv(start_date, end_date)

        if gmv == Decimal("0"):
            return Decimal("0")

        take_rate = (platform_revenue / gmv) * Decimal("100")
        return min(take_rate, Decimal("100"))

    def get_vendor_rankings(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10,
    ) -> list[tuple[str, Decimal]]:
        """Rank vendors by GMV.

        Args:
            start_date: Period start.
            end_date: Period end.
            limit: Maximum vendors to return.

        Returns:
            List of (vendor_id, gmv) tuples.
        """
        vendor_gmv: dict[str, Decimal] = defaultdict(Decimal)

        for order in self._orders:
            if start_date <= order.created_at <= end_date:
                if order.status != OrderStatus.CANCELLED:
                    # Sum by vendor from order items
                    for item in order.items:
                        vendor_id = item.get("vendor_id")
                        if vendor_id:
                            item_total = Decimal(str(item.get("unit_price", 0))) * Decimal(str(item.get("quantity", 0)))
                            vendor_gmv[vendor_id] += item_total

        sorted_vendors = sorted(vendor_gmv.items(), key=lambda x: x[1], reverse=True)
        return sorted_vendors[:limit]

    def get_buyer_retention_cohort(
        self,
        cohort_date: datetime,
        lookback_days: int = 30,
    ) -> Decimal:
        """Calculate buyer retention rate.

        Percentage of buyers from cohort_date who made repeat purchases
        within lookback_days.

        Args:
            cohort_date: Cohort start date.
            lookback_days: Days to look back for repeat purchases.

        Returns:
            Retention rate 0-100.
        """
        cohort_end = cohort_date + timedelta(days=lookback_days)
        cohort_buyers = set()
        repeat_buyers = set()

        # Find initial cohort
        for order in self._orders:
            if (
                cohort_date <= order.created_at <= cohort_date + timedelta(days=1)
                and order.status == OrderStatus.COMPLETED
            ):
                cohort_buyers.add(order.buyer_id)

        if not cohort_buyers:
            return Decimal("0")

        # Find repeat purchases
        for order in self._orders:
            if (
                cohort_date < order.created_at <= cohort_end
                and order.buyer_id in cohort_buyers
                and order.status == OrderStatus.COMPLETED
            ):
                repeat_buyers.add(order.buyer_id)

        retention = (
            (Decimal(len(repeat_buyers)) / Decimal(len(cohort_buyers))) * Decimal("100")
            if cohort_buyers
            else Decimal("0")
        )
        return retention

    def get_conversion_funnel(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[ConversionFunnelStep]:
        """Calculate conversion funnel (view → add to cart → purchase).

        Args:
            start_date: Period start.
            end_date: Period end.

        Returns:
            Conversion funnel steps.
        """
        period_events = [e for e in self._events if start_date <= e["timestamp"] <= end_date]

        views = len([e for e in period_events if e["type"] == "view"])
        add_to_cart = len([e for e in period_events if e["type"] == "add_to_cart"])
        purchases = len([e for e in period_events if e["type"] == "purchase"])

        steps = []

        # View step
        steps.append(
            ConversionFunnelStep(
                step="view",
                count=views,
                conversion_rate=Decimal("100"),
            )
        )

        # Add to cart
        if views > 0:
            add_to_cart_rate = (Decimal(add_to_cart) / Decimal(views)) * Decimal("100")
        else:
            add_to_cart_rate = Decimal("0")

        steps.append(
            ConversionFunnelStep(
                step="add_to_cart",
                count=add_to_cart,
                conversion_rate=add_to_cart_rate,
            )
        )

        # Purchase
        if add_to_cart > 0:
            purchase_rate = (Decimal(purchases) / Decimal(add_to_cart)) * Decimal("100")
        else:
            purchase_rate = Decimal("0")

        steps.append(
            ConversionFunnelStep(
                step="purchase",
                count=purchases,
                conversion_rate=purchase_rate,
            )
        )

        return steps

    def get_category_performance(
        self,
        start_date: datetime,
        end_date: datetime,
        category_sales: dict[str, Decimal],
        category_names: dict[str, str],
    ) -> list[CategoryPerformance]:
        """Get performance metrics by category.

        Args:
            start_date: Period start.
            end_date: Period end.
            category_sales: Category ID to sales mapping.
            category_names: Category ID to name mapping.

        Returns:
            List of category performance metrics.
        """
        results = []

        for category_id, sales in category_sales.items():
            perf = CategoryPerformance(
                category_id=category_id,
                category_name=category_names.get(category_id, category_id),
                total_listings=0,
                active_listings=0,
                total_sales=sales,
                total_items_sold=0,
                avg_item_price=Decimal("0"),
                avg_rating=Decimal("0"),
            )
            results.append(perf)

        # Sort by sales
        results.sort(key=lambda r: r.total_sales, reverse=True)
        return results

    def get_pricing_analysis(self, prices: list[Decimal]) -> PricingAnalysis:
        """Analyze price distribution.

        Args:
            prices: List of prices to analyze.

        Returns:
            Pricing analysis with quartiles.
        """
        if not prices:
            return PricingAnalysis(
                price_min=Decimal("0"),
                price_max=Decimal("0"),
                price_avg=Decimal("0"),
                price_median=Decimal("0"),
                price_std_dev=Decimal("0"),
            )

        sorted_prices = sorted(prices)
        n = len(sorted_prices)

        price_min = sorted_prices[0]
        price_max = sorted_prices[-1]
        price_avg = sum(prices) / Decimal(n)

        # Median
        if n % 2 == 0:
            price_median = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / Decimal("2")
        else:
            price_median = sorted_prices[n // 2]

        # Standard deviation
        variance = sum((p - price_avg) ** 2 for p in prices) / Decimal(n)
        import math

        price_std_dev = Decimal(str(math.sqrt(float(variance))))

        # Quartiles
        q1_idx = n // 4
        q3_idx = (3 * n) // 4

        quartiles = {
            "q1": sorted_prices[q1_idx],
            "q2": price_median,
            "q3": sorted_prices[q3_idx],
        }

        return PricingAnalysis(
            price_min=price_min,
            price_max=price_max,
            price_avg=price_avg,
            price_median=price_median,
            price_std_dev=price_std_dev,
            price_quartiles=quartiles,
        )

    def get_search_effectiveness(
        self,
        search_queries: dict[str, int],
        zero_result_queries: list[str],
    ) -> tuple[Decimal, list[str]]:
        """Analyze search effectiveness.

        Args:
            search_queries: Query to result count mapping.
            zero_result_queries: Queries with zero results.

        Returns:
            Tuple of (effectiveness_rate, common_zero_result_queries).
        """
        if not search_queries:
            return Decimal("0"), []

        # Effectiveness = queries with results / total queries
        queries_with_results = sum(1 for count in search_queries.values() if count > 0)
        effectiveness = (
            (Decimal(queries_with_results) / Decimal(len(search_queries))) * Decimal("100")
            if search_queries
            else Decimal("0")
        )

        return effectiveness, zero_result_queries[:10]

    def get_summary_analytics(
        self,
        start_date: datetime,
        end_date: datetime,
        platform_revenue: Decimal = Decimal("0"),
    ) -> Analytics:
        """Get summary analytics for period.

        Args:
            start_date: Period start.
            end_date: Period end.
            platform_revenue: Platform revenue.

        Returns:
            Analytics summary.
        """
        gmv = self.calculate_gmv(start_date, end_date)

        # Order counts
        total_orders = len([o for o in self._orders if start_date <= o.created_at <= end_date])

        len(
            [o for o in self._orders if (start_date <= o.created_at <= end_date and o.status == OrderStatus.COMPLETED)]
        )

        # Items
        total_items = sum(
            sum(item.get("quantity", 0) for item in o.items)
            for o in self._orders
            if start_date <= o.created_at <= end_date
        )

        # Averages
        avg_order_value = gmv / Decimal(total_orders) if total_orders > 0 else Decimal("0")

        # Take rate
        take_rate = self.calculate_take_rate(start_date, end_date, platform_revenue)

        # Conversion (stub)
        conversion_rate = Decimal("2.5") if total_orders > 0 else Decimal("0")

        return Analytics(
            period_start=start_date,
            period_end=end_date,
            gmv=gmv,
            take_rate=take_rate,
            total_orders=total_orders,
            total_items_sold=total_items,
            avg_order_value=avg_order_value,
            buyer_retention_rate=self.get_buyer_retention_cohort(start_date),
            conversion_rate=conversion_rate,
            avg_response_time=24.0,
        )
