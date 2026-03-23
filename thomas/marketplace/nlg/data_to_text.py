"""Data-to-text generation: converting structured data to text.

Implements data-to-text generation including:
- Statistical summary generation
- Comparison generation
- Table description
- Time series narration
- Sports recap generation
- Weather report generation
- Financial summary generation
"""

import statistics
from typing import Any

from thomas.marketplace.nlg._exceptions import NLGException
from thomas.marketplace.nlg._types import SemanticFrame, Slot


class DataToTextError(NLGException):
    """Raised when data-to-text conversion fails."""

    pass


class DataToTextGenerator:
    """Generates text from structured data.

    Converts tables, time series, box scores, forecast data, and other
    structured information into natural language descriptions.
    """

    def __init__(self) -> None:
        """Initialize data-to-text generator."""
        self.significance_threshold = 0.1  # 10% difference is significant
        self.summary_threshold = 3  # Minimum items to summarize

    def describe_statistics(self, data: list[float], label: str = "") -> str:
        """Generate statistical summary from numeric data.

        Args:
            data: List of numeric values
            label: Label for the data

        Returns:
            Text description of statistics

        Raises:
            DataToTextError: If description fails
        """
        if not data or len(data) < self.summary_threshold:
            raise DataToTextError("Insufficient data for statistical summary")

        mean = statistics.mean(data)
        median = statistics.median(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        min_val = min(data)
        max_val = max(data)

        # Build description
        parts = []

        if label:
            parts.append(f"{label}:")

        parts.append(f"average {mean:.1f}")
        parts.append(f"median {median:.1f}")
        parts.append(f"range {min_val:.1f} to {max_val:.1f}")

        if stdev > 0:
            parts.append(f"variance {stdev:.1f}")

        return ", ".join(parts)

    def describe_trends(self, time_series: list[tuple[Any, float]], label: str = "") -> str:
        """Generate trend description from time series data.

        Args:
            time_series: List of (timestamp, value) pairs
            label: Label for the trend

        Returns:
            Text description of trend

        Raises:
            DataToTextError: If description fails
        """
        if len(time_series) < 2:
            raise DataToTextError("Need at least 2 data points for trend")

        values = [v for _, v in time_series]
        first_val = values[0]
        last_val = values[-1]

        # Calculate trend direction
        change = last_val - first_val
        percent_change = (change / first_val) * 100 if first_val != 0 else 0

        # Describe trend
        parts = []
        if label:
            parts.append(label)

        if percent_change > self.significance_threshold * 100:
            parts.append(f"increased {abs(percent_change):.1f}%")
        elif percent_change < -self.significance_threshold * 100:
            parts.append(f"decreased {abs(percent_change):.1f}%")
        else:
            parts.append("remained stable")

        parts.append(f"from {first_val:.1f} to {last_val:.1f}")

        return " ".join(parts)

    def compare_values(self, value1: float, value2: float, label1: str = "", label2: str = "") -> str:
        """Generate comparison text.

        Args:
            value1: First value
            value2: Second value
            label1: Label for first value
            label2: Label for second value

        Returns:
            Comparison text

        Raises:
            DataToTextError: If comparison fails
        """
        if value1 == 0 and value2 == 0:
            raise DataToTextError("Cannot compare zero values")

        # Calculate difference
        diff = value2 - value1
        percent_diff = (diff / value1) * 100 if value1 != 0 else 0

        # Generate text
        parts = []
        if label1 and label2:
            parts.append(f"{label2} is")

        if percent_diff > 0:
            parts.append(f"{abs(percent_diff):.1f}% higher than {label1}")
        elif percent_diff < 0:
            parts.append(f"{abs(percent_diff):.1f}% lower than {label1}")
        else:
            parts.append(f"equal to {label1}")

        return " ".join(parts)

    def describe_table(self, table: list[dict[str, Any]]) -> str:
        """Generate description of table data.

        Args:
            table: List of row dictionaries

        Returns:
            Table description

        Raises:
            DataToTextError: If description fails
        """
        if not table:
            raise DataToTextError("Empty table")

        # Identify structure
        if not table:
            return ""

        keys = list(table[0].keys())
        row_count = len(table)

        parts = [f"Table with {row_count} rows and {len(keys)} columns"]

        # Identify numeric columns
        numeric_cols = []
        for key in keys:
            try:
                values = [float(row[key]) for row in table if key in row]
                numeric_cols.append((key, values))
            except (ValueError, TypeError):
                pass

        # Summarize numeric columns
        for col_name, values in numeric_cols:
            if values:
                parts.append(self.describe_statistics(values, label=col_name))

        return ". ".join(parts)

    def narrate_timeseries(self, time_series: list[tuple[str, float]], event_label: str = "") -> str:
        """Generate narrative from time series data.

        Args:
            time_series: List of (timestamp, value) pairs
            event_label: Label for the event/metric

        Returns:
            Time series narrative

        Raises:
            DataToTextError: If narration fails
        """
        if len(time_series) < 2:
            raise DataToTextError("Need at least 2 data points")

        narrative_parts = []

        # Opening statement
        if event_label:
            narrative_parts.append(f"{event_label} over time:")

        # Describe each segment
        for i in range(len(time_series) - 1):
            ts1, val1 = time_series[i]
            ts2, val2 = time_series[i + 1]

            # Trend between points
            change = val2 - val1
            direction = "increased" if change > 0 else "decreased" if change < 0 else "remained"

            narrative_parts.append(f"At {ts1}: {val1:.1f}")
            narrative_parts.append(f"By {ts2}: {val2:.1f} ({direction} by {abs(change):.1f})")

        return ", ".join(narrative_parts)

    def generate_sports_recap(self, box_score: dict[str, Any]) -> str:
        """Generate sports recap from box score.

        Args:
            box_score: Box score dictionary with teams and stats

        Returns:
            Sports recap text

        Raises:
            DataToTextError: If recap generation fails
        """
        if not box_score or "teams" not in box_score:
            raise DataToTextError("Invalid box score format")

        teams = box_score["teams"]
        if len(teams) != 2:
            raise DataToTextError("Box score must have 2 teams")

        team1, team2 = teams[0], teams[1]

        # Get scores
        score1 = team1.get("score", 0)
        score2 = team2.get("score", 0)

        # Build recap
        parts = []
        parts.append(f"{team1.get('name', 'Team 1')} defeated")
        parts.append(f"{team2.get('name', 'Team 2')} {score1}-{score2}")

        # Add key statistics
        if "key_stats" in team1:
            parts.append(f"Key stat: {team1['key_stats']}")

        return " ".join(parts)

    def generate_weather_report(self, forecast: dict[str, Any]) -> str:
        """Generate weather report from forecast data.

        Args:
            forecast: Forecast dictionary

        Returns:
            Weather report

        Raises:
            DataToTextError: If report generation fails
        """
        if not forecast:
            raise DataToTextError("Empty forecast")

        parts = []

        # Temperature
        if "temperature" in forecast:
            temp = forecast["temperature"]
            parts.append(f"Temperature {temp}°")

        # Conditions
        if "conditions" in forecast:
            parts.append(forecast["conditions"])

        # Wind
        if "wind" in forecast:
            wind = forecast["wind"]
            parts.append(f"wind {wind} mph")

        # Precipitation
        if "precipitation_chance" in forecast:
            chance = forecast["precipitation_chance"]
            parts.append(f"{chance}% chance of precipitation")

        return ". ".join(parts) + "."

    def generate_financial_summary(self, data: dict[str, Any]) -> str:
        """Generate financial summary.

        Args:
            data: Financial data dictionary

        Returns:
            Financial summary

        Raises:
            DataToTextError: If summary generation fails
        """
        if not data:
            raise DataToTextError("Empty financial data")

        parts = []

        # Opening price
        if "opening_price" in data and "closing_price" in data:
            opening = data["opening_price"]
            closing = data["closing_price"]
            change = closing - opening
            percent_change = (change / opening) * 100 if opening != 0 else 0

            parts.append(f"Stock opened at ${opening:.2f}")
            parts.append(f"closed at ${closing:.2f}")
            parts.append(f"({percent_change:+.2f}%)")

        # Volume
        if "volume" in data:
            parts.append(f"Volume: {data['volume']}")

        # High/Low
        if "high" in data and "low" in data:
            parts.append(f"Range: ${data['low']:.2f} - ${data['high']:.2f}")

        return " ".join(parts)

    def _extract_salient_facts(self, data: list[dict[str, Any]], count: int = 3) -> list[dict[str, Any]]:
        """Extract most salient facts from data.

        Args:
            data: Data to extract from
            count: Number of facts to extract

        Returns:
            List of salient facts
        """
        if not data:
            return []

        # Score items by various metrics
        scored = []
        for i, item in enumerate(data):
            score = 0.0

            # Numeric fields
            for key, value in item.items():
                if isinstance(value, (int, float)):
                    score += abs(value) / 100.0

            # Length of description
            if "description" in item:
                score += len(str(item["description"])) / 100.0

            scored.append((i, score))

        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)

        # Return top items
        return [data[i] for i, _ in scored[:count]]

    def build_semantic_frames(self, data: dict[str, Any]) -> list[SemanticFrame]:
        """Convert data to semantic frames.

        Args:
            data: Structured data

        Returns:
            List of semantic frames

        Raises:
            DataToTextError: If conversion fails
        """
        if not data:
            raise DataToTextError("Empty data")

        frames: list[SemanticFrame] = []

        for key, value in data.items():
            # Create frame for each data point
            frame = SemanticFrame(predicate=key)

            if isinstance(value, dict):
                for prop, prop_val in value.items():
                    slot = Slot(name=prop, value_type="any")
                    slot.filler = prop_val
                    frame.slots.append(slot)
            else:
                slot = Slot(name="value", value_type="any")
                slot.filler = value
                frame.slots.append(slot)

            frames.append(frame)

        return frames
