"""Lease and tenant management."""

import statistics
from datetime import date, timedelta
from decimal import Decimal

from thomas.real_estate._exceptions import ValidationError
from thomas.real_estate._types import Lease, Tenant


class LeaseDatabase:
    """Lease storage and retrieval."""

    def __init__(self) -> None:
        """Initialize lease database."""
        self._leases: dict[str, Lease] = {}
        self._by_property: dict[str, list[str]] = {}
        self._by_tenant: dict[str, list[str]] = {}

    def create(self, lease: Lease) -> None:
        """Create a new lease.

        Args:
            lease: Lease instance

        Raises:
            ValidationError: If lease data invalid
            ValueError: If lease already exists
        """
        self._validate_lease(lease)
        if lease.lease_id in self._leases:
            raise ValueError(f"Lease {lease.lease_id} already exists")

        self._leases[lease.lease_id] = lease
        if lease.property_id not in self._by_property:
            self._by_property[lease.property_id] = []
        self._by_property[lease.property_id].append(lease.lease_id)

        if lease.tenant_id not in self._by_tenant:
            self._by_tenant[lease.tenant_id] = []
        self._by_tenant[lease.tenant_id].append(lease.lease_id)

    def read(self, lease_id: str) -> Lease:
        """Retrieve lease by ID.

        Args:
            lease_id: Lease identifier

        Returns:
            Lease instance

        Raises:
            ValueError: If not found
        """
        if lease_id not in self._leases:
            raise ValueError(f"Lease {lease_id} not found")
        return self._leases[lease_id]

    def update(self, lease: Lease) -> None:
        """Update existing lease.

        Args:
            lease: Lease with updated data

        Raises:
            ValueError: If not found
            ValidationError: If invalid
        """
        self._validate_lease(lease)
        if lease.lease_id not in self._leases:
            raise ValueError(f"Lease {lease.lease_id} not found")
        self._leases[lease.lease_id] = lease

    def delete(self, lease_id: str) -> None:
        """Delete lease.

        Args:
            lease_id: Lease identifier

        Raises:
            ValueError: If not found
        """
        if lease_id not in self._leases:
            raise ValueError(f"Lease {lease_id} not found")

        lease = self._leases.pop(lease_id)
        self._by_property[lease.property_id].remove(lease_id)
        self._by_tenant[lease.tenant_id].remove(lease_id)

    def find_by_property(self, property_id: str) -> list[Lease]:
        """Find leases for property.

        Args:
            property_id: Property identifier

        Returns:
            List of leases
        """
        lease_ids = self._by_property.get(property_id, [])
        return [self._leases[lid] for lid in lease_ids]

    def find_by_tenant(self, tenant_id: str) -> list[Lease]:
        """Find leases for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of leases
        """
        lease_ids = self._by_tenant.get(tenant_id, [])
        return [self._leases[lid] for lid in lease_ids]

    def find_active(self) -> list[Lease]:
        """Find all active leases.

        Returns:
            List of active leases
        """
        today = date.today()
        return [l for l in self._leases.values() if l.status == "active" and l.start_date <= today <= l.end_date]

    @staticmethod
    def _validate_lease(lease: Lease) -> None:
        """Validate lease data.

        Args:
            lease: Lease to validate

        Raises:
            ValidationError: If invalid
        """
        if not lease.lease_id:
            raise ValidationError("Lease ID required")
        if lease.end_date <= lease.start_date:
            raise ValidationError("End date must be after start date")
        if lease.monthly_rent < 0:
            raise ValidationError("Rent must be non-negative")
        if lease.security_deposit < 0:
            raise ValidationError("Deposit must be non-negative")


class LeaseLifecycle:
    """Lease status and lifecycle management."""

    VALID_STATUSES = ["draft", "active", "month_to_month", "terminated"]

    @staticmethod
    def convert_to_month_to_month(lease: Lease) -> None:
        """Convert lease to month-to-month.

        Args:
            lease: Lease to convert

        Raises:
            ValueError: If lease cannot convert
        """
        if lease.status not in ["active", "month_to_month"]:
            raise ValueError(f"Cannot convert lease with status {lease.status}")
        lease.status = "month_to_month"
        lease.end_date = date.today() + timedelta(days=30)

    @staticmethod
    def terminate_lease(lease: Lease, termination_date: date) -> None:
        """Terminate lease on specified date.

        Args:
            lease: Lease to terminate
            termination_date: Termination date

        Raises:
            ValueError: If date invalid
        """
        if termination_date < date.today():
            raise ValueError("Termination date cannot be in past")
        lease.status = "terminated"
        lease.end_date = termination_date


