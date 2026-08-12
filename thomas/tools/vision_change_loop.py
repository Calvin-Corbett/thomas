"""Multimodal vision *change* loop over a live surface (CAP-017).

This is **not** image->code generation. It operates on an *already-rendered live
surface* -- a page, a panel, a rendered UI -- and drives a
``capture -> diagnose -> change -> re-capture`` loop until what the surface
actually renders matches a goal specification, or an iteration bound is reached.

The four stages, each behind an **injectable adapter** so the whole core runs
hermetically while a real system can be wired in at the edges:

1. **Capture.** :class:`Capturer` produces a :class:`RenderState` -- a structured
   view of what the surface *currently renders* (element ids -> visual
   attributes such as ``color`` / ``label`` / ``position``). The documented live
   default, :class:`ProviderCapturer`, hooks a real screenshot provider (screen
   grab / browser capture) and is system-gated: without a provider it raises
   :class:`CaptureUnavailableError` rather than fabricating a screenshot. Tests
   inject :class:`FakeCapturer`, which renders the surface's own source/config
   deterministically.

2. **Diagnose.** :class:`Analyzer` compares a :class:`RenderState` against the
   :class:`GoalSpec` and returns a deterministic, sorted list of
   :class:`Discrepancy` records (missing element, wrong/absent attribute). The
   hermetic default, :class:`StructuralAnalyzer`, is pure stdlib. The
   credential-gated live lane, :class:`VisionAnalyzer`, delegates to a real
   vision-model client and raises :class:`VisionCredentialsError` when none is
   supplied -- it never pretends a live analysis happened.

3. **Change.** :class:`Mutator` edits the surface's *source/config* to resolve a
   single discrepancy. The default, :class:`ConfigMutator`, mutates the
   in-memory :class:`Surface` config; it is injectable so a test (or a real
   deployment) can substitute a mutator that writes to a template, a stylesheet,
   or a component prop.

4. **Loop.** :func:`vision_change_loop` iterates capture -> diagnose -> change,
   **re-capturing after every change**, recording each :class:`Iteration`, until
   the diagnosis is empty (converged) or the bound is hit / progress stalls
   (residual reported honestly).

Everything in the core is deterministic -- sorted diagnosis, no clock, no
network, no temp state -- so an identical ``(surface, goal)`` yields an identical
:class:`VisionChangeLoopResult`.
"""

from __future__ import annotations

import copy
import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "RenderState",
    "GoalSpec",
    "Surface",
    "DiscrepancyKind",
    "Discrepancy",
    "Capturer",
    "FakeCapturer",
    "ProviderCapturer",
    "CaptureUnavailableError",
    "Analyzer",
    "StructuralAnalyzer",
    "VisionAnalyzer",
    "VisionCredentialsError",
    "Mutator",
    "ConfigMutator",
    "Iteration",
    "VisionChangeLoopResult",
    "vision_change_loop",
]


# ---------------------------------------------------------------------------
# Data model -- surfaces, render states, goals.
# ---------------------------------------------------------------------------
# An "element" is keyed by a stable id; its value is a flat mapping of visual
# attributes (e.g. {"color": "#0a0", "label": "Save", "x": "12"}). The same
# shape describes the surface source/config, the captured render state, and the
# goal spec, so a diff compares like with like.
Attributes = dict[str, str]


@dataclass
class Surface:
    """A live surface whose *source/config* is the thing a change edits.

    ``config`` maps element id -> visual attributes. It is the mutable source of
    truth a :class:`Mutator` edits; a :class:`Capturer` turns it (or the real
    rendered pixels) into a :class:`RenderState`.
    """

    config: dict[str, Attributes] = field(default_factory=dict)
    name: str = "surface"

    def clone(self) -> Surface:
        return Surface(config=copy.deepcopy(self.config), name=self.name)


