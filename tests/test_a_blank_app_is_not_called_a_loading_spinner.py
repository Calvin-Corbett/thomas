"""An app nobody measured must not be diagnosed as a loading spinner.

`runtime_smoke_load` polls a render probe across a settle window and keeps the
best sample. `best` used to be SEEDED::

    best = {"visText": 0, "loadingOnly": True, "hasApp": False, "canvasDrawn": False, "dom": 0}

A seeded sample is indistinguishable from one the probe actually returned. So a
page whose every real sample lost the `better` comparison -- or where the poll
loop exited before its first tick -- kept the seed, and the seed says
`loadingOnly: True`. The run then reported

    app rendered nothing usable — still showing a loading placeholder

about a page the checker had never successfully measured. That is a diagnosis
invented from a default value, and it points whoever reads it at a spinner that
may not exist.

`best` now starts as None, `probed` records whether any sample arrived, and the
unmeasured case says so in its own words instead of borrowing the loading verdict.

This guards the reporting contract at the seam rather than driving a real
browser, because the defect is in what the result SAYS, and that is decided
entirely by `probed` and the `_result` it flows into.
"""

from __future__ import annotations

import inspect
import re

from thomas.server import deliverable_runtime_verify as verify
from thomas.server.deliverable_runtime_verify import RuntimeResult

SOURCE = inspect.getsource(verify)


def _code() -> str:
    """Source minus comments -- this change is documented above itself, and the
    prose quotes the seeded literal it removes."""

    return "\n".join(
        line for line in SOURCE.splitlines() if not line.lstrip().startswith("#")
    )


def test_the_render_probe_is_not_seeded_with_a_fake_sample() -> None:
    code = _code()
    assert '"loadingOnly": True, "hasApp": False' not in code, (
        "the poll loop seeds `best` with a synthetic sample again. A seeded "
        "sample is indistinguishable from a real one, so a page that never "
        "reported back keeps `loadingOnly: True` and is diagnosed as a loading "
        "spinner on no evidence."
    )
    assert re.search(r"best:\s*dict\s*\|\s*None\s*=\s*None", code), (
        "`best` no longer starts as None, so 'the probe has not answered yet' "
        "is once more indistinguishable from 'the probe answered blank'"
    )


def test_an_unmeasured_render_is_reported_as_unmeasured() -> None:
    """Not as blank, and not as a loading placeholder."""

    code = _code()
    assert "never reported back" in code, (
        "the unmeasured case no longer has its own wording, so it falls through "
        "to the blank/loading diagnosis that the checker has no evidence for"
    )
    # And that branch must come BEFORE the blank/loading verdict, or it is dead.
    unmeasured = code.find("never reported back")
    blank = code.find("app rendered nothing usable")
    assert 0 < unmeasured < blank, (
        "the unmeasured branch is reached after the blank/loading verdict has "
        "already returned, so it can never run"
    )


def test_probed_defaults_true_so_existing_callers_are_unaffected() -> None:
    """Every other construction site means "measured"; only the new one does not."""

    assert RuntimeResult(ok=True, entry="index.html").probed is True


def test_a_summary_says_when_the_render_was_never_sampled() -> None:
    """A JS error with no measurement is weaker evidence than one with it."""

    sampled = RuntimeResult(ok=False, entry="index.html", page_errors=["boom"], probed=True)
    unsampled = RuntimeResult(ok=False, entry="index.html", page_errors=["boom"], probed=False)
    assert "never sampled" not in sampled.summary(), (
        f"a measured failure is annotated as unsampled: {sampled.summary()!r}"
    )
    assert "never sampled" in unsampled.summary(), (
        "a failure where the render was never sampled reads identically to one "
        f"that was measured: {unsampled.summary()!r}"
    )


def test_a_rendering_app_still_reads_as_ok() -> None:
    """The opposite failure: calling every page unmeasured."""

    good = RuntimeResult(ok=True, entry="index.html", rendered_chars=420, dom_nodes=90)
    assert "runtime OK" in good.summary()
    assert "never sampled" not in good.summary()
