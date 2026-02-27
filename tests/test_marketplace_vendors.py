"""Tests for vendor management module."""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import (
    VendorAlreadyExists,
    VendorNotFoundError,
)
from thomas.marketplace._types import (
    Badge,
    Vendor,
    VendorStatus,
    VerificationLevel,
)
from thomas.marketplace.vendors import (
    VendorDashboard,
    VendorRegistry,
    VendorStateManager,
)


class TestVendorStateManager:
    """Test vendor state machine."""

    def test_valid_transition_applied_to_verified(self) -> None:
        """Test transition from APPLIED to VERIFIED."""
        assert VendorStateManager.can_transition(VendorStatus.APPLIED, VendorStatus.VERIFIED)

    def test_valid_transition_verified_to_active(self) -> None:
        """Test transition from VERIFIED to ACTIVE."""
        assert VendorStateManager.can_transition(VendorStatus.VERIFIED, VendorStatus.ACTIVE)

    def test_valid_transition_active_to_suspended(self) -> None:
        """Test transition from ACTIVE to SUSPENDED."""
        assert VendorStateManager.can_transition(VendorStatus.ACTIVE, VendorStatus.SUSPENDED)

    def test_invalid_transition_applied_to_active(self) -> None:
        """Test invalid transition from APPLIED to ACTIVE."""
        assert not VendorStateManager.can_transition(VendorStatus.APPLIED, VendorStatus.ACTIVE)

    def test_invalid_transition_closed(self) -> None:
        """Test closed status has no transitions."""
        assert not VendorStateManager.can_transition(VendorStatus.CLOSED, VendorStatus.ACTIVE)

    def test_perform_transition(self) -> None:
        """Test performing state transition."""
        vendor = Vendor(
            id="vendor_123",
            name="Test Vendor",
            email="test@example.com",
            status=VendorStatus.APPLIED,
            verification_level=VerificationLevel.UNVERIFIED,
            created_at=datetime.utcnow(),
            verified_at=None,
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 Test St",
            bank_account="1234567890",
            tax_id="12-3456789",
            response_time_hours=24.0,
            order_fulfillment_rate=Decimal("0"),
            review_score=Decimal("0"),
        )

        updated = VendorStateManager.transition(vendor, VendorStatus.VERIFIED)
        assert updated.status == VendorStatus.VERIFIED
        assert updated.verified_at is not None


