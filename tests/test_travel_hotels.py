"""Tests for hotel booking module."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.travel._exceptions import HotelNotAvailableError
from thomas.travel._types import Hotel, HotelBookingStatus
from thomas.travel.hotels import (
    HotelBookingEngine,
    OverbookingManager,
    RatePricingEngine,
    RoomAssignmentOptimizer,
    RoomInventoryMatrix,
)


@pytest.fixture
def sample_hotel():
    """Create sample hotel."""
    return Hotel(
        name="Grand Hotel",
        city="New York",
        country="USA",
        latitude=40.7580,
        longitude=-73.9855,
        star_rating=5.0,
        check_in_time="15:00",
        check_out_time="11:00",
        room_types={"standard": 50, "deluxe": 30, "suite": 10},
        amenities=["WiFi", "Pool", "Gym"],
    )


@pytest.fixture
def inventory_matrix(sample_hotel):
    """Create inventory matrix."""
    return RoomInventoryMatrix(sample_hotel)


@pytest.fixture
def pricing_engine():
    """Create pricing engine."""
    return RatePricingEngine()


@pytest.fixture
def booking_engine(sample_hotel):
    """Create hotel booking engine."""
    return HotelBookingEngine(sample_hotel)


class TestRoomInventoryMatrix:
    """Test room inventory management."""

    def test_set_availability(self, inventory_matrix):
        """Test setting room availability."""
        test_date = date.today()
        inventory_matrix.set_availability("standard", test_date, 50)
        assert inventory_matrix.get_availability("standard", test_date) == 50

    def test_get_availability_default(self, inventory_matrix, sample_hotel):
        """Test getting default availability."""
        test_date = date.today()
        default = sample_hotel.room_types["standard"]
        assert inventory_matrix.get_availability("standard", test_date) == default

    def test_get_availability_range(self, inventory_matrix):
        """Test getting minimum availability across date range."""
        start_date = date.today()
        end_date = start_date + timedelta(days=2)

        inventory_matrix.set_availability("standard", start_date, 50)
        inventory_matrix.set_availability("standard", start_date + timedelta(days=1), 20)

        available = inventory_matrix.get_availability_range("standard", start_date, end_date)
        assert available == 20  # Minimum across range

    def test_reserve_room(self, inventory_matrix):
        """Test reserving room."""
        start_date = date.today()
        end_date = start_date + timedelta(days=1)
        inventory_matrix.set_availability("standard", start_date, 10)

        result = inventory_matrix.reserve_room("standard", start_date, end_date)
        assert result is True
        assert inventory_matrix.get_availability("standard", start_date) == 9

    def test_reserve_room_unavailable(self, inventory_matrix):
        """Test error when reserving unavailable room."""
        start_date = date.today()
        end_date = start_date + timedelta(days=1)
        inventory_matrix.set_availability("standard", start_date, 0)

        with pytest.raises(HotelNotAvailableError):
            inventory_matrix.reserve_room("standard", start_date, end_date)

    def test_release_room(self, inventory_matrix):
        """Test releasing reserved room."""
        start_date = date.today()
        end_date = start_date + timedelta(days=1)

        initial = inventory_matrix.get_availability("standard", start_date)
        inventory_matrix.release_room("standard", start_date, end_date)
        assert inventory_matrix.get_availability("standard", start_date) == initial + 1


class TestRatePricingEngine:
    """Test hotel rate pricing."""

    def test_set_rack_rate(self, pricing_engine):
        """Test setting rack rate."""
        pricing_engine.set_rack_rate("GRAND001", "standard", Decimal("100"))
        rate = pricing_engine.calculate_nightly_rate("GRAND001", "standard", date.today())
        assert rate == Decimal("100")

    def test_set_corporate_rate(self, pricing_engine):
        """Test setting corporate rate."""
        pricing_engine.set_rack_rate("GRAND001", "standard", Decimal("100"))
        pricing_engine.set_corporate_rate("GRAND001", "standard", Decimal("75"))

        rate = pricing_engine.calculate_nightly_rate("GRAND001", "standard", date.today(), is_corporate=True)
        assert rate == Decimal("75")

    def test_seasonal_multiplier(self, pricing_engine):
        """Test seasonal pricing."""
        pricing_engine.set_rack_rate("GRAND001", "standard", Decimal("100"))
        test_date = date.today()
        pricing_engine.set_seasonal_multiplier(test_date, 1.5)

        rate = pricing_engine.calculate_nightly_rate("GRAND001", "standard", test_date)
        assert rate == Decimal("150")

    def test_calculate_stay_total(self, pricing_engine):
        """Test calculating total stay cost."""
        pricing_engine.set_rack_rate("GRAND001", "standard", Decimal("100"))

        start_date = date.today()
        end_date = start_date + timedelta(days=3)

        total = pricing_engine.calculate_stay_total("GRAND001", "standard", start_date, end_date)

        assert total == Decimal("300")

    def test_advance_purchase_discount(self, pricing_engine):
        """Test advance purchase discount."""
        pricing_engine.set_rack_rate("GRAND001", "standard", Decimal("100"))

        start_date = date.today() + timedelta(days=60)
        end_date = start_date + timedelta(days=2)

        # 30+ days advance = 20% discount
        total = pricing_engine.calculate_stay_total("GRAND001", "standard", start_date, end_date, days_advance=60)

        assert total < Decimal("200")


class TestRoomAssignmentOptimizer:
    """Test room assignment."""

    def test_assign_room(self):
        """Test assigning room to booking."""
        optimizer = RoomAssignmentOptimizer()
        room = optimizer.assign_room("GRAND001", "BK001", "standard")
        assert room is not None
        assert optimizer.get_assignment("BK001") == room

    def test_mark_upgrade_eligible(self):
        """Test marking booking for upgrade."""
        optimizer = RoomAssignmentOptimizer()
        optimizer.mark_upgrade_eligible("BK001")
        room1 = optimizer.assign_room("GRAND001", "BK001", "standard")
        room2 = optimizer.assign_room("GRAND001", "BK002", "standard")

        # Upgraded room should be different
        assert room1 != room2


class TestOverbookingManager:
    """Test overbooking management."""

    def test_can_accept_overbooking(self):
        """Test overbooking threshold check."""
        manager = OverbookingManager(overbooking_percentage=0.05)

        # With 50 rooms, 2 can be overbooked
        can_overbook = manager.can_accept_overbooking(0, 50)
        assert can_overbook is True

    def test_register_overbooking(self):
        """Test registering overbooked reservation."""
        manager = OverbookingManager()
        manager.register_overbooking("BK001", Decimal("100"))

        assert manager.get_compensation("BK001") == Decimal("100")


class TestHotelBookingEngine:
    """Test hotel booking engine."""

    def test_search_availability(self, booking_engine):
        """Test searching room availability."""
        check_in = date.today()
        check_out = check_in + timedelta(days=2)

        result = booking_engine.search_availability("standard", check_in, check_out)

        assert result["available_rooms"] > 0
        assert result["nightly_rate"] > 0

    def test_create_booking(self, booking_engine):
        """Test creating hotel booking."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=2)

        booking = booking_engine.create_booking("John Doe", "standard", check_in, check_out)

        assert booking["status"] == HotelBookingStatus.RESERVED
        assert booking["guest_name"] == "John Doe"
        assert booking["total_cost"] > 0

    def test_confirm_booking(self, booking_engine):
        """Test confirming booking."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=2)

        booking = booking_engine.create_booking("John Doe", "standard", check_in, check_out)
        booking_id = booking["booking_id"]

        confirmed = booking_engine.confirm_booking(booking_id)
        assert confirmed["status"] == HotelBookingStatus.CONFIRMED

    def test_check_in(self, booking_engine):
        """Test checking in guest."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=2)

        booking = booking_engine.create_booking("John Doe", "standard", check_in, check_out)
        booking_engine.confirm_booking(booking["booking_id"])

        checked_in = booking_engine.check_in(booking["booking_id"])
        assert checked_in["status"] == HotelBookingStatus.CHECKED_IN
        assert "check_in_time" in checked_in

    def test_check_out(self, booking_engine):
        """Test checking out guest."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=2)

        booking = booking_engine.create_booking("John Doe", "standard", check_in, check_out)
        booking_engine.check_in(booking["booking_id"])

        checked_out = booking_engine.check_out(booking["booking_id"])
        assert checked_out["status"] == HotelBookingStatus.CHECKED_OUT

    def test_cancel_booking(self, booking_engine):
        """Test cancelling booking."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=2)

        booking = booking_engine.create_booking("John Doe", "standard", check_in, check_out)

        cancelled = booking_engine.cancel_booking(booking["booking_id"])
        assert cancelled["status"] == HotelBookingStatus.CANCELLED


class TestHotelIntegration:
    """Integration tests for hotel operations."""

    def test_end_to_end_stay(self, booking_engine):
        """Test complete hotel stay lifecycle."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=3)

        # Create booking
        booking = booking_engine.create_booking("Jane Smith", "deluxe", check_in, check_out)
        booking_id = booking["booking_id"]

        # Confirm
        booking_engine.confirm_booking(booking_id)

        # Check in
        booking_engine.check_in(booking_id)

        # Check out
        booking_engine.check_out(booking_id)

    def test_multi_booking_inventory_sync(self, booking_engine):
        """Test inventory consistency across multiple bookings."""
        check_in = date.today() + timedelta(days=1)
        check_out = check_in + timedelta(days=1)

        # Create first booking
        booking1 = booking_engine.create_booking("Guest 1", "standard", check_in, check_out)

        # Create second booking
        booking2 = booking_engine.create_booking("Guest 2", "standard", check_in, check_out)

        # Both should succeed with different room assignments
        assert booking1["assigned_room"] != booking2["assigned_room"]
