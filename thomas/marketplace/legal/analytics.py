"""Legal practice analytics and business intelligence module."""

import logging
from datetime import date, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class CaseAnalytics:
    """Analyzes individual case profitability and performance."""

    def __init__(
        self,
        case_id: str,
        case_name: str,
        client_id: str,
    ) -> None:
        """Initialize case analytics."""
        self.case_id = case_id
        self.case_name = case_name
        self.client_id = client_id
        self.revenue = Decimal("0.00")
        self.costs = Decimal("0.00")
        self.billable_hours = Decimal("0.00")
        self.total_hours = Decimal("0.00")
        self.created_at = datetime.now()

    def calculate_profitability(self) -> dict[str, Decimal]:
        """Calculate profitability metrics for the case."""
        profit = self.revenue - self.costs

        return {
            "revenue": self.revenue,
            "costs": self.costs,
            "gross_profit": profit,
            "profit_margin": ((profit / self.revenue * 100) if self.revenue > 0 else Decimal("0.00")),
            "cost_ratio": ((self.costs / self.revenue * 100) if self.revenue > 0 else Decimal("0.00")),
        }


class AttorneyAnalytics:
    """Analyzes individual attorney utilization and productivity."""

    def __init__(self, attorney_id: str, attorney_name: str) -> None:
        """Initialize attorney analytics."""
        self.attorney_id = attorney_id
        self.attorney_name = attorney_name
        self.billable_hours = Decimal("0.00")
        self.non_billable_hours = Decimal("0.00")
        self.billed_amount = Decimal("0.00")
        self.collected_amount = Decimal("0.00")

    def calculate_utilization(
        self,
        available_hours: Decimal,
    ) -> Decimal:
        """Calculate utilization rate: billable_hours / available_hours."""
        if available_hours == 0:
            return Decimal("0.00")

        return self.billable_hours / available_hours * 100

    def calculate_realization_rate(self) -> Decimal:
        """Calculate realization rate: billed / worked."""
        if self.billable_hours == 0:
            return Decimal("1.00")

        if self.billed_amount == 0:
            return Decimal("0.00")

        return self.collected_amount / self.billed_amount * 100


