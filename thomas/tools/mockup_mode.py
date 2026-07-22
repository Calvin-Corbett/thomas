"""Interactive mockup mode -- approval + clickable prototype + implementation (CAP-112).

An *interactive mockup* is a small, deterministic model of a UI prototype: a set
of **screens**, each holding **elements** (buttons, links, ...), where an element
may carry a **transition** to another screen. On top of that model this module
provides three capabilities an agent needs to take a mockup from sketch to code:

1. **Approval state machine** -- a mockup moves through a strict lifecycle
   ``draft -> pending -> approved | rejected``. Only a *pending* mockup can be
   approved or rejected, and only an *approved* mockup may be committed to
   implementation. Every illegal move raises :class:`ApprovalError` rather than
   silently mutating state.

2. **Clickable prototype flow** -- the mockup's transitions form a directed
   graph over screens. :meth:`Mockup.validate_flow` proves the graph is coherent
   (no transition points at a missing screen); :meth:`Mockup.click` follows one
   element's transition to the next screen, and :meth:`Mockup.walk` replays a
   whole click path. A dangling transition is rejected loudly with
   :class:`DanglingTransitionError`.

3. **Implementation commit** -- :meth:`Mockup.commit_to_implementation` turns an
   approved mockup into a :class:`LinkedImplementation`: every screen and element
   is linked to a generated code-artifact id, and the mapping is **bidirectional**
   (mockup node -> artifact id, and artifact id -> mockup node) so traceability
   round-trips in both directions. Committing a not-yet-approved mockup raises
   :class:`ApprovalError`.

The artifact id generator is an **injectable adapter**: the default
(:class:`DeterministicArtifactIds`) derives stable, content-addressed ids purely
from the mockup so a commit is reproducible with no clock or network. Tests may
inject a fake to assert exact ids. Everything here is standard-library-only and
fully deterministic, so it runs hermetically.
"""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable, Protocol

__all__ = [
    "ApprovalState",
    "MockupError",
    "ApprovalError",
    "FlowError",
    "DanglingTransitionError",
    "NoSuchScreenError",
    "NoSuchElementError",
    "Element",
    "Screen",
    "Mockup",
    "ArtifactLink",
    "LinkedImplementation",
    "ArtifactIdFactory",
    "DeterministicArtifactIds",
]


# ---------------------------------------------------------------------------
# Approval lifecycle
# ---------------------------------------------------------------------------


class ApprovalState(str, enum.Enum):
    """Lifecycle state of a mockup. String-valued for stable serialization."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Allowed state transitions: current -> set of reachable next states.
_ALLOWED_TRANSITIONS: dict[ApprovalState, frozenset[ApprovalState]] = {
    ApprovalState.DRAFT: frozenset({ApprovalState.PENDING}),
    ApprovalState.PENDING: frozenset({ApprovalState.APPROVED, ApprovalState.REJECTED}),
    ApprovalState.APPROVED: frozenset(),
    ApprovalState.REJECTED: frozenset({ApprovalState.PENDING}),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MockupError(Exception):
    """Base class for all mockup-mode errors."""


class ApprovalError(MockupError):
    """An approval-lifecycle rule was violated (illegal state move / gate)."""


class FlowError(MockupError):
    """Base class for clickable-flow errors."""


class NoSuchScreenError(FlowError):
    """A referenced screen id does not exist in the mockup."""


class NoSuchElementError(FlowError):
    """A referenced element id does not exist on the given screen."""


class DanglingTransitionError(FlowError):
    """An element's transition points at a screen that does not exist."""

    def __init__(self, dangling: Iterable[tuple[str, str, str]]) -> None:
        self.dangling: tuple[tuple[str, str, str], ...] = tuple(dangling)
        detail = ", ".join(f"{screen}.{element} -> {target}" for screen, element, target in self.dangling)
        super().__init__(f"dangling transition(s): {detail}")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Element:
    """An interactive element on a screen.

    ``transition`` names the screen reached by clicking this element, or is
    ``None`` for a terminal / non-navigating element.
    """

    id: str
    label: str = ""
    transition: str | None = None


@dataclass(frozen=True)
class Screen:
    """A single mockup screen holding an ordered list of elements."""

    id: str
    name: str = ""
    elements: tuple[Element, ...] = ()

    def element(self, element_id: str) -> Element:
        for el in self.elements:
            if el.id == element_id:
                return el
        raise NoSuchElementError(f"screen {self.id!r} has no element {element_id!r}")


