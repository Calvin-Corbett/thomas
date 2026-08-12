"""Opening the app is the default, and "I could not look" is not silence.

`runtime_executability_warning` is the only check in Thomas that opens a generated
app and watches it load. Two things were wrong with it:

  * it ran only when `THOMAS_RUNTIME_VERIFY` was switched on, and that variable is
    set in exactly one place in this repository — a test file. So it had never run
    for a real user.
  * `if result.ok or result.skipped: return ""` gave the same answer to "we looked
    and it was fine" and "we never looked". Silence from a step advertised as
    "I open the app and watch it run" reads to a person as "someone checked".

Measured on 2026-08-05: Thomas built a three-file expense tracker whose app.js
referenced an undeclared `refreshButton` on its last line. The page threw on load
and rendered nothing, and Thomas handed it over with no warning, because nothing
opened it. Every static check passed — every file really was present.

Nothing here can reject a run. The function returns a sentence to append, and every
path inside it returns a sentence.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from thomas.server import chat_delegation_deliverable_postprocess as mod


@dataclass
class _Result:
    ok: bool
    skipped: bool
    reason: str


def _run(monkeypatch, tmp_path, result: _Result, env: str | None = None) -> str:
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    monkeypatch.setattr(
        "thomas.server.deliverable_runtime_verify.runtime_smoke_load",
        lambda work_dir, entry=None: result,
    )
    if env is None:
        monkeypatch.delenv("THOMAS_RUNTIME_VERIFY", raising=False)
    else:
        monkeypatch.setenv("THOMAS_RUNTIME_VERIFY", env)
    return mod.runtime_executability_warning(tmp_path, ["index.html"])


def test_the_check_runs_without_anyone_switching_it_on(monkeypatch, tmp_path) -> None:
    """The regression that mattered: opt-in meant never."""

    warning = _run(monkeypatch, tmp_path, _Result(False, False, "uncaught JS error during load/run"))

    assert "did not run cleanly" in warning, (
        "the browser check is opt-in again, so it will never run for a real user"
    )
    assert "uncaught JS error" in warning, "the reason was dropped; the user cannot act on 'it failed'"


def test_a_check_that_could_not_run_says_so(monkeypatch, tmp_path) -> None:
    """The half that made silence ambiguous."""

    warning = _run(monkeypatch, tmp_path, _Result(False, True, "no browser available"))

    assert warning.strip(), "a skipped check returned silence, which reads as 'someone checked'"
    assert "could not open" in warning
    assert "no browser available" in warning
    # It must NOT claim the app is broken — nothing was observed either way.
    assert "did not run cleanly" not in warning


def test_an_app_that_opens_cleanly_stays_quiet(monkeypatch, tmp_path) -> None:
    """The control. A warning that fires on everything is worth nothing."""

    assert _run(monkeypatch, tmp_path, _Result(True, False, "")) == ""


@pytest.mark.parametrize("off", ["0", "off", "false", "no"])
def test_it_can_still_be_switched_off_deliberately(monkeypatch, tmp_path, off: str) -> None:
    """Opt-out survives; only the default flipped."""

    assert _run(monkeypatch, tmp_path, _Result(False, False, "boom"), env=off) == ""


def test_nothing_to_open_is_not_a_warning(monkeypatch, tmp_path) -> None:
    """A run that produced no HTML has nothing to say here, and must not invent it."""

    monkeypatch.delenv("THOMAS_RUNTIME_VERIFY", raising=False)
    assert mod.runtime_executability_warning(tmp_path, ["notes.md", "data.csv"]) == ""
    assert mod.runtime_executability_warning(None, ["index.html"]) == ""
