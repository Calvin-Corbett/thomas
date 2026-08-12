"""Real-browser click-type-assert E2E gate mechanism (CAP-088).

DORMANT: nothing in production imports this module, so it gates nothing today.
This is the mechanism a required browser gate would be built from, not a gate
in force.  The missing piece is an *input*, not a call site:
:func:`enforce_e2e_gate` needs a caller-supplied :class:`E2EFlow` -- the
click/type/assert steps for the change under review -- and no production module
builds one.  Forcing it on without a flow producer is not a gate either way:
assertion-free steps answer ``allow`` for a run that asserted nothing, and an
empty flow (or a machine lacking the browser runtime) answers ``block`` for
every interactive change.  Delete this notice in the same change that adds a
production caller; ``tests/test_e2e_gate_is_not_wired_in`` fails when the notice
and the import graph disagree, in either direction.

The existing headless smoke (``thomas.forge.anvil.web_artifact_smoke``) proves
that a web artifact *boots* without console errors -- it is advisory and
boot-only.  This module supplies the three parts a *required* completion gate
for interactive changes would need:

1. an INTERACTIVE-CHANGE CLASSIFIER decides whether a change touches
   UI/interactive surfaces and would therefore *require* a browser E2E run;
2. a CLICK-TYPE-ASSERT flow runner drives an *injectable* browser driver
   (a real Playwright-backed default via the live ``thomas.tools.browser``
   seam, and a hermetic fake for tests) performing click/type steps and
   ASSERTING on **computed** visibility / style / text -- text and style
   assertions are refused on non-computed-visible nodes, closing the
   hidden-DOM verification trap (reading ``innerText`` off a ``display:none``
   node must never satisfy an assertion);
3. the result is *shaped* for promotion to a REQUIRED gate: for an interactive
   change a missing or failed E2E run yields ``block``, and the outcome is
   **fail-closed** when no real browser is present.  Nothing acts on that
   outcome yet.

Integration with the completion gate is done by *shape*, not by import: the
gate emits an outcome whose string values mirror
``thomas.agent.completion_gate`` (``allow`` / ``block``), and
:func:`to_gate_decision` builds a real ``GateDecision`` through an injected
factory.  This keeps the ext-tier ``browser`` package from importing the
core-tier ``agent`` package (see ``thomas/_architecture.py``) while still
producing the exact completion-gate decision shape.  No production caller
performs that integration: ``thomas.agent.loop_completion`` builds its
``GateDecision`` from ``thomas.agent.completion_gate`` alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Outcome string constants -- deliberately identical to
# ``thomas.agent.completion_gate.GATE_ALLOW`` / ``GATE_BLOCK`` so an emitted
# outcome slots into the completion-gate decision shape without translation.
GATE_ALLOW = "allow"
GATE_BLOCK = "block"

# Concrete faults a browser driver (fake or real) may raise mid-step.  We catch
# this WIDE SPECIFIC TUPLE rather than a bare ``Exception`` so an unexpected
# programming error still surfaces instead of being silently swallowed.
_DRIVER_FAULTS: tuple[type[BaseException], ...] = (
    KeyError,
    ValueError,
    TypeError,
    RuntimeError,
    LookupError,
    AttributeError,
    OSError,
    TimeoutError,
)


class E2EDriverError(RuntimeError):
    """Raised by a browser driver when a low-level operation cannot proceed."""


# ---------------------------------------------------------------------------
# 1. Interactive-change classifier
# ---------------------------------------------------------------------------

# Suffixes that are always interactive UI surfaces regardless of location.
_INTERACTIVE_SUFFIXES = frozenset({".html", ".htm", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".svelte"})
# Suffixes that are interactive only when they live under a UI directory.
_UI_SCOPED_SUFFIXES = frozenset({".css", ".scss", ".sass", ".less"})
# Path fragments that mark a UI / front-end surface.
_UI_DIR_HINTS = (
    "server/web/",
    "/web/",
    "templates/",
    "/static/",
    "components/",
    "/ui/",
    "frontend/",
)


@dataclass(frozen=True)
class ChangeClassification:
    """Whether a change requires a browser E2E gate, and why."""

    required: bool
    interactive_files: tuple[str, ...]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "interactive_files": list(self.interactive_files),
            "reason": self.reason,
        }


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def _is_interactive_file(path: str) -> bool:
    norm = _normalized(path)
    if not norm:
        return False
    lowered = norm.lower()
    suffix = PurePosixPath(lowered).suffix
    if suffix in _INTERACTIVE_SUFFIXES:
        return True
    if suffix in _UI_SCOPED_SUFFIXES and any(hint in lowered for hint in _UI_DIR_HINTS):
        return True
    return False


def classify_change(
    changed_files: list[str] | tuple[str, ...],
    *,
    diff_text: str | None = None,
) -> ChangeClassification:
    """Decide whether a change requires a browser E2E gate.

    A change is *interactive* -- and therefore requires the gate -- when it
    touches any front-end surface: an HTML/JS/TS/component file anywhere, or a
    stylesheet under a UI directory.  Pure back-end Python, docs, config, and
    tests are non-interactive and do not require the gate.
    """
    files = tuple(_normalized(f) for f in (changed_files or ()) if _normalized(f))
    interactive = tuple(f for f in files if _is_interactive_file(f))
    if interactive:
        return ChangeClassification(
            required=True,
            interactive_files=interactive,
            reason=(
                "interactive surface(s) touched: "
                + ", ".join(interactive[:8])
                + ("" if len(interactive) <= 8 else f" (+{len(interactive) - 8} more)")
            ),
        )
    return ChangeClassification(
        required=False,
        interactive_files=(),
        reason="no interactive UI surfaces touched",
    )


# ---------------------------------------------------------------------------
# 2. Click-type-assert flow over an injectable driver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class E2ETarget:
    """The page a flow runs against: a URL, or self-contained HTML."""

    url: str | None = None
    html: str | None = None


@dataclass(frozen=True)
class Click:
    selector: str


@dataclass(frozen=True)
class Type:
    selector: str
    text: str


@dataclass(frozen=True)
class AssertVisible:
    """Assert a node's *computed* visibility (``expected=False`` = hidden)."""

    selector: str
    expected: bool = True


