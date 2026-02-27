"""Tests for data-to-text generation."""

import pytest

from thomas.nlg.data_to_text import DataToTextError, DataToTextGenerator


class TestStatisticalSummary:
    """Test statistical summary generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_summarize_basic_stats(self) -> None:
        """Test basic statistical summary."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        summary = self.generator.describe_statistics(data)

        assert "average" in summary.lower()
        assert "median" in summary.lower()

    def test_summarize_with_label(self) -> None:
        """Test summary with label."""
        data = [1.0, 2.0, 3.0]
        summary = self.generator.describe_statistics(data, label="Test")

        assert "Test" in summary

    def test_insufficient_data_fails(self) -> None:
        """Test that insufficient data fails."""
        with pytest.raises(DataToTextError):
            self.generator.describe_statistics([1.0, 2.0])

    def test_empty_data_fails(self) -> None:
        """Test that empty data fails."""
        with pytest.raises(DataToTextError):
            self.generator.describe_statistics([])


class TestTrendDescription:
    """Test trend description generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_increasing_trend(self) -> None:
        """Test describing increasing trend."""
        timeseries = [(1, 10.0), (2, 15.0), (3, 20.0)]
        summary = self.generator.describe_trends(timeseries)

        assert "increased" in summary.lower()

    def test_decreasing_trend(self) -> None:
        """Test describing decreasing trend."""
        timeseries = [(1, 20.0), (2, 15.0), (3, 10.0)]
        summary = self.generator.describe_trends(timeseries)

        assert "decreased" in summary.lower()

    def test_stable_trend(self) -> None:
        """Test describing stable trend."""
        timeseries = [(1, 10.0), (2, 10.5), (3, 10.2)]
        summary = self.generator.describe_trends(timeseries)

        assert "stable" in summary.lower() or "change" in summary.lower()

    def test_single_point_fails(self) -> None:
        """Test that single point fails."""
        with pytest.raises(DataToTextError):
            self.generator.describe_trends([(1, 10.0)])

    def test_with_label(self) -> None:
        """Test trend with label."""
        timeseries = [(1, 10.0), (2, 20.0)]
        summary = self.generator.describe_trends(timeseries, label="Trend")

        assert "Trend" in summary


class TestComparison:
    """Test value comparison generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_higher_comparison(self) -> None:
        """Test higher value comparison."""
        comparison = self.generator.compare_values(100, 120)

        assert "higher" in comparison.lower()

    def test_lower_comparison(self) -> None:
        """Test lower value comparison."""
        comparison = self.generator.compare_values(120, 100)

        assert "lower" in comparison.lower()

    def test_equal_comparison(self) -> None:
        """Test equal values."""
        comparison = self.generator.compare_values(100, 100)

        assert "equal" in comparison.lower()

    def test_with_labels(self) -> None:
        """Test comparison with labels."""
        comparison = self.generator.compare_values(100, 120, label1="Value1", label2="Value2")

        assert "Value2" in comparison or "higher" in comparison.lower()

    def test_zero_comparison_fails(self) -> None:
        """Test that zero comparison fails."""
        with pytest.raises(DataToTextError):
            self.generator.compare_values(0, 0)


class TestTableDescription:
    """Test table description generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_describe_basic_table(self) -> None:
        """Test describing basic table."""
        table = [
            {"name": "A", "value": 10},
            {"name": "B", "value": 20},
            {"name": "C", "value": 30},
        ]
        description = self.generator.describe_table(table)

        assert "Table" in description or "row" in description.lower()

    def test_describe_numeric_columns(self) -> None:
        """Test table with numeric columns."""
        table = [
            {"col1": 10, "col2": 20},
            {"col1": 15, "col2": 25},
            {"col1": 20, "col2": 30},
        ]
        description = self.generator.describe_table(table)

        assert len(description) > 0

    def test_empty_table_fails(self) -> None:
        """Test that empty table fails."""
        with pytest.raises(DataToTextError):
            self.generator.describe_table([])


class TestTimeSeriesNarration:
    """Test time series narration."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_narrate_basic_timeseries(self) -> None:
        """Test basic time series narration."""
        timeseries = [
            ("Jan", 10.0),
            ("Feb", 15.0),
            ("Mar", 20.0),
        ]
        narrative = self.generator.narrate_timeseries(timeseries)

        assert "Jan" in narrative or "10" in narrative

    def test_narrate_with_label(self) -> None:
        """Test narration with event label."""
        timeseries = [("T1", 10.0), ("T2", 20.0)]
        narrative = self.generator.narrate_timeseries(timeseries, event_label="Test Event")

        assert "Test Event" in narrative

    def test_single_point_fails(self) -> None:
        """Test that single point fails."""
        with pytest.raises(DataToTextError):
            self.generator.narrate_timeseries([("T1", 10.0)])


