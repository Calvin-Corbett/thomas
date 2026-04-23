"""
Deal management for the CRM system.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from thomas.marketplace.crm._exceptions import DealNotFoundError
from thomas.marketplace.crm._types import Deal


class DealManager:
    """Manages deals in the CRM system.

    Handles CRUD operations, deal scoring, aging alerts, competitive tracking,
    line item management, win/loss analysis, and deal cloning.
    """

    def __init__(self) -> None:
        """Initialize the deal manager."""
        self._deals: dict[str, Deal] = {}
        self._deal_scores: dict[str, float] = {}
        self._competitive_deals: dict[str, list[str]] = {}

    def create_deal(
        self,
        name: str,
        company_id: str,
        contact_id: str,
        stage_id: str,
        value: Decimal,
        probability: int,
        expected_close: datetime,
        owner: str,
        products: list[dict[str, Any]] | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> Deal:
        """Create a new deal.

        Args:
            name: Deal name
            company_id: Associated company ID
            contact_id: Primary contact ID
            stage_id: Initial pipeline stage ID
            value: Deal value
            probability: Win probability (0-100)
            expected_close: Expected close date
            owner: Sales rep/owner
            products: List of products/line items
            custom_fields: Additional custom fields

        Returns:
            Created Deal object
        """
        deal_id = str(uuid.uuid4())

        deal = Deal(
            id=deal_id,
            name=name,
            company_id=company_id,
            contact_id=contact_id,
            stage_id=stage_id,
            value=value,
            probability=probability,
            expected_close=expected_close,
            owner=owner,
            products=products or [],
            custom_fields=custom_fields or {},
        )

        self._deals[deal_id] = deal
        self._deal_scores[deal_id] = 50.0  # Default score

        return deal

    def get_deal(self, deal_id: str) -> Deal:
        """Get a deal by ID.

        Args:
            deal_id: Deal identifier

        Returns:
            Deal object

        Raises:
            DealNotFoundError: If deal not found
        """
        if deal_id not in self._deals:
            raise DealNotFoundError(f"Deal {deal_id} not found")
        return self._deals[deal_id]

    def update_deal(self, deal_id: str, **kwargs: Any) -> Deal:
        """Update a deal's information.

        Args:
            deal_id: Deal identifier
            **kwargs: Fields to update

        Returns:
            Updated Deal object

        Raises:
            DealNotFoundError: If deal not found
        """
        deal = self.get_deal(deal_id)

        for key, value in kwargs.items():
            if hasattr(deal, key):
                setattr(deal, key, value)

        return deal

    def delete_deal(self, deal_id: str) -> None:
        """Delete a deal.

        Args:
            deal_id: Deal identifier

        Raises:
            DealNotFoundError: If deal not found
        """
        if deal_id not in self._deals:
            raise DealNotFoundError(f"Deal {deal_id} not found")

        del self._deals[deal_id]
        if deal_id in self._deal_scores:
            del self._deal_scores[deal_id]
        if deal_id in self._competitive_deals:
            del self._competitive_deals[deal_id]

    def list_deals(self) -> list[Deal]:
        """Get all deals.

        Returns:
            List of Deal objects
        """
        return list(self._deals.values())

    def search_deals(
        self,
        name: str | None = None,
        owner: str | None = None,
        company_id: str | None = None,
        contact_id: str | None = None,
        min_value: Decimal | None = None,
        max_value: Decimal | None = None,
    ) -> list[Deal]:
        """Search for deals.

        Args:
            name: Deal name (partial match)
            owner: Deal owner name
            company_id: Company ID
            contact_id: Contact ID
            min_value: Minimum deal value
            max_value: Maximum deal value

        Returns:
            List of matching Deal objects
        """
        results = list(self._deals.values())

        if name:
            name_lower = name.lower()
            results = [d for d in results if name_lower in d.name.lower()]

        if owner:
            owner_lower = owner.lower()
            results = [d for d in results if owner_lower in d.owner.lower()]

        if company_id:
            results = [d for d in results if d.company_id == company_id]

        if contact_id:
            results = [d for d in results if d.contact_id == contact_id]

        if min_value:
            results = [d for d in results if d.value >= min_value]

        if max_value:
            results = [d for d in results if d.value <= max_value]

        return results

    def calculate_deal_score(
        self,
        deal_id: str,
        size_weight: float = 0.25,
        probability_weight: float = 0.25,
        engagement_weight: float = 0.25,
        timeline_weight: float = 0.25,
    ) -> float:
        """Calculate a deal score based on weighted factors.

        Args:
            deal_id: Deal identifier
            size_weight: Weight for deal size (0-1)
            probability_weight: Weight for probability (0-1)
            engagement_weight: Weight for engagement (0-1)
            timeline_weight: Weight for timeline (0-1)

        Returns:
            Deal score (0-100)

        Raises:
            DealNotFoundError: If deal not found
        """
        deal = self.get_deal(deal_id)

        # Normalize deal size (max 100k assumed)
        size_score = min((float(deal.value) / 100000.0) * 100, 100.0)

        # Probability is already 0-100
        probability_score = float(deal.probability)

        # Engagement score based on activities (0-100, simplified)
        engagement_score = 50.0  # Default mid-range

        # Timeline score: closer deadline = higher score
        days_until_close = (deal.expected_close - datetime.utcnow()).days
        if days_until_close < 0:
            timeline_score = 0.0
        elif days_until_close < 30:
            timeline_score = 100.0
        elif days_until_close < 90:
            timeline_score = 70.0
        else:
            timeline_score = 30.0

        # Calculate weighted score
        total_weight = size_weight + probability_weight + engagement_weight + timeline_weight

        if total_weight == 0:
            total_weight = 1.0

        score = (
            (size_score * size_weight)
            + (probability_score * probability_weight)
            + (engagement_score * engagement_weight)
            + (timeline_score * timeline_weight)
        ) / total_weight

        self._deal_scores[deal_id] = score
        return score

    def get_deal_score(self, deal_id: str) -> float:
        """Get the current deal score.

        Args:
            deal_id: Deal identifier

        Returns:
            Deal score (0-100)

        Raises:
            DealNotFoundError: If deal not found
        """
        self.get_deal(deal_id)
        return self._deal_scores.get(deal_id, 50.0)

    def get_aging_deals(
        self,
        days_threshold: int = 30,
    ) -> list[dict[str, Any]]:
        """Get deals that are aging (overdue or close to expiration).

        Args:
            days_threshold: Number of days past expected close to consider aging

        Returns:
            List of aging deals with details
        """
        aging = []
        now = datetime.utcnow()

        for deal in self._deals.values():
            days_overdue = (now - deal.expected_close).days

            if days_overdue > 0:  # Deal is past expected close
                aging.append(
                    {
                        "deal_id": deal.id,
                        "deal_name": deal.name,
                        "owner": deal.owner,
                        "value": deal.value,
                        "days_overdue": days_overdue,
                        "status": "overdue",
                    }
                )

        return sorted(aging, key=lambda x: x["days_overdue"], reverse=True)

    def add_product_to_deal(
        self,
        deal_id: str,
        product_name: str,
        quantity: int,
        unit_price: Decimal,
    ) -> None:
        """Add a product/line item to a deal.

        Args:
            deal_id: Deal identifier
            product_name: Product name
            quantity: Quantity
            unit_price: Unit price

        Raises:
            DealNotFoundError: If deal not found
        """
        deal = self.get_deal(deal_id)

        product = {
            "id": str(uuid.uuid4()),
            "name": product_name,
            "quantity": quantity,
            "unit_price": str(unit_price),
            "total": str(unit_price * Decimal(quantity)),
        }

        deal.products.append(product)

    def remove_product_from_deal(
        self,
        deal_id: str,
        product_id: str,
    ) -> None:
        """Remove a product/line item from a deal.

        Args:
            deal_id: Deal identifier
            product_id: Product ID

        Raises:
            DealNotFoundError: If deal not found
        """
        deal = self.get_deal(deal_id)

        deal.products = [p for p in deal.products if p["id"] != product_id]

    def add_competitor(
        self,
        deal_id: str,
        competitor_name: str,
    ) -> None:
        """Track a competitor in a deal.

        Args:
            deal_id: Deal identifier
            competitor_name: Name of competing vendor

        Raises:
            DealNotFoundError: If deal not found
        """
        self.get_deal(deal_id)

        if deal_id not in self._competitive_deals:
            self._competitive_deals[deal_id] = []

        if competitor_name not in self._competitive_deals[deal_id]:
            self._competitive_deals[deal_id].append(competitor_name)

    def get_competitors(self, deal_id: str) -> list[str]:
        """Get all competitors tracked for a deal.

        Args:
            deal_id: Deal identifier

        Returns:
            List of competitor names

        Raises:
            DealNotFoundError: If deal not found
        """
        self.get_deal(deal_id)
        return self._competitive_deals.get(deal_id, []).copy()

    def clone_deal(
        self,
        deal_id: str,
        new_name: str,
        contact_id: str | None = None,
        probability: int | None = None,
    ) -> Deal:
        """Clone a deal to create a similar opportunity.

        Args:
            deal_id: Deal to clone
            new_name: Name for the new deal
            contact_id: Contact for the new deal (defaults to original)
            probability: Probability for the new deal (defaults to original)

        Returns:
            Cloned Deal object

        Raises:
            DealNotFoundError: If deal not found
        """
        original_deal = self.get_deal(deal_id)

        new_deal = Deal(
            id=str(uuid.uuid4()),
            name=new_name,
            company_id=original_deal.company_id,
            contact_id=contact_id or original_deal.contact_id,
            stage_id=original_deal.stage_id,
            value=original_deal.value,
            probability=probability or original_deal.probability,
            expected_close=original_deal.expected_close,
            owner=original_deal.owner,
            products=original_deal.products.copy(),
            custom_fields=original_deal.custom_fields.copy(),
        )

        self._deals[new_deal.id] = new_deal
        self._deal_scores[new_deal.id] = self._deal_scores.get(deal_id, 50.0)

        # Clone competitive deals
        if deal_id in self._competitive_deals:
            self._competitive_deals[new_deal.id] = self._competitive_deals[deal_id].copy()

        return new_deal

    def analyze_win_loss(
        self,
        closed_won_deals: list[str],
        closed_lost_deals: list[str],
    ) -> dict[str, Any]:
        """Analyze win/loss patterns.

        Args:
            closed_won_deals: List of won deal IDs
            closed_lost_deals: List of lost deal IDs

        Returns:
            Dictionary with win/loss statistics
        """
        won_deals = [self.get_deal(d) for d in closed_won_deals]
        lost_deals = [self.get_deal(d) for d in closed_lost_deals]

        total_deals = len(won_deals) + len(lost_deals)
        win_rate = (len(won_deals) / total_deals * 100) if total_deals > 0 else 0

        avg_won_value = sum(d.value for d in won_deals) / len(won_deals) if won_deals else Decimal(0)

        avg_lost_value = sum(d.value for d in lost_deals) / len(lost_deals) if lost_deals else Decimal(0)

        # Identify common competitors in lost deals
        lost_competitors: dict[str, int] = {}
        for deal_id in closed_lost_deals:
            competitors = self.get_competitors(deal_id)
            for comp in competitors:
                lost_competitors[comp] = lost_competitors.get(comp, 0) + 1

        return {
            "total_deals": total_deals,
            "won_deals": len(won_deals),
            "lost_deals": len(lost_deals),
            "win_rate": win_rate,
            "avg_won_value": avg_won_value,
            "avg_lost_value": avg_lost_value,
            "top_competitors": sorted(lost_competitors.items(), key=lambda x: x[1], reverse=True)[:5],
        }

    def get_deals_by_owner(self, owner: str) -> list[Deal]:
        """Get all deals for a specific owner.

        Args:
            owner: Owner name

        Returns:
            List of Deal objects owned by the owner
        """
        return [d for d in self._deals.values() if d.owner == owner]

    def get_deals_by_company(self, company_id: str) -> list[Deal]:
        """Get all deals for a company.

        Args:
            company_id: Company identifier

        Returns:
            List of Deal objects for the company
        """
        return [d for d in self._deals.values() if d.company_id == company_id]