class RentRoll:
    """Rent roll management and reporting."""

    @staticmethod
    def generate_rent_roll(leases: list[Lease]) -> dict[str, Decimal]:
        """Generate rent roll report.

        Args:
            leases: List of leases

        Returns:
            Dictionary of property_id -> monthly rent
        """
        rent_roll: dict[str, Decimal] = {}
        for lease in leases:
            if lease.status == "active":
                if lease.property_id not in rent_roll:
                    rent_roll[lease.property_id] = Decimal("0")
                rent_roll[lease.property_id] += lease.monthly_rent

        return rent_roll

    @staticmethod
    def total_monthly_rent(leases: list[Lease]) -> Decimal:
        """Calculate total monthly rent from leases.

        Args:
            leases: List of leases

        Returns:
            Total monthly rental income
        """
        return sum(
            (l.monthly_rent for l in leases if l.status == "active"),
            Decimal("0"),
        )

    @staticmethod
    def calculate_occupancy_rate(total_units: int, leased_units: int) -> Decimal:
        """Calculate occupancy rate.

        Args:
            total_units: Total number of units
            leased_units: Number of leased units

        Returns:
            Occupancy rate (e.g., 0.95 for 95%)
        """
        if total_units == 0:
            return Decimal("0")
        return Decimal(leased_units) / Decimal(total_units)


class RentEscalation:
    """Rent escalation and adjustment calculations."""

    @staticmethod
    def calculate_escalated_rent(
        current_rent: Decimal,
        annual_escalation_rate: Decimal,
        years: int,
    ) -> Decimal:
        """Calculate escalated rent with compound growth.

        Args:
            current_rent: Current monthly rent
            annual_escalation_rate: Annual increase rate
            years: Number of years

        Returns:
            Projected rent amount
        """
        return current_rent * ((1 + annual_escalation_rate) ** years)

    @staticmethod
    def cpi_adjusted_rent(
        current_rent: Decimal,
        cpi_increases: list[Decimal],
    ) -> Decimal:
        """Calculate CPI-adjusted rent.

        Args:
            current_rent: Current monthly rent
            cpi_increases: List of CPI increases (one per period)

        Returns:
            CPI-adjusted rent
        """
        rent = current_rent
        for cpi_increase in cpi_increases:
            rent = rent * (1 + cpi_increase)
        return rent

    @staticmethod
    def percentage_escalation_schedule(
        base_rent: Decimal,
        annual_rate: Decimal,
        years: int,
    ) -> list[tuple[int, Decimal]]:
        """Generate rent escalation schedule.

        Args:
            base_rent: Starting monthly rent
            annual_rate: Annual escalation rate
            years: Number of years

        Returns:
            List of (year, monthly_rent) tuples
        """
        schedule = [(0, base_rent)]
        current_rent = base_rent

        for year in range(1, years + 1):
            current_rent = RentEscalation.calculate_escalated_rent(base_rent, annual_rate, year)
            schedule.append((year, current_rent))

        return schedule


class CAMCalculation:
    """Common Area Maintenance (CAM) charge calculation."""

    @staticmethod
    def calculate_monthly_cam(annual_cam_cost: Decimal, num_units: int) -> Decimal:
        """Calculate monthly CAM per unit.

        Args:
            annual_cam_cost: Total annual CAM expenses
            num_units: Number of units in property

        Returns:
            Monthly CAM per unit
        """
        if num_units == 0:
            return Decimal("0")
        return (annual_cam_cost / Decimal(num_units)) / Decimal(12)

    @staticmethod
    def calculate_total_with_cam(base_rent: Decimal, monthly_cam: Decimal) -> Decimal:
        """Calculate total rent including CAM.

        Args:
            base_rent: Base monthly rent
            monthly_cam: Monthly CAM charge

        Returns:
            Total monthly payment
        """
        return base_rent + monthly_cam

    @staticmethod
    def estimate_cam_recovery(
        budgeted_cam: Decimal,
        actual_cam: Decimal,
        tenant_share: Decimal,
    ) -> Decimal:
        """Calculate CAM over/under recovery adjustment.

        Args:
            budgeted_cam: Budgeted annual CAM
            actual_cam: Actual annual CAM
            tenant_share: Tenant's share percentage

        Returns:
            Adjustment amount (positive = credit, negative = charge)
        """
        variance = budgeted_cam - actual_cam
        return variance * tenant_share