@dataclass(frozen=True)
class AssertText:
    """Assert visible text.  Refused on non-computed-visible nodes."""

    selector: str
    expected: str
    mode: str = "equals"  # "equals" | "contains"


@dataclass(frozen=True)
class AssertStyle:
    """Assert a computed style property.  Refused on non-visible nodes."""

    selector: str
    prop: str
    expected: str


Step = Click | Type | AssertVisible | AssertText | AssertStyle


@dataclass(frozen=True)
class E2EFlow:
    """A named click-type-assert flow against a target page."""

    name: str
    target: E2ETarget
    steps: tuple[Step, ...]


@runtime_checkable
class BrowserDriver(Protocol):
    """Injectable browser edge.  Assertions read *computed* state only."""

    @property
    def available(self) -> bool: ...

    def open(self, target: E2ETarget) -> None: ...

    def click(self, selector: str) -> None: ...

    def type(self, selector: str, text: str) -> None: ...

    def is_visible(self, selector: str) -> bool:
        """Computed visibility -- honours display/visibility/opacity/rects."""
        ...

    def computed_style(self, selector: str, prop: str) -> str: ...

    def text_content(self, selector: str) -> str:
        """Visible text of a node.  Callers must gate this on visibility."""
        ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class StepOutcome:
    index: int
    kind: str
    selector: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class E2ERunResult:
    """Outcome of running one click-type-assert flow."""

    ok: bool
    attempted: bool
    flow: str
    steps: tuple[StepOutcome, ...] = ()
    summary: str = ""

    @property
    def failures(self) -> tuple[StepOutcome, ...]:
        return tuple(step for step in self.steps if not step.ok)


def _describe(step: Step) -> tuple[str, str]:
    kind = type(step).__name__
    selector = getattr(step, "selector", "")
    return kind, str(selector)


def _run_step(driver: BrowserDriver, step: Step) -> tuple[bool, str]:
    """Execute one step and return ``(ok, detail)``.

    The hidden-DOM trap is closed here: text and style assertions first require
    *computed* visibility and only then read text/style; a hidden node fails the
    assertion instead of silently passing on ``innerText`` scraped off a
    ``display:none`` element.
    """
    if isinstance(step, Click):
        driver.click(step.selector)
        return True, f"clicked {step.selector}"
    if isinstance(step, Type):
        driver.type(step.selector, step.text)
        return True, f"typed into {step.selector}"
    if isinstance(step, AssertVisible):
        actual = bool(driver.is_visible(step.selector))
        if actual == step.expected:
            return True, f"{step.selector} computed-visible={actual}"
        return False, (f"{step.selector} computed-visible={actual}, expected {step.expected}")
    if isinstance(step, AssertText):
        if not driver.is_visible(step.selector):
            return False, (
                f"{step.selector} is not computed-visible; refusing to assert text on a hidden node (hidden-DOM trap)"
            )
        text = str(driver.text_content(step.selector))
        if step.mode == "contains":
            ok = step.expected in text
        else:
            ok = text.strip() == step.expected.strip()
        return ok, (
            f"{step.selector} text={text!r} "
            f"({'contains' if step.mode == 'contains' else 'equals'} "
            f"{step.expected!r}): {'ok' if ok else 'mismatch'}"
        )
    if isinstance(step, AssertStyle):
        if not driver.is_visible(step.selector):
            return False, (
                f"{step.selector} is not computed-visible; refusing to assert computed style on a hidden node"
            )
        value = str(driver.computed_style(step.selector, step.prop))
        ok = value.strip() == step.expected.strip()
        return ok, (f"{step.selector} {step.prop}={value!r} expected {step.expected!r}: {'ok' if ok else 'mismatch'}")
    return False, f"unknown step {type(step).__name__}"