class TestSportsRecap:
    """Test sports recap generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_generate_basic_recap(self) -> None:
        """Test basic sports recap."""
        box_score = {
            "teams": [
                {"name": "Team A", "score": 100},
                {"name": "Team B", "score": 90},
            ]
        }
        recap = self.generator.generate_sports_recap(box_score)

        assert "Team A" in recap or "Team B" in recap

    def test_recap_with_key_stats(self) -> None:
        """Test recap with key statistics."""
        box_score = {
            "teams": [
                {"name": "Team A", "score": 100, "key_stats": "Strong defense"},
                {"name": "Team B", "score": 90},
            ]
        }
        recap = self.generator.generate_sports_recap(box_score)

        assert len(recap) > 0

    def test_invalid_box_score_fails(self) -> None:
        """Test that invalid box score fails."""
        with pytest.raises(DataToTextError):
            self.generator.generate_sports_recap({})

    def test_wrong_team_count_fails(self) -> None:
        """Test that wrong team count fails."""
        with pytest.raises(DataToTextError):
            self.generator.generate_sports_recap({"teams": [{"name": "Team A", "score": 100}]})


class TestWeatherReport:
    """Test weather report generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_generate_basic_report(self) -> None:
        """Test basic weather report."""
        forecast = {
            "temperature": 72,
            "conditions": "Sunny",
        }
        report = self.generator.generate_weather_report(forecast)

        assert "72" in report or "Sunny" in report

    def test_report_with_wind(self) -> None:
        """Test report with wind."""
        forecast = {
            "temperature": 70,
            "wind": 10,
        }
        report = self.generator.generate_weather_report(forecast)

        assert "wind" in report.lower() or "10" in report

    def test_report_with_precipitation(self) -> None:
        """Test report with precipitation chance."""
        forecast = {
            "temperature": 65,
            "precipitation_chance": 80,
        }
        report = self.generator.generate_weather_report(forecast)

        assert "precipitation" in report.lower() or "80" in report

    def test_empty_forecast_fails(self) -> None:
        """Test that empty forecast fails."""
        with pytest.raises(DataToTextError):
            self.generator.generate_weather_report({})


class TestFinancialSummary:
    """Test financial summary generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_generate_basic_summary(self) -> None:
        """Test basic financial summary."""
        data = {
            "opening_price": 100.0,
            "closing_price": 105.0,
        }
        summary = self.generator.generate_financial_summary(data)

        assert "100" in summary or "105" in summary

    def test_summary_with_volume(self) -> None:
        """Test summary with volume."""
        data = {
            "opening_price": 100.0,
            "closing_price": 105.0,
            "volume": 1000000,
        }
        summary = self.generator.generate_financial_summary(data)

        assert "Volume" in summary

    def test_summary_with_range(self) -> None:
        """Test summary with price range."""
        data = {
            "opening_price": 100.0,
            "closing_price": 105.0,
            "high": 110.0,
            "low": 95.0,
        }
        summary = self.generator.generate_financial_summary(data)

        assert "Range" in summary or "high" in summary.lower()

    def test_empty_data_fails(self) -> None:
        """Test that empty data fails."""
        with pytest.raises(DataToTextError):
            self.generator.generate_financial_summary({})


class TestSemanticFrameBuilding:
    """Test semantic frame building from data."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.generator = DataToTextGenerator()

    def test_build_frames_from_data(self) -> None:
        """Test building semantic frames."""
        data = {
            "subject": "John",
            "action": "runs",
        }
        frames = self.generator.build_semantic_frames(data)

        assert len(frames) > 0

    def test_frames_have_predicates(self) -> None:
        """Test that frames have predicates."""
        data = {"test": "value"}
        frames = self.generator.build_semantic_frames(data)

        assert all(f.predicate for f in frames)

    def test_frames_have_slots(self) -> None:
        """Test that frames have slots."""
        data = {"key": "value"}
        frames = self.generator.build_semantic_frames(data)

        assert all(f.slots for f in frames)

    def test_empty_data_fails(self) -> None:
        """Test that empty data fails."""
        with pytest.raises(DataToTextError):
            self.generator.build_semantic_frames({})
