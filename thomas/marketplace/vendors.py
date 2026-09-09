"""Vendor management with state machine, verification, and performance metrics."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from thomas.marketplace._exceptions import (
    VendorAlreadyExists,
    VendorException,
    VendorNotFoundError,
)
from thomas.marketplace._types import (
    Badge,
    Commission,
    CommissionTier,
    Vendor,
    VendorStatus,
    VerificationLevel,
)


@dataclass
class VendorMetrics:
    """Vendor performance metrics snapshot."""

    vendor_id: str
    order_fulfillment_rate: Decimal
    response_time_hours: float
    review_score: Decimal
    total_orders: int
    completed_orders: int
    avg_response_time_hours: float
    total_reviews: int
    positive_reviews: int
    calculated_at: datetime


@dataclass
class VendorDashboard:
    """Vendor-facing dashboard data."""

    vendor_id: str
    vendor_name: str
    active_listings: int
    total_products: int
    monthly_gmv: Decimal
    monthly_commissions: Decimal
    pending_payouts: Decimal
    available_balance: Decimal
    metrics: VendorMetrics
    recent_orders: int
    pending_reviews: int
    open_disputes: int
    commission_tier: CommissionTier


class VendorStateManager:
    """State machine for vendor lifecycle: applied→verified→active→suspended."""

    VALID_TRANSITIONS: dict[VendorStatus, list[VendorStatus]] = {
        VendorStatus.APPLIED: [VendorStatus.VERIFIED, VendorStatus.CLOSED],
        VendorStatus.VERIFIED: [VendorStatus.ACTIVE, VendorStatus.CLOSED],
        VendorStatus.ACTIVE: [VendorStatus.SUSPENDED, VendorStatus.CLOSED],
        VendorStatus.SUSPENDED: [VendorStatus.ACTIVE, VendorStatus.CLOSED],
        VendorStatus.CLOSED: [],
    }

    @staticmethod
    def can_transition(current_status: VendorStatus, target_status: VendorStatus) -> bool:
        """Check if state transition is valid.

        Args:
            current_status: Current vendor status.
            target_status: Target vendor status.

        Returns:
            True if transition is valid, False otherwise.
        """
        return target_status in VendorStateManager.VALID_TRANSITIONS.get(current_status, [])

    @staticmethod
    def transition(vendor: Vendor, target_status: VendorStatus) -> Vendor:
        """Perform vendor status transition.

        Args:
            vendor: Vendor to transition.
            target_status: Target status.

        Returns:
            Updated vendor with new status.

        Raises:
            VendorException: If transition is invalid.
        """
        if not VendorStateManager.can_transition(vendor.status, target_status):
            raise VendorException(
                f"Cannot transition from {vendor.status.value} to {target_status.value}",
                "INVALID_TRANSITION",
            )

        vendor.status = target_status
        if target_status == VendorStatus.VERIFIED:
            vendor.verified_at = datetime.utcnow()

        return vendor


class VendorRegistry:
    """In-memory vendor registry with performance tracking."""

    def __init__(self) -> None:
        """Initialize vendor registry."""
        self._vendors: dict[str, Vendor] = {}
        self._metrics: dict[str, VendorMetrics] = {}
        self._commission_tiers: dict[str, Commission] = {}

    def register_vendor(
        self,
        name: str,
        email: str,
        description: str,
        logo_url: str,
        phone: str,
        address: str,
        bank_account: str,
        tax_id: str,
    ) -> Vendor:
        """Register new vendor in APPLIED state.

        Args:
            name: Vendor business name.
            email: Contact email.
            description: Business description.
            logo_url: Logo image URL.
            phone: Contact phone.
            address: Business address.
            bank_account: Bank account for payouts.
            tax_id: Tax identification number.

        Returns:
            Newly created vendor.

        Raises:
            VendorAlreadyExists: If vendor email already registered.
        """
        if any(v.email == email for v in self._vendors.values()):
            raise VendorAlreadyExists(email)

        vendor_id = f"vendor_{uuid.uuid4().hex[:12]}"
        vendor = Vendor(
            id=vendor_id,
            name=name,
            email=email,
            status=VendorStatus.APPLIED,
            verification_level=VerificationLevel.UNVERIFIED,
            created_at=datetime.utcnow(),
            verified_at=None,
            description=description,
            logo_url=logo_url,
            phone=phone,
            address=address,
            bank_account=bank_account,
            tax_id=tax_id,
            response_time_hours=24.0,
            order_fulfillment_rate=Decimal("0"),
            review_score=Decimal("0"),
            commission_tier=CommissionTier.TIER_1,
        )

        self._vendors[vendor_id] = vendor
        return vendor

    def verify_vendor(self, vendor_id: str, verification_level: VerificationLevel = VerificationLevel.BASIC) -> Vendor:
        """Verify vendor after identity checks.

        Args:
            vendor_id: Vendor identifier.
            verification_level: Verification level to assign.

        Returns:
            Verified vendor.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)
        vendor = VendorStateManager.transition(vendor, VendorStatus.VERIFIED)
        vendor.verification_level = verification_level
        return vendor

    def activate_vendor(self, vendor_id: str) -> Vendor:
        """Activate vendor to ACTIVE state.

        Args:
            vendor_id: Vendor identifier.

        Returns:
            Activated vendor.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)
        vendor = VendorStateManager.transition(vendor, VendorStatus.ACTIVE)
        vendor.is_active = True
        return vendor

    def suspend_vendor(self, vendor_id: str, reason: str = "") -> Vendor:
        """Suspend vendor for violations.

        Args:
            vendor_id: Vendor identifier.
            reason: Suspension reason.

        Returns:
            Suspended vendor.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)
        vendor = VendorStateManager.transition(vendor, VendorStatus.SUSPENDED)
        vendor.is_active = False
        return vendor

    def get_vendor(self, vendor_id: str) -> Vendor:
        """Get vendor by ID.

        Args:
            vendor_id: Vendor identifier.

        Returns:
            Vendor object.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self._vendors.get(vendor_id)
        if not vendor:
            raise VendorNotFoundError(vendor_id)
        return vendor

    def list_vendors(self, status: VendorStatus | None = None, is_active: bool | None = None) -> list[Vendor]:
        """List vendors with optional filtering.

        Args:
            status: Filter by vendor status.
            is_active: Filter by active state.

        Returns:
            List of vendors matching filters.
        """
        vendors = list(self._vendors.values())
        if status:
            vendors = [v for v in vendors if v.status == status]
        if is_active is not None:
            vendors = [v for v in vendors if v.is_active == is_active]
        return vendors

    def update_performance_metrics(
        self,
        vendor_id: str,
        order_fulfillment_rate: Decimal,
        response_time_hours: float,
        review_score: Decimal,
        total_orders: int,
        completed_orders: int,
    ) -> VendorMetrics:
        """Update vendor performance metrics.

        Args:
            vendor_id: Vendor identifier.
            order_fulfillment_rate: Percentage of completed orders.
            response_time_hours: Average response time.
            review_score: Average review rating.
            total_orders: Total orders received.
            completed_orders: Orders completed successfully.

        Returns:
            Updated metrics snapshot.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)

        vendor.order_fulfillment_rate = order_fulfillment_rate
        vendor.response_time_hours = response_time_hours
        vendor.review_score = review_score

        metrics = VendorMetrics(
            vendor_id=vendor_id,
            order_fulfillment_rate=order_fulfillment_rate,
            response_time_hours=response_time_hours,
            review_score=review_score,
            total_orders=total_orders,
            completed_orders=completed_orders,
            avg_response_time_hours=response_time_hours,
            total_reviews=0,
            positive_reviews=0,
            calculated_at=datetime.utcnow(),
        )

        self._metrics[vendor_id] = metrics
        self._update_commission_tier(vendor)

        return metrics

    def _update_commission_tier(self, vendor: Vendor) -> None:
        """Update vendor commission tier based on performance.

        Tier assignments based on monthly GMV (estimated from order metrics).

        Args:
            vendor: Vendor to update tier for.
        """
        # Simplified tier assignment based on metrics
        if vendor.order_fulfillment_rate >= Decimal("95") and vendor.review_score >= Decimal("4.5"):
            vendor.commission_tier = CommissionTier.TIER_4
        elif vendor.order_fulfillment_rate >= Decimal("90") and vendor.review_score >= Decimal("4"):
            vendor.commission_tier = CommissionTier.TIER_3
        elif vendor.order_fulfillment_rate >= Decimal("85"):
            vendor.commission_tier = CommissionTier.TIER_2
        else:
            vendor.commission_tier = CommissionTier.TIER_1

    def award_badge(self, vendor_id: str, badge: Badge) -> Vendor:
        """Award achievement badge to vendor.

        Args:
            vendor_id: Vendor identifier.
            badge: Badge to award.

        Returns:
            Updated vendor with badge.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)
        if badge not in vendor.badges:
            vendor.badges.append(badge)
        return vendor

    def calculate_vendor_payout(self, vendor_id: str, period_revenue: Decimal) -> dict[str, Decimal]:
        """Calculate vendor payout for a period.

        Args:
            vendor_id: Vendor identifier.
            period_revenue: Gross revenue for the period.

        Returns:
            Dictionary with revenue, commissions, and net payout.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)

        # Get commission tier rates
        commission_percent = self._get_commission_rate(vendor.commission_tier)

        commission = period_revenue * commission_percent / Decimal("100")
        payout = period_revenue - commission
        try:
            tier_level = Decimal(str(int(vendor.commission_tier.value.rsplit("_", 1)[-1])))
        except Exception:
            tier_level = Decimal("0")

        return {
            "period_revenue": period_revenue,
            "commission_percent": commission_percent,
            "commission_amount": commission,
            "net_payout": payout,
            "tier": tier_level,
        }

    def _get_commission_rate(self, tier: CommissionTier) -> Decimal:
        """Get commission percentage for tier.

        Args:
            tier: Commission tier.

        Returns:
            Commission percentage.
        """
        rates: dict[CommissionTier, Decimal] = {
            CommissionTier.TIER_1: Decimal("15"),
            CommissionTier.TIER_2: Decimal("12"),
            CommissionTier.TIER_3: Decimal("10"),
            CommissionTier.TIER_4: Decimal("8"),
        }
        return rates.get(tier, Decimal("15"))

    def get_vendor_dashboard(
        self,
        vendor_id: str,
        active_listings: int = 0,
        total_products: int = 0,
        monthly_gmv: Decimal = Decimal("0"),
    ) -> VendorDashboard:
        """Get vendor dashboard data.

        Args:
            vendor_id: Vendor identifier.
            active_listings: Number of active product listings.
            total_products: Total products in catalog.
            monthly_gmv: Monthly gross merchandise value.

        Returns:
            Dashboard data for vendor.

        Raises:
            VendorNotFoundError: If vendor not found.
        """
        vendor = self.get_vendor(vendor_id)
        metrics = self._metrics.get(vendor_id)

        if not metrics:
            metrics = VendorMetrics(
                vendor_id=vendor_id,
                order_fulfillment_rate=vendor.order_fulfillment_rate,
                response_time_hours=vendor.response_time_hours,
                review_score=vendor.review_score,
                total_orders=0,
                completed_orders=0,
                avg_response_time_hours=vendor.response_time_hours,
                total_reviews=0,
                positive_reviews=0,
                calculated_at=datetime.utcnow(),
            )

        commission_info = self.calculate_vendor_payout(vendor_id, monthly_gmv)

        return VendorDashboard(
            vendor_id=vendor_id,
            vendor_name=vendor.name,
            active_listings=active_listings,
            total_products=total_products,
            monthly_gmv=monthly_gmv,
            monthly_commissions=commission_info["commission_amount"],
            pending_payouts=Decimal("0"),
            available_balance=commission_info["net_payout"],
            metrics=metrics,
            recent_orders=0,
            pending_reviews=0,
            open_disputes=0,
            commission_tier=vendor.commission_tier,
        )
