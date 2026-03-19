"""Tests for booking engine module."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.travel._exceptions import BookingError, InvalidPassportError
from thomas.travel._types import Airport, FareClass, Flight, Passenger, Seat
from thomas.travel.booking import (
    BookingModificationEngine,
    BookingWorkflow,
    CancellationEngine,
    PassengerValidator,
    PNRGenerator,
    SeatAssignment,
    WaitlistManager,
)


@pytest.fixture
def pnr_generator():
    """Create PNR generator."""
    return PNRGenerator()


@pytest.fixture
def sample_airport():
    """Create sample airport."""
    return Airport(
        iata_code="JFK",
        icao_code="KJFK",
        name="John F. Kennedy",
        city="New York",
        country="USA",
        latitude=40.6413,
        longitude=-73.7781,
        timezone="America/New_York",
        altitude_feet=13,
    )


@pytest.fixture
def sample_flight(sample_airport):
    """Create sample flight."""
    return Flight(
        flight_number="AA100",
        airline_code="AA",
        aircraft_type="Boeing 777",
        origin=sample_airport,
        destination=sample_airport,
        departure_time=datetime.now() + timedelta(days=7),
        arrival_time=datetime.now() + timedelta(days=7, hours=5),
        duration_minutes=300,
        seats={
            "1A": Seat("1A", 1, "A", FareClass.ECONOMY),
            "1B": Seat("1B", 1, "B", FareClass.ECONOMY),
            "1C": Seat("1C", 1, "C", FareClass.ECONOMY),
        },
    )


@pytest.fixture
def sample_passengers():
    """Create sample passengers."""
    return [
        Passenger(
            first_name="John",
            last_name="Doe",
            date_of_birth=datetime(1990, 1, 1),
            email="john@example.com",
            phone="+1234567890",
            passport_number="ABC123456",
            passport_expiry=datetime.now() + timedelta(days=365),
            passport_country="USA",
        ),
        Passenger(
            first_name="Jane",
            last_name="Doe",
            date_of_birth=datetime(1992, 6, 15),
            email="jane@example.com",
            phone="+1234567891",
            passport_number="XYZ789012",
            passport_expiry=datetime.now() + timedelta(days=365),
            passport_country="USA",
        ),
    ]


class TestPNRGenerator:
    """Test PNR generation."""

    def test_generate_pnr(self, pnr_generator):
        """Test generating PNR."""
        pnr = pnr_generator.generate_pnr()
        assert len(pnr) == 6
        assert pnr_generator.is_generated(pnr)

    def test_unique_pnrs(self, pnr_generator):
        """Test that PNRs are unique."""
        pnr1 = pnr_generator.generate_pnr()
        pnr2 = pnr_generator.generate_pnr()
        assert pnr1 != pnr2

    def test_validate_pnr_format(self, pnr_generator):
        """Test PNR format validation."""
        valid = pnr_generator.validate_pnr("ABC123")
        assert valid

        invalid = pnr_generator.validate_pnr("AB12")  # Too short
        assert not invalid

    def test_validate_pnr_existence(self, pnr_generator):
        """Test PNR existence validation."""
        pnr = pnr_generator.generate_pnr()
        assert pnr_generator.is_generated(pnr)
        assert not pnr_generator.is_generated("FAKE00")


class TestPassengerValidator:
    """Test passenger validation."""

    def test_validate_passenger_valid(self, sample_passengers):
        """Test validating valid passenger."""
        passenger = sample_passengers[0]
        travel_date = datetime.now() + timedelta(days=30)

        result = PassengerValidator.validate_passenger(passenger, travel_date)
        assert result is True

    def test_validate_passenger_expired_passport(self, sample_passengers):
        """Test error with expired passport."""
        passenger = sample_passengers[0]
        passenger.passport_expiry = datetime.now() - timedelta(days=1)

        travel_date = datetime.now() + timedelta(days=30)

        with pytest.raises(InvalidPassportError):
            PassengerValidator.validate_passenger(passenger, travel_date)

    def test_validate_multiple_passengers(self, sample_passengers):
        """Test validating multiple passengers."""
        travel_date = datetime.now() + timedelta(days=30)

        result = PassengerValidator.validate_passengers(sample_passengers, travel_date)
        assert result is True


class TestSeatAssignment:
    """Test seat assignment."""

    def test_assign_seats(self, sample_flight, sample_passengers):
        """Test assigning seats to passengers."""
        assigner = SeatAssignment(sample_flight)

        assignments = assigner.assign_seats(sample_passengers, FareClass.ECONOMY)

        assert len(assignments) == 2
        assert all(v in ["1A", "1B", "1C"] for v in assignments.values())

    def test_get_assignment(self, sample_flight, sample_passengers):
        """Test retrieving seat assignment."""
        assigner = SeatAssignment(sample_flight)
        assignments = assigner.assign_seats(sample_passengers, FareClass.ECONOMY)

        for passenger_name, seat in assignments.items():
            assert assigner.get_assignment(passenger_name) == seat

    def test_insufficient_seats(self, sample_flight):
        """Test error when insufficient seats available."""
        assigner = SeatAssignment(sample_flight)

        # Create more passengers than seats
        passengers = [
            Passenger(
                first_name=f"Passenger{i}",
                last_name="Test",
                date_of_birth=datetime(1990, 1, 1),
                email=f"p{i}@example.com",
                phone="+1234567890",
            )
            for i in range(5)
        ]

        with pytest.raises(BookingError):
            assigner.assign_seats(passengers, FareClass.ECONOMY)


class TestBookingWorkflow:
    """Test booking workflow."""

    def test_create_booking_session(self, pnr_generator, sample_flight):
        """Test creating booking session."""
        workflow = BookingWorkflow(pnr_generator)
        session_id = workflow.create_booking_session(sample_flight, FareClass.ECONOMY)

        assert session_id is not None

    def test_add_passengers(self, pnr_generator, sample_flight, sample_passengers):
        """Test adding passengers to booking."""
        workflow = BookingWorkflow(pnr_generator)
        session_id = workflow.create_booking_session(sample_flight, FareClass.ECONOMY)

        workflow.add_passengers(session_id, sample_passengers)

    def test_process_payment(self, pnr_generator, sample_flight):
        """Test processing payment."""
        workflow = BookingWorkflow(pnr_generator)
        session_id = workflow.create_booking_session(sample_flight, FareClass.ECONOMY)

        result = workflow.process_payment(session_id, "CC4532", Decimal("500"))
        assert result is True

    def test_confirm_booking(self, pnr_generator, sample_flight, sample_passengers):
        """Test confirming booking."""
        workflow = BookingWorkflow(pnr_generator)
        session_id = workflow.create_booking_session(sample_flight, FareClass.ECONOMY)

        workflow.add_passengers(session_id, sample_passengers)
        workflow.process_payment(session_id, "CC4532", Decimal("500"))

        booking = workflow.confirm_booking(session_id)

        assert booking.pnr is not None
        assert booking.flight == sample_flight
        assert len(booking.passengers) == 2


class TestBookingModification:
    """Test booking modifications."""

    def test_change_date(self, sample_flight):
        """Test changing flight date."""
        engine = BookingModificationEngine()

        from thomas.travel.booking import Booking, BookingStatus

        booking = Booking(
            pnr="ABC123",
            flight=sample_flight,
            passengers=[],
            fare_class=FareClass.ECONOMY,
            seats={},
            status=BookingStatus.CONFIRMED,
        )

        new_date = sample_flight.departure_time + timedelta(days=1)
        modification = engine.change_date("ABC123", booking, new_date, Decimal("50"))

        assert modification["type"] == "date_change"
        assert modification["change_fee"] == Decimal("50")

    def test_correct_passenger_name(self):
        """Test correcting passenger name."""
        engine = BookingModificationEngine()

        modification = engine.correct_passenger_name("ABC123", 0, "John Smith")

        assert modification["type"] == "name_correction"
        assert modification["corrected_name"] == "John Smith"

    def test_add_service(self):
        """Test adding service to booking."""
        engine = BookingModificationEngine()

        service = engine.add_service("ABC123", "extra_baggage", Decimal("50"))

        assert service["type"] == "add_service"
        assert service["service"] == "extra_baggage"

    def test_get_modification_history(self):
        """Test retrieving modification history."""
        engine = BookingModificationEngine()

        engine.add_service("ABC123", "extra_baggage", Decimal("50"))
        engine.add_service("ABC123", "seat_selection", Decimal("10"))

        history = engine.get_modification_history("ABC123")
        assert len(history) == 2


class TestCancellation:
    """Test booking cancellation."""

    def test_cancel_booking_full_refund(self, sample_flight):
        """Test cancellation with full refund."""
        from thomas.travel.booking import Booking, BookingStatus

        booking = Booking(
            pnr="ABC123",
            flight=sample_flight,
            passengers=[],
            fare_class=FareClass.ECONOMY,
            seats={},
            status=BookingStatus.CONFIRMED,
            price=Decimal("500"),
        )

        engine = CancellationEngine()
        cancellation = engine.cancel_booking("ABC123", booking)

        # Booking is 7+ days away, should be full refund
        assert cancellation["refund_amount"] == Decimal("500")

    def test_cancel_booking_partial_refund(self, sample_flight):
        """Test cancellation with partial refund."""
        from thomas.travel.booking import Booking, BookingStatus

        # Flight is 2 days away
        near_flight = Flight(
            flight_number="AA100",
            airline_code="AA",
            aircraft_type="Boeing 777",
            origin=sample_flight.origin,
            destination=sample_flight.destination,
            departure_time=datetime.now() + timedelta(days=2),
            arrival_time=datetime.now() + timedelta(days=2, hours=5),
            duration_minutes=300,
        )

        booking = Booking(
            pnr="ABC123",
            flight=near_flight,
            passengers=[],
            fare_class=FareClass.ECONOMY,
            seats={},
            status=BookingStatus.CONFIRMED,
            price=Decimal("500"),
        )

        engine = CancellationEngine()
        cancellation = engine.cancel_booking("ABC123", booking)

        # Cancellation < 3 days before = 25% refund
        assert cancellation["refund_amount"] < Decimal("500")


class TestWaitlist:
    """Test waitlist management."""

    def test_add_to_waitlist(self):
        """Test adding passenger to waitlist."""
        manager = WaitlistManager()

        entry = manager.add_to_waitlist("AA100", "John Doe", "john@example.com", FareClass.ECONOMY)

        assert entry["position"] == 1
        assert entry["passenger_name"] == "John Doe"

    def test_get_waitlist(self):
        """Test retrieving waitlist."""
        manager = WaitlistManager()

        manager.add_to_waitlist("AA100", "John", "john@example.com", FareClass.ECONOMY)
        manager.add_to_waitlist("AA100", "Jane", "jane@example.com", FareClass.ECONOMY)

        waitlist = manager.get_waitlist("AA100")
        assert len(waitlist) == 2

    def test_confirm_from_waitlist(self):
        """Test confirming passenger from waitlist."""
        manager = WaitlistManager()

        manager.add_to_waitlist("AA100", "John", "john@example.com", FareClass.ECONOMY)

        confirmed = manager.confirm_from_waitlist("AA100", 1)

        assert confirmed is not None
        assert confirmed["confirmed"] is True


class TestBookingIntegration:
    """Integration tests for booking operations."""

    def test_complete_booking_flow(self, pnr_generator, sample_flight, sample_passengers):
        """Test complete booking workflow."""
        # Create session
        workflow = BookingWorkflow(pnr_generator)
        session_id = workflow.create_booking_session(sample_flight, FareClass.ECONOMY)

        # Add passengers
        workflow.add_passengers(session_id, sample_passengers)

        # Process payment
        workflow.process_payment(session_id, "CC4532", Decimal("500"))

        # Confirm
        booking = workflow.confirm_booking(session_id)

        assert booking.pnr is not None
        assert booking.status.value == "confirmed"
        assert len(booking.seats) > 0
