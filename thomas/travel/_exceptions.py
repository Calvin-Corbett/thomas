"""Exception classes for travel module."""


class TravelException(Exception):
    """Base exception for travel module."""

    pass


class FlightNotAvailableError(TravelException):
    """Raised when flight is not available."""

    pass


class InvalidConnectionError(TravelException):
    """Raised when connection time is insufficient."""

    pass


class PassengerError(TravelException):
    """Raised for passenger-related errors."""

    pass


class InvalidPassportError(PassengerError):
    """Raised when passport is invalid or expired."""

    pass


class BookingError(TravelException):
    """Raised for booking-related errors."""

    pass


class PaymentError(TravelException):
    """Raised for payment processing errors."""

    pass


class HotelNotAvailableError(TravelException):
    """Raised when hotel room not available."""

    pass


class OverbookingError(TravelException):
    """Raised when overbooking limit exceeded."""

    pass


class ItineraryConflictError(TravelException):
    """Raised when bookings conflict in itinerary."""

    pass


class PricingError(TravelException):
    """Raised for pricing calculation errors."""

    pass


class CurrencyConversionError(PricingError):
    """Raised when currency conversion fails."""

    pass


class LoyaltyError(TravelException):
    """Raised for loyalty program errors."""

    pass


class InsufficientPointsError(LoyaltyError):
    """Raised when insufficient points for redemption."""

    pass


class ExpenseError(TravelException):
    """Raised for expense management errors."""

    pass


class PolicyComplianceError(ExpenseError):
    """Raised when expense violates policy."""

    pass


class GeographyError(TravelException):
    """Raised for geography-related errors."""

    pass


class InvalidAirportError(GeographyError):
    """Raised when airport code is invalid."""

    pass


class RoutingError(TravelException):
    """Raised when route calculation fails."""

    pass


class NoRouteFoundError(RoutingError):
    """Raised when no flight path exists."""

    pass


class InvalidSearchError(TravelException):
    """Raised for invalid search parameters."""

    pass


class CancellationError(TravelException):
    """Raised for cancellation-related errors."""

    pass
