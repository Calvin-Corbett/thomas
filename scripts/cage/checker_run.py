"""One checker job, start to answer: the copies, the tests that cover the change, the re-runs and the boot check.

Split from scripts/cage/checker_service.py (Task 36), which keeps the loop, the lock, the fence probe and ``main``.
Each job: copies at its commit and at its base (``git clone --shared`` of your checkout's objects); the tests that cover
the changed files (thomas/server/proof), plus any it names; each failure re-run alone with the change and alone on the
base, blocking unless it passes alone (noise) or fails alone on the base too, and UNAVAILABLE (tried again) when no
re-run could settle it; and a boot check that Thomas still imports. Then the answer, once every test process has
ended, and the copies removed.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.cage import checker_jobs as cj

from thomas.server import proof
from thomas.server.proof.environment import NOT_STARTED, REFUSED, TIMED_OUT

if TYPE_CHECKING:
    from scripts.cage.checker_runner import Runner

log = logging.getLogger("thomas.checker")

JOB_DEADLINE_S = 2400.0
WORKERS = 4
BOOT_IMPORTS = ("thomas", "thomas.core.config", "thomas.memory", "thomas.agent", "thomas.server", "thomas.server.app")
BOOT_TIMEOUT_S = 180.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NO_HOOKS = str(Path(tempfile.gettempdir()) / "thomas-checker-no-hooks")
CONFIG = "pyproject.toml"  # the only pytest config a run reads: the copy's own, which never lands in a window


class CopyFailed(RuntimeError):
    """A copy for the job could not be made."""


def _remove(path: Path) -> None:
    """Remove *path* whole. Git's object files are read-only on Windows, and a test that makes a repository leaves
    some in its copy: each is made writable first, so copies never pile up on the disk."""

    def writable(func: Callable[[str], object], target: str, _exc: BaseException) -> None:
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            log.warning("could not remove %s", target)

    if os.path.lexists(path):
        shutil.rmtree(path, onexc=writable)


@dataclass
class Tools:
    """What a job runs with. Tests replace these; nothing else does."""

    select: Callable[..., proof.Selection] = proof.select
    run_tests: Callable[..., proof.ProofRun] = proof.run_tests
    run_one: Callable[..., str] = proof.run_one
    confirm: Callable[..., proof.Verdict] = proof.confirm
    run: Callable[..., tuple[int, str]] = proof.run_quietly


def _git(cwd: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    """git as this account: your checkout belongs to another account, so it is named safe for this run only."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-c", f"core.hooksPath={_NO_HOOKS}", "-c", "core.fsmonitor=false"]
        + ["-c", "core.longpaths=true", *args],
        cwd=None if cwd is None else str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=_NO_WINDOW,
    )


