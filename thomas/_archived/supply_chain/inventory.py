"""
Inventory management module for supply chain optimization.

Provides inventory management capabilities including ABC/XYZ classification,
economic order quantity calculation, reorder point management, inventory
valuation methods, and multi-echelon optimization.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._exceptions import InvalidInventoryValuationException, InventoryException
from thomas.supply_chain._types import SKU, InventoryClassification, InventoryLevel, InventoryValuationMethod, Warehouse


@dataclass
class EOQResult:
    """Economic Order Quantity calculation result."""

    sku: SKU
    economic_order_quantity: Decimal
    annual_demand: Decimal
    order_cost: Decimal
    holding_cost_per_unit: Decimal
    total_annual_cost: Decimal
    orders_per_year: Decimal
    reorder_cost_per_order: Decimal


@dataclass
class ReorderPoint:
    """Reorder point and safety stock calculation."""

    sku: SKU
    reorder_point: Decimal
    safety_stock: Decimal
    average_lead_time: int
    demand_during_lead_time: Decimal
    service_level: Decimal  # Percentage (95, 99, etc.)
    z_score: Decimal  # Standard normal deviate
    demand_std_dev: Decimal


@dataclass
class ReviewPolicyResult:
    """Periodic and continuous review policy results."""

    sku: SKU
    policy_type: str  # "periodic_review" or "continuous_review"
    review_period: int  # days
    reorder_quantity: Decimal
    maximum_stock: Decimal
    minimum_stock: Decimal
    average_inventory: Decimal
    estimated_stockouts_per_year: Decimal


@dataclass
class ABCClassification:
    """ABC inventory classification result."""

    sku: SKU
    classification: InventoryClassification
    annual_value: Decimal
    percentage_of_total: Decimal
    cumulative_percentage: Decimal


@dataclass
class XYZClassification:
    """XYZ demand pattern classification."""

    sku: SKU
    classification: str  # X (smooth), Y (variable), Z (erratic)
    coefficient_of_variation: Decimal
    demand_pattern: str


@dataclass
class InventorySnapshot:
    """Inventory snapshot at a point in time."""

    timestamp: datetime
    warehouse_id: UUID
    total_value: Decimal
    total_units: Decimal
    inventory_turnover: Decimal
    inventory_age_days: int
    storage_utilization: Decimal
    slow_moving_count: int
    fast_moving_count: int


class InventoryManager:
    """
    Comprehensive inventory management system.

    Handles inventory valuation, ABC/XYZ classification, EOQ calculations,
    reorder point management, and multi-echelon optimization.
    """

    def __init__(self) -> None:
        """Initialize inventory manager."""
        self._z_scores: dict[str, Decimal] = {
            "90": Decimal("1.28"),
            "95": Decimal("1.645"),
            "99": Decimal("2.33"),
            "99.9": Decimal("3.09"),
        }

    def calculate_eoq(
        self,
        sku: SKU,
        annual_demand: Decimal,
        order_cost: Decimal,
        holding_cost_per_unit: Decimal,
        quantity_discount_breaks: list[tuple[Decimal, Decimal]] | None = None,
    ) -> EOQResult:
        """
        Calculate Economic Order Quantity (EOQ) with optional quantity discounts.

        Args:
            sku: Stock keeping unit
            annual_demand: Annual demand in units
            order_cost: Cost per order
            holding_cost_per_unit: Annual holding cost per unit
            quantity_discount_breaks: List of (quantity, unit_cost) tuples for discounts

        Returns:
            EOQResult with optimal order quantity and costs

        Raises:
            InventoryException: If parameters are invalid
        """
        if annual_demand <= 0 or order_cost < 0 or holding_cost_per_unit < 0:
            raise InventoryException(
                f"Invalid parameters: annual_demand={annual_demand}, "
                f"order_cost={order_cost}, holding_cost={holding_cost_per_unit}"
            )

        # Calculate basic EOQ
        eoq_value = Decimal(2) * annual_demand * order_cost / holding_cost_per_unit
        base_eoq = Decimal(str(math.sqrt(float(eoq_value))))

        # Calculate total cost for base EOQ
        annual_demand / base_eoq if base_eoq > 0 else Decimal("0")
        base_cost = (annual_demand / base_eoq) * order_cost + (base_eoq / Decimal("2")) * holding_cost_per_unit

        optimal_eoq = base_eoq
        optimal_cost = base_cost
        optimal_unit_cost = holding_cost_per_unit

        # Check quantity discounts if provided
        if quantity_discount_breaks:
            for quantity_threshold, unit_cost in quantity_discount_breaks:
                if quantity_threshold >= base_eoq:
                    total_cost = (annual_demand / quantity_threshold) * order_cost + (
                        quantity_threshold / Decimal("2")
                    ) * unit_cost
                    if total_cost < optimal_cost:
                        optimal_eoq = quantity_threshold
                        optimal_cost = total_cost
                        optimal_unit_cost = unit_cost

        return EOQResult(
            sku=sku,
            economic_order_quantity=optimal_eoq,
            annual_demand=annual_demand,
            order_cost=order_cost,
            holding_cost_per_unit=optimal_unit_cost,
            total_annual_cost=optimal_cost,
            orders_per_year=annual_demand / optimal_eoq if optimal_eoq > 0 else Decimal("0"),
            reorder_cost_per_order=order_cost,
        )

    def calculate_reorder_point(
        self,
        sku: SKU,
        average_daily_demand: Decimal,
        lead_time_days: int,
        demand_std_dev: Decimal,
        service_level: Decimal = Decimal("95"),
    ) -> ReorderPoint:
        """
        Calculate reorder point with safety stock based on service level.

        Args:
            sku: Stock keeping unit
            average_daily_demand: Average daily demand
            lead_time_days: Lead time in days
            demand_std_dev: Standard deviation of daily demand
            service_level: Service level percentage (default 95%)

        Returns:
            ReorderPoint with safety stock and reorder level

        Raises:
            InventoryException: If parameters are invalid
        """
        if average_daily_demand < 0 or lead_time_days < 0 or demand_std_dev < 0:
            raise InventoryException(
                f"Invalid parameters: demand={average_daily_demand}, "
                f"lead_time={lead_time_days}, std_dev={demand_std_dev}"
            )

        # Get z-score for service level
        z_score = self._z_scores.get(
            str(service_level),
            Decimal("1.645"),  # Default 95%
        )

        # Calculate demand during lead time
        lead_time_demand = average_daily_demand * Decimal(lead_time_days)

        # Calculate standard deviation during lead time
        lt_std_dev = demand_std_dev * Decimal(str(math.sqrt(lead_time_days)))

        # Calculate safety stock
        safety_stock = z_score * lt_std_dev

        # Reorder point = expected demand during lead time + safety stock
        reorder_point = lead_time_demand + safety_stock

        return ReorderPoint(
            sku=sku,
            reorder_point=reorder_point,
            safety_stock=safety_stock,
            average_lead_time=lead_time_days,
            demand_during_lead_time=lead_time_demand,
            service_level=service_level,
            z_score=z_score,
            demand_std_dev=demand_std_dev,
        )

    def periodic_review_policy(
        self,
        sku: SKU,
        average_daily_demand: Decimal,
        demand_std_dev: Decimal,
        review_period_days: int,
        lead_time_days: int,
        holding_cost: Decimal,
        order_cost: Decimal,
        service_level: Decimal = Decimal("95"),
    ) -> ReviewPolicyResult:
        """
        Calculate periodic review (R,S) inventory policy.

        Args:
            sku: Stock keeping unit
            average_daily_demand: Average daily demand
            demand_std_dev: Standard deviation of daily demand
            review_period_days: Review interval in days
            lead_time_days: Lead time in days
            holding_cost: Annual holding cost per unit
            order_cost: Cost per order
            service_level: Service level percentage

        Returns:
            ReviewPolicyResult with review parameters
        """
        z_score = self._z_scores.get(str(service_level), Decimal("1.645"))

        # Protection interval = review period + lead time
        protection_interval = review_period_days + lead_time_days
        pi_decimal = Decimal(protection_interval)

        # Average demand during protection interval
        avg_demand_pi = average_daily_demand * pi_decimal

        # Standard deviation during protection interval
        pi_std_dev = demand_std_dev * Decimal(str(math.sqrt(protection_interval)))

        # Maximum stock level (order-up-to level)
        maximum_stock = avg_demand_pi + (z_score * pi_std_dev)

        # Minimum stock (safety stock)
        minimum_stock = z_score * pi_std_dev

        # Average inventory
        avg_inventory = (maximum_stock / Decimal("2")) + minimum_stock

        # Estimate stockouts per year
        review_cycles_per_year = Decimal("365") / Decimal(review_period_days)
        stockouts_per_year = review_cycles_per_year * (Decimal("1") - (service_level / Decimal("100")))

        return ReviewPolicyResult(
            sku=sku,
            policy_type="periodic_review",
            review_period=review_period_days,
            reorder_quantity=maximum_stock,
            maximum_stock=maximum_stock,
            minimum_stock=minimum_stock,
            average_inventory=avg_inventory,
            estimated_stockouts_per_year=stockouts_per_year,
        )

    def continuous_review_policy(
        self,
        sku: SKU,
        annual_demand: Decimal,
        average_daily_demand: Decimal,
        demand_std_dev: Decimal,
        lead_time_days: int,
        order_cost: Decimal,
        holding_cost: Decimal,
        service_level: Decimal = Decimal("95"),
    ) -> ReviewPolicyResult:
        """
        Calculate continuous review (s,Q) inventory policy.

        Args:
            sku: Stock keeping unit
            annual_demand: Annual demand
            average_daily_demand: Average daily demand
            demand_std_dev: Standard deviation of daily demand
            lead_time_days: Lead time in days
            order_cost: Cost per order
            holding_cost: Annual holding cost per unit
            service_level: Service level percentage

        Returns:
            ReviewPolicyResult with reorder point and order quantity
        """
        # Calculate EOQ
        eoq_value = Decimal(2) * annual_demand * order_cost / holding_cost
        order_quantity = Decimal(str(math.sqrt(float(eoq_value))))

        # Calculate reorder point with safety stock
        z_score = self._z_scores.get(str(service_level), Decimal("1.645"))
        lt_std_dev = demand_std_dev * Decimal(str(math.sqrt(lead_time_days)))
        safety_stock = z_score * lt_std_dev
        reorder_point = (average_daily_demand * Decimal(lead_time_days)) + safety_stock

        # Average inventory
        avg_inventory = (order_quantity / Decimal("2")) + safety_stock

        # Estimate stockouts per year
        stockouts_per_year = (Decimal("1") - service_level / Decimal("100")) * annual_demand / order_quantity

        return ReviewPolicyResult(
            sku=sku,
            policy_type="continuous_review",
            review_period=1,
            reorder_quantity=order_quantity,
            maximum_stock=reorder_point + order_quantity,
            minimum_stock=reorder_point,
            average_inventory=avg_inventory,
            estimated_stockouts_per_year=stockouts_per_year,
        )

    def abc_classification(
        self,
        inventory_levels: list[InventoryLevel],
        annual_usage: dict[SKU, Decimal],
        a_percentage: Decimal = Decimal("80"),
        b_percentage: Decimal = Decimal("95"),
    ) -> list[ABCClassification]:
        """
        Classify inventory items using ABC analysis (Pareto principle).

        Args:
            inventory_levels: List of current inventory levels
            annual_usage: Dictionary of annual unit usage by SKU
            a_percentage: Cumulative value threshold for A class (default 80%)
            b_percentage: Cumulative value threshold for B class (default 95%)

        Returns:
            List of ABCClassification results sorted by value
        """
        # Calculate annual value for each item
        classifications = []
        total_value = Decimal("0")

        for level in inventory_levels:
            annual_units = annual_usage.get(level.sku, Decimal("0"))
            annual_value = annual_units * level.unit_cost
            total_value += annual_value
            classifications.append((level.sku, annual_value))

        # Sort by value descending
        classifications.sort(key=lambda x: x[1], reverse=True)

        # Assign classes
        results = []
        cumulative_value = Decimal("0")

        for sku, annual_value in classifications:
            cumulative_value += annual_value
            cumulative_pct = cumulative_value / total_value * Decimal("100") if total_value > 0 else Decimal("0")

            if cumulative_pct <= a_percentage:
                classification = InventoryClassification.A
            elif cumulative_pct <= b_percentage:
                classification = InventoryClassification.B
            else:
                classification = InventoryClassification.C

            results.append(
                ABCClassification(
                    sku=sku,
                    classification=classification,
                    annual_value=annual_value,
                    percentage_of_total=annual_value / total_value * Decimal("100")
                    if total_value > 0
                    else Decimal("0"),
                    cumulative_percentage=cumulative_pct,
                )
            )

        return results

    def xyz_classification(self, sku: SKU, historical_demand: list[Decimal]) -> XYZClassification:
        """
        Classify inventory based on demand pattern using coefficient of variation.

        Args:
            sku: Stock keeping unit
            historical_demand: Historical demand values

        Returns:
            XYZClassification with demand pattern analysis
        """
        if not historical_demand or len(historical_demand) < 2:
            raise InventoryException(f"Insufficient demand history for SKU {sku.code}")

        floats = [float(d) for d in historical_demand]
        mean = statistics.mean(floats)
        std_dev = statistics.stdev(floats) if len(floats) > 1 else 0

        # Coefficient of variation (CV) = std_dev / mean
        cv = Decimal(str(std_dev / mean)) if mean > 0 else Decimal("0")

        # Classify based on CV
        if cv < Decimal("0.5"):
            classification = "X"  # Smooth, predictable
            pattern = "smooth"
        elif cv < Decimal("1.0"):
            classification = "Y"  # Variable, moderate variation
            pattern = "variable"
        else:
            classification = "Z"  # Erratic, high variation
            pattern = "erratic"

        return XYZClassification(
            sku=sku, classification=classification, coefficient_of_variation=cv, demand_pattern=pattern
        )

    def inventory_valuation(
        self,
        method: InventoryValuationMethod,
        purchases: list[tuple[datetime, Decimal, Decimal]],  # date, qty, cost
        issues: list[tuple[datetime, Decimal]],  # date, qty
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate inventory value using different valuation methods.

        Args:
            method: Valuation method (FIFO, LIFO, WEIGHTED_AVERAGE)
            purchases: List of (date, quantity, unit_cost) tuples
            issues: List of (date, quantity) tuples for inventory issues

        Returns:
            Tuple of (inventory_value, cost_of_goods_sold)

        Raises:
            InvalidInventoryValuationException: If method is not supported
        """
        if method not in InventoryValuationMethod:
            raise InvalidInventoryValuationException(f"Unknown valuation method: {method}")

        # Sort purchases and issues by date
        purchases = sorted(purchases, key=lambda x: x[0])
        issues = sorted(issues, key=lambda x: x[0])

        if method == InventoryValuationMethod.FIFO:
            return self._fifo_valuation(purchases, issues)
        elif method == InventoryValuationMethod.LIFO:
            return self._lifo_valuation(purchases, issues)
        elif method == InventoryValuationMethod.WEIGHTED_AVERAGE:
            return self._weighted_average_valuation(purchases, issues)
        else:
            raise InvalidInventoryValuationException(f"Unknown method: {method}")

    def _fifo_valuation(
        self, purchases: list[tuple[datetime, Decimal, Decimal]], issues: list[tuple[datetime, Decimal]]
    ) -> tuple[Decimal, Decimal]:
        """First-In-First-Out valuation."""
        layers = []  # List of (quantity, unit_cost)
        cogs = Decimal("0")

        purchase_idx = 0
        for issue_date, issue_qty in issues:
            qty_remaining = issue_qty

            while qty_remaining > 0 and purchase_idx < len(purchases):
                purchase_date, purchase_qty, purchase_cost = purchases[purchase_idx]

                if purchase_date > issue_date and layers:
                    break

                # Use from current layer
                used_qty = min(qty_remaining, purchase_qty)
                cogs += used_qty * purchase_cost
                qty_remaining -= used_qty
                purchase_qty -= used_qty

                if purchase_qty > 0:
                    purchases[purchase_idx] = (purchase_date, purchase_qty, purchase_cost)
                else:
                    purchase_idx += 1

        # Calculate remaining inventory value
        ending_inventory = Decimal("0")
        for _, qty, cost in purchases[purchase_idx:]:
            ending_inventory += qty * cost

        return ending_inventory, cogs

    def _lifo_valuation(
        self, purchases: list[tuple[datetime, Decimal, Decimal]], issues: list[tuple[datetime, Decimal]]
    ) -> tuple[Decimal, Decimal]:
        """Last-In-First-Out valuation."""
        purchase_stack = list(reversed(purchases))
        cogs = Decimal("0")

        for issue_date, issue_qty in issues:
            qty_remaining = issue_qty

            while qty_remaining > 0 and purchase_stack:
                purchase_date, purchase_qty, purchase_cost = purchase_stack.pop()

                used_qty = min(qty_remaining, purchase_qty)
                cogs += used_qty * purchase_cost
                qty_remaining -= used_qty

                if purchase_qty > used_qty:
                    purchase_stack.append((purchase_date, purchase_qty - used_qty, purchase_cost))

        # Calculate remaining inventory value
        ending_inventory = Decimal("0")
        for _, qty, cost in purchase_stack:
            ending_inventory += qty * cost

        return ending_inventory, cogs

    def _weighted_average_valuation(
        self, purchases: list[tuple[datetime, Decimal, Decimal]], issues: list[tuple[datetime, Decimal]]
    ) -> tuple[Decimal, Decimal]:
        """Weighted average cost valuation."""
        total_units = Decimal("0")
        total_cost = Decimal("0")
        cogs = Decimal("0")

        for purchase_date, purchase_qty, purchase_cost in purchases:
            total_units += purchase_qty
            total_cost += purchase_qty * purchase_cost

        for issue_date, issue_qty in issues:
            if total_units > 0:
                weighted_avg_cost = total_cost / total_units
                cogs += issue_qty * weighted_avg_cost
                total_units -= issue_qty
                total_cost -= issue_qty * weighted_avg_cost
            else:
                raise InventoryException("Insufficient inventory for valuation")

        return total_cost, cogs

    def cycle_count(
        self, expected_levels: list[InventoryLevel], counted_levels: list[InventoryLevel]
    ) -> dict[SKU, dict[str, Decimal]]:
        """
        Perform cycle count variance analysis.

        Args:
            expected_levels: Expected inventory levels
            counted_levels: Physical count results

        Returns:
            Dictionary with variance analysis by SKU
        """
        expected_dict = {level.sku: level for level in expected_levels}
        counted_dict = {level.sku: level for level in counted_levels}
        variances = {}

        for sku, expected in expected_dict.items():
            counted = counted_dict.get(sku)

            if counted is None:
                variance_qty = -expected.quantity_on_hand
                variance_pct = Decimal("-100")
            else:
                variance_qty = counted.quantity_on_hand - expected.quantity_on_hand
                if expected.quantity_on_hand > 0:
                    variance_pct = (variance_qty / expected.quantity_on_hand) * Decimal("100")
                else:
                    variance_pct = Decimal("0") if variance_qty == 0 else Decimal("100")

            variances[sku] = {
                "expected_qty": expected.quantity_on_hand,
                "counted_qty": counted.quantity_on_hand if counted else Decimal("0"),
                "variance_qty": variance_qty,
                "variance_percentage": variance_pct,
                "variance_value": variance_qty * expected.unit_cost,
            }

        return variances

    def multi_echelon_optimization(
        self,
        warehouses: list[Warehouse],
        sku: SKU,
        annual_demand: Decimal,
        order_cost: Decimal,
        holding_cost: Decimal,
        inventory_levels: list[InventoryLevel],
    ) -> dict[UUID, Decimal]:
        """
        Optimize inventory levels across multiple warehouse echelons.

        Args:
            warehouses: List of warehouses in the supply chain
            sku: Stock keeping unit
            annual_demand: Annual demand at lowest echelon
            order_cost: Cost per order
            holding_cost: Annual holding cost per unit
            inventory_levels: Current inventory levels

        Returns:
            Dictionary mapping warehouse IDs to optimal stock levels
        """
        optimal_levels = {}

        for warehouse in warehouses:
            # Demand is proportional to warehouse's share of total demand
            next((l.quantity_on_hand for l in inventory_levels if l.warehouse_id == warehouse.id), Decimal("0"))

            # Calculate optimal level for this warehouse
            eoq = Decimal(str(math.sqrt(float(Decimal(2) * annual_demand * order_cost / holding_cost))))

            # Adjust for warehouse capacity
            capacity_ratio = (warehouse.total_capacity - warehouse.current_utilization) / warehouse.total_capacity
            adjusted_eoq = min(eoq, warehouse.total_capacity * capacity_ratio)

            optimal_levels[warehouse.id] = max(Decimal("0"), adjusted_eoq)

        return optimal_levels
