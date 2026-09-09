"""Hermetic tests for interactive mockup mode (CAP-112).

Acceptance line proven here:

* a mockup moves through ``draft -> pending -> approved``;
* an *unapproved* mockup CANNOT be committed to implementation;
* the clickable flow follows transitions across screens and *rejects a
  dangling transition*;
* committing an approved mockup produces a *bidirectional* mockup<->code link;
* round-trip (node -> artifact -> node and artifact -> node -> artifact).

All deterministic, standard-library only, no network.
"""

from __future__ import annotations

import pytest

from thomas.tools.mockup_mode import (
    ApprovalError,
    ApprovalState,
    DanglingTransitionError,
    DeterministicArtifactIds,
    Element,
    FlowError,
    LinkedImplementation,
    Mockup,
    NoSuchElementError,
    NoSuchScreenError,
    Screen,
)


def _coherent_mockup() -> Mockup:
    """A three-screen mockup whose transitions form a coherent graph."""
    home = Screen(
        id="home",
        name="Home",
        elements=(
            Element(id="to_login", label="Log in", transition="login"),
            Element(id="to_about", label="About", transition="about"),
        ),
    )
    login = Screen(
        id="login",
        name="Login",
        elements=(
            Element(id="submit", label="Submit", transition="home"),
            Element(id="noop", label="Forgot?", transition=None),
        ),
    )
    about = Screen(id="about", name="About", elements=())
    return Mockup(id="mk1", title="Onboarding", screens=(home, login, about))


# ---------------------------------------------------------------------------
# Approval state machine
# ---------------------------------------------------------------------------


def test_lifecycle_draft_pending_approved() -> None:
    mk = _coherent_mockup()
    assert mk.approval_state is ApprovalState.DRAFT
    assert mk.submit_for_review() is ApprovalState.PENDING
    assert mk.approval_state is ApprovalState.PENDING
    assert mk.approve() is ApprovalState.APPROVED
    assert mk.is_approved


def test_cannot_approve_a_draft_directly() -> None:
    mk = _coherent_mockup()
    with pytest.raises(ApprovalError):
        mk.approve()
    assert mk.approval_state is ApprovalState.DRAFT


def test_reject_then_resubmit_and_approve() -> None:
    mk = _coherent_mockup()
    mk.submit_for_review()
    assert mk.reject() is ApprovalState.REJECTED
    # A rejected mockup can go back for another review round.
    assert mk.submit_for_review() is ApprovalState.PENDING
    assert mk.approve() is ApprovalState.APPROVED


def test_approved_is_terminal() -> None:
    mk = _coherent_mockup()
    mk.submit_for_review()
    mk.approve()
    with pytest.raises(ApprovalError):
        mk.reject()
    with pytest.raises(ApprovalError):
        mk.submit_for_review()


# ---------------------------------------------------------------------------
# Implementation-commit approval gate
# ---------------------------------------------------------------------------


def test_unapproved_mockup_cannot_be_committed() -> None:
    mk = _coherent_mockup()
    # draft
    with pytest.raises(ApprovalError):
        mk.commit_to_implementation()
    # pending is still not approved
    mk.submit_for_review()
    with pytest.raises(ApprovalError):
        mk.commit_to_implementation()
    # rejected is not approved either
    mk.reject()
    with pytest.raises(ApprovalError):
        mk.commit_to_implementation()


# ---------------------------------------------------------------------------
# Clickable prototype flow
# ---------------------------------------------------------------------------


def test_click_follows_transition_across_screens() -> None:
    mk = _coherent_mockup()
    assert mk.click("home", "to_login") == "login"
    assert mk.click("login", "submit") == "home"


def test_walk_replays_a_multi_screen_path() -> None:
    mk = _coherent_mockup()
    # home --to_login--> login --submit--> home --to_about--> about
    path = mk.walk(["to_login", "submit", "to_about"])
    assert path == ("home", "login", "home", "about")


def test_walk_uses_entry_screen_by_default() -> None:
    mk = _coherent_mockup()
    assert mk.entry_screen == "home"
    assert mk.walk([]) == ("home",)


