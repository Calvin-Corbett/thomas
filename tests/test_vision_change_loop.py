"""Tests for the CAP-017 multimodal vision *change* loop.

Proves the exact Level-2 acceptance line: close a
``screenshot -> diagnosis -> change -> re-screenshot`` loop on a live surface
with an injectable analyzer --

* the loop detects a visual discrepancy vs the goal, applies a change,
  re-captures, and converges to zero discrepancies;
* at a bound it reports the residual honestly (no false convergence);
* a surface already matching the goal makes zero changes;
* each iteration is recorded (captured state + discrepancies + the change);
* determinism: identical inputs yield an identical result.

Everything is hermetic: the capture edge is :class:`FakeCapturer` (renders the
surface's own config), the analyzer is the stdlib :class:`StructuralAnalyzer`
(with an injected-analyzer test), and there is no network, clock, or temp state.
The live lanes (:class:`ProviderCapturer`, :class:`VisionAnalyzer`) are proven to
refuse to fabricate a run without their credential/system-gated edge.
"""

from __future__ import annotations

import pytest

from thomas.tools.vision_change_loop import (
    Analyzer,
    CaptureUnavailableError,
    ConfigMutator,
    Discrepancy,
    DiscrepancyKind,
    FakeCapturer,
    GoalSpec,
    Mutator,
    ProviderCapturer,
    RenderState,
    StructuralAnalyzer,
    Surface,
    VisionAnalyzer,
    VisionCredentialsError,
    vision_change_loop,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers.
# ---------------------------------------------------------------------------
def _button_surface(color: str = "#f00", label: str = "Save") -> Surface:
    return Surface(config={"button": {"color": color, "label": label}}, name="panel")


def _button_goal(color: str = "#0a0", label: str = "Save") -> GoalSpec:
    return GoalSpec(elements={"button": {"color": color, "label": label}})


# ---------------------------------------------------------------------------
# Core acceptance: detect -> change -> re-capture -> converge to zero.
# ---------------------------------------------------------------------------
def test_detects_discrepancy_changes_recaptures_and_converges():
    surface = _button_surface(color="#f00")  # wrong colour vs goal
    goal = _button_goal(color="#0a0")

    result = vision_change_loop(surface, goal, capturer=FakeCapturer())

    # Converged to zero discrepancies.
    assert result.converged is True
    assert result.residual == ()
    assert result.final_state.attributes("button") == {"color": "#0a0", "label": "Save"}

    # The very first pass detected the colour discrepancy...
    first = result.iterations[0]
    assert first.discrepancy_count == 1
    assert first.discrepancies[0].kind is DiscrepancyKind.ATTR_MISMATCH
    assert first.discrepancies[0].attribute == "color"
    assert first.discrepancies[0].actual == "#f00"
    assert first.discrepancies[0].expected == "#0a0"
    assert first.change_applied is not None  # a change was applied

    # ...and a *later re-capture* saw zero discrepancies (the loop re-captured
    # after the change rather than trusting the mutation blindly).
    assert result.iterations[-1].discrepancy_count == 0
    assert result.iterations[-1].change_applied is None
    # The surface config was actually edited.
    assert surface.config["button"]["color"] == "#0a0"


def test_multiple_discrepancies_converge_one_change_per_recapture():
    # Two attributes wrong + one whole element missing.
    surface = Surface(
        config={"title": {"color": "#111", "text": "Hello"}},
        name="screen",
    )
    goal = GoalSpec(
        elements={
            "title": {"color": "#000", "text": "Welcome"},
            "cta": {"label": "Go"},
        }
    )

    result = vision_change_loop(surface, goal, capturer=FakeCapturer())

    assert result.converged is True
    assert result.residual == ()
    # One change is applied per re-capture cycle, so it takes several passes.
    assert result.changes >= 3
    # Final rendered state matches the goal for every pinned attribute.
    final = result.final_state
    assert final.attributes("title") == {"color": "#000", "text": "Welcome"}
    assert final.attributes("cta") == {"label": "Go"}


def test_missing_element_is_created_then_filled_layer_by_layer():
    surface = Surface(config={}, name="empty")
    goal = GoalSpec(elements={"badge": {"label": "New", "color": "#00f"}})

    result = vision_change_loop(surface, goal, capturer=FakeCapturer())

    assert result.converged is True
    # First discrepancy is the whole element missing...
    assert result.iterations[0].discrepancies[0].kind is DiscrepancyKind.MISSING_ELEMENT
    # ...and the element ends up fully populated.
    assert result.final_state.attributes("badge") == {"label": "New", "color": "#00f"}


# ---------------------------------------------------------------------------
# A surface already matching the goal makes zero changes.
# ---------------------------------------------------------------------------
def test_matching_surface_makes_zero_changes():
    surface = _button_surface(color="#0a0")  # already matches
    goal = _button_goal(color="#0a0")

    result = vision_change_loop(surface, goal, capturer=FakeCapturer())

    assert result.converged is True
    assert result.changes == 0
    assert result.residual == ()
    # Exactly one pass: capture, diagnose (empty), done.
    assert len(result.iterations) == 1
    assert result.iterations[0].discrepancy_count == 0
    assert result.iterations[0].change_applied is None


# ---------------------------------------------------------------------------
# Each iteration is recorded.
# ---------------------------------------------------------------------------
def test_each_iteration_is_recorded():
    surface = _button_surface(color="#f00")
    goal = GoalSpec(elements={"button": {"color": "#0a0", "label": "Submit"}})

    result = vision_change_loop(surface, goal, capturer=FakeCapturer())

    assert len(result.iterations) >= 2
    for expected_index, it in enumerate(result.iterations):
        assert it.index == expected_index
        assert isinstance(it.captured, RenderState)
        assert it.discrepancy_count == len(it.discrepancies)
    # Recorded captured states are stable snapshots: the first pass's captured
    # state still shows the ORIGINAL colour even though the surface was mutated.
    assert result.iterations[0].captured.attributes("button")["color"] == "#f00"


# ---------------------------------------------------------------------------
# Residual reported at the bound (no false convergence).
# ---------------------------------------------------------------------------
def test_residual_reported_at_iteration_bound():
    surface = Surface(
        config={"a": {"v": "0"}, "b": {"v": "0"}, "c": {"v": "0"}},
        name="grid",
    )
    goal = GoalSpec(elements={"a": {"v": "1"}, "b": {"v": "1"}, "c": {"v": "1"}})

    result = vision_change_loop(surface, goal, capturer=FakeCapturer(), max_iterations=1)

    assert result.converged is False
    assert result.residual  # non-empty residual reported
    # max_iterations=1 => at most 2 passes recorded (pass 0 applies, pass 1 is
    # the bound and applies nothing).
    assert len(result.iterations) == 2
    assert result.iterations[-1].change_applied is None


def test_stall_reported_when_no_change_can_be_applied():
    class NoOpMutator:
        def apply(self, surface: Surface, discrepancy: Discrepancy) -> bool:  # noqa: ARG002
            return False

    surface = _button_surface(color="#f00")
    goal = _button_goal(color="#0a0")

    result = vision_change_loop(surface, goal, capturer=FakeCapturer(), mutator=NoOpMutator(), max_iterations=5)

    assert result.converged is False
    assert result.changes == 0
    assert result.residual
    # Stalls on the first pass -- no progress possible.
    assert len(result.iterations) == 1
    assert isinstance(NoOpMutator(), Mutator)  # structural-typing sanity


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------
def test_determinism_identical_runs():
    def run() -> tuple:
        surface = Surface(
            config={"x": {"color": "#f00"}, "y": {"label": "old"}},
            name="s",
        )
        goal = GoalSpec(elements={"x": {"color": "#0f0", "pos": "top"}, "y": {"label": "new"}})
        res = vision_change_loop(surface, goal, capturer=FakeCapturer())
        return (
            res.converged,
            res.changes,
            tuple(
                (
                    it.index,
                    it.discrepancy_count,
                    tuple(d.sort_key() for d in it.discrepancies),
                    None if it.change_applied is None else it.change_applied.sort_key(),
                )
                for it in res.iterations
            ),
        )

    assert run() == run()


# ---------------------------------------------------------------------------
# Injectable analyzer -- the loop honours a substituted diagnosis edge.
# ---------------------------------------------------------------------------
def test_injectable_analyzer_is_used():
    calls: list[int] = []

    class CountingAnalyzer:
        def __init__(self) -> None:
            self._inner = StructuralAnalyzer()

        def diagnose(self, state: RenderState, goal: GoalSpec) -> list[Discrepancy]:
            calls.append(1)
            return self._inner.diagnose(state, goal)

    surface = _button_surface(color="#f00")
    goal = _button_goal(color="#0a0")

    analyzer = CountingAnalyzer()
    assert isinstance(analyzer, Analyzer)  # structural-typing sanity
    result = vision_change_loop(surface, goal, capturer=FakeCapturer(), analyzer=analyzer)

    assert result.converged is True
    # The injected analyzer was invoked once per iteration (capture+diagnose).
    assert len(calls) == len(result.iterations)


# ---------------------------------------------------------------------------
# Live lanes refuse to fabricate a run without their gated edge.
# ---------------------------------------------------------------------------
def test_provider_capturer_requires_provider():
    capturer = ProviderCapturer()
    with pytest.raises(CaptureUnavailableError):
        capturer.capture(_button_surface())


def test_provider_capturer_delegates_to_injected_provider():
    sentinel = RenderState(elements={"button": {"color": "#0a0", "label": "Save"}})

    class FakeProvider:
        def capture_render_state(self, surface: Surface) -> RenderState:  # noqa: ARG002
            return sentinel

    capturer = ProviderCapturer(provider=FakeProvider())
    goal = _button_goal(color="#0a0")
    # Surface config is irrelevant here -- the provider dictates the render state.
    result = vision_change_loop(_button_surface(color="#f00"), goal, capturer=capturer)

    assert result.converged is True
    assert result.changes == 0  # provider already reports a matching state


def test_vision_analyzer_requires_client():
    analyzer = VisionAnalyzer()
    with pytest.raises(VisionCredentialsError):
        analyzer.diagnose(RenderState(elements={}), GoalSpec(elements={}))


def test_vision_analyzer_delegates_to_injected_client():
    want = [Discrepancy(DiscrepancyKind.ATTR_MISMATCH, "button", attribute="color", expected="#0a0", actual="#f00")]

    class FakeVisionClient:
        def diagnose(self, state: RenderState, goal: GoalSpec) -> list[Discrepancy]:  # noqa: ARG002
            return list(want)

    analyzer = VisionAnalyzer(model_client=FakeVisionClient())
    got = analyzer.diagnose(RenderState(elements={}), GoalSpec(elements={}))
    assert got == want


def test_config_mutator_edits_surface_source():
    surface = _button_surface(color="#f00")
    mutator = ConfigMutator()
    d = Discrepancy(DiscrepancyKind.ATTR_MISMATCH, "button", attribute="color", expected="#0a0", actual="#f00")

    assert mutator.apply(surface, d) is True
    assert surface.config["button"]["color"] == "#0a0"


def test_negative_bound_rejected():
    with pytest.raises(ValueError):
        vision_change_loop(_button_surface(), _button_goal(), capturer=FakeCapturer(), max_iterations=-1)
