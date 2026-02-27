"""Exploratory Data Analysis module for data profiling and statistical analysis."""

from thomas.eda.core import (
    ColumnProfile,
    CorrelationAnalyzer,
    DataProfiler,
    DataReport,
    DistributionAnalyzer,
    OutlierDetector,
)
from thomas.eda.tools import register_eda_tools

__all__ = [
    "ColumnProfile",
    "DataProfiler",
    "DistributionAnalyzer",
    "CorrelationAnalyzer",
    "OutlierDetector",
    "DataReport",
    "register_eda_tools",
]