@dataclass(frozen=True)
class RenderState:
    """A structured snapshot of what a surface *currently renders*.

    This stands in for the analysed content of a screenshot: element id -> the
    visual attributes observed for that element.
    """

    elements: Mapping[str, Attributes]

    def attributes(self, element: str) -> Attributes | None:
        got = self.elements.get(element)
        return dict(got) if got is not None else None


@dataclass(frozen=True)
class GoalSpec:
    """The desired rendered state -- a *partial* spec.

    Only the elements and attributes listed here are checked; anything the
    surface renders in addition is ignored. This models a real design goal that
    pins the things that matter (a label's text, a button's colour) without
    over-specifying the whole surface.
    """

    elements: Mapping[str, Attributes]


# ---------------------------------------------------------------------------
# Discrepancies.
# ---------------------------------------------------------------------------
class DiscrepancyKind(enum.Enum):
    MISSING_ELEMENT = "missing_element"
    ATTR_MISSING = "attr_missing"
    ATTR_MISMATCH = "attr_mismatch"


@dataclass(frozen=True)
class Discrepancy:
    """One visual difference between the render state and the goal.

    ``expected`` is the goal value the change should install. For
    :attr:`DiscrepancyKind.MISSING_ELEMENT` the whole element is absent, so
    ``attribute``/``expected`` are ``None`` (the element is created first, and
    its attributes surface as fresh discrepancies on the next capture -- the loop
    refines one layer at a time).
    """

    kind: DiscrepancyKind
    element: str
    attribute: str | None = None
    expected: str | None = None
    actual: str | None = None

    def sort_key(self) -> tuple[str, str, str]:
        return (self.element, self.attribute or "", self.kind.value)


# ---------------------------------------------------------------------------
# Capture edge -- injectable.
# ---------------------------------------------------------------------------
@runtime_checkable
class Capturer(Protocol):
    """Produces a :class:`RenderState` for a surface."""

    def capture(self, surface: Surface) -> RenderState: ...


class CaptureUnavailableError(RuntimeError):
    """Raised when the live capture lane is used without a screenshot provider."""


class FakeCapturer:
    """Hermetic fake: render the surface's own config into a :class:`RenderState`.

    This models a faithful renderer -- what the source/config declares is what
    the surface shows. A change to the config is therefore visible on the next
    capture, which is exactly what makes the loop observable in tests.
    """

    def capture(self, surface: Surface) -> RenderState:
        return RenderState(elements=copy.deepcopy(surface.config))


class ProviderCapturer:
    """Documented live lane: capture a real screenshot of the surface.

    The *provider* is the credential/system-gated edge -- a screen-grab or
    browser capture facility that returns a structured :class:`RenderState`
    (element ids -> observed attributes) for the given surface. It must be
    injected; without one, :meth:`capture` raises :class:`CaptureUnavailableError`
    rather than pretending a screenshot was taken. The core loop never depends on
    this path -- tests inject :class:`FakeCapturer` instead.

    The provider contract is ``capture_render_state(surface) -> RenderState``.
    """

    def __init__(self, provider: object | None = None) -> None:
        self._provider = provider

    def capture(self, surface: Surface) -> RenderState:
        if self._provider is None:
            raise CaptureUnavailableError(
                "ProviderCapturer requires a screenshot provider "
                "(credential/system-gated live lane); inject FakeCapturer for "
                "hermetic runs."
            )
        state = self._provider.capture_render_state(surface)  # type: ignore[attr-defined]
        if not isinstance(state, RenderState):
            raise CaptureUnavailableError("screenshot provider did not return a RenderState")
        return state


# ---------------------------------------------------------------------------
# Diagnose edge -- injectable.
# ---------------------------------------------------------------------------
@runtime_checkable
class Analyzer(Protocol):
    """Diagnoses a render state against a goal -> a discrepancy list."""

    def diagnose(self, state: RenderState, goal: GoalSpec) -> list[Discrepancy]: ...


class VisionCredentialsError(RuntimeError):
    """Raised when the live vision-analysis lane is used without a model client."""


