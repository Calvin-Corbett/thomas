"""The planner must not hedge a factual request into a placeholder chart."""

from __future__ import annotations

from thomas.server.chat_delegation_canvas import _PLAN_SYSTEM


def test_the_planner_is_told_to_chart_actual_figures() -> None:
    """Calvin asked how people commute to work and got ONE bar reading 100%,
    captioned "Illustrative distribution" -- the shape of a chart with none of
    the information. The existing rule only forbade placeholders "in geometry",
    which says nothing about the data itself."""
    text = _PLAN_SYSTEM.lower()

    assert "chart the actual figures" in text
    for hedge in ("illustrative", "sample", "example", "dummy"):
        assert hedge in text, f"planner does not name {hedge!r} as a forbidden caption"
    assert "single 100% bar" in text
    assert "at least 2 categories" in text


def test_approximation_is_allowed_but_must_be_labelled() -> None:
    """The instruction must not push the model into false precision -- the
    escape hatch is an honest estimate, not a fabricated shape."""
    text = _PLAN_SYSTEM.lower()

    assert "approximate" in text
    assert "an honest estimate of the real thing is useful" in text


def test_the_planner_is_asked_to_state_its_series() -> None:
    """Everything downstream used to reverse-engineer the numbers out of the
    drawing, and each chart shape needed its own pairing rule while the previous
    one quietly stopped matching. The planner knows the series outright."""
    text = _PLAN_SYSTEM

    assert '"data"' in text
    assert '{"label":"<category>","value":<number>}' in text
    lowered = text.lower()
    assert "the same numbers you drew" in lowered
    # Units and separators in a value are what forced the string-parsing paths.
    assert "no % sign, no units, no thousands separators" in lowered
    assert "never series 1" in lowered
