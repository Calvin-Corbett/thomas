"""A file the engine check passed on must not be listed as never validated.

`_build_open_risks` decides which changed files a passing check covered by
looking for their names in the check's output. It looked in `evidence`, the
240-character excerpt the card shows, instead of the check's whole recorded
result -- so on a run with enough changed files the report accused its own
passing check of having skipped the ones whose lines fell past the cut.

Measured by driving the REAL verifier (`build_verify.verify_python_changes`) on
real files, same code and same exit 0, varying only how many files changed::

    changed files   BEFORE (open risk)                        AFTER
    3               (none)                                    (none)
    9               src/module_number_07.py,                  (none)
                    src/module_number_08.py
    9 + 1 deleted   src/module_number_07.py,                  deleted_by_the_run.py
                    src/module_number_08.py,
                    deleted_by_the_run.py

Both of the falsely flagged files are named in the check's own recorded result
(`compiled src/module_number_07.py`), 349 characters of which the report kept
240. The last row is the control that matters: a file the verifier genuinely
never saw is still reported, and now reported alone, so the fix cannot have
worked by deleting the risk.
"""

from __future__ import annotations

from thomas.forge.anvil.run_report import build_run_report

_COVERAGE_RISK = "files changed without a matching passing validation"

# Nine changed files, which is where the excerpt starts cutting. Long enough
# paths that the 240-character limit bites, which is the whole point.
CHECKED = [f"src/module_number_{i:02d}.py" for i in range(9)]


def _static_check_events(checked: list[str]) -> list[dict[str, object]]:
    """The events `build_verify.verify_python_changes` really emits, exactly.

    A `run` tool call carrying `label[:200]`, then one `tool_result` carrying
    `detail[:500]`: `exit 0`, one `compiled <file>` line per file, then the
    verifier's own `STATIC_VERIFY_OK` summary.
    """

    label = "static checks: syntax + parse + open (" + ", ".join(checked) + ")"
    detail = "\n".join(
        [
            "exit 0",
            *(f"compiled {name}" for name in checked),
            f"STATIC_VERIFY_OK: {len(checked)} files checked, 0 imported",
        ]
    )
    return [
        {"fc": "tool", "name": "run", "text": label[:200]},
        {"fc": "tool_result", "text": detail[:500], "is_error": False},
    ]


def _coverage_risk_detail(checked: list[str], changed: list[str]) -> str:
    report = build_run_report(
        goal="Make the app",
        events=_static_check_events(checked),
        changed_files=changed,
        returncode=0,
        ok=True,
        outcome="completed",
        reason=f"{len(changed)} file(s) changed",
    )
    hits = [str(risk["detail"]) for risk in report["open_risks"] if risk["risk"] == _COVERAGE_RISK]
    return hits[0] if hits else ""


def test_a_file_the_check_compiled_is_not_reported_as_unvalidated() -> None:
    detail = _coverage_risk_detail(CHECKED, CHECKED)
    assert detail == "", (
        "every changed file was compiled by the passing check, yet the report "
        f"says some were never validated: {detail!r}"
    )


def test_a_file_no_check_ever_saw_is_still_reported() -> None:
    """The control. Without this the test above passes if the risk is deleted."""

    changed = [*CHECKED, "deleted_by_the_run.py"]
    detail = _coverage_risk_detail(CHECKED, changed)
    assert "deleted_by_the_run.py" in detail, (
        "a changed file the verifier never checked is no longer reported; the "
        f"risk has stopped working rather than become truthful. Got: {detail!r}"
    )
    for name in CHECKED:
        assert name not in detail, f"{name} was compiled by the passing check and must not be flagged: {detail!r}"


def test_a_small_run_is_unaffected() -> None:
    """Three files fit inside the excerpt, so this row never lied and must not start."""

    assert _coverage_risk_detail(CHECKED[:3], CHECKED[:3]) == ""
    assert "deleted_by_the_run.py" in _coverage_risk_detail(CHECKED[:3], [*CHECKED[:3], "deleted_by_the_run.py"])


def test_the_card_excerpt_is_still_short() -> None:
    """Fixed by reading the full record, NOT by showing more of it.

    Widening `evidence` would have silenced the risk too, while pushing a
    350-character blob into a card sized for a line. The excerpt stays capped;
    the coverage question is simply no longer asked of it.
    """

    report = build_run_report(events=_static_check_events(CHECKED), changed_files=CHECKED, ok=True, returncode=0)
    check = report["validations"][0]
    assert len(check["evidence"]) <= 240, "the display excerpt grew instead of the lookup widening"
    assert "src/module_number_08.py" not in check["evidence"], "the excerpt no longer cuts, so this proves nothing"
    assert "src/module_number_08.py" in check["evidence_full"], "the whole recorded result is not being kept"
