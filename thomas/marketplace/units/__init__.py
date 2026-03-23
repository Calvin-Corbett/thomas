"""Units of measurement and conversion system.

Provides unit definitions, conversions, and dimensional analysis.
"""

from .core import (
    Dimension,
    DimensionalAnalysis,
    Quantity,
    Unit,
    UnitRegistry,
)

__all__ = [
    "Dimension",
    "Unit",
    "UnitRegistry",
    "Quantity",
    "DimensionalAnalysis",
]

__version__ = "1.0.0"
