"""Units of measurement and conversion system.

Provides unit definitions, conversions, and dimensional analysis.
"""

from dataclasses import dataclass
from enum import Enum


class Dimension(Enum):
    """Physical dimensions."""

    LENGTH = "length"
    MASS = "mass"
    TIME = "time"
    TEMPERATURE = "temperature"
    VOLUME = "volume"
    VELOCITY = "velocity"
    ACCELERATION = "acceleration"
    FORCE = "force"
    ENERGY = "energy"
    POWER = "power"


@dataclass
class Unit:
    """Physical unit."""

    name: str
    symbol: str
    dimension: Dimension
    to_base_factor: float = 1.0
    offset: float = 0.0

    def convert_to_base(self, value: float) -> float:
        """Convert to base unit."""
        return (value + self.offset) * self.to_base_factor

    def convert_from_base(self, value: float) -> float:
        """Convert from base unit."""
        return value / self.to_base_factor - self.offset


class UnitRegistry:
    """Registry of units."""

    def __init__(self):
        self.units: dict[str, Unit] = {}
        self.base_units: dict[Dimension, Unit] = {}
        self._initialize_standard_units()

    def _initialize_standard_units(self) -> None:
        """Initialize standard SI units."""
        # Length
        meter = Unit("meter", "m", Dimension.LENGTH, 1.0)
        self.register_unit(meter)
        self.base_units[Dimension.LENGTH] = meter

        kilometer = Unit("kilometer", "km", Dimension.LENGTH, 1000.0)
        self.register_unit(kilometer)

        # Mass
        kilogram = Unit("kilogram", "kg", Dimension.MASS, 1.0)
        self.register_unit(kilogram)
        self.base_units[Dimension.MASS] = kilogram

        gram = Unit("gram", "g", Dimension.MASS, 0.001)
        self.register_unit(gram)

        # Time
        second = Unit("second", "s", Dimension.TIME, 1.0)
        self.register_unit(second)
        self.base_units[Dimension.TIME] = second

        minute = Unit("minute", "min", Dimension.TIME, 60.0)
        self.register_unit(minute)

        # Temperature
        kelvin = Unit("kelvin", "K", Dimension.TEMPERATURE, 1.0)
        self.register_unit(kelvin)
        self.base_units[Dimension.TEMPERATURE] = kelvin

        # Volume
        liter = Unit("liter", "L", Dimension.VOLUME, 0.001)
        self.register_unit(liter)

    def register_unit(self, unit: Unit) -> None:
        """Register unit."""
        self.units[unit.symbol] = unit
        self.units[unit.name] = unit

    def get_unit(self, name: str) -> Unit | None:
        """Get unit by name or symbol."""
        return self.units.get(name)

    def convert(self, value: float, from_unit: str, to_unit: str) -> float | None:
        """Convert between units."""
        from_u = self.get_unit(from_unit)
        to_u = self.get_unit(to_unit)

        if not from_u or not to_u:
            return None

        if from_u.dimension != to_u.dimension:
            return None

        # Convert to base unit then to target unit
        base_value = from_u.convert_to_base(value)
        return to_u.convert_from_base(base_value)

    def list_units(self, dimension: Dimension = None) -> list:
        """List available units."""
        if dimension:
            return [u for u in self.units.values() if u.dimension == dimension]
        return list(self.units.values())


class Quantity:
    """Physical quantity with unit."""

    def __init__(self, value: float, unit: Unit):
        self.value = value
        self.unit = unit

    def convert_to(self, target_unit: Unit) -> "Quantity":
        """Convert to another unit."""
        if self.unit.dimension != target_unit.dimension:
            raise ValueError("Incompatible dimensions")

        base_value = self.unit.convert_to_base(self.value)
        new_value = target_unit.convert_from_base(base_value)
        return Quantity(new_value, target_unit)

    def __str__(self) -> str:
        return f"{self.value} {self.unit.symbol}"


class DimensionalAnalysis:
    """Dimensional analysis tools."""

    @staticmethod
    def check_compatibility(dim1: Dimension, dim2: Dimension) -> bool:
        """Check if dimensions are compatible."""
        return dim1 == dim2

    @staticmethod
    def multiply_dimensions(dim1: Dimension, dim2: Dimension) -> Dimension | None:
        """Multiply dimensions."""
        # Simplified dimensional multiplication
        if dim1 == Dimension.LENGTH and dim2 == Dimension.LENGTH:
            return Dimension.VOLUME
        if dim1 == Dimension.LENGTH and dim2 == Dimension.TIME:
            return Dimension.VELOCITY
        return None

    @staticmethod
    def divide_dimensions(dim1: Dimension, dim2: Dimension) -> Dimension | None:
        """Divide dimensions."""
        if dim1 == Dimension.LENGTH and dim2 == Dimension.TIME:
            return Dimension.VELOCITY
        if dim1 == Dimension.VELOCITY and dim2 == Dimension.TIME:
            return Dimension.ACCELERATION
        return None
