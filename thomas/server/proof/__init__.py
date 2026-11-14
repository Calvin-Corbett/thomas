"""The proof step: run the tests that cover a change, and say what the change itself broke.

One caller today: :mod:`thomas.server.precard`, which runs it before a Thomas project's card reaches you.
A second one is not on dev yet -- it is being built in another project's copy: the ratchet's §3 "the proof set"
(``docs/superpowers/specs/2026-09-23-praxis-ratchet-design.md``) asks for a ``proof_set(changed_files)``
at ``thomas/ratchet/proof.py``, and says of it "has no equivalent in the repo today". This is that
equivalent, kept out of the card check so the ratchet can call the step instead of writing it again; its
plan (``docs/superpowers/plans/2026-09-24-praxis-ratchet.md``, Tasks 3-4) now says to call it.
Both want the same five things:

* :func:`~thomas.server.proof.selection.select` -- which test files prove a set of changed files, and
  which ones the cap left out.
* :func:`~thomas.server.proof.runner.run_tests` / :func:`~thomas.server.proof.runner.run_one` -- run them
  in shards in a copy, read the failures back from JUnit by test id, re-run one on its own. ``run=`` says
  how a command runs (here, or in the cage).
* :func:`~thomas.server.proof.compare.confirm` -- re-run each failure on its own, with the change and on the base,
  excusing it only when it fails alone on the base.
* :func:`~thomas.server.proof.environment.sandbox_env` -- an environment with none of your ``THOMAS_*``
  or ``GIT_*`` variables in it and a data folder of its own.
* :class:`~thomas.server.proof.deadline.Deadline` -- one clock for the whole proof.

Nothing here knows about Thomas projects, greens, cards or candidates. It takes a work folder, a list of
files and an interpreter, and answers with test ids.
"""

from __future__ import annotations

from thomas.server.proof.compare import RERUN_CAP, Verdict, confirm
from thomas.server.proof.deadline import Deadline
from thomas.server.proof.environment import PYTHON_ENV, interpreter, run_quietly, sandbox_env
from thomas.server.proof.junit import Report, read_report, test_id
from thomas.server.proof.runner import (
    FAILED,
    MISSING,
    NO_PLACE,
    PASSED,
    TIMEOUT,
    UNKNOWN,
    ProofRun,
    Run,
    run_one,
    run_tests,
)
from thomas.server.proof.runner import _pytest as pytest_command  # public here: runner.py's own name stays as it is
from thomas.server.proof.selection import (
    ALWAYS,
    CAP,
    TESTS_DIR,
    Selection,
    proof_set,
    select,
    select_from,
    version_bumps,
)

__all__ = [
    "ALWAYS",
    "CAP",
    "TESTS_DIR",
    "FAILED",
    "MISSING",
    "NO_PLACE",
    "PASSED",
    "PYTHON_ENV",
    "RERUN_CAP",
    "TIMEOUT",
    "UNKNOWN",
    "Deadline",
    "ProofRun",
    "Report",
    "Run",
    "Selection",
    "Verdict",
    "confirm",
    "interpreter",
    "proof_set",
    "pytest_command",
    "read_report",
    "run_one",
    "run_quietly",
    "run_tests",
    "sandbox_env",
    "select",
    "select_from",
    "test_id",
    "version_bumps",
]
