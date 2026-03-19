"""
Supply chain analytics and KPI dashboard module.

Provides comprehensive supply chain KPI calculation, bullwhip effect
measurement, total landed cost analysis, supply chain mapping, risk
assessment, and what-if scenario analysis.
"""

import statistics
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._types import SKU, InventoryLevel, PurchaseOrder, Shipment


@dataclass
class KPIDashboard:
    """Supply chain KPI dashboard."""

    otif: Decimal  # On-Time In-Full
    fill_rate: Decimal
    inventory_turns: Decimal
    cash_to_cash_cycle_days: int
    perfect_order_rate: Decimal
    forecast_accuracy: Decimal
    supplier_quality_rate: Decimal
    landed_cost_per_unit: Decimal
    order_fulfillment_cost: Decimal
    supply_chain_cost_percent_revenue: Decimal


@dataclass
class BullwhipMetrics:
    """Bullwhip effect measurement metrics."""

    demand_variance_ratio: Decimal  # Upstream / Downstream
    order_variance_ratio: Decimal
    bullwhip_index: Decimal
    information_distortion: Decimal
    batching_effect: Decimal
    price_variation_effect: Decimal
    interpretation: str


@dataclass
class TotalLandedCost:
    """Total landed cost analysis."""

    sku: SKU
    supplier_id: UUID
    unit_price: Decimal
    quantity: Decimal
    freight_cost: Decimal
    tariffs_duties: Decimal
    insurance: Decimal
    inspection_cost: Decimal
    warehousing_cost: Decimal
    handling_cost: Decimal
    total_landed_cost: Decimal
    cost_per_unit: Decimal
    percentage_breakdown: dict[str, Decimal]


@dataclass
class SupplyChainNode:
    """Node in supply chain network map."""

    node_id: str
    node_type: str  # supplier, warehouse, customer, manufacturer
    name: str
    location: tuple[Decimal, Decimal]
    connections: list["SupplyChainEdge"]


@dataclass
class SupplyChainEdge:
    """Edge/connection in supply chain network."""

    from_node: str
    to_node: str
    transport_mode: str
    lead_time_days: int
    cost_per_unit: Decimal
    volume_capacity: Decimal


@dataclass
class RiskHeatMap:
    """Risk assessment heat map entry."""

    entity_id: str
    entity_name: str
    entity_type: str  # supplier, facility, product, region
    probability: Decimal  # 0-1
    impact: Decimal  # 0-100
    risk_score: Decimal  # 0-100
    category: str  # quality, delivery, financial, regulatory
    mitigation_actions: list[str]


@dataclass
class ScenarioAnalysis:
    """What-if scenario analysis result."""

    scenario_name: str
    scenario_description: str
    variables_changed: dict[str, str]
    base_case_cost: Decimal
    scenario_cost: Decimal
    cost_delta: Decimal
    cost_delta_percent: Decimal
    affected_kpis: dict[str, Decimal]


