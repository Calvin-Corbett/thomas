"""Hotel booking engine with room inventory and pricing management."""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from thomas.travel._exceptions import BookingError, HotelNotAvailableError, OverbookingError
from thomas.travel._types import Hotel, HotelBookingStatus, LoyaltyTier


class RoomInventoryMatrix:
    """Room inventory tracking across dates and room types."""

    def __init__(self, hotel: Hotel) -> None:
        """
        Initialize inventory matrix.

        Args:
            hotel: Hotel object
        """
        self.hotel = hotel
        # Matrix: {room_type: {date: available_count}}
        self._inventory: dict[str, dict[date, int]] = {}
        self._overbooking_threshold: dict[str, float] = {}

        for room_type, count in hotel.room_types.items():
            self._inventory[room_type] = {}
            self._overbooking_threshold[room_type] = 0.05  # 5% overbooking

    def set_availability(self, room_type: str, check_date: date, available: int) -> None:
        """
        Set availability for room type on date.

        Args:
            room_type: Room type code
            check_date: Date to set availability
            available: Number of available rooms
        """
        if room_type not in self._inventory:
            self._inventory[room_type] = {}

        self._inventory[room_type][check_date] = available

    def get_availability(self, room_type: str, check_date: date) -> int:
        """
        Get available rooms for date.

        Args:
            room_type: Room type code
            check_date: Date to check

        Returns:
            Number of available rooms
        """
        if room_type not in self._inventory:
            return 0

        return self._inventory[room_type].get(check_date, self.hotel.room_types.get(room_type, 0))

    def get_availability_range(
        self,
        room_type: str,
        check_in: date,
        check_out: date,
    ) -> int:
        """
        Get minimum availability across date range.

        Args:
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date

        Returns:
            Minimum available rooms for any date in range
        """
        current = check_in
        min_available = float("inf")

        while current < check_out:
            available = self.get_availability(room_type, current)
            min_available = min(min_available, available)
            current += timedelta(days=1)

        return max(0, int(min_available))

    def reserve_room(
        self,
        room_type: str,
        check_in: date,
        check_out: date,
    ) -> bool:
        """
        Reserve room across date range.

        Args:
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date

        Returns:
            True if reservation successful

        Raises:
            HotelNotAvailableError: If rooms not available
        """
        # Check availability across all dates
        available = self.get_availability_range(room_type, check_in, check_out)
        if available <= 0:
            raise HotelNotAvailableError(f"No {room_type} rooms available for {check_in} to {check_out}")

        # Reduce availability for each date
        current = check_in
        while current < check_out:
            current_available = self.get_availability(room_type, current)
            self.set_availability(room_type, current, current_available - 1)
            current += timedelta(days=1)

        return True

    def release_room(
        self,
        room_type: str,
        check_in: date,
        check_out: date,
    ) -> None:
        """
        Release reserved room.

        Args:
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date
        """
        current = check_in
        while current < check_out:
            current_available = self.get_availability(room_type, current)
            self.set_availability(room_type, current, current_available + 1)
            current += timedelta(days=1)


