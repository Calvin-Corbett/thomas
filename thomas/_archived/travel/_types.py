"""Type definitions for travel booking and itinerary management."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class FareClass(Enum):
    """Fare classification for flights."""

    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class BookingStatus(Enum):
    """Status of a booking."""

    SEARCH = "search"
    SELECTED = "selected"
    PASSENGER_DETAILS = "passenger_details"
    PAYMENT = "payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class HotelBookingStatus(Enum):
    """Status of a hotel booking."""

    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"


class ExpenseStatus(Enum):
    """Status of an expense report."""

    SUBMITTED = "submitted"
    APPROVED = "approved"
    REIMBURSED = "reimbursed"
    REJECTED = "rejected"


class LoyaltyTier(Enum):
    """Loyalty program tier."""

    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class Currency(Enum):
    """Supported currencies."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    AUD = "AUD"
    CAD = "CAD"


@dataclass
class Airport:
    """Airport representation with geographic and operational data."""

    iata_code: str
    icao_code: str
    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    altitude_feet: int
    is_hub: bool = False
    terminal_count: int = 1

    def __hash__(self) -> int:
        """Return hash of IATA code."""
        return hash(self.iata_code)

    def __eq__(self, other: object) -> bool:
        """Check equality by IATA code."""
        if not isinstance(other, Airport):
            return NotImplemented
        return self.iata_code == other.iata_code


@dataclass
class Route:
    """Flight route between two airports."""

    origin: Airport
    destination: Airport
    distance_km: float
    average_flight_time_minutes: int
    is_direct: bool = True

    def reverse(self) -> "Route":
        """Return reverse route."""
        return Route(
            origin=self.destination,
            destination=self.origin,
            distance_km=self.distance_km,
            average_flight_time_minutes=self.average_flight_time_minutes,
            is_direct=self.is_direct,
        )


@dataclass
class Fare:
    """Fare information for a flight."""

    base_price: Decimal
    taxes: Decimal
    fees: Decimal
    currency: Currency
    fare_class: FareClass
    availability_count: int
    advance_purchase_days: int = 0
    is_refundable: bool = False
    change_fee: Decimal = Decimal("0")
    cancellation_penalty: Decimal = Decimal("0")

    @property
    def total_price(self) -> Decimal:
        """Calculate total fare price."""
        return self.base_price + self.taxes + self.fees

    def is_available(self) -> bool:
        """Check if fare class has availability."""
        return self.availability_count > 0


@dataclass
class Seat:
    """Seat information on an aircraft."""

    seat_number: str
    row: int
    column: str
    fare_class: FareClass
    is_available: bool = True
    is_emergency_exit: bool = False
    extra_legroom: bool = False
    price_upcharge: Decimal = Decimal("0")


@dataclass
class Flight:
    """Flight representation with schedule and pricing."""

    flight_number: str
    airline_code: str
    aircraft_type: str
    origin: Airport
    destination: Airport
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int
    stops: int = 0
    fares: dict[FareClass, Fare] = field(default_factory=dict)
    seats: dict[str, Seat] = field(default_factory=dict)
    codeshare_with: str | None = None
    operating_airline: str | None = None
    is_cancelled: bool = False

    def available_seats_by_class(self, fare_class: FareClass) -> list[Seat]:
        """Get available seats for fare class."""
        return [seat for seat in self.seats.values() if seat.is_available and seat.fare_class == fare_class]

    def get_fare(self, fare_class: FareClass) -> Fare | None:
        """Get fare for specific class."""
        return self.fares.get(fare_class)


@dataclass
class Passenger:
    """Passenger information."""

    first_name: str
    last_name: str
    date_of_birth: datetime
    email: str
    phone: str
    passport_number: str | None = None
    passport_expiry: datetime | None = None
    passport_country: str | None = None
    loyalty_number: str | None = None
    seat_preference: str | None = None
    meal_preference: str | None = None

    @property
    def full_name(self) -> str:
        """Get full name."""
        return f"{self.first_name} {self.last_name}"

    def is_passport_valid(self, check_date: datetime) -> bool:
        """Check if passport is valid on given date."""
        if not self.passport_expiry:
            return False
        return check_date < self.passport_expiry


@dataclass
class Booking:
    """Flight booking record."""

    pnr: str
    flight: Flight
    passengers: list[Passenger]
    fare_class: FareClass
    seats: dict[str, Seat]
    status: BookingStatus = BookingStatus.SEARCH
    booking_date: datetime = field(default_factory=datetime.utcnow)
    price: Decimal = Decimal("0")
    currency: Currency = Currency.USD
    payment_method: str | None = None
    confirmation_sent: bool = False
    itinerary_reference: str | None = None

    def total_passengers(self) -> int:
        """Get number of passengers."""
        return len(self.passengers)

    def is_confirmed(self) -> bool:
        """Check if booking is confirmed."""
        return self.status == BookingStatus.CONFIRMED


@dataclass
class Hotel:
    """Hotel property with room inventory."""

    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    star_rating: float
    check_in_time: str
    check_out_time: str
    room_types: dict[str, int] = field(default_factory=dict)
    amenities: list[str] = field(default_factory=list)
    policies: dict[str, str] = field(default_factory=dict)

    def rooms_available_on_date(self, room_type: str, date: datetime) -> int:
        """Get available rooms for type on date."""
        return self.room_types.get(room_type, 0)