class StructuralAnalyzer:
    """Hermetic default: deterministic structural diff of state vs goal.

    Emits, in a stable sorted order:

    * :attr:`DiscrepancyKind.MISSING_ELEMENT` when a goal element is absent from
      the render state;
    * :attr:`DiscrepancyKind.ATTR_MISSING` when a goal attribute is absent;
    * :attr:`DiscrepancyKind.ATTR_MISMATCH` when a goal attribute renders with a
      different value.

    Elements/attributes the surface renders but the goal does not mention are
    ignored (the goal is a partial spec). An empty list means the surface
    matches the goal.
    """

    def diagnose(self, state: RenderState, goal: GoalSpec) -> list[Discrepancy]:
        out: list[Discrepancy] = []
        for element in goal.elements:
            observed = state.attributes(element)
            if observed is None:
                out.append(Discrepancy(DiscrepancyKind.MISSING_ELEMENT, element))
                continue
            for attr, want in goal.elements[element].items():
                if attr not in observed:
                    out.append(
                        Discrepancy(
                            DiscrepancyKind.ATTR_MISSING,
                            element,
                            attribute=attr,
                            expected=want,
                        )
                    )
                elif observed[attr] != want:
                    out.append(
                        Discrepancy(
                            DiscrepancyKind.ATTR_MISMATCH,
                            element,
                            attribute=attr,
                            expected=want,
                            actual=observed[attr],
                        )
                    )
        out.sort(key=Discrepancy.sort_key)
        return out


class VisionAnalyzer:
    """Documented live lane: diagnose a screenshot with a real vision model.

    The credential-gated production path. A ``model_client`` capable of comparing
    a render state against a goal and returning discrepancies must be injected;
    without one, :meth:`diagnose` raises :class:`VisionCredentialsError` rather
    than fabricating a diagnosis. The core loop never depends on this path --
    tests inject :class:`StructuralAnalyzer` instead.

    The client contract is ``diagnose(state, goal) -> list[Discrepancy]``.
    """

    def __init__(self, model_client: object | None = None) -> None:
        self._client = model_client

    def diagnose(self, state: RenderState, goal: GoalSpec) -> list[Discrepancy]:
        if self._client is None:
            raise VisionCredentialsError(
                "VisionAnalyzer requires a vision-model client (credential-gated "
                "live lane); inject StructuralAnalyzer for hermetic runs."
            )
        result = self._client.diagnose(state, goal)  # type: ignore[attr-defined]
        discreps = list(result)
        if not all(isinstance(d, Discrepancy) for d in discreps):
            raise VisionCredentialsError("vision client did not return Discrepancy records")
        discreps.sort(key=Discrepancy.sort_key)
        return discreps


# ---------------------------------------------------------------------------
# Change edge -- injectable.
# ---------------------------------------------------------------------------
@runtime_checkable
class Mutator(Protocol):
    """Edits the surface source/config to resolve one discrepancy.

    Returns ``True`` if a change was applied, ``False`` if this mutator cannot
    resolve the given discrepancy (the loop treats an all-``False`` pass as a
    stall and stops, reporting the residual).
    """

    def apply(self, surface: Surface, discrepancy: Discrepancy) -> bool: ...


class ConfigMutator:
    """Default change: edit the in-memory surface config.

    * :attr:`DiscrepancyKind.MISSING_ELEMENT` -> create the element as an empty
      attribute set (its attributes then surface as fresh discrepancies on the
      next capture -- one refinement layer at a time).
    * :attr:`DiscrepancyKind.ATTR_MISSING` / ``ATTR_MISMATCH`` -> set the
      attribute to the goal's expected value.
    """

    def apply(self, surface: Surface, discrepancy: Discrepancy) -> bool:
        if discrepancy.kind is DiscrepancyKind.MISSING_ELEMENT:
            surface.config.setdefault(discrepancy.element, {})
            return True
        if discrepancy.attribute is None or discrepancy.expected is None:
            return False
        element = surface.config.setdefault(discrepancy.element, {})
        element[discrepancy.attribute] = discrepancy.expected
        return True