class RatePricingEngine:
    """Dynamic rate pricing with multiple rate plans."""

    def __init__(self) -> None:
        """Initialize pricing engine."""
        self._rates: dict[str, dict[str, Decimal]] = {}
        self._seasonal_multipliers: dict[date, float] = {}
        self._advance_purchase_discounts: dict[int, float] = {}

        # Set default advance purchase discounts
        self._advance_purchase_discounts[30] = 0.20  # 20% off 30+ days
        self._advance_purchase_discounts[14] = 0.10  # 10% off 14+ days
        self._advance_purchase_discounts[7] = 0.05  # 5% off 7+ days

    def set_rack_rate(
        self,
        hotel_id: str,
        room_type: str,
        nightly_rate: Decimal,
    ) -> None:
        """
        Set rack rate (full nightly rate) for room type.

        Args:
            hotel_id: Hotel identifier
            room_type: Room type code
            nightly_rate: Nightly rate in currency
        """
        key = f"{hotel_id}:{room_type}"
        if key not in self._rates:
            self._rates[key] = {}

        self._rates[key]["rack"] = nightly_rate

    def set_corporate_rate(
        self,
        hotel_id: str,
        room_type: str,
        nightly_rate: Decimal,
    ) -> None:
        """
        Set corporate negotiated rate.

        Args:
            hotel_id: Hotel identifier
            room_type: Room type code
            nightly_rate: Nightly rate
        """
        key = f"{hotel_id}:{room_type}"
        if key not in self._rates:
            self._rates[key] = {}

        self._rates[key]["corporate"] = nightly_rate

    def set_loyalty_rate(
        self,
        hotel_id: str,
        room_type: str,
        tier: LoyaltyTier,
        discount: float,
    ) -> None:
        """
        Set loyalty discount rate.

        Args:
            hotel_id: Hotel identifier
            room_type: Room type code
            tier: Loyalty tier
            discount: Discount percentage (0.0 to 1.0)
        """
        key = f"{hotel_id}:{room_type}:{tier.value}"
        if key not in self._rates:
            self._rates[key] = {}

        self._rates[key]["loyalty"] = Decimal(1.0 - discount)

    def set_seasonal_multiplier(self, check_date: date, multiplier: float) -> None:
        """
        Set seasonal pricing multiplier.

        Args:
            check_date: Date for multiplier
            multiplier: Price multiplier (1.0 = no change, 1.5 = 50% premium)
        """
        self._seasonal_multipliers[check_date] = multiplier

    def calculate_nightly_rate(
        self,
        hotel_id: str,
        room_type: str,
        check_in: date,
        is_corporate: bool = False,
        loyalty_tier: LoyaltyTier | None = None,
    ) -> Decimal:
        """
        Calculate nightly rate with all applicable discounts.

        Args:
            hotel_id: Hotel identifier
            room_type: Room type code
            check_in: Check-in date
            is_corporate: Whether corporate rate applies
            loyalty_tier: Loyalty tier for discount

        Returns:
            Nightly rate in currency
        """
        key = f"{hotel_id}:{room_type}"
        rates = self._rates.get(key, {})

        # Get base rate (corporate > rack)
        if is_corporate and "corporate" in rates:
            rate = rates["corporate"]
        else:
            rate = rates.get("rack", Decimal("100"))

        # Apply seasonal multiplier
        multiplier = self._seasonal_multipliers.get(check_in, 1.0)
        rate = rate * Decimal(multiplier)

        # Apply loyalty discount
        if loyalty_tier:
            loyalty_key = f"{hotel_id}:{room_type}:{loyalty_tier.value}"
            loyalty_rates = self._rates.get(loyalty_key, {})
            if "loyalty" in loyalty_rates:
                rate = rate * loyalty_rates["loyalty"]

        return rate

    def calculate_stay_total(
        self,
        hotel_id: str,
        room_type: str,
        check_in: date,
        check_out: date,
        is_corporate: bool = False,
        loyalty_tier: LoyaltyTier | None = None,
        days_advance: int = 0,
    ) -> Decimal:
        """
        Calculate total stay cost with advance purchase discount.

        Args:
            hotel_id: Hotel identifier
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date
            is_corporate: Whether corporate rate applies
            loyalty_tier: Loyalty tier
            days_advance: Days in advance (for advance purchase discount)

        Returns:
            Total cost for stay
        """
        current = check_in
        total = Decimal("0")

        # Accumulate nightly rates
        while current < check_out:
            nightly = self.calculate_nightly_rate(hotel_id, room_type, current, is_corporate, loyalty_tier)
            total += nightly
            current += timedelta(days=1)

        # Apply advance purchase discount
        for days, discount in sorted(self._advance_purchase_discounts.items(), reverse=True):
            if days_advance >= days:
                total = total * Decimal(1.0 - discount)
                break

        return total