class AnalyticsManager:
    """Manages legal practice analytics and reporting."""

    def __init__(self) -> None:
        """Initialize the analytics manager."""
        self.case_analytics: dict[str, CaseAnalytics] = {}
        self.attorney_analytics: dict[str, AttorneyAnalytics] = {}
        self.budgets: dict[str, dict] = {}  # case_id -> budget
        self.aging_receivables: list[dict] = []

    def create_case_analytics(
        self,
        case_id: str,
        case_name: str,
        client_id: str,
    ) -> CaseAnalytics:
        """Create analytics tracking for a case."""
        analytics = CaseAnalytics(case_id, case_name, client_id)
        self.case_analytics[case_id] = analytics
        logger.info(f"Created case analytics for {case_id}")
        return analytics

    def update_case_revenue(
        self,
        case_id: str,
        amount: Decimal,
    ) -> CaseAnalytics:
        """Record revenue for a case."""
        if case_id not in self.case_analytics:
            raise ValueError(f"Case {case_id} not found")

        analytics = self.case_analytics[case_id]
        analytics.revenue += amount
        logger.info(f"Updated revenue for case {case_id}: +${amount}")
        return analytics

    def update_case_costs(
        self,
        case_id: str,
        amount: Decimal,
    ) -> CaseAnalytics:
        """Record costs for a case."""
        if case_id not in self.case_analytics:
            raise ValueError(f"Case {case_id} not found")

        analytics = self.case_analytics[case_id]
        analytics.costs += amount
        logger.info(f"Updated costs for case {case_id}: +${amount}")
        return analytics

    def update_case_hours(
        self,
        case_id: str,
        billable_hours: Decimal,
        total_hours: Decimal,
    ) -> CaseAnalytics:
        """Update billable and total hours for a case."""
        if case_id not in self.case_analytics:
            raise ValueError(f"Case {case_id} not found")

        analytics = self.case_analytics[case_id]
        analytics.billable_hours += billable_hours
        analytics.total_hours += total_hours
        return analytics

    def set_case_budget(
        self,
        case_id: str,
        total_budget: Decimal,
        budget_by_phase: dict[str, Decimal] | None = None,
    ) -> None:
        """Set budget for a case with optional phase breakdown."""
        self.budgets[case_id] = {
            "total": total_budget,
            "by_phase": budget_by_phase or {},
            "created_at": datetime.now(),
        }

    def get_budget_vs_actual(
        self,
        case_id: str,
    ) -> dict[str, object]:
        """Compare budget vs actual spend for a case."""
        if case_id not in self.budgets:
            return {"status": "no_budget"}

        if case_id not in self.case_analytics:
            return {"status": "no_analytics"}

        budget = self.budgets[case_id]["total"]
        analytics = self.case_analytics[case_id]

        variance = analytics.costs - budget
        variance_pct = (variance / budget * 100) if budget > 0 else Decimal("0.00")

        return {
            "case_id": case_id,
            "budget": budget,
            "actual_spend": analytics.costs,
            "variance": variance,
            "variance_percent": variance_pct,
            "status": ("under_budget" if variance < 0 else "over_budget" if variance > 0 else "on_budget"),
            "remaining": budget - analytics.costs,
        }

    def create_attorney_analytics(
        self,
        attorney_id: str,
        attorney_name: str,
    ) -> AttorneyAnalytics:
        """Create analytics tracking for an attorney."""
        analytics = AttorneyAnalytics(attorney_id, attorney_name)
        self.attorney_analytics[attorney_id] = analytics
        logger.info(f"Created attorney analytics for {attorney_id}")
        return analytics

    def update_attorney_hours(
        self,
        attorney_id: str,
        billable_hours: Decimal,
        non_billable_hours: Decimal,
    ) -> AttorneyAnalytics:
        """Update hours for an attorney."""
        if attorney_id not in self.attorney_analytics:
            raise ValueError(f"Attorney {attorney_id} not found")

        analytics = self.attorney_analytics[attorney_id]
        analytics.billable_hours += billable_hours
        analytics.non_billable_hours += non_billable_hours
        return analytics

    def update_attorney_billing(
        self,
        attorney_id: str,
        billed_amount: Decimal,
        collected_amount: Decimal,
    ) -> AttorneyAnalytics:
        """Update billing amounts for an attorney."""
        if attorney_id not in self.attorney_analytics:
            raise ValueError(f"Attorney {attorney_id} not found")

        analytics = self.attorney_analytics[attorney_id]
        analytics.billed_amount += billed_amount
        analytics.collected_amount += collected_amount
        return analytics

    def get_attorney_utilization(
        self,
        attorney_id: str,
        available_hours: Decimal,
    ) -> dict[str, object]:
        """Get utilization metrics for an attorney."""
        if attorney_id not in self.attorney_analytics:
            raise ValueError(f"Attorney {attorney_id} not found")

        analytics = self.attorney_analytics[attorney_id]
        utilization = analytics.calculate_utilization(available_hours)
        total_hours = analytics.billable_hours + analytics.non_billable_hours

        return {
            "attorney_id": attorney_id,
            "billable_hours": analytics.billable_hours,
            "non_billable_hours": analytics.non_billable_hours,
            "total_hours": total_hours,
            "available_hours": available_hours,
            "utilization_rate": utilization,
            "target_utilization": Decimal("80.00"),
            "status": ("above_target" if utilization > 80 else "below_target"),
        }

    def get_attorney_realization(
        self,
        attorney_id: str,
    ) -> dict[str, object]:
        """Get realization rate for an attorney."""
        if attorney_id not in self.attorney_analytics:
            raise ValueError(f"Attorney {attorney_id} not found")

        analytics = self.attorney_analytics[attorney_id]

        return {
            "attorney_id": attorney_id,
            "billed_amount": analytics.billed_amount,
            "collected_amount": analytics.collected_amount,
            "realization_rate": analytics.calculate_realization_rate(),
            "write_offs": (analytics.billed_amount - analytics.collected_amount),
        }

    def track_aging_receivable(
        self,
        invoice_id: str,
        client_id: str,
        amount: Decimal,
        invoice_date: date,
        status: str,
    ) -> None:
        """Track aging of accounts receivable."""
        days_outstanding = (date.today() - invoice_date).days

        self.aging_receivables.append(
            {
                "invoice_id": invoice_id,
                "client_id": client_id,
                "amount": amount,
                "invoice_date": invoice_date,
                "days_outstanding": days_outstanding,
                "status": status,
                "bucket": self._categorize_aging_bucket(days_outstanding),
            }
        )

    def get_aging_receivables_summary(self) -> dict[str, object]:
        """Get summary of aging receivables by age bucket."""
        if not self.aging_receivables:
            return {
                "total_outstanding": Decimal("0.00"),
                "by_bucket": {},
                "over_90_days": Decimal("0.00"),
            }

        by_bucket = {
            "current": Decimal("0.00"),
            "30_60": Decimal("0.00"),
            "60_90": Decimal("0.00"),
            "over_90": Decimal("0.00"),
        }

        for receivable in self.aging_receivables:
            if receivable["status"] != "paid":
                bucket = receivable["bucket"]
                by_bucket[bucket] += receivable["amount"]

        total = sum(by_bucket.values())
        over_90 = by_bucket["over_90"]

        return {
            "total_outstanding": total,
            "by_bucket": by_bucket,
            "over_90_days": over_90,
            "over_90_percent": ((over_90 / total * 100) if total > 0 else Decimal("0.00")),
        }

    def get_practice_area_performance(
        self,
        case_analytics_by_practice_area: dict[str, list[CaseAnalytics]],
    ) -> dict[str, object]:
        """Analyze profitability by practice area."""
        performance = {}

        for area, cases in case_analytics_by_practice_area.items():
            if not cases:
                continue

            total_revenue = sum(c.revenue for c in cases)
            total_costs = sum(c.costs for c in cases)
            total_hours = sum(c.total_hours for c in cases)

            performance[area] = {
                "case_count": len(cases),
                "revenue": total_revenue,
                "costs": total_costs,
                "profit": total_revenue - total_costs,
                "profit_margin": (
                    ((total_revenue - total_costs) / total_revenue * 100) if total_revenue > 0 else Decimal("0.00")
                ),
                "revenue_per_hour": ((total_revenue / total_hours) if total_hours > 0 else Decimal("0.00")),
            }

        return performance

    def get_client_concentration(
        self,
        case_analytics_list: list[CaseAnalytics],
    ) -> dict[str, object]:
        """Analyze client concentration risk."""
        by_client: dict[str, Decimal] = {}

        for analytics in case_analytics_list:
            if analytics.client_id not in by_client:
                by_client[analytics.client_id] = Decimal("0.00")
            by_client[analytics.client_id] += analytics.revenue

        total_revenue = sum(by_client.values())

        if total_revenue == 0:
            return {
                "concentration_ratio": Decimal("0.00"),
                "top_clients": [],
                "risk_level": "low",
            }

        # Calculate Herfindahl index (concentration)
        herfindahl = sum(((revenue / total_revenue) ** 2) * 10000 for revenue in by_client.values())

        top_clients = sorted(
            by_client.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        risk_level = "high" if herfindahl > 2500 else "medium" if herfindahl > 1500 else "low"

        return {
            "total_revenue": total_revenue,
            "concentration_ratio": herfindahl / 10000,
            "top_clients": [{"client_id": cid, "revenue": rev} for cid, rev in top_clients],
            "risk_level": risk_level,
        }

    @staticmethod
    def _categorize_aging_bucket(days: int) -> str:
        """Categorize days outstanding into aging buckets."""
        if days <= 30:
            return "current"
        elif days <= 60:
            return "30_60"
        elif days <= 90:
            return "60_90"
        else:
            return "over_90"