class TestVendorRegistry:
    """Test vendor registry operations."""

    def test_register_vendor(self) -> None:
        """Test vendor registration."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="New Vendor",
            email="vendor@example.com",
            description="A new vendor",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 Main St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        assert vendor.status == VendorStatus.APPLIED
        assert vendor.verification_level == VerificationLevel.UNVERIFIED
        assert vendor.email == "vendor@example.com"

    def test_register_duplicate_vendor(self) -> None:
        """Test duplicate vendor registration fails."""
        registry = VendorRegistry()

        registry.register_vendor(
            name="Vendor 1",
            email="duplicate@example.com",
            description="First",
            logo_url="http://example.com/logo.png",
            phone="1111111111",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-1111111",
        )

        with pytest.raises(VendorAlreadyExists):
            registry.register_vendor(
                name="Vendor 2",
                email="duplicate@example.com",
                description="Second",
                logo_url="http://example.com/logo.png",
                phone="2222222222",
                address="456 St",
                bank_account="2222222222",
                tax_id="12-2222222",
            )

    def test_verify_vendor(self) -> None:
        """Test vendor verification."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="To Verify",
            email="verify@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        verified = registry.verify_vendor(vendor.id, VerificationLevel.STANDARD)
        assert verified.status == VendorStatus.VERIFIED
        assert verified.verification_level == VerificationLevel.STANDARD

    def test_activate_vendor(self) -> None:
        """Test vendor activation."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="To Activate",
            email="activate@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        verified = registry.verify_vendor(vendor.id)
        active = registry.activate_vendor(verified.id)

        assert active.status == VendorStatus.ACTIVE
        assert active.is_active

    def test_suspend_vendor(self) -> None:
        """Test vendor suspension."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="To Suspend",
            email="suspend@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        verified = registry.verify_vendor(vendor.id)
        active = registry.activate_vendor(verified.id)
        suspended = registry.suspend_vendor(active.id, "Policy violation")

        assert suspended.status == VendorStatus.SUSPENDED
        assert not suspended.is_active

    def test_get_vendor(self) -> None:
        """Test retrieving vendor."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="Get Test",
            email="get@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        retrieved = registry.get_vendor(vendor.id)
        assert retrieved.id == vendor.id
        assert retrieved.email == "get@example.com"

    def test_get_nonexistent_vendor(self) -> None:
        """Test getting nonexistent vendor raises error."""
        registry = VendorRegistry()

        with pytest.raises(VendorNotFoundError):
            registry.get_vendor("vendor_nonexistent")

    def test_list_vendors(self) -> None:
        """Test listing vendors."""
        registry = VendorRegistry()

        v1 = registry.register_vendor(
            name="Vendor 1",
            email="v1@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1111111111",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-1111111",
        )

        v2 = registry.register_vendor(
            name="Vendor 2",
            email="v2@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="2222222222",
            address="456 St",
            bank_account="2222222222",
            tax_id="12-2222222",
        )

        vendors = registry.list_vendors()
        assert len(vendors) == 2

        applied_vendors = registry.list_vendors(status=VendorStatus.APPLIED)
        assert len(applied_vendors) == 2

    def test_update_performance_metrics(self) -> None:
        """Test updating vendor performance metrics."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="Metric Test",
            email="metrics@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        metrics = registry.update_performance_metrics(
            vendor.id,
            order_fulfillment_rate=Decimal("95"),
            response_time_hours=12.0,
            review_score=Decimal("4.8"),
            total_orders=100,
            completed_orders=95,
        )

        assert metrics.order_fulfillment_rate == Decimal("95")
        assert metrics.response_time_hours == 12.0
        assert metrics.review_score == Decimal("4.8")

    def test_award_badge(self) -> None:
        """Test awarding badge to vendor."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="Badge Test",
            email="badge@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        badge = Badge(
            id="badge_top_seller",
            name="Top Seller",
            description="Consistent high sales",
            icon_url="http://example.com/badge.png",
            earned_at=datetime.utcnow(),
            category="sales",
        )

        updated = registry.award_badge(vendor.id, badge)
        assert len(updated.badges) == 1
        assert updated.badges[0].name == "Top Seller"

    def test_calculate_vendor_payout(self) -> None:
        """Test vendor payout calculation."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="Payout Test",
            email="payout@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        payout_info = registry.calculate_vendor_payout(
            vendor.id,
            Decimal("1000"),
        )

        assert payout_info["period_revenue"] == Decimal("1000")
        assert payout_info["commission_amount"] > Decimal("0")
        assert payout_info["net_payout"] < Decimal("1000")

    def test_get_vendor_dashboard(self) -> None:
        """Test vendor dashboard data."""
        registry = VendorRegistry()

        vendor = registry.register_vendor(
            name="Dashboard Test",
            email="dashboard@example.com",
            description="Test",
            logo_url="http://example.com/logo.png",
            phone="1234567890",
            address="123 St",
            bank_account="1111111111",
            tax_id="12-3456789",
        )

        dashboard = registry.get_vendor_dashboard(
            vendor.id,
            active_listings=50,
            total_products=75,
            monthly_gmv=Decimal("10000"),
        )

        assert dashboard.vendor_name == "Dashboard Test"
        assert dashboard.active_listings == 50
        assert dashboard.monthly_gmv == Decimal("10000")
        assert isinstance(dashboard, VendorDashboard)
