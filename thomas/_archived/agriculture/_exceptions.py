"""Custom exceptions for the agriculture module."""


class AgriculturalError(Exception):
    """Base exception for agriculture module."""

    pass


class CropError(AgriculturalError):
    """Exception for crop-related errors."""

    pass


class SoilError(AgriculturalError):
    """Exception for soil-related errors."""

    pass


class IrrigationError(AgriculturalError):
    """Exception for irrigation-related errors."""

    pass


class NutrientError(AgriculturalError):
    """Exception for nutrient management errors."""

    pass


class PestError(AgriculturalError):
    """Exception for pest management errors."""

    pass


class WeatherError(AgriculturalError):
    """Exception for weather-related errors."""

    pass


class PrecisionError(AgriculturalError):
    """Exception for precision agriculture errors."""

    pass


class LivestockError(AgriculturalError):
    """Exception for livestock management errors."""

    pass


class EconomicsError(AgriculturalError):
    """Exception for farm economics errors."""

    pass