# ---------------------------------------------------------------------------
# The capture -> diagnose -> change -> re-capture loop.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Iteration:
    """One pass of the loop: what was captured, what differed, what changed.

    ``captured`` is the render state at the *start* of the pass (before any
    change this pass). ``change_applied`` is the single discrepancy resolved this
    pass, or ``None`` when the pass converged, hit the bound, or stalled.
    """

    index: int
    captured: RenderState
    discrepancy_count: int
    discrepancies: tuple[Discrepancy, ...]
    change_applied: Discrepancy | None


@dataclass(frozen=True)
class VisionChangeLoopResult:
    """Outcome of the whole loop."""

    surface_name: str
    iterations: tuple[Iteration, ...]
    converged: bool
    residual: tuple[Discrepancy, ...]

    @property
    def changes(self) -> int:
        """Number of change->re-capture cycles applied."""
        return sum(1 for it in self.iterations if it.change_applied is not None)

    @property
    def final_state(self) -> RenderState:
        """The render state captured on the last pass."""
        return self.iterations[-1].captured


def vision_change_loop(
    surface: Surface,
    goal: GoalSpec,
    *,
    capturer: Capturer,
    analyzer: Analyzer | None = None,
    mutator: Mutator | None = None,
    max_iterations: int = 8,
) -> VisionChangeLoopResult:
    """Run the capture -> diagnose -> change -> re-capture loop on ``surface``.

    Each pass captures the surface's current render state, diagnoses it against
    ``goal``, records the pass, and -- if there is work left and the bound is not
    yet reached -- applies the first resolvable discrepancy, then loops to
    **re-capture**. The loop ends when a capture yields zero discrepancies
    (converged), when ``max_iterations`` change passes have run (residual
    reported at the bound), or when no discrepancy in a pass can be resolved
    (stall; residual reported).

    Args:
        surface: The live surface; its config is mutated in place by the mutator.
        goal: The desired rendered state (a partial spec).
        capturer: Injectable capture adapter (screenshot edge).
        analyzer: Injectable diagnosis adapter (defaults to
            :class:`StructuralAnalyzer`).
        mutator: Injectable change adapter (defaults to :class:`ConfigMutator`).
        max_iterations: Maximum number of change passes (>= 0).

    Returns:
        A :class:`VisionChangeLoopResult` recording every iteration, whether the
        surface converged to the goal, and any residual discrepancies.

    Raises:
        ValueError: If ``max_iterations`` is negative.
        CaptureUnavailableError: If a live capturer has no provider.
        VisionCredentialsError: If a live analyzer has no model client.
    """
    if max_iterations < 0:
        raise ValueError("max_iterations must be >= 0")
    analyzer = analyzer or StructuralAnalyzer()
    mutator = mutator or ConfigMutator()

    iterations: list[Iteration] = []
    converged = False
    residual: tuple[Discrepancy, ...] = ()

    for i in range(max_iterations + 1):
        state = capturer.capture(surface)
        discreps = analyzer.diagnose(state, goal)

        applied: Discrepancy | None = None
        at_bound = i == max_iterations
        if discreps and not at_bound:
            for d in discreps:
                if mutator.apply(surface, d):
                    applied = d
                    break

        iterations.append(
            Iteration(
                index=i,
                captured=state,
                discrepancy_count=len(discreps),
                discrepancies=tuple(discreps),
                change_applied=applied,
            )
        )

        if not discreps:
            converged = True
            residual = ()
            break
        residual = tuple(discreps)
        if at_bound or applied is None:
            # Bound reached, or no discrepancy could be resolved this pass
            # (stall). Either way, report the residual honestly.
            break

    return VisionChangeLoopResult(
        surface_name=surface.name,
        iterations=tuple(iterations),
        converged=converged,
        residual=residual,
    )