@dataclass
class Mockup:
    """An interactive mockup: screens + transitions + approval state."""

    id: str
    title: str = ""
    screens: tuple[Screen, ...] = ()
    entry_screen: str | None = None
    approval_state: ApprovalState = ApprovalState.DRAFT

    # -- construction helpers ------------------------------------------------

    def __post_init__(self) -> None:
        self.screens = tuple(self.screens)
        if self.entry_screen is None and self.screens:
            self.entry_screen = self.screens[0].id

    def screen(self, screen_id: str) -> Screen:
        for sc in self.screens:
            if sc.id == screen_id:
                return sc
        raise NoSuchScreenError(f"mockup {self.id!r} has no screen {screen_id!r}")

    def _screen_ids(self) -> frozenset[str]:
        return frozenset(sc.id for sc in self.screens)

    # -- approval state machine ---------------------------------------------

    def _move_to(self, target: ApprovalState) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.approval_state]
        if target not in allowed:
            raise ApprovalError(
                f"cannot move mockup {self.id!r} from {self.approval_state.value!r} to {target.value!r}"
            )
        self.approval_state = target

    def submit_for_review(self) -> ApprovalState:
        """``draft`` (or ``rejected``) -> ``pending``."""
        self._move_to(ApprovalState.PENDING)
        return self.approval_state

    def approve(self) -> ApprovalState:
        """``pending`` -> ``approved``."""
        self._move_to(ApprovalState.APPROVED)
        return self.approval_state

    def reject(self) -> ApprovalState:
        """``pending`` -> ``rejected``."""
        self._move_to(ApprovalState.REJECTED)
        return self.approval_state

    @property
    def is_approved(self) -> bool:
        return self.approval_state is ApprovalState.APPROVED

    # -- clickable prototype flow -------------------------------------------

    def dangling_transitions(self) -> tuple[tuple[str, str, str], ...]:
        """Return ``(screen_id, element_id, target)`` for every broken link."""
        valid = self._screen_ids()
        broken: list[tuple[str, str, str]] = []
        for sc in self.screens:
            for el in sc.elements:
                if el.transition is not None and el.transition not in valid:
                    broken.append((sc.id, el.id, el.transition))
        return tuple(broken)

    def validate_flow(self) -> None:
        """Raise :class:`DanglingTransitionError` if any transition is broken."""
        broken = self.dangling_transitions()
        if broken:
            raise DanglingTransitionError(broken)

    def click(self, screen_id: str, element_id: str) -> str:
        """Click ``element_id`` on ``screen_id``; return the destination screen id.

        Raises :class:`NoSuchScreenError` / :class:`NoSuchElementError` for
        unknown ids, :class:`FlowError` if the element has no transition, and
        :class:`DanglingTransitionError` if it points at a missing screen.
        """
        element = self.screen(screen_id).element(element_id)
        if element.transition is None:
            raise FlowError(f"element {element_id!r} on screen {screen_id!r} has no transition")
        if element.transition not in self._screen_ids():
            raise DanglingTransitionError([(screen_id, element_id, element.transition)])
        return element.transition

    def walk(self, clicks: Iterable[str], *, start: str | None = None) -> tuple[str, ...]:
        """Replay a sequence of element clicks, returning the visited screen path.

        ``start`` defaults to :attr:`entry_screen`. The returned tuple begins
        with the start screen and appends the destination after each click, so a
        two-click walk yields three screen ids.
        """
        current = start if start is not None else self.entry_screen
        if current is None:
            raise FlowError(f"mockup {self.id!r} has no entry screen to walk from")
        # Validate the start screen exists up front.
        self.screen(current)
        path: list[str] = [current]
        for element_id in clicks:
            current = self.click(current, element_id)
            path.append(current)
        return tuple(path)

    # -- implementation commit ----------------------------------------------

    def commit_to_implementation(self, artifacts: ArtifactIdFactory | None = None) -> LinkedImplementation:
        """Commit an *approved* mockup, producing a bidirectional code link.

        Only an approved mockup may be committed (otherwise
        :class:`ApprovalError`). The flow graph is validated first so a mockup
        with dangling transitions cannot be committed. Each screen and element
        is linked to a generated artifact id via the injectable ``artifacts``
        factory (default: :class:`DeterministicArtifactIds`).
        """
        if not self.is_approved:
            raise ApprovalError(
                f"mockup {self.id!r} is {self.approval_state.value!r}; "
                "only an approved mockup can be committed to implementation"
            )
        self.validate_flow()
        factory = artifacts if artifacts is not None else DeterministicArtifactIds()

        links: list[ArtifactLink] = []
        for sc in self.screens:
            links.append(
                ArtifactLink(
                    node_kind="screen",
                    node_key=sc.id,
                    artifact_id=factory("screen", sc.id, None),
                )
            )
            for el in sc.elements:
                links.append(
                    ArtifactLink(
                        node_kind="element",
                        node_key=_element_key(sc.id, el.id),
                        artifact_id=factory("element", el.id, sc.id),
                    )
                )
        return LinkedImplementation(mockup_id=self.id, links=tuple(links))


