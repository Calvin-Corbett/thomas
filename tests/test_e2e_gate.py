"""Tests for the CAP-088 real-browser E2E required-completion gate.

Everything is proven against a hermetic fake browser driver -- no network, no
real browser, injected DOM state.  The completion-gate decision shape is proven
against the *real* ``thomas.agent.completion_gate.GateDecision`` (tests are not
subject to the ext->core architecture layering rule that the runtime module is).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pytest

from thomas.agent import completion_gate
from thomas.browser.e2e_gate import (
    GATE_ALLOW,
    GATE_BLOCK,
    AssertStyle,
    AssertText,
    AssertVisible,
    ChangeClassification,
    Click,
    E2EFlow,
    E2ETarget,
    Type,
    classify_change,
    enforce_e2e_gate,
    evaluate_e2e_gate,
    run_flow,
    to_gate_decision,
)

# ---------------------------------------------------------------------------
# Hermetic fake driver
# ---------------------------------------------------------------------------


@dataclass
class FakeNode:
    visible: bool = True
    text: str = ""
    value: str = ""
    style: dict[str, str] = field(default_factory=dict)


class FakeBrowserDriver:
    """In-memory DOM with scripted click/type mutations.

    ``is_visible`` models *computed* visibility; ``text_content`` returns a
    node's text regardless of visibility, so the runner -- not the driver -- is
    responsible for refusing text assertions on hidden nodes.
    """

    def __init__(
        self,
        nodes: dict[str, FakeNode],
        *,
        available: bool = True,
        on_click: dict[str, Callable[[dict[str, FakeNode]], None]] | None = None,
    ) -> None:
        self._nodes = nodes
        self._available = available
        self._on_click = on_click or {}
        self.opened = False
        self.closed = False

    @property
    def available(self) -> bool:
        return self._available

    def open(self, target: E2ETarget) -> None:
        self.opened = True

    def _node(self, selector: str) -> FakeNode:
        if selector not in self._nodes:
            raise KeyError(f"no such node: {selector}")
        return self._nodes[selector]

    def click(self, selector: str) -> None:
        self._node(selector)  # ensure it exists
        handler = self._on_click.get(selector)
        if handler is not None:
            handler(self._nodes)

    def type(self, selector: str, text: str) -> None:
        self._node(selector).value = text

    def is_visible(self, selector: str) -> bool:
        return bool(self._node(selector).visible)

    def computed_style(self, selector: str, prop: str) -> str:
        return self._node(selector).style.get(prop, "")

    def text_content(self, selector: str) -> str:
        return self._node(selector).text

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# 1. Classifier: interactive REQUIRES the gate; non-interactive does NOT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "thomas/server/web/app.js",
        "thomas/server/web/index.html",
        "src/components/Login.tsx",
        "frontend/store.ts",
        "thomas/server/web/styles.css",  # css under a UI dir
    ],
)
def test_interactive_change_requires_gate(path: str) -> None:
    classification = classify_change([path])
    assert classification.required is True
    assert path.replace("\\", "/") in classification.interactive_files


@pytest.mark.parametrize(
    "path",
    [
        "thomas/core/config.py",
        "docs/readme.md",
        "tests/test_thing.py",
        "pyproject.toml",
        "styles.css",  # bare css NOT under a UI dir -> not interactive
    ],
)
def test_non_interactive_change_does_not_require_gate(path: str) -> None:
    classification = classify_change([path])
    assert classification.required is False
    assert classification.interactive_files == ()


# ---------------------------------------------------------------------------
# 2. A passing click-type-assert flow satisfies the gate
# ---------------------------------------------------------------------------


def _login_driver(available: bool = True) -> FakeBrowserDriver:
    """A #welcome banner starts hidden and is revealed by clicking #login."""

    def reveal(nodes: dict[str, FakeNode]) -> None:
        nodes["#welcome"].visible = True

    nodes = {
        "#user": FakeNode(visible=True, value=""),
        "#login": FakeNode(visible=True, text="Log in"),
        "#welcome": FakeNode(visible=False, text="Hello alice", style={"color": "rgb(0, 128, 0)"}),
    }
    return FakeBrowserDriver(nodes, available=available, on_click={"#login": reveal})


def _login_flow(expected_text: str = "Hello alice") -> E2EFlow:
    return E2EFlow(
        name="login",
        target=E2ETarget(html="<html><body>...</body></html>"),
        steps=(
            Type("#user", "alice"),
            Click("#login"),
            AssertVisible("#welcome"),
            AssertText("#welcome", expected_text),
            AssertStyle("#welcome", "color", "rgb(0, 128, 0)"),
        ),
    )


def test_passing_flow_satisfies_gate() -> None:
    driver = _login_driver()
    result = run_flow(driver, _login_flow())
    assert result.ok is True
    assert result.attempted is True
    assert result.failures == ()
    assert driver.closed is True

    outcome = evaluate_e2e_gate(
        classification=ChangeClassification(True, ("app.js",), "ui"),
        run_result=result,
    )
    assert outcome.outcome == GATE_ALLOW


# ---------------------------------------------------------------------------
# 3. A failed assertion BLOCKS
# ---------------------------------------------------------------------------