class SupplyChainAnalytics:
    """
    Comprehensive supply chain analytics system.

    Provides KPI dashboard, bullwhip effect analysis, total landed cost,
    network mapping, risk assessment, and scenario analysis.
    """

    def __init__(self) -> None:
        """Initialize supply chain analytics."""
        pass

    def calculate_kpi_dashboard(
        self,
        shipments: list[Shipment],
        purchase_orders: list[PurchaseOrder],
        inventory_levels: list[InventoryLevel],
        annual_revenue: Decimal,
        supply_chain_costs: Decimal,
        forecast_demand: list[Decimal],
        actual_demand: list[Decimal],
    ) -> KPIDashboard:
        """
        Calculate comprehensive KPI dashboard.

        Args:
            shipments: Recent shipments
            purchase_orders: Recent purchase orders
            inventory_levels: Current inventory levels
            annual_revenue: Annual revenue
            supply_chain_costs: Total supply chain costs
            forecast_demand: Forecasted demands
            actual_demand: Actual demands

        Returns:
            KPIDashboard with all key metrics
        """
        # OTIF: On-Time In-Full
        on_time = sum(1 for s in shipments if s.actual_delivery <= s.expected_delivery) if shipments else 0
        in_full = sum(1 for s in shipments if s.status.value == "delivered") if shipments else 0
        otif = Decimal(on_time) / Decimal(len(shipments)) * Decimal("100") if shipments else Decimal("0")

        # Fill rate
        total_ordered = Decimal(sum(s.line_items[0].quantity_shipped if s.line_items else 0 for s in shipments))
        total_delivered = Decimal(sum(s.line_items[0].quantity_delivered if s.line_items else 0 for s in shipments))
        fill_rate = total_delivered / total_ordered * Decimal("100") if total_ordered > 0 else Decimal("0")

        # Inventory turns
        total_inventory_value = Decimal(sum(level.quantity_on_hand * level.unit_cost for level in inventory_levels))
        cogs = Decimal("0")  # Would come from accounting system
        inventory_turns = supply_chain_costs / total_inventory_value if total_inventory_value > 0 else Decimal("0")

        # Cash-to-cash cycle (Days)
        dpo = 30  # Days payable outstanding (assumed)
        dio = 45  # Days inventory outstanding (estimated)
        dso = 30  # Days sales outstanding (assumed)
        c2c_days = dio + dso - dpo

        # Perfect order rate (on-time, in-full, damage-free)
        perfect_orders = sum(
            1 for s in shipments if (s.actual_delivery <= s.expected_delivery and s.status.value == "delivered")
        )
        perfect_order_rate = (
            Decimal(perfect_orders) / Decimal(len(shipments)) * Decimal("100") if shipments else Decimal("0")
        )

        # Forecast accuracy
        if forecast_demand and actual_demand:
            mape = self._calculate_mape(forecast_demand, actual_demand)
            forecast_accuracy = max(Decimal("0"), Decimal("100") - mape)
        else:
            forecast_accuracy = Decimal("0")

        # Supplier quality rate
        supplier_quality = Decimal("98")  # Would come from inspection data

        # Landed cost per unit
        total_units = total_ordered
        if total_units > 0:
            landed_cost_per_unit = supply_chain_costs / total_units
        else:
            landed_cost_per_unit = Decimal("0")

        # Order fulfillment cost
        order_count = len(shipments)
        order_fulfillment_cost = supply_chain_costs / Decimal(order_count) if order_count > 0 else Decimal("0")

        # SC cost as percent of revenue
        sc_cost_percent = supply_chain_costs / annual_revenue * Decimal("100") if annual_revenue > 0 else Decimal("0")

        return KPIDashboard(
            otif=otif,
            fill_rate=fill_rate,
            inventory_turns=inventory_turns,
            cash_to_cash_cycle_days=c2c_days,
            perfect_order_rate=perfect_order_rate,
            forecast_accuracy=forecast_accuracy,
            supplier_quality_rate=supplier_quality,
            landed_cost_per_unit=landed_cost_per_unit,
            order_fulfillment_cost=order_fulfillment_cost,
            supply_chain_cost_percent_revenue=sc_cost_percent,
        )

    def _calculate_mape(self, forecast: list[Decimal], actual: list[Decimal]) -> Decimal:
        """Calculate Mean Absolute Percentage Error."""
        if len(forecast) != len(actual):
            return Decimal("0")

        errors = []
        for f, a in zip(forecast, actual):
            if a != 0:
                errors.append(abs((a - f) / a) * Decimal("100"))

        return Decimal(sum(errors)) / Decimal(len(errors)) if errors else Decimal("0")

    def measure_bullwhip_effect(
        self,
        customer_orders: list[Decimal],
        retailer_orders: list[Decimal],
        wholesaler_orders: list[Decimal],
        manufacturer_orders: list[Decimal],
    ) -> BullwhipMetrics:
        """
        Measure bullwhip effect across supply chain.

        Args:
            customer_orders: Customer order history
            retailer_orders: Retailer orders to wholesaler
            wholesaler_orders: Wholesaler orders to manufacturer
            manufacturer_orders: Manufacturer orders to supplier

        Returns:
            BullwhipMetrics with effect measurements
        """
        # Calculate variance at each level
        customer_var = (
            Decimal(str(statistics.variance([float(o) for o in customer_orders])))
            if len(customer_orders) > 1
            else Decimal("0")
        )
        retailer_var = (
            Decimal(str(statistics.variance([float(o) for o in retailer_orders])))
            if len(retailer_orders) > 1
            else Decimal("0")
        )
        wholesaler_var = (
            Decimal(str(statistics.variance([float(o) for o in wholesaler_orders])))
            if len(wholesaler_orders) > 1
            else Decimal("0")
        )
        manufacturer_var = (
            Decimal(str(statistics.variance([float(o) for o in manufacturer_orders])))
            if len(manufacturer_orders) > 1
            else Decimal("0")
        )

        # Variance ratios
        demand_var_ratio = retailer_var / customer_var if customer_var > 0 else Decimal("1")
        order_var_ratio = manufacturer_var / customer_var if customer_var > 0 else Decimal("1")

        # Bullwhip index (average variance amplification)
        bullwhip_index = (demand_var_ratio + order_var_ratio) / Decimal("2")

        # Information distortion (caused by lack of visibility)
        info_distortion = max(Decimal("0"), bullwhip_index - Decimal("1"))

        # Batching effect (from order batching)
        batching_effect = Decimal("0.2") if manufacturer_var > retailer_var * Decimal("3") else Decimal("0")

        # Price variation effect
        price_effect = Decimal("0.1")

        # Interpretation
        if bullwhip_index < Decimal("1.2"):
            interpretation = "Excellent - minimal bullwhip effect"
        elif bullwhip_index < Decimal("1.5"):
            interpretation = "Good - moderate bullwhip effect"
        elif bullwhip_index < Decimal("2"):
            interpretation = "Fair - significant bullwhip effect"
        else:
            interpretation = "Poor - severe bullwhip effect detected"

        return BullwhipMetrics(
            demand_variance_ratio=demand_var_ratio,
            order_variance_ratio=order_var_ratio,
            bullwhip_index=bullwhip_index,
            information_distortion=info_distortion,
            batching_effect=batching_effect,
            price_variation_effect=price_effect,
            interpretation=interpretation,
        )

    def calculate_total_landed_cost(
        self,
        sku: SKU,
        supplier_id: UUID,
        unit_price: Decimal,
        quantity: Decimal,
        freight_cost: Decimal = Decimal("0"),
        tariffs: Decimal = Decimal("0"),
        insurance_cost: Decimal = Decimal("0"),
        inspection_cost: Decimal = Decimal("0.5"),
        warehousing_cost: Decimal = Decimal("0.2"),
        handling_cost: Decimal = Decimal("0.3"),
    ) -> TotalLandedCost:
        """
        Calculate total landed cost for a product.

        Args:
            sku: Stock keeping unit
            supplier_id: Supplier ID
            unit_price: Supplier unit price
            quantity: Quantity ordered
            freight_cost: Freight costs
            tariffs: Tariffs and duties
            insurance_cost: Insurance costs
            inspection_cost: Inspection cost per unit
            warehousing_cost: Warehousing cost per unit
            handling_cost: Handling cost per unit

        Returns:
            TotalLandedCost analysis
        """
        total_freight = freight_cost
        total_tariffs = tariffs
        total_insurance = insurance_cost
        total_inspection = Decimal(inspection_cost) * quantity
        total_warehousing = Decimal(warehousing_cost) * quantity
        total_handling = Decimal(handling_cost) * quantity

        total_landed = (
            (unit_price * quantity)
            + total_freight
            + total_tariffs
            + total_insurance
            + total_inspection
            + total_warehousing
            + total_handling
        )

        cost_per_unit = total_landed / quantity if quantity > 0 else Decimal("0")

        # Breakdown percentages
        total_cost = total_landed
        breakdown = {
            "unit_price": (unit_price * quantity / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "freight": (total_freight / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "tariffs": (total_tariffs / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "insurance": (total_insurance / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "inspection": (total_inspection / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "warehousing": (total_warehousing / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
            "handling": (total_handling / total_cost * Decimal("100") if total_cost > 0 else Decimal("0")),
        }

        return TotalLandedCost(
            sku=sku,
            supplier_id=supplier_id,
            unit_price=unit_price,
            quantity=quantity,
            freight_cost=total_freight,
            tariffs_duties=total_tariffs,
            insurance=total_insurance,
            inspection_cost=total_inspection,
            warehousing_cost=total_warehousing,
            handling_cost=total_handling,
            total_landed_cost=total_landed,
            cost_per_unit=cost_per_unit,
            percentage_breakdown=breakdown,
        )

    def build_supply_chain_map(
        self,
        suppliers: list[tuple[str, str, tuple[Decimal, Decimal]]],  # (id, name, location)
        warehouses: list[tuple[str, str, tuple[Decimal, Decimal]]],
        customers: list[tuple[str, str, tuple[Decimal, Decimal]]],
        connections: list[tuple[str, str, str, int, Decimal]],  # (from, to, mode, lead_time, cost)
    ) -> dict[str, any]:
        """
        Build supply chain network map.

        Args:
            suppliers: Supplier nodes
            warehouses: Warehouse nodes
            customers: Customer nodes
            connections: Edges between nodes

        Returns:
            Dictionary with network map structure
        """
        nodes = []

        for node_id, name, location in suppliers:
            nodes.append({"id": node_id, "type": "supplier", "name": name, "location": location})

        for node_id, name, location in warehouses:
            nodes.append({"id": node_id, "type": "warehouse", "name": name, "location": location})

        for node_id, name, location in customers:
            nodes.append({"id": node_id, "type": "customer", "name": name, "location": location})

        edges = []
        for from_node, to_node, transport_mode, lead_time, cost in connections:
            edges.append(
                {
                    "from": from_node,
                    "to": to_node,
                    "transport_mode": transport_mode,
                    "lead_time_days": lead_time,
                    "cost_per_unit": float(cost),
                }
            )

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "supplier_count": len(suppliers),
            "warehouse_count": len(warehouses),
            "customer_count": len(customers),
        }

    def create_risk_heat_map(
        self,
        suppliers: list[tuple[UUID, str, Decimal, Decimal]],  # (id, name, prob, impact)
        products: list[tuple[UUID, str, Decimal, Decimal]],
        facilities: list[tuple[UUID, str, Decimal, Decimal]],
        regions: list[tuple[str, Decimal, Decimal]],
    ) -> list[RiskHeatMap]:
        """
        Create risk heat map for supply chain entities.

        Args:
            suppliers: Supplier risks (id, name, probability, impact)
            products: Product risks
            facilities: Facility risks
            regions: Regional risks

        Returns:
            List of RiskHeatMap entries
        """
        heat_map = []

        for entity_id, name, prob, impact in suppliers:
            risk_score = prob * impact
            category = "delivery" if prob > Decimal("0.3") else "quality"

            mitigations = [
                f"Diversify suppliers away from {name}",
                f"Increase safety stock for products from {name}",
                "Establish backup supplier relationships",
            ]

            heat_map.append(
                RiskHeatMap(
                    entity_id=str(entity_id),
                    entity_name=name,
                    entity_type="supplier",
                    probability=prob,
                    impact=impact,
                    risk_score=risk_score,
                    category=category,
                    mitigation_actions=mitigations,
                )
            )

        for entity_id, name, prob, impact in products:
            risk_score = prob * impact
            heat_map.append(
                RiskHeatMap(
                    entity_id=str(entity_id),
                    entity_name=name,
                    entity_type="product",
                    probability=prob,
                    impact=impact,
                    risk_score=risk_score,
                    category="quality",
                    mitigation_actions=[f"Increase QC for {name}"],
                )
            )

        for entity_id, name, prob, impact in facilities:
            risk_score = prob * impact
            heat_map.append(
                RiskHeatMap(
                    entity_id=str(entity_id),
                    entity_name=name,
                    entity_type="facility",
                    probability=prob,
                    impact=impact,
                    risk_score=risk_score,
                    category="operational",
                    mitigation_actions=[f"Disaster recovery plan for {name}"],
                )
            )

        for region, prob, impact in regions:
            risk_score = prob * impact
            heat_map.append(
                RiskHeatMap(
                    entity_id=region,
                    entity_name=region,
                    entity_type="region",
                    probability=prob,
                    impact=impact,
                    risk_score=risk_score,
                    category="regulatory",
                    mitigation_actions=["Regional diversification strategy"],
                )
            )

        return sorted(heat_map, key=lambda x: x.risk_score, reverse=True)

    def scenario_analysis(
        self,
        base_case_cost: Decimal,
        scenario_name: str,
        scenario_description: str,
        variable_changes: dict[str, tuple[Decimal, Decimal]],  # (original, new)
        kpi_impact: dict[str, Decimal],
    ) -> ScenarioAnalysis:
        """
        Perform what-if scenario analysis.

        Args:
            base_case_cost: Base case total cost
            scenario_name: Scenario name
            scenario_description: Scenario description
            variable_changes: Variables changed with (original, new) values
            kpi_impact: Impact on KPIs

        Returns:
            ScenarioAnalysis result
        """
        # Calculate scenario cost based on variable changes
        # Simplified: assume first variable is cost multiplier
        cost_multiplier = Decimal("1")
        for var_name, (original, new) in variable_changes.items():
            if "cost" in var_name.lower() or "price" in var_name.lower():
                if original != 0:
                    cost_multiplier *= new / original

        scenario_cost = base_case_cost * cost_multiplier
        cost_delta = scenario_cost - base_case_cost
        cost_delta_pct = cost_delta / base_case_cost * Decimal("100") if base_case_cost > 0 else Decimal("0")

        variables_str = {k: f"{float(v[0])} -> {float(v[1])}" for k, v in variable_changes.items()}

        return ScenarioAnalysis(
            scenario_name=scenario_name,
            scenario_description=scenario_description,
            variables_changed=variables_str,
            base_case_cost=base_case_cost,
            scenario_cost=scenario_cost,
            cost_delta=cost_delta,
            cost_delta_percent=cost_delta_pct,
            affected_kpis=kpi_impact,
        )