class RoomAssignmentOptimizer:
    """Optimize room assignment based on preferences and upgrades."""

    def __init__(self) -> None:
        """Initialize optimizer."""
        self._room_assignments: dict[str, str] = {}  # booking_id -> room_number
        self._upgrade_eligible: set[str] = set()  # booking_ids eligible for upgrade

    def mark_upgrade_eligible(self, booking_id: str) -> None:
        """
        Mark booking as eligible for room upgrade.

        Args:
            booking_id: Booking identifier
        """
        self._upgrade_eligible.add(booking_id)

    def assign_room(
        self,
        hotel_id: str,
        booking_id: str,
        room_type: str,
        preference: str | None = None,
    ) -> str:
        """
        Assign room to booking.

        Args:
            hotel_id: Hotel identifier
            booking_id: Booking identifier
            room_type: Room type code
            preference: Room preference (e.g., "high_floor", "quiet")

        Returns:
            Assigned room number
        """
        # Generate room number based on type and preference
        if preference == "high_floor":
            floor = random.randint(5, 10)
        elif preference == "quiet":
            floor = random.randint(1, 3)
        else:
            floor = random.randint(1, 8)

        room_number = f"{floor}{random.randint(1, 50):02d}"
        self._room_assignments[booking_id] = room_number

        # Upgrade if eligible
        if booking_id in self._upgrade_eligible:
            room_number = self._apply_upgrade(room_number, room_type)

        return room_number

    def _apply_upgrade(self, original_room: str, original_type: str) -> str:
        """
        Apply room upgrade.

        Args:
            original_room: Original room number
            original_type: Original room type

        Returns:
            Upgraded room number
        """
        # Simple upgrade: move to higher floor
        floor = int(original_room[0])
        if floor < 8:
            floor += 1
        room_number = f"{floor}{original_room[1:]}"
        return room_number

    def get_assignment(self, booking_id: str) -> str | None:
        """
        Get assigned room for booking.

        Args:
            booking_id: Booking identifier

        Returns:
            Room number, or None if not assigned
        """
        return self._room_assignments.get(booking_id)


class OverbookingManager:
    """Manage hotel overbooking with compensation tracking."""

    def __init__(self, overbooking_percentage: float = 0.05) -> None:
        """
        Initialize overbooking manager.

        Args:
            overbooking_percentage: Percentage of inventory to overbook (default 5%)
        """
        self.overbooking_percentage = overbooking_percentage
        self._overbooked_reservations: dict[str, Decimal] = {}  # booking_id -> compensation

    def can_accept_overbooking(
        self,
        available: int,
        inventory_size: int,
    ) -> bool:
        """
        Check if overbooking threshold allows new reservation.

        Args:
            available: Current available rooms
            inventory_size: Total room inventory

        Returns:
            True if overbooking can be accepted
        """
        overbooked = inventory_size - available
        max_overbooked = inventory_size * self.overbooking_percentage
        return overbooked < max_overbooked

    def register_overbooking(self, booking_id: str, compensation: Decimal) -> None:
        """
        Register overbooked reservation with compensation.

        Args:
            booking_id: Booking identifier
            compensation: Compensation amount for guest
        """
        self._overbooked_reservations[booking_id] = compensation

    def get_compensation(self, booking_id: str) -> Decimal | None:
        """
        Get compensation for overbooking.

        Args:
            booking_id: Booking identifier

        Returns:
            Compensation amount, or None
        """
        return self._overbooked_reservations.get(booking_id)