def test_failed_assertion_blocks() -> None:
    driver = _login_driver()
    result = run_flow(driver, _login_flow(expected_text="Goodbye"))
    assert result.ok is False
    assert result.attempted is True
    # The AssertText step (index 3) is the failure; the AssertStyle after it
    # never ran (stop-at-first-failure).
    assert result.failures[0].kind == "AssertText"

    outcome = evaluate_e2e_gate(
        classification=ChangeClassification(True, ("app.js",), "ui"),
        run_result=result,
    )
    assert outcome.outcome == GATE_BLOCK


# ---------------------------------------------------------------------------
# 4. Absent browser BLOCKS (fail-closed)
# ---------------------------------------------------------------------------


def test_absent_browser_blocks_fail_closed() -> None:
    driver = _login_driver(available=False)
    result = run_flow(driver, _login_flow())
    assert result.attempted is False
    assert result.ok is False

    outcome = evaluate_e2e_gate(
        classification=ChangeClassification(True, ("app.js",), "ui"),
        run_result=result,
    )
    assert outcome.outcome == GATE_BLOCK
    assert "no real browser" in outcome.reason


def test_required_change_with_no_run_blocks() -> None:
    outcome = evaluate_e2e_gate(
        classification=ChangeClassification(True, ("app.js",), "ui"),
        run_result=None,
    )
    assert outcome.outcome == GATE_BLOCK


# ---------------------------------------------------------------------------
# 5. A non-interactive change does not require a run -> allow
# ---------------------------------------------------------------------------


def test_non_interactive_change_allows_without_run() -> None:
    outcome = evaluate_e2e_gate(
        classification=classify_change(["thomas/core/config.py"]),
        run_result=None,
    )
    assert outcome.outcome == GATE_ALLOW
    assert outcome.required is False


# ---------------------------------------------------------------------------
# 6. A hidden element fails the visibility assert (closes hidden-DOM trap)
# ---------------------------------------------------------------------------


def test_hidden_element_fails_visibility_assert() -> None:
    nodes = {"#banner": FakeNode(visible=False, text="Success")}
    driver = FakeBrowserDriver(nodes)
    flow = E2EFlow(
        name="visibility",
        target=E2ETarget(html="<html></html>"),
        steps=(AssertVisible("#banner"),),
    )
    result = run_flow(driver, flow)
    assert result.ok is False
    assert result.failures[0].kind == "AssertVisible"


def test_text_assert_refused_on_hidden_node() -> None:
    """A hidden node with matching innerText must NOT satisfy a text assert."""
    nodes = {"#banner": FakeNode(visible=False, text="Success")}
    driver = FakeBrowserDriver(nodes)
    flow = E2EFlow(
        name="hidden-text",
        target=E2ETarget(html="<html></html>"),
        steps=(AssertText("#banner", "Success"),),
    )
    result = run_flow(driver, flow)
    assert result.ok is False
    failure = result.failures[0]
    assert failure.kind == "AssertText"
    assert "hidden-DOM trap" in failure.detail


# ---------------------------------------------------------------------------
# Completion-gate decision-shape integration (real GateDecision)
# ---------------------------------------------------------------------------


def test_outcome_constants_match_completion_gate() -> None:
    assert GATE_ALLOW == completion_gate.GATE_ALLOW
    assert GATE_BLOCK == completion_gate.GATE_BLOCK


def test_to_gate_decision_builds_real_completion_gate_decision() -> None:
    driver = _login_driver()
    report = enforce_e2e_gate(
        changed_files=["thomas/server/web/app.js"],
        flow=_login_flow(),
        driver=driver,
        decision_factory=completion_gate.GateDecision,
    )
    assert isinstance(report.decision, completion_gate.GateDecision)
    assert report.decision.outcome == completion_gate.GATE_ALLOW
    assert report.blocked is False
    # And the real completion gate accepts this outcome shape unchanged.
    assert report.decision.to_payload()["outcome"] == "allow"


def test_enforce_blocks_interactive_change_on_failed_flow() -> None:
    driver = _login_driver()
    report = enforce_e2e_gate(
        changed_files=["thomas/server/web/app.js"],
        flow=_login_flow(expected_text="Goodbye"),
        driver=driver,
        decision_factory=completion_gate.GateDecision,
    )
    assert isinstance(report.decision, completion_gate.GateDecision)
    assert report.decision.outcome == completion_gate.GATE_BLOCK
    assert report.blocked is True


def test_to_gate_decision_default_payload() -> None:
    outcome = evaluate_e2e_gate(
        classification=classify_change(["thomas/core/config.py"]),
        run_result=None,
    )
    payload = to_gate_decision(outcome)
    assert payload == {"outcome": "allow", "reason": outcome.reason}


def test_enforce_skips_browser_for_non_interactive_change() -> None:
    driver = _login_driver()
    report = enforce_e2e_gate(
        changed_files=["thomas/core/config.py", "docs/x.md"],
        flow=_login_flow(),
        driver=driver,
        decision_factory=completion_gate.GateDecision,
    )
    assert report.run_result is None
    assert driver.opened is False  # browser never touched
    assert report.decision.outcome == completion_gate.GATE_ALLOW
