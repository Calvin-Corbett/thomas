"""Tools for exploratory data analysis."""

from typing import Any

from thomas.eda import core
from thomas.tools.base import Tool, ToolResult


class ProfileTool(Tool):
    """Profile and analyze datasets."""

    name = "eda_profile"
    category = "eda"
    description = "Profile datasets and generate statistical summaries"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["profile_all", "profile_column", "summary_stats"],
                "description": "Profiling action",
            },
            "data": {"type": "array", "description": "Data rows to analyze"},
            "column": {"type": "string", "description": "Column name to profile"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            data = args.get("data", [])
            column = args.get("column", "")

            profiler = core.DataProfiler()
            if data:
                profiler.load_data(data)

            if action == "profile_all":
                profiles = profiler.profile_all()
                result = {
                    name: {
                        "dtype": p.dtype,
                        "non_null": p.non_null,
                        "null_count": p.null_count,
                        "unique": p.unique,
                        "min": p.min_val,
                        "max": p.max_val,
                        "mean": p.mean,
                    }
                    for name, p in profiles.items()
                }
                return ToolResult(ok=True, data=result)

            elif action == "profile_column":
                if not column or not data:
                    return ToolResult(ok=False, error="column and data required")
                profile = profiler.profile_column(column)
                if not profile:
                    return ToolResult(ok=False, error=f"Column {column} not found")
                return ToolResult(
                    ok=True,
                    data={
                        "dtype": profile.dtype,
                        "non_null": profile.non_null,
                        "null_count": profile.null_count,
                        "unique": profile.unique,
                        "min": profile.min_val,
                        "max": profile.max_val,
                        "mean": profile.mean,
                        "median": profile.median,
                    },
                )

            elif action == "summary_stats":
                if not data:
                    return ToolResult(ok=False, error="data required")
                stats = profiler.get_summary_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DistributionTool(Tool):
    """Analyze distributions and value counts."""

    name = "eda_distribution"
    category = "eda"
    description = "Analyze value distributions and generate histograms"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["value_counts", "histogram"], "description": "Distribution action"},
            "data": {"type": "array", "description": "Data rows"},
            "column": {"type": "string", "description": "Column to analyze"},
            "top_n": {"type": "integer", "description": "Top N values to return"},
            "bins": {"type": "integer", "description": "Number of histogram bins"},
        },
        "required": ["action", "column"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            data = args.get("data", [])
            column = args.get("column", "")
            top_n = args.get("top_n", 10)
            bins = args.get("bins", 10)

            if not data:
                return ToolResult(ok=False, error="data required")

            analyzer = core.DistributionAnalyzer(data)

            if action == "value_counts":
                counts = analyzer.value_counts(column, top_n=top_n)
                return ToolResult(ok=True, data={"counts": counts})

            elif action == "histogram":
                hist = analyzer.histogram(column, bins=bins)
                return ToolResult(ok=True, data=hist)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CorrelationTool(Tool):
    """Analyze correlations between columns."""

    name = "eda_correlation"
    category = "eda"
    description = "Calculate correlations and generate correlation matrices"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["correlation_matrix", "pearson_correlation"],
                "description": "Correlation action",
            },
            "data": {"type": "array", "description": "Data rows"},
            "column1": {"type": "string", "description": "First column"},
            "column2": {"type": "string", "description": "Second column"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            data = args.get("data", [])

            if not data:
                return ToolResult(ok=False, error="data required")

            analyzer = core.CorrelationAnalyzer(data)

            if action == "correlation_matrix":
                matrix = analyzer.correlation_matrix()
                return ToolResult(ok=True, data={"matrix": matrix})

            elif action == "pearson_correlation":
                col1 = args.get("column1", "")
                col2 = args.get("column2", "")
                if not col1 or not col2:
                    return ToolResult(ok=False, error="column1 and column2 required")
                corr = analyzer.pearson_correlation(col1, col2)
                return ToolResult(ok=True, data={"correlation": corr})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class OutlierTool(Tool):
    """Detect outliers in data."""

    name = "eda_outliers"
    category = "eda"
    description = "Detect outliers using IQR and Z-score methods"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["iqr_outliers", "zscore_outliers"],
                "description": "Outlier detection method",
            },
            "data": {"type": "array", "description": "Data rows"},
            "column": {"type": "string", "description": "Column to analyze"},
            "multiplier": {"type": "number", "description": "IQR multiplier (default 1.5)"},
            "threshold": {"type": "number", "description": "Z-score threshold (default 3.0)"},
        },
        "required": ["action", "column"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            data = args.get("data", [])
            column = args.get("column", "")
            multiplier = args.get("multiplier", 1.5)
            threshold = args.get("threshold", 3.0)

            if not data:
                return ToolResult(ok=False, error="data required")

            detector = core.OutlierDetector(data)

            if action == "iqr_outliers":
                outliers = detector.iqr_outliers(column, multiplier=multiplier)
                return ToolResult(ok=True, data={"outliers": outliers, "count": len(outliers)})

            elif action == "zscore_outliers":
                outliers = detector.zscore_outliers(column, threshold=threshold)
                return ToolResult(ok=True, data={"outliers": outliers, "count": len(outliers)})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_eda_tools(registry):
    """Register all EDA tools."""
    registry.register(ProfileTool())
    registry.register(DistributionTool())
    registry.register(CorrelationTool())
    registry.register(OutlierTool())