def _element_key(screen_id: str, element_id: str) -> str:
    """Composite key identifying an element within its screen."""
    return f"{screen_id}/{element_id}"


# ---------------------------------------------------------------------------
# Implementation link (bidirectional mockup <-> code traceability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactLink:
    """A single mockup-node <-> code-artifact link."""

    node_kind: str  # "screen" | "element"
    node_key: str  # screen id, or "screen_id/element_id"
    artifact_id: str


@dataclass(frozen=True)
class LinkedImplementation:
    """The result of committing a mockup: bidirectional node<->artifact maps."""

    mockup_id: str
    links: tuple[ArtifactLink, ...]

    def _forward(self) -> dict[str, str]:
        return {link.node_key: link.artifact_id for link in self.links}

    def _reverse(self) -> dict[str, str]:
        return {link.artifact_id: link.node_key for link in self.links}

    def artifact_for(self, node_key: str) -> str:
        """Forward lookup: mockup node key -> generated artifact id."""
        forward = self._forward()
        if node_key not in forward:
            raise MockupError(f"no artifact linked for node {node_key!r}")
        return forward[node_key]

    def artifact_for_element(self, screen_id: str, element_id: str) -> str:
        """Convenience forward lookup for an element node."""
        return self.artifact_for(_element_key(screen_id, element_id))

    def node_for(self, artifact_id: str) -> str:
        """Reverse lookup: generated artifact id -> mockup node key."""
        reverse = self._reverse()
        if artifact_id not in reverse:
            raise MockupError(f"no mockup node linked for artifact {artifact_id!r}")
        return reverse[artifact_id]

    def is_bidirectional(self) -> bool:
        """True iff every link round-trips node -> artifact -> node.

        Also requires artifact ids to be unique, so the reverse map is total and
        unambiguous (no two nodes share one artifact).
        """
        forward = self._forward()
        if len(forward) != len(self.links):
            return False  # duplicate node keys collapsed the forward map
        reverse = self._reverse()
        if len(reverse) != len(self.links):
            return False  # duplicate artifact ids collapsed the reverse map
        for node_key, artifact_id in forward.items():
            if reverse.get(artifact_id) != node_key:
                return False
        return True


# ---------------------------------------------------------------------------
# Injectable artifact-id adapter
# ---------------------------------------------------------------------------


class ArtifactIdFactory(Protocol):
    """Callable that mints a code-artifact id for a mockup node.

    ``kind`` is ``"screen"`` or ``"element"``; ``key`` is the node's own id;
    ``scope`` is the owning screen id for elements (``None`` for screens).
    Implementations must be deterministic for a given ``(kind, key, scope)``.
    """

    def __call__(self, kind: str, key: str, scope: str | None) -> str: ...


@dataclass
class DeterministicArtifactIds:
    """Default adapter: content-addressed, stable ids with no clock/network.

    An id looks like ``art-screen-<hash>`` / ``art-element-<hash>`` where the
    hash is a short blake2b digest over the node's fully-qualified path. Stable
    across processes and runs, and unique per distinct node.
    """

    prefix: str = "art"
    digest_size: int = 8

    def __call__(self, kind: str, key: str, scope: str | None) -> str:
        path = key if scope is None else f"{scope}/{key}"
        material = f"{kind}:{path}".encode()
        digest = hashlib.blake2b(material, digest_size=self.digest_size).hexdigest()
        return f"{self.prefix}-{kind}-{digest}"


# A convenience alias for callers that prefer a plain function type.
ArtifactIdCallable = Callable[[str, str, "str | None"], str]