class HotelBookingEngine:
    """Main hotel booking engine."""

    def __init__(self, hotel: Hotel) -> None:
        """
        Initialize booking engine.

        Args:
            hotel: Hotel object
        """
        self.hotel = hotel
        self.inventory = RoomInventoryMatrix(hotel)
        self.pricing = RatePricingEngine()
        self.assignment = RoomAssignmentOptimizer()
        self.overbooking = OverbookingManager()
        self._bookings: dict[str, dict] = {}
        self._booking_counter = 0

    def search_availability(
        self,
        room_type: str,
        check_in: date,
        check_out: date,
    ) -> dict[str, any]:
        """
        Search room availability.

        Args:
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date

        Returns:
            Availability information
        """
        available = self.inventory.get_availability_range(room_type, check_in, check_out)
        nightly_rate = self.pricing.calculate_nightly_rate(self.hotel.name, room_type, check_in)

        return {
            "room_type": room_type,
            "available_rooms": available,
            "nightly_rate": nightly_rate,
            "check_in": check_in,
            "check_out": check_out,
            "total_nights": (check_out - check_in).days,
        }

    def create_booking(
        self,
        guest_name: str,
        room_type: str,
        check_in: date,
        check_out: date,
        is_corporate: bool = False,
        loyalty_tier: LoyaltyTier | None = None,
    ) -> dict[str, any]:
        """
        Create hotel booking.

        Args:
            guest_name: Guest name
            room_type: Room type code
            check_in: Check-in date
            check_out: Check-out date
            is_corporate: Whether corporate rate applies
            loyalty_tier: Loyalty tier

        Returns:
            Booking confirmation

        Raises:
            HotelNotAvailableError: If rooms not available
            OverbookingError: If overbooking limit exceeded
        """
        available = self.inventory.get_availability_range(room_type, check_in, check_out)

        if available <= 0:
            # Check overbooking possibility
            inventory_size = self.hotel.room_types.get(room_type, 0)
            if not self.overbooking.can_accept_overbooking(available, inventory_size):
                raise OverbookingError(f"Cannot overbook {room_type} rooms")

            # Create overbooking with compensation
            compensation = Decimal("100")  # Flat compensation
            self._booking_counter += 1
            booking_id = f"OB-{self.hotel.name}-{self._booking_counter}"
            self.overbooking.register_overbooking(booking_id, compensation)
        else:
            # Normal reservation
            self.inventory.reserve_room(room_type, check_in, check_out)
            self._booking_counter += 1
            booking_id = f"HB-{self.hotel.name}-{self._booking_counter}"

        # Calculate total
        days_advance = (check_in - date.today()).days
        total_cost = self.pricing.calculate_stay_total(
            self.hotel.name, room_type, check_in, check_out, is_corporate, loyalty_tier, days_advance
        )

        # Assign room
        assigned_room = self.assignment.assign_room(self.hotel.name, booking_id, room_type)

        booking = {
            "booking_id": booking_id,
            "hotel": self.hotel.name,
            "guest_name": guest_name,
            "room_type": room_type,
            "assigned_room": assigned_room,
            "check_in": check_in,
            "check_out": check_out,
            "total_nights": (check_out - check_in).days,
            "nightly_rate": self.pricing.calculate_nightly_rate(
                self.hotel.name, room_type, check_in, is_corporate, loyalty_tier
            ),
            "total_cost": total_cost,
            "status": HotelBookingStatus.RESERVED,
            "created": datetime.now(),
        }

        self._bookings[booking_id] = booking
        return booking

    def confirm_booking(self, booking_id: str) -> dict[str, any]:
        """
        Confirm hotel booking.

        Args:
            booking_id: Booking identifier

        Returns:
            Confirmed booking

        Raises:
            BookingError: If booking not found
        """
        if booking_id not in self._bookings:
            raise BookingError(f"Booking {booking_id} not found")

        booking = self._bookings[booking_id]
        booking["status"] = HotelBookingStatus.CONFIRMED
        return booking

    def check_in(self, booking_id: str) -> dict[str, any]:
        """
        Check in guest.

        Args:
            booking_id: Booking identifier

        Returns:
            Updated booking

        Raises:
            BookingError: If booking not found
        """
        if booking_id not in self._bookings:
            raise BookingError(f"Booking {booking_id} not found")

        booking = self._bookings[booking_id]
        booking["status"] = HotelBookingStatus.CHECKED_IN
        booking["check_in_time"] = datetime.now()
        return booking

    def check_out(self, booking_id: str) -> dict[str, any]:
        """
        Check out guest.

        Args:
            booking_id: Booking identifier

        Returns:
            Updated booking
        """
        if booking_id not in self._bookings:
            raise BookingError(f"Booking {booking_id} not found")

        booking = self._bookings[booking_id]
        booking["status"] = HotelBookingStatus.CHECKED_OUT
        booking["check_out_time"] = datetime.now()
        return booking

    def cancel_booking(self, booking_id: str) -> dict[str, any]:
        """
        Cancel hotel booking.

        Args:
            booking_id: Booking identifier

        Returns:
            Cancelled booking
        """
        if booking_id not in self._bookings:
            raise BookingError(f"Booking {booking_id} not found")

        booking = self._bookings[booking_id]
        booking["status"] = HotelBookingStatus.CANCELLED
        booking["cancellation_time"] = datetime.now()

        # Release room inventory
        if booking_id.startswith("HB-"):
            self.inventory.release_room(booking["room_type"], booking["check_in"], booking["check_out"])

        return booking
