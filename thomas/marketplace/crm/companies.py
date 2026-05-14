"""
Company management system for the CRM.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from thomas.marketplace.crm._exceptions import CompanyNotFoundError
from thomas.marketplace.crm._types import Company


class CompanyManager:
    """Manages companies in the CRM system.

    Handles CRUD operations, hierarchy management, contact association,
    health scoring, industry classification, and timeline tracking.
    """

    def __init__(self) -> None:
        """Initialize the company manager."""
        self._companies: dict[str, Company] = {}
        self._company_activities: dict[str, list[dict[str, Any]]] = {}

    def create_company(
        self,
        name: str,
        domain: str | None = None,
        industry: str | None = None,
        size: int | None = None,
        revenue: Decimal | None = None,
        parent_company_id: str | None = None,
    ) -> Company:
        """Create a new company.

        Args:
            name: Company name
            domain: Company website domain
            industry: Industry classification
            size: Number of employees
            revenue: Annual revenue
            parent_company_id: Parent company ID for subsidiaries

        Returns:
            Created Company object
        """
        company_id = str(uuid.uuid4())

        company = Company(
            id=company_id,
            name=name,
            domain=domain,
            industry=industry,
            size=size,
            revenue=revenue,
            parent_company_id=parent_company_id,
        )

        self._companies[company_id] = company
        self._company_activities[company_id] = []

        return company

    def get_company(self, company_id: str) -> Company:
        """Get a company by ID.

        Args:
            company_id: Company identifier

        Returns:
            Company object

        Raises:
            CompanyNotFoundError: If company not found
        """
        if company_id not in self._companies:
            raise CompanyNotFoundError(f"Company {company_id} not found")
        return self._companies[company_id]

    def update_company(self, company_id: str, **kwargs: Any) -> Company:
        """Update a company's information.

        Args:
            company_id: Company identifier
            **kwargs: Fields to update

        Returns:
            Updated Company object

        Raises:
            CompanyNotFoundError: If company not found
        """
        company = self.get_company(company_id)

        for key, value in kwargs.items():
            if hasattr(company, key):
                setattr(company, key, value)

        return company

    def delete_company(self, company_id: str) -> None:
        """Delete a company.

        Args:
            company_id: Company identifier

        Raises:
            CompanyNotFoundError: If company not found
        """
        if company_id not in self._companies:
            raise CompanyNotFoundError(f"Company {company_id} not found")

        del self._companies[company_id]
        if company_id in self._company_activities:
            del self._company_activities[company_id]

    def list_companies(self) -> list[Company]:
        """Get all companies.

        Returns:
            List of Company objects
        """
        return list(self._companies.values())

    def search_companies(
        self,
        name: str | None = None,
        industry: str | None = None,
        domain: str | None = None,
    ) -> list[Company]:
        """Search for companies.

        Args:
            name: Company name (partial match)
            industry: Industry classification
            domain: Company domain

        Returns:
            List of matching Company objects
        """
        results = list(self._companies.values())

        if name:
            name_lower = name.lower()
            results = [c for c in results if name_lower in c.name.lower()]

        if industry:
            industry_lower = industry.lower()
            results = [c for c in results if c.industry and industry_lower in c.industry.lower()]

        if domain:
            domain_lower = domain.lower()
            results = [c for c in results if c.domain and domain_lower in c.domain.lower()]

        return results

    def add_contact_to_company(
        self,
        company_id: str,
        contact_id: str,
    ) -> None:
        """Associate a contact with a company.

        Args:
            company_id: Company identifier
            contact_id: Contact identifier

        Raises:
            CompanyNotFoundError: If company not found
        """
        company = self.get_company(company_id)

        if contact_id not in company.contacts:
            company.contacts.append(contact_id)

    def remove_contact_from_company(
        self,
        company_id: str,
        contact_id: str,
    ) -> None:
        """Remove a contact from a company.

        Args:
            company_id: Company identifier
            contact_id: Contact identifier

        Raises:
            CompanyNotFoundError: If company not found
        """
        company = self.get_company(company_id)

        if contact_id in company.contacts:
            company.contacts.remove(contact_id)

    def get_company_contacts(self, company_id: str) -> list[str]:
        """Get all contact IDs for a company.

        Args:
            company_id: Company identifier

        Returns:
            List of contact IDs

        Raises:
            CompanyNotFoundError: If company not found
        """
        company = self.get_company(company_id)
        return company.contacts.copy()

    def get_subsidiaries(self, parent_company_id: str) -> list[Company]:
        """Get all subsidiary companies.

        Args:
            parent_company_id: Parent company identifier

        Returns:
            List of subsidiary Company objects
        """
        return [c for c in self._companies.values() if c.parent_company_id == parent_company_id]

    def get_parent_company(self, company_id: str) -> Company | None:
        """Get the parent company if it exists.

        Args:
            company_id: Company identifier

        Returns:
            Parent Company object or None

        Raises:
            CompanyNotFoundError: If company not found
        """
        company = self.get_company(company_id)

        if company.parent_company_id:
            return self.get_company(company.parent_company_id)

        return None

    def calculate_health_score(self, company_id: str) -> float:
        """Calculate company health score (0-100).

        Based on recent deal activity, engagement frequency, and deal value.

        Args:
            company_id: Company identifier

        Returns:
            Health score from 0 to 100

        Raises:
            CompanyNotFoundError: If company not found
        """
        self.get_company(company_id)

        activities = self._company_activities.get(company_id, [])

        if not activities:
            return 0.0

        # Count recent activities (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_activities = [a for a in activities if datetime.fromisoformat(a["timestamp"]) > thirty_days_ago]

        activity_score = min(len(recent_activities) * 10, 40)

        # Count different activity types
        activity_types = len({a["type"] for a in recent_activities})
        engagement_score = min(activity_types * 15, 30)

        # Recent deals (positive indicator)
        recent_deals = [a for a in recent_activities if a.get("type") == "deal_created"]
        deal_score = min(len(recent_deals) * 20, 30)

        total_score = activity_score + engagement_score + deal_score

        return min(total_score, 100.0)

    def log_activity(
        self,
        company_id: str,
        activity_type: str,
        notes: str,
        deal_id: str | None = None,
    ) -> None:
        """Log an activity for a company.

        Args:
            company_id: Company identifier
            activity_type: Type of activity
            notes: Activity notes
            deal_id: Associated deal ID

        Raises:
            CompanyNotFoundError: If company not found
        """
        self.get_company(company_id)  # Verify company exists

        if company_id not in self._company_activities:
            self._company_activities[company_id] = []

        activity = {
            "id": str(uuid.uuid4()),
            "type": activity_type,
            "timestamp": datetime.utcnow().isoformat(),
            "notes": notes,
            "deal_id": deal_id,
        }

        self._company_activities[company_id].append(activity)

    def get_company_timeline(self, company_id: str) -> list[dict[str, Any]]:
        """Get the activity timeline for a company.

        Args:
            company_id: Company identifier

        Returns:
            List of activities, sorted by timestamp (newest first)

        Raises:
            CompanyNotFoundError: If company not found
        """
        self.get_company(company_id)

        activities = self._company_activities.get(company_id, [])
        return sorted(activities, key=lambda x: x["timestamp"], reverse=True)

    def get_companies_by_industry(self, industry: str) -> list[Company]:
        """Get all companies in a specific industry.

        Args:
            industry: Industry classification

        Returns:
            List of Company objects
        """
        return [c for c in self._companies.values() if c.industry and c.industry.lower() == industry.lower()]

    def get_companies_by_size(self, min_size: int, max_size: int) -> list[Company]:
        """Get companies within a size range.

        Args:
            min_size: Minimum number of employees
            max_size: Maximum number of employees

        Returns:
            List of matching Company objects
        """
        return [c for c in self._companies.values() if c.size and min_size <= c.size <= max_size]

    def get_top_companies_by_revenue(self, limit: int = 10) -> list[Company]:
        """Get companies sorted by revenue.

        Args:
            limit: Maximum number of companies to return

        Returns:
            List of Company objects sorted by revenue (highest first)
        """
        companies_with_revenue = [c for c in self._companies.values() if c.revenue is not None]

        sorted_companies = sorted(companies_with_revenue, key=lambda c: c.revenue, reverse=True)

        return sorted_companies[:limit]

    def merge_companies(
        self,
        primary_id: str,
        secondary_id: str,
    ) -> Company:
        """Merge two companies.

        Args:
            primary_id: Primary company ID (kept)
            secondary_id: Secondary company ID (merged into primary)

        Returns:
            Merged Company object

        Raises:
            CompanyNotFoundError: If either company not found
        """
        primary = self.get_company(primary_id)
        secondary = self.get_company(secondary_id)

        # Merge contacts
        for contact_id in secondary.contacts:
            if contact_id not in primary.contacts:
                primary.contacts.append(contact_id)

        # Merge activities
        if secondary_id in self._company_activities:
            if primary_id not in self._company_activities:
                self._company_activities[primary_id] = []
            self._company_activities[primary_id].extend(self._company_activities[secondary_id])

        # Delete secondary company
        self.delete_company(secondary_id)

        return primary
