"""Concurrency evidence keeps agent lifetimes separate from provider requests."""

from thomas.core.praxis.progress import interval_concurrency


def test_half_open_intervals_measure_true_overlap():
    result = interval_concurrency({"first": (0, 2), "second": (1, 3), "third": (2, 4), "zero": (2, 2)}, (2, 3))
    assert result["peak"] == 2
    assert result["seconds_at_or_above"] == {"2": 2.0, "3": 0.0}
    assert result["span_s"] == 4.0