class LeaseAbstraction:
    """Extract key lease terms and data."""

    @staticmethod
    def extract_key_terms(lease: Lease) -> dict[str, str]:
        """Extract key lease terms.

        Args:
            lease: Lease instance

        Returns:
            Dictionary of key terms
        """
        terms = {
            "lease_type": lease.lease_type,
            "start_date": lease.start_date.isoformat(),
            "end_date": lease.end_date.isoformat(),
            "monthly_rent": str(lease.monthly_rent),
            "security_deposit": str(lease.security_deposit),
            "rent_escalation": f"{lease.rent_escalation * 100}%",
        }
        terms.update(lease.lease_terms)
        return terms

    @staticmethod
    def calculate_total_lease_value(lease: Lease) -> Decimal:
        """Calculate total value of lease.

        Args:
            lease: Lease instance

        Returns:
            Total rent plus CAM over lease term
        """
        months = max((lease.end_date - lease.start_date).days // 30, 1)
        base_total = lease.monthly_rent * Decimal(months)
        cam_total = lease.cam_charges * Decimal(months)
        return base_total + cam_total


class TenantScreening:
    """Tenant screening and scoring."""

    @staticmethod
    def calculate_screening_score(
        tenant: Tenant,
        min_credit_score: int = 620,
        min_income_ratio: Decimal = Decimal("2.5"),
    ) -> float:
        """Calculate tenant screening score (0-100).

        Args:
            tenant: Tenant instance
            min_credit_score: Minimum credit score (default 620)
            min_income_ratio: Minimum income-to-rent ratio (default 2.5x)

        Returns:
            Screening score
        """
        score = 50.0

        if tenant.credit_score >= min_credit_score:
            score += 25
        elif tenant.credit_score >= min_credit_score - 100:
            score += 15
        elif tenant.credit_score >= min_credit_score - 200:
            score += 5

        if tenant.background_check:
            score += 15

        if len(tenant.rental_history) > 0:
            score += 10

        return min(score, 100.0)

    @staticmethod
    def verify_income_requirement(
        annual_income: Decimal,
        monthly_rent: Decimal,
        income_ratio_requirement: Decimal = Decimal("2.5"),
    ) -> bool:
        """Verify tenant meets income requirement.

        Args:
            annual_income: Tenant annual income
            monthly_rent: Monthly rent
            income_ratio_requirement: Required income ratio (default 2.5x)

        Returns:
            True if income requirement met
        """
        if annual_income == 0:
            return False

        monthly_income = annual_income / Decimal(12)
        income_ratio = monthly_income / monthly_rent
        return income_ratio >= income_ratio_requirement


class VacancyTracking:
    """Vacancy tracking and analysis."""

    def __init__(self) -> None:
        """Initialize vacancy tracker."""
        self._vacancies: dict[str, list[tuple[date, date]]] = {}

    def record_vacancy(self, property_id: str, start_date: date, end_date: date) -> None:
        """Record vacancy period.

        Args:
            property_id: Property identifier
            start_date: Vacancy start date
            end_date: Vacancy end date
        """
        if property_id not in self._vacancies:
            self._vacancies[property_id] = []
        self._vacancies[property_id].append((start_date, end_date))

    def get_vacancy_days(self, property_id: str) -> int:
        """Get total vacancy days for property.

        Args:
            property_id: Property identifier

        Returns:
            Total vacancy days
        """
        vacancies = self._vacancies.get(property_id, [])
        return sum((end - start).days for start, end in vacancies)

    def get_vacancy_rate(self, property_id: str, period_days: int = 365) -> Decimal:
        """Calculate vacancy rate.

        Args:
            property_id: Property identifier
            period_days: Period to calculate over (default 365 days)

        Returns:
            Vacancy rate as decimal
        """
        vacancy_days = self.get_vacancy_days(property_id)
        if period_days == 0:
            return Decimal("0")
        return Decimal(vacancy_days) / Decimal(period_days)

    def get_average_days_vacant(self, property_id: str) -> float | None:
        """Get average days vacant per vacancy period.

        Args:
            property_id: Property identifier

        Returns:
            Average days vacant or None if no vacancies
        """
        vacancies = self._vacancies.get(property_id, [])
        if not vacancies:
            return None

        days_list = [(end - start).days for start, end in vacancies]
        return statistics.mean(days_list)