def run_flow(driver: BrowserDriver, flow: E2EFlow) -> E2ERunResult:
    """Run a click-type-assert flow against ``driver``.

    When the driver reports no real browser, the run is *not attempted* and the
    result is not ``ok`` -- the gate treats this as fail-closed.
    """
    if not driver.available:
        return E2ERunResult(
            ok=False,
            attempted=False,
            flow=flow.name,
            summary="no real browser available; E2E run not attempted",
        )

    outcomes: list[StepOutcome] = []
    ok = True
    try:
        driver.open(flow.target)
        for index, step in enumerate(flow.steps):
            kind, selector = _describe(step)
            try:
                step_ok, detail = _run_step(driver, step)
            except _DRIVER_FAULTS as exc:
                logger.warning("e2e step %s (%s) errored: %s", index, kind, exc)
                step_ok, detail = False, f"driver error: {type(exc).__name__}: {exc}"
            outcomes.append(StepOutcome(index=index, kind=kind, selector=selector, ok=step_ok, detail=detail))
            if not step_ok:
                ok = False
                break
    finally:
        try:
            driver.close()
        except _DRIVER_FAULTS as exc:
            logger.debug("e2e driver close raised %s: %s", type(exc).__name__, exc)

    if ok and outcomes:
        summary = f"{flow.name}: {len(outcomes)} steps passed"
    elif outcomes:
        last = outcomes[-1]
        summary = f"{flow.name}: failed at step {last.index} ({last.kind}): {last.detail}"
    else:
        summary = f"{flow.name}: no steps executed"
    return E2ERunResult(
        ok=ok and bool(outcomes), attempted=True, flow=flow.name, steps=tuple(outcomes), summary=summary
    )


# ---------------------------------------------------------------------------
# 3. Promotion to a required completion gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class E2EGateOutcome:
    """Gate decision in this module's own vocabulary (allow / block)."""

    outcome: str
    reason: str
    required: bool
    attempted: bool
    run_ok: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "required": self.required,
            "attempted": self.attempted,
            "run_ok": self.run_ok,
        }


def evaluate_e2e_gate(
    *,
    classification: ChangeClassification,
    run_result: E2ERunResult | None,
) -> E2EGateOutcome:
    """Promote a classification + run into an allow/block completion decision.

    - Non-interactive change: ``allow`` (no browser E2E required).
    - Interactive change, passing run: ``allow``.
    - Interactive change, missing run / no browser / failed run: ``block``
      (fail-closed).
    """
    if not classification.required:
        return E2EGateOutcome(
            outcome=GATE_ALLOW,
            reason="non-interactive change; browser E2E not required",
            required=False,
            attempted=bool(run_result and run_result.attempted),
            run_ok=bool(run_result and run_result.ok),
        )

    if run_result is None:
        return E2EGateOutcome(
            outcome=GATE_BLOCK,
            reason=("interactive change requires a click-type-assert browser E2E run, but none was provided"),
            required=True,
            attempted=False,
            run_ok=False,
        )

    if not run_result.attempted:
        return E2EGateOutcome(
            outcome=GATE_BLOCK,
            reason=(
                f"interactive change requires browser E2E, but no real browser was available ({run_result.summary})"
            ),
            required=True,
            attempted=False,
            run_ok=False,
        )

    if run_result.ok:
        return E2EGateOutcome(
            outcome=GATE_ALLOW,
            reason=f"browser E2E passed ({run_result.summary})",
            required=True,
            attempted=True,
            run_ok=True,
        )

    return E2EGateOutcome(
        outcome=GATE_BLOCK,
        reason=f"browser E2E failed ({run_result.summary})",
        required=True,
        attempted=True,
        run_ok=False,
    )