def test_validate_flow_passes_for_coherent_graph() -> None:
    mk = _coherent_mockup()
    assert mk.dangling_transitions() == ()
    mk.validate_flow()  # does not raise


def test_flow_rejects_dangling_transition() -> None:
    broken = Mockup(
        id="broken",
        screens=(
            Screen(
                id="home",
                elements=(Element(id="go", transition="ghost"),),
            ),
        ),
    )
    assert broken.dangling_transitions() == (("home", "go", "ghost"),)
    with pytest.raises(DanglingTransitionError):
        broken.validate_flow()
    # Clicking the dangling element also raises.
    with pytest.raises(DanglingTransitionError):
        broken.click("home", "go")


def test_click_errors_on_unknown_ids_and_terminal_element() -> None:
    mk = _coherent_mockup()
    with pytest.raises(NoSuchScreenError):
        mk.click("nope", "x")
    with pytest.raises(NoSuchElementError):
        mk.click("home", "missing")
    with pytest.raises(FlowError):
        mk.click("login", "noop")  # transition is None


def test_dangling_mockup_cannot_be_committed_even_if_approved() -> None:
    broken = Mockup(
        id="broken",
        screens=(Screen(id="home", elements=(Element(id="go", transition="ghost"),)),),
    )
    broken.submit_for_review()
    broken.approve()
    with pytest.raises(DanglingTransitionError):
        broken.commit_to_implementation()


# ---------------------------------------------------------------------------
# Implementation commit + bidirectional link + round-trip
# ---------------------------------------------------------------------------


def _approved() -> Mockup:
    mk = _coherent_mockup()
    mk.submit_for_review()
    mk.approve()
    return mk


def test_commit_produces_bidirectional_link() -> None:
    mk = _approved()
    impl = mk.commit_to_implementation()
    assert isinstance(impl, LinkedImplementation)
    assert impl.mockup_id == "mk1"
    # One link per screen (3) + one per element (2 + 2 + 0 = 4) = 7.
    assert len(impl.links) == 7
    assert impl.is_bidirectional()


def test_commit_link_round_trips_both_directions() -> None:
    mk = _approved()
    impl = mk.commit_to_implementation()

    # Forward: mockup node -> artifact id, then reverse back to the same node.
    screen_art = impl.artifact_for("home")
    assert impl.node_for(screen_art) == "home"

    element_art = impl.artifact_for_element("home", "to_login")
    assert impl.node_for(element_art) == "home/to_login"

    # Reverse first, then forward back to the same artifact -- full round trip.
    for link in impl.links:
        node = impl.node_for(link.artifact_id)
        assert impl.artifact_for(node) == link.artifact_id


def test_default_artifact_ids_are_deterministic_and_unique() -> None:
    impl_a = _approved().commit_to_implementation()
    impl_b = _approved().commit_to_implementation()
    ids_a = [link.artifact_id for link in impl_a.links]
    ids_b = [link.artifact_id for link in impl_b.links]
    assert ids_a == ids_b  # deterministic across independent commits
    assert len(set(ids_a)) == len(ids_a)  # unique per node
    assert all(a.startswith("art-") for a in ids_a)


def test_injected_fake_artifact_factory() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def fake(kind: str, key: str, scope: str | None) -> str:
        calls.append((kind, key, scope))
        return f"fake:{kind}:{scope or '-'}:{key}"

    mk = _approved()
    impl = mk.commit_to_implementation(fake)
    assert impl.artifact_for("home") == "fake:screen:-:home"
    assert impl.artifact_for_element("home", "to_login") == "fake:element:home:to_login"
    assert impl.is_bidirectional()
    # The factory was consulted for every screen and element node.
    assert ("screen", "home", None) in calls
    assert ("element", "to_login", "home") in calls


def test_deterministic_ids_class_directly() -> None:
    factory = DeterministicArtifactIds()
    first = factory("screen", "home", None)
    again = factory("screen", "home", None)
    assert first == again
    assert factory("element", "to_login", "home") != first