@dataclass
class CarRental:
    """Car rental booking."""

    company: str
    vehicle_type: str
    pickup_location: str
    dropoff_location: str
    pickup_time: datetime
    dropoff_time: datetime
    daily_rate: Decimal
    currency: Currency
    driver_age: int
    insurance_type: str | None = None
    fuel_option: str = "full_to_full"
    mileage_limit: int | None = None

    @property
    def rental_days(self) -> int:
        """Calculate rental duration in days."""
        return (self.dropoff_time.date() - self.pickup_time.date()).days

    @property
    def total_cost(self) -> Decimal:
        """Calculate total rental cost."""
        return self.daily_rate * Decimal(max(1, self.rental_days))


@dataclass
class Activity:
    """Travel activity booking."""

    name: str
    location: str
    start_time: datetime
    end_time: datetime
    category: str
    price: Decimal
    currency: Currency
    duration_minutes: int
    participants: int
    provider: str
    confirmation_number: str | None = None
    cancellation_deadline: datetime | None = None
    notes: str | None = None

    def is_available_on_date(self, date: datetime) -> bool:
        """Check if activity is on specified date."""
        return self.start_time.date() == date.date()

    def has_passed(self, current_time: datetime) -> bool:
        """Check if activity has ended."""
        return current_time > self.end_time


@dataclass
class Trip:
    """Complete trip representation."""

    trip_id: str
    start_date: datetime
    end_date: datetime
    origin_city: str
    destination_cities: list[str]
    budget: Decimal
    currency: Currency
    passengers: list[Passenger]
    trip_type: str  # "round_trip", "one_way", "multi_city"
    created_date: datetime = field(default_factory=datetime.utcnow)
    is_business: bool = False

    @property
    def duration_days(self) -> int:
        """Calculate trip duration in days."""
        return (self.end_date.date() - self.start_date.date()).days + 1

    def remaining_budget(self, spent: Decimal) -> Decimal:
        """Calculate remaining budget."""
        return self.budget - spent


@dataclass
class Itinerary:
    """Complete travel itinerary."""

    itinerary_id: str
    trip: Trip
    flights: list[Flight] = field(default_factory=list)
    hotels: list[Hotel] = field(default_factory=list)
    car_rentals: list[CarRental] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    version: int = 1
    created_date: datetime = field(default_factory=datetime.utcnow)
    last_modified: datetime = field(default_factory=datetime.utcnow)
    shared_with: set[str] = field(default_factory=set)
    notes: str = ""

    def get_daily_activities(self, date: datetime) -> list[Activity]:
        """Get activities for specific day."""
        return [a for a in self.activities if a.is_available_on_date(date)]

    def has_conflicts(self) -> bool:
        """Check for overlapping bookings."""
        # Simple conflict check: any overlapping time ranges
        all_events = []
        for flight in self.flights:
            all_events.append((flight.departure_time, flight.arrival_time))
        for activity in self.activities:
            all_events.append((activity.start_time, activity.end_time))

        for i, (start1, end1) in enumerate(all_events):
            for start2, end2 in all_events[i + 1 :]:
                if start1 < end2 and start2 < end1:
                    return True
        return False

    def calculate_total_cost(self) -> Decimal:
        """Calculate total itinerary cost."""
        total = Decimal("0")
        for activity in self.activities:
            total += activity.price
        for rental in self.car_rentals:
            total += rental.total_cost
        return total


@dataclass
class Loyalty:
    """Loyalty program membership."""

    member_id: str
    member_name: str
    tier: LoyaltyTier
    points_balance: int
    qualifying_points: int = 0
    segments_flown: int = 0
    miles_flown: int = 0
    enrollment_date: datetime = field(default_factory=datetime.utcnow)
    tier_expiry_date: datetime | None = None
    status_matches: int = 0
    certificate_balance: int = 0
    lounge_access: bool = False

    def points_per_dollar(self) -> float:
        """Get earning rate based on tier."""
        rates = {
            LoyaltyTier.STANDARD: 1.0,
            LoyaltyTier.SILVER: 1.25,
            LoyaltyTier.GOLD: 1.5,
            LoyaltyTier.PLATINUM: 2.0,
        }
        return rates.get(self.tier, 1.0)

    def can_redeem_award(self, miles_required: int) -> bool:
        """Check if member can redeem award."""
        return self.miles_flown >= miles_required

    def is_tier_active(self, current_date: datetime) -> bool:
        """Check if tier membership is active."""
        if not self.tier_expiry_date:
            return True
        return current_date <= self.tier_expiry_date


@dataclass
class Expense:
    """Travel expense record."""

    expense_id: str
    amount: Decimal
    currency: Currency
    category: str
    date: datetime
    description: str
    receipt_url: str | None = None
    merchant: str | None = None
    status: ExpenseStatus = ExpenseStatus.SUBMITTED
    policy_compliant: bool = True
    reimbursement_amount: Decimal | None = None
    notes: str = ""

    def is_over_limit(self, limit: Decimal) -> bool:
        """Check if expense exceeds limit."""
        return self.amount > limit


@dataclass
class TravelPolicy:
    """Corporate travel policy."""

    policy_id: str
    airline_preferred: list[str] = field(default_factory=list)
    hotel_preferred: list[str] = field(default_factory=list)
    max_daily_hotel_rate: Decimal = Decimal("250")
    max_daily_meal_allowance: Decimal = Decimal("75")
    max_ground_transportation: Decimal = Decimal("100")
    advance_booking_required_days: int = 14
    economy_only_below_hours: int = 6
    requires_manager_approval_above: Decimal = Decimal("5000")
    allows_personal_items: bool = True
    requires_receipt_above: Decimal = Decimal("25")
    currency: Currency = Currency.USD

    def is_airline_preferred(self, airline: str) -> bool:
        """Check if airline is preferred."""
        return airline in self.airline_preferred

    def is_hotel_preferred(self, hotel_name: str) -> bool:
        """Check if hotel is preferred."""
        return hotel_name in self.hotel_preferred