def to_gate_decision(
    outcome: E2EGateOutcome,
    *,
    decision_factory: Callable[..., Any] | None = None,
) -> Any:
    """Adapt an :class:`E2EGateOutcome` into the completion-gate decision shape.

    ``decision_factory`` is injected by the agent-tier caller, typically
    ``thomas.agent.completion_gate.GateDecision`` -- e.g.::

        to_gate_decision(outcome, decision_factory=GateDecision)

    The outcome strings already match ``GATE_ALLOW`` / ``GATE_BLOCK`` in
    ``completion_gate``, so the produced decision needs no translation.  When no
    factory is injected a plain ``{"outcome", "reason"}`` payload is returned.
    """
    if decision_factory is None:
        return {"outcome": outcome.outcome, "reason": outcome.reason}
    return decision_factory(outcome=outcome.outcome, reason=outcome.reason)


@dataclass(frozen=True)
class E2EGateReport:
    """Everything the caller needs to enforce and explain the gate."""

    classification: ChangeClassification
    run_result: E2ERunResult | None
    outcome: E2EGateOutcome
    decision: Any = field(default=None)

    @property
    def blocked(self) -> bool:
        return self.outcome.outcome == GATE_BLOCK


def enforce_e2e_gate(
    *,
    changed_files: list[str] | tuple[str, ...],
    flow: E2EFlow,
    driver: BrowserDriver,
    diff_text: str | None = None,
    decision_factory: Callable[..., Any] | None = None,
) -> E2EGateReport:
    """Classify a change, run the E2E flow if required, and decide the gate.

    The E2E flow is only executed when the change is classified interactive; a
    non-interactive change is allowed without touching a browser.
    """
    classification = classify_change(changed_files, diff_text=diff_text)
    run_result = run_flow(driver, flow) if classification.required else None
    outcome = evaluate_e2e_gate(classification=classification, run_result=run_result)
    decision = to_gate_decision(outcome, decision_factory=decision_factory)
    return E2EGateReport(
        classification=classification,
        run_result=run_result,
        outcome=outcome,
        decision=decision,
    )


# ---------------------------------------------------------------------------
# Real default driver -- live-gated, Playwright-backed via the existing seam
# ---------------------------------------------------------------------------


class PlaywrightBrowserDriver:
    """Real browser driver over the live ``thomas.tools.browser`` seam.

    This is the production default.  ``available`` reflects a genuine capability
    probe (Playwright import + the canonical browser runtime); when either is
    absent it reports ``False`` so the gate fails closed.  The step execution
    path uses Playwright's synchronous API and asserts on **computed** style and
    visibility.  It is exercised only on the credential/browser-gated *live*
    lane -- the offline test-suite drives the hermetic fake instead, and no live
    run is claimed here.
    """

    def __init__(
        self, *, headless: bool = True, runtime_probe: Callable[[], tuple[Any, dict[str, Any]]] | None = None
    ) -> None:
        self._headless = bool(headless)
        self._runtime_probe = runtime_probe
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None

    @property
    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        probe = self._runtime_probe
        if probe is None:
            from thomas.browser.runtime_bridge import import_browser_runtime

            probe = import_browser_runtime
        try:
            _module, meta = probe()
        except _DRIVER_FAULTS as exc:
            logger.info("browser runtime probe failed: %s", exc)
            return False
        return bool(meta.get("available"))

    def open(self, target: E2ETarget) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page()
        if target.url:
            self._page.goto(target.url)
        elif target.html is not None:
            self._page.set_content(target.html)
        else:
            raise E2EDriverError("E2ETarget requires a url or html payload")

    def _require_page(self) -> Any:
        if self._page is None:
            raise E2EDriverError("driver.open must be called before interacting")
        return self._page

    def click(self, selector: str) -> None:
        self._require_page().click(selector)

    def type(self, selector: str, text: str) -> None:
        self._require_page().fill(selector, text)

    def is_visible(self, selector: str) -> bool:
        return bool(self._require_page().is_visible(selector))

    def computed_style(self, selector: str, prop: str) -> str:
        page = self._require_page()
        return str(
            page.eval_on_selector(
                selector,
                "(el, prop) => getComputedStyle(el).getPropertyValue(prop)",
                prop,
            )
        )

    def text_content(self, selector: str) -> str:
        return str(self._require_page().inner_text(selector))

    def close(self) -> None:
        for handle, name in ((self._page, "page"), (self._browser, "browser"), (self._pw, "pw")):
            if handle is None:
                continue
            closer = getattr(handle, "stop", None) or getattr(handle, "close", None)
            if closer is None:
                continue
            try:
                closer()
            except _DRIVER_FAULTS as exc:
                logger.debug("closing %s raised %s: %s", name, type(exc).__name__, exc)
        self._page = self._browser = self._pw = None


def default_driver() -> BrowserDriver:
    """Return the production Playwright-backed driver (live-gated)."""
    return PlaywrightBrowserDriver()
