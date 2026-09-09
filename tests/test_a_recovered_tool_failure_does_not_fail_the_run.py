"""A worker that stumbled, retried, and delivered is not stamped unverified.

Completion review forgave a failed tool only if its name appeared in a hardcoded
allowlist of four filesystem-read names. Everything else was fatal. So two runs
that produced the identical file on disk got opposite verdicts purely on which
tool had stumbled on the way:

    fs.read_file failed, then succeeded  ->  verified
    shell        failed, then succeeded  ->  NOT verified

The signal the allowlist was groping for is already computed a line earlier: the
tool that failed also appears in `succeeded_tools`, meaning the worker recovered.
That is the same signal whatever the tool is called.

File evidence is what actually guards this, and it is untouched: every file the
worker claimed must exist and be non-empty. A tool receipt is the weaker of the
two signals and must not overrule a deliverable sitting on disk.
"""

from __future__ import annotations

import pytest

from thomas.server.chat_delegation_artifact_verification import _hidden_completion_review_passes


@pytest.fixture()
def delivered(tmp_path):
    """A run that really did produce its file."""

    (tmp_path / "report.html").write_text("<h1>real output</h1>", encoding="utf-8")
    return tmp_path


def _review(work_dir, *, failed, succeeded, files=("report.html",), summary="Created report.html."):
    return _hidden_completion_review_passes(
        "", work_dir, list(files), summary, True, list(failed), succeeded_tools=list(succeeded)
    )


@pytest.mark.parametrize("tool", ["shell", "shell.exec", "web.search", "python", "fs.write_file"])
def test_a_tool_that_failed_then_succeeded_does_not_sink_the_run(delivered, tool: str) -> None:
    assert _review(delivered, failed=[tool], succeeded=[tool]), (
        f"{tool} failed and then succeeded, and the file is on disk, but the run was "
        "stamped unverified -- the old allowlist is back"
    )


def test_the_verdict_no_longer_depends_on_which_tool_stumbled(delivered) -> None:
    """The comparison that made this a bug rather than a policy."""

    allowlisted = _review(delivered, failed=["fs.read_file"], succeeded=["fs.read_file"])
    ordinary = _review(delivered, failed=["shell"], succeeded=["shell"])

    assert allowlisted == ordinary, (
        "identical deliverables still get different verdicts based on the tool's name"
    )


# --- the controls: loosening this must not gut it -------------------------


def test_a_tool_that_never_succeeded_still_fails_the_run(delivered) -> None:
    assert not _review(delivered, failed=["shell"], succeeded=[]), (
        "an unrecovered failure now passes; the check has been gutted rather than fixed"
    )


def test_a_claimed_file_that_is_not_there_still_fails(delivered) -> None:
    assert not _review(delivered, failed=[], succeeded=[], files=("ghost.html",))


def test_an_empty_file_still_fails(delivered) -> None:
    (delivered / "hollow.html").write_text("", encoding="utf-8")
    assert not _review(delivered, failed=[], succeeded=[], files=("hollow.html",))


def test_a_missing_summary_still_fails(delivered) -> None:
    assert not _review(delivered, failed=[], succeeded=[], summary="   ")


def test_recovery_is_not_credited_when_the_deliverable_is_missing(delivered) -> None:
    """Recovery only counts when files landed. A run that recovered its tools but
    produced nothing real must not ride the recovery path to a pass."""

    assert not _review(delivered, failed=["shell"], succeeded=["shell"], files=("ghost.html",))
