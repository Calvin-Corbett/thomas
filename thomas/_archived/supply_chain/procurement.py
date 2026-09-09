"""
Procurement and sourcing module for supply chain.

Provides supplier management, supplier scoring, RFQ management, purchase order
lifecycle, contract management, spend analysis, supplier risk assessment, and
lead time tracking.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._exceptions import InvalidSupplierException, ProcurementException
from thomas.supply_chain._types import SKU, OrderLineItem, OrderStatus, PurchaseOrder, Supplier


@dataclass
class SupplierScore:
    """Supplier performance score."""

    supplier_id: UUID
    supplier_name: str
    quality_score: Decimal  # 0-100
    cost_score: Decimal  # 0-100
    delivery_score: Decimal  # 0-100
    responsiveness_score: Decimal  # 0-100
    overall_score: Decimal  # 0-100
    risk_rating: str  # "low", "medium", "high"


@dataclass
class RFQResponse:
    """Response to Request for Quote."""

    supplier_id: UUID
    sku: SKU
    quantity: Decimal
    unit_price: Decimal
    lead_time_days: int
    total_price: Decimal
    terms: str
    validity_days: int = 30


@dataclass
class ContractTerms:
    """Supplier contract terms."""

    contract_id: str
    supplier_id: UUID
    effective_date: datetime
    end_date: datetime
    sku_list: list[SKU]
    minimum_order_quantity: Decimal
    maximum_order_quantity: Decimal
    unit_price: Decimal
    volume_discounts: list[tuple[Decimal, Decimal]]  # (quantity, discount_percentage)
    payment_terms: str
    quality_requirements: str
    delivery_penalties: Decimal = Decimal("0")


@dataclass
class SpendAnalysis:
    """Spend analysis result."""

    sku: SKU
    total_annual_spend: Decimal
    order_count: int
    supplier_count: int
    average_unit_cost: Decimal
    cost_variance: Decimal
    pareto_class: str  # "A", "B", "C"
    savings_opportunity: Decimal


@dataclass
class LeadTimeAnalysis:
    """Lead time tracking and analysis."""

    supplier_id: UUID
    sku: SKU
    average_lead_time_days: Decimal
    minimum_lead_time_days: int
    maximum_lead_time_days: int
    std_deviation: Decimal
    on_time_percentage: Decimal
    variability_index: Decimal


@dataclass
class TotalCostOfOwnership:
    """Total Cost of Ownership (TCO) analysis."""

    sku: SKU
    supplier_id: UUID
    unit_price: Decimal
    quality_cost: Decimal  # Rework, warranty, returns
    logistics_cost: Decimal  # Transportation
    inventory_holding_cost: Decimal
    lead_time_risk_cost: Decimal
    total_cost_per_unit: Decimal


class ProcurementManager:
    """
    Comprehensive procurement and sourcing management system.

    Handles supplier management, RFQ processing, purchase order lifecycle,
    spend analysis, and supplier risk assessment.
    """

    def __init__(self) -> None:
        """Initialize procurement manager."""
        pass

    def score_supplier(
        self,
        supplier: Supplier,
        quality_weight: Decimal = Decimal("0.3"),
        cost_weight: Decimal = Decimal("0.3"),
        delivery_weight: Decimal = Decimal("0.2"),
        responsiveness_weight: Decimal = Decimal("0.2"),
    ) -> SupplierScore:
        """
        Calculate supplier performance score using weighted criteria.

        Args:
            supplier: Supplier to score
            quality_weight: Weight for quality score
            cost_weight: Weight for cost score
            delivery_weight: Weight for delivery score
            responsiveness_weight: Weight for responsiveness score

        Returns:
            SupplierScore with overall rating and risk assessment
        """
        # Base scores from supplier data
        quality_score = supplier.quality_score
        cost_score = supplier.cost_score
        delivery_score = supplier.reliability_score
        responsiveness_score = Decimal("85")  # Default, could come from data

        # Validate weights sum to 1.0
        total_weight = quality_weight + cost_weight + delivery_weight + responsiveness_weight
        if total_weight != Decimal("1"):
            quality_weight = quality_weight / total_weight
            cost_weight = cost_weight / total_weight
            delivery_weight = delivery_weight / total_weight
            responsiveness_weight = responsiveness_weight / total_weight

        # Calculate weighted overall score
        overall_score = (
            quality_score * quality_weight
            + cost_score * cost_weight
            + delivery_score * delivery_weight
            + responsiveness_score * responsiveness_weight
        )

        # Determine risk rating
        if overall_score >= Decimal("85"):
            risk_rating = "low"
        elif overall_score >= Decimal("70"):
            risk_rating = "medium"
        else:
            risk_rating = "high"

        return SupplierScore(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            quality_score=quality_score,
            cost_score=cost_score,
            delivery_score=delivery_score,
            responsiveness_score=responsiveness_score,
            overall_score=overall_score,
            risk_rating=risk_rating,
        )

    def rank_rfq_responses(
        self, responses: list[RFQResponse], supplier_scores: dict[UUID, SupplierScore]
    ) -> list[tuple[RFQResponse, Decimal]]:
        """
        Rank RFQ responses based on price, lead time, and supplier score.

        Args:
            responses: List of RFQ responses
            supplier_scores: Dictionary of supplier scores by ID

        Returns:
            Ranked list of (RFQResponse, score) tuples
        """
        if not responses:
            return []

        # Normalize prices
        min_price = min(r.unit_price for r in responses)
        max_price = max(r.unit_price for r in responses)
        price_range = max_price - min_price if max_price > min_price else Decimal("1")

        # Normalize lead times
        min_lt = min(r.lead_time_days for r in responses)
        max_lt = max(r.lead_time_days for r in responses)
        lt_range = max_lt - min_lt if max_lt > min_lt else 1

        ranked = []
        for response in responses:
            # Price score (lower is better)
            price_score = Decimal("100") - ((response.unit_price - min_price) / price_range * Decimal("100"))

            # Lead time score (lower is better)
            lt_score = (
                Decimal("100") - ((response.lead_time_days - min_lt) / lt_range * Decimal("100"))
                if lt_range > 0
                else Decimal("100")
            )

            # Supplier score
            supplier_score = supplier_scores.get(
                response.supplier_id,
                SupplierScore(
                    supplier_id=response.supplier_id,
                    supplier_name="",
                    quality_score=Decimal("50"),
                    cost_score=Decimal("50"),
                    delivery_score=Decimal("50"),
                    responsiveness_score=Decimal("50"),
                    overall_score=Decimal("50"),
                    risk_rating="medium",
                ),
            )

            # Weighted score
            overall_response_score = (
                price_score * Decimal("0.3") + lt_score * Decimal("0.2") + supplier_score.overall_score * Decimal("0.5")
            )

            ranked.append((response, overall_response_score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def create_purchase_order(
        self,
        supplier: Supplier,
        line_items: list[tuple[SKU, Decimal, Decimal]],  # (sku, quantity, unit_price)
        expected_delivery_days: int = 7,
        incoterm: str = "FOB",
    ) -> PurchaseOrder:
        """
        Create purchase order from supplier and line items.

        Args:
            supplier: Supplier to purchase from
            line_items: List of (SKU, quantity, unit_price) tuples
            expected_delivery_days: Expected delivery lead time
            incoterm: Incoterm (FOB, CIF, etc.)

        Returns:
            Created PurchaseOrder

        Raises:
            InvalidSupplierException: If supplier is not approved
        """
        if not supplier.is_approved:
            raise InvalidSupplierException(str(supplier.id))

        po = PurchaseOrder(
            id=UUID(int=0),
            po_number=f"PO_{int(datetime.utcnow().timestamp())}",
            supplier_id=supplier.id,
            status=OrderStatus.DRAFT,
            expected_delivery=datetime.utcnow() + timedelta(days=expected_delivery_days),
            incoterm=incoterm,
        )

        total_amount = Decimal("0")
        for sku, quantity, unit_price in line_items:
            line_total = quantity * unit_price
            item = OrderLineItem(
                id=UUID(int=0), sku=sku, quantity_ordered=quantity, unit_price=unit_price, line_total=line_total
            )
            po.line_items.append(item)
            total_amount += line_total

        po.total_amount = total_amount
        return po

    def calculate_contract_discount(
        self, base_price: Decimal, order_quantity: Decimal, volume_discounts: list[tuple[Decimal, Decimal]]
    ) -> Decimal:
        """
        Calculate unit price with volume discounts.

        Args:
            base_price: Base unit price
            order_quantity: Order quantity
            volume_discounts: List of (quantity_threshold, discount_percentage) tuples

        Returns:
            Adjusted unit price after discount
        """
        discount = Decimal("0")

        for threshold, discount_pct in volume_discounts:
            if order_quantity >= threshold:
                discount = discount_pct

        return base_price * (Decimal("1") - discount / Decimal("100"))

    def perform_spend_analysis(
        self,
        purchase_orders: list[PurchaseOrder],
        a_threshold: Decimal = Decimal("80"),
        b_threshold: Decimal = Decimal("95"),
    ) -> list[SpendAnalysis]:
        """
        Perform Pareto (ABC) spend analysis.

        Args:
            purchase_orders: List of purchase orders
            a_threshold: Cumulative percentage for A class
            b_threshold: Cumulative percentage for B class

        Returns:
            List of SpendAnalysis results sorted by spend
        """
        # Aggregate spend by SKU
        sku_spend = {}
        for po in purchase_orders:
            for item in po.line_items:
                key = item.sku
                if key not in sku_spend:
                    sku_spend[key] = {"spend": Decimal("0"), "orders": 0, "suppliers": set(), "prices": []}
                sku_spend[key]["spend"] += item.line_total
                sku_spend[key]["orders"] += 1
                sku_spend[key]["suppliers"].add(str(po.supplier_id))
                sku_spend[key]["prices"].append(item.unit_price)

        # Calculate total spend
        total_spend = Decimal(sum(data["spend"] for data in sku_spend.values()))

        # Calculate statistics and classify
        results = []
        cumulative_spend = Decimal("0")

        for sku, data in sorted(sku_spend.items(), key=lambda x: x[1]["spend"], reverse=True):
            cumulative_spend += data["spend"]
            cumulative_pct = (cumulative_spend / total_spend * Decimal("100")) if total_spend > 0 else Decimal("0")

            if cumulative_pct <= a_threshold:
                pareto_class = "A"
            elif cumulative_pct <= b_threshold:
                pareto_class = "B"
            else:
                pareto_class = "C"

            avg_price = Decimal(sum(data["prices"])) / Decimal(len(data["prices"]))
            price_variance = (
                Decimal(str(statistics.variance([float(p) for p in data["prices"]])))
                if len(data["prices"]) > 1
                else Decimal("0")
            )

            # Estimate savings opportunity (5-10% for A items)
            savings_multiplier = Decimal("0.1") if pareto_class == "A" else Decimal("0.05")
            savings = data["spend"] * savings_multiplier

            results.append(
                SpendAnalysis(
                    sku=sku,
                    total_annual_spend=data["spend"],
                    order_count=data["orders"],
                    supplier_count=len(data["suppliers"]),
                    average_unit_cost=avg_price,
                    cost_variance=price_variance,
                    pareto_class=pareto_class,
                    savings_opportunity=savings,
                )
            )

        return results

    def analyze_lead_times(
        self,
        supplier_id: UUID,
        sku: SKU,
        historical_orders: list[tuple[datetime, datetime]],  # (order_date, delivery_date)
    ) -> LeadTimeAnalysis:
        """
        Analyze supplier lead time performance.

        Args:
            supplier_id: Supplier ID
            sku: SKU ordered
            historical_orders: List of (order_date, delivery_date) tuples

        Returns:
            LeadTimeAnalysis with statistics
        """
        if not historical_orders:
            raise ProcurementException("No historical order data for lead time analysis")

        lead_times = []
        on_time = 0

        for order_date, delivery_date in historical_orders:
            lead_time = (delivery_date - order_date).days
            lead_times.append(lead_time)

            if lead_time > 0:
                on_time += 1

        avg_lead_time = Decimal(sum(lead_times)) / Decimal(len(lead_times))
        min_lead_time = min(lead_times)
        max_lead_time = max(lead_times)

        std_dev = (
            Decimal(str(statistics.stdev([float(lt) for lt in lead_times]))) if len(lead_times) > 1 else Decimal("0")
        )
        on_time_pct = Decimal(on_time) / Decimal(len(lead_times)) * Decimal("100")

        # Variability index (std dev / mean)
        variability = std_dev / avg_lead_time if avg_lead_time > 0 else Decimal("0")

        return LeadTimeAnalysis(
            supplier_id=supplier_id,
            sku=sku,
            average_lead_time_days=avg_lead_time,
            minimum_lead_time_days=min_lead_time,
            maximum_lead_time_days=max_lead_time,
            std_deviation=std_dev,
            on_time_percentage=on_time_pct,
            variability_index=variability,
        )

    def calculate_total_cost_of_ownership(
        self,
        sku: SKU,
        supplier_id: UUID,
        unit_price: Decimal,
        quality_defect_rate: Decimal = Decimal("2"),  # percentage
        rework_cost_per_unit: Decimal = Decimal("5"),
        lead_time_days: int = 7,
        safety_stock_cost_per_unit: Decimal = Decimal("2"),
        logistics_cost_per_unit: Decimal = Decimal("1"),
    ) -> TotalCostOfOwnership:
        """
        Calculate Total Cost of Ownership (TCO).

        Args:
            sku: Stock keeping unit
            supplier_id: Supplier ID
            unit_price: Unit price from supplier
            quality_defect_rate: Expected defect rate (percentage)
            rework_cost_per_unit: Cost to rework defective units
            lead_time_days: Lead time in days
            safety_stock_cost_per_unit: Cost to hold safety stock
            logistics_cost_per_unit: Logistics costs per unit

        Returns:
            TotalCostOfOwnership analysis
        """
        # Quality cost
        quality_cost = (unit_price * quality_defect_rate / Decimal("100")) + (
            rework_cost_per_unit * quality_defect_rate / Decimal("100")
        )

        # Lead time risk cost
        lt_risk = Decimal(max(0, lead_time_days - 7)) / Decimal("7") * Decimal("0.05")  # 5% per week variance
        lead_time_risk_cost = unit_price * lt_risk

        # Total cost per unit
        total_cost = (
            unit_price + quality_cost + logistics_cost_per_unit + safety_stock_cost_per_unit + lead_time_risk_cost
        )

        return TotalCostOfOwnership(
            sku=sku,
            supplier_id=supplier_id,
            unit_price=unit_price,
            quality_cost=quality_cost,
            logistics_cost=logistics_cost_per_unit,
            inventory_holding_cost=safety_stock_cost_per_unit,
            lead_time_risk_cost=lead_time_risk_cost,
            total_cost_per_unit=total_cost,
        )

    def assess_supplier_risk(
        self, supplier: Supplier, score: SupplierScore, lead_time_analysis: LeadTimeAnalysis | None = None
    ) -> dict[str, any]:
        """
        Assess supplier risk factors.

        Args:
            supplier: Supplier to assess
            score: Supplier score
            lead_time_analysis: Optional lead time analysis

        Returns:
            Risk assessment dictionary
        """
        risks = []
        risk_score = Decimal("0")

        # Quality risk
        if score.quality_score < Decimal("80"):
            risks.append("Quality performance below standard")
            risk_score += Decimal("20")

        # Cost risk
        if score.cost_score < Decimal("70"):
            risks.append("High cost compared to alternatives")
            risk_score += Decimal("15")

        # Delivery risk
        if score.delivery_score < Decimal("75"):
            risks.append("Poor on-time delivery performance")
            risk_score += Decimal("25")

        # Lead time variability risk
        if lead_time_analysis:
            if lead_time_analysis.variability_index > Decimal("0.3"):
                risks.append("High lead time variability")
                risk_score += Decimal("20")

        # Single supplier risk
        if supplier.primary_products:
            risks.append(f"Concentration risk: {len(supplier.primary_products)} products")
            risk_score += Decimal("10")

        # Overall risk level
        if risk_score >= Decimal("50"):
            risk_level = "high"
        elif risk_score >= Decimal("30"):
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "identified_risks": risks,
            "mitigation_actions": self._generate_mitigation_actions(risks, supplier),
        }

    def _generate_mitigation_actions(self, risks: list[str], supplier: Supplier) -> list[str]:
        """Generate mitigation actions for identified risks."""
        actions = []

        for risk in risks:
            if "Quality" in risk:
                actions.append(f"Implement incoming inspection for all {supplier.name} deliveries")
                actions.append("Establish quality improvement plan with supplier")
            elif "Cost" in risk:
                actions.append("Conduct cost benchmarking with alternative suppliers")
                actions.append(f"Negotiate contract terms with {supplier.name}")
            elif "Delivery" in risk:
                actions.append(f"Request updated delivery schedule from {supplier.name}")
                actions.append("Consider safety stock increase")
            elif "variability" in risk:
                actions.append(f"Establish buffer stock for {supplier.name} products")
                actions.append("Implement just-in-time procurement alternatives")
            elif "Concentration" in risk:
                actions.append("Identify and qualify alternative suppliers")
                actions.append("Develop dual sourcing strategy")

        return list(set(actions))  # Remove duplicates