def make_copy(repo: Path, commit: str, dest: Path) -> None:
    """A copy of *repo* at *commit* in *dest*, sharing your checkout's objects and writing none of them."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cloned = _git(None, "clone", "--quiet", "--no-checkout", "--shared", str(repo), str(dest))
    if cloned.returncode:
        raise CopyFailed(f"git clone failed: {cloned.stderr.strip()[:200]}")
    _git(dest, "config", "core.longpaths", "true")  # some plan folders' names pass Windows' 260 characters
    checked = _git(dest, "checkout", "--quiet", "--detach", commit)
    if checked.returncode:
        raise CopyFailed(f"git checkout {commit[:12]} failed: {checked.stderr.strip()[:200]}")


# A boot check that timed out, would not launch or got no place proved nothing about the change (review B5).
_BOOT_UNSETTLED = (TIMED_OUT, NOT_STARTED, REFUSED)


def _boot(work: Path, python: str, data_dir: Path, run: Callable[..., tuple[int, str]]) -> tuple[int, str]:
    env = proof.sandbox_env(work, data_dir)
    code, out = run([python, "-c", "import " + ", ".join(BOOT_IMPORTS)], cwd=work, env=env, timeout_s=BOOT_TIMEOUT_S)
    if code == 0:
        return 0, ""
    lines = [line.strip() for line in str(out).splitlines() if line.strip()]
    return code, (lines[-1] if lines else f"exit code {code}")[:300]


def boot_problem(work: Path, python: str, data_dir: Path, run: Callable[..., tuple[int, str]]) -> str:
    """Why Thomas does not start in *work* (its modules do not import), or "" when it does."""
    return _boot(work, python, data_dir, run)[1]


def _needs_coverage(path: str) -> bool:
    """A ``.py`` file outside ``tests/`` and ``changelog.d/``: code a test should exercise (plan Task 36)."""
    lowered = path.lower()
    return lowered.endswith((".py", ".pyi")) and not lowered.startswith(("tests/", "changelog.d/"))


def _uncovered(tools: Tools, work: Path, changed: tuple[str, ...]) -> list[str]:
    """The changed code files in *work* that no test but the always-run ones would exercise. ``select`` always adds
    tests/test_architecture.py, so "nothing selected" never happens and is no test of coverage (review, B3)."""
    return [
        path
        for path in changed
        if _needs_coverage(path)
        and (work / path).is_file()  # a deleted module has no code left to exercise; its importers are run
        and not [rel for rel in tools.select(work, [path]).files if rel not in proof.ALWAYS]
    ]


def _answer(job: cj.Job, verdict: str, why: str, clock: Callable[[], float], **fields: object) -> cj.Result:
    return cj.Result(job.id, job.kind, job.base, job.commit, job.tree, verdict, why, finished_at=clock(), **fields)


def run_job(
    job: cj.Job,
    *,
    repo: Path,
    copies: Path,
    python: str,
    tools: Tools | None = None,
    runner: Runner | None = None,
    clock: Callable[[], float] = time.time,
) -> cj.Result:
    """Check *job* and answer it. Never raises for anything the job or its copies did.

    *runner* is the isolated test-runner identity (review B1). When one is given and it is not available, the job is
    UNAVAILABLE at once -- no copy is made and no test is run, because running a change's tests as the checker's own
    account is exactly the risk the runner exists to remove. When it is available, its tools launch every test process
    as that account."""
    if runner is not None and not runner.available():
        why = f"the checker has no isolated test-runner identity, so it will not run the tests as itself: {runner.reason()}"
        return _answer(job, cj.UNAVAILABLE, why, clock)
    if tools is None:
        tools = runner.tools() if runner is not None else Tools()
    place = Path(copies) / job.id
    _remove(place)
    try:
        work, base = place / "work", place / "base"
        try:
            make_copy(repo, job.commit, work)
            make_copy(repo, job.base, base)
        except CopyFailed as exc:
            return _answer(job, cj.UNAVAILABLE, f"the copies could not be made: {exc}", clock)
        tree = _git(work, "rev-parse", "HEAD^{tree}").stdout.strip()
        if tree != job.tree:
            return _answer(
                job, cj.UNAVAILABLE, f"the copy holds tree {tree[:12]}, not the job's {job.tree[:12]}", clock
            )
        if not python:
            return _answer(job, cj.UNAVAILABLE, "there is no Python to run the tests with", clock)
        deadline = proof.Deadline(JOB_DEADLINE_S)
        selection = tools.select(work, list(job.changed))
        uncovered = _uncovered(tools, work, job.changed)
        if uncovered:
            words = f"no test covers this change: only {proof.ALWAYS[0]} is chosen for {', '.join(uncovered[:5])}"
            return _answer(job, cj.UNAVAILABLE, words, clock)
        if selection.left_out:
            words = f"{len(selection.left_out)} test file(s) that cover this change are past the cap of {proof.CAP}"
            return _answer(job, cj.UNAVAILABLE, words + "; it needs its card", clock)
        chosen = list(dict.fromkeys([*selection.files, *job.tests]))
        # Every run's data goes in a folder of its own beside the two copies, never inside one: clutter in the base
        # checkout could only make the base fail, and a failure on the base excuses a regression (review, B4). Every
        # run reads only its copy's own pytest config, and a shard that collected nothing did not run (review, B3). With
        # *folder*, a chosen file its shard's report holds no case for did not run either: a covering test emptied by
        # the change never stands behind a pass that other files' cases made (from Codex's lineage of this fix).
        run = tools.run_tests(work, chosen, python=python, data_dir=place / "data-run", shard_workers=WORKERS,
                              deadline=deadline, config=work / CONFIG, require_cases=True, folder=True,
                              strict_report=True)  # fmt: skip
        counts = {"ran": sum(1 for rel in chosen if (work / rel).is_file()), "seen": run.seen}
        # The report is written by thomas-runner, the identity whose change is checked (review B1, Finding A). A report
        # a crashed process left, or one carrying cases for files the checker did not select, is not evidence the
        # change passed: FAILED, never a pass. The other defences are the account's own: the runner may write only its
        # job's work/base trees, and the launcher harvests each report to a folder it alone can write (enable_window).
        if run.crashed:
            words = f"a test process did not finish as a run but left a report: {', '.join(sorted(run.crashed)[:3])}"
            return _answer(job, cj.FAILED, words, clock, **{**counts, "failed": tuple(run.failed)})
        if run.unexpected:
            words = f"the test report carried cases for files the checker did not run: {', '.join(sorted(run.unexpected)[:3])}"
            return _answer(job, cj.FAILED, words, clock, **{**counts, "failed": tuple(run.failed)})
        if not run.ran:
            return _answer(job, cj.UNAVAILABLE, run.why or "the tests did not run to the end", clock, **counts)
        if not run.seen:
            return _answer(job, cj.UNAVAILABLE, "no test ran: the run's reports hold no test", clock, **counts)
        verdict = tools.confirm(
            run.failed,
            rerun_with_change=lambda test: tools.run_one(
                work, test, python=python, data_dir=place / "data-again", deadline=deadline, config=work / CONFIG
            ),
            rerun_on_base=lambda test: tools.run_one(
                base, test, python=python, data_dir=place / "data-base", deadline=deadline, config=base / CONFIG
            ),
        )
        boot_code, boot = _boot(work, python, place / "data-boot", tools.run)
        # A regression is a test that fails alone with the change and not without it, or a failing test the change
        # brought. A failure no re-run could settle (unconfirmed, timed out, never started: the pool gave its re-run no
        # place) is the checker's own trouble, not the change's: UNAVAILABLE, tried again, never a FAILED that sends a
        # good change back, and never a pass either (review B5, plan Task 36). A boot check that did not finish is the
        # same: it says nothing about whether Thomas starts.
        regressions = verdict.findings + verdict.added
        unsettled = verdict.unconfirmed + verdict.timed_out + verdict.not_started
        found = {**counts, "failed": tuple(run.failed), "findings": tuple(regressions), "boot": boot}
        if boot_code in _BOOT_UNSETTLED:
            words = f"the boot check did not finish ({boot}); the checker retries"
            return _answer(job, cj.UNAVAILABLE, words, clock, **{**found, "boot": ""})
        if boot:
            return _answer(job, cj.FAILED, f"Thomas no longer starts with this change: {boot}", clock, **found)
        if regressions:
            words = f"{len(regressions)} test(s) fail alone with the change and not without it"
            return _answer(job, cj.FAILED, words, clock, **found)
        if unsettled:
            words = f"{len(unsettled)} failure(s) could not be settled by a re-run on their own; the checker retries"
            return _answer(job, cj.UNAVAILABLE, words, clock, **found)
        return _answer(job, cj.PASSED, "", clock, **found)
    finally:
        _remove(place)


__all__ = ["BOOT_IMPORTS", "JOB_DEADLINE_S", "WORKERS", "CopyFailed", "Tools", "boot_problem", "make_copy", "run_job"]
