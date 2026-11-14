"""Check a finished change before its card is shown to you, the way it was checked by hand.

You said it plainly on 2026-09-25: "Every change you make to yourself reaches my Windows sign-in card
with nothing on it that says whether it was checked. Tonight every hand-in was checked by hand before I
saw its card, and 9 of 10 checks found something real... I want you to check every change yourself before
its card is shown to me."

:func:`check_before_card` is that check, in the order you described it:

1. Take the change's patch and the dev commit the promoter will re-derive it against.
2. Apply it with ``git apply --3way`` to a scratch copy of that dev. A conflict is a finding.
3. Run the tests that cover it on that copy, once -- the change's own test files, ``tests/test_architecture.py``,
   and every test file that imports a module the change touches -- in shards across the machine's pool.
4. Re-run each failure on its own, with the change and then on an unpatched copy of the same dev: only a failure
   that fails alone with the change and passes alone on dev counts. Dev runs in full only when the change's run did
   not finish, had more than 40 failures, or left failures no re-run on its own could settle, to tell a broken dev
   from a broken change. Failures dev is known to have (:mod:`~thomas.server.precard.known`) are re-run last; that
   record only orders the re-runs and never excuses a failure.
5. Run ``ruff check`` and ``ruff format --check`` on the changed files, counting only what is new.
6. Apply the repo's size rule.

Three answers, and the third is the one that keeps this honest. :data:`PASSED` shows the card, and the
card says what passed. :data:`FAILED` never reaches you: ``settle_if_finished`` raises
:class:`ChangeFailedCheck` and the change goes back to its team as a repair round with these findings,
the same way ``POST /api/self/projects/{id}/send-back`` sends one back -- except a change that will not
apply to dev, which raises :class:`ChangeDoesNotApply` and goes back the way a promoter's dev-moved
refusal does, with dev merged into its copy first. :data:`UNAVAILABLE` means the
check itself could not run. Unless it was intentionally turned off or the change is empty,
Thomas holds the change before your card instead of claiming it was checked.

The proof step -- which tests, run them in shards, read JUnit by test id, confirm each failure alone --
is :mod:`thomas.server.proof`, kept separate on purpose so the ratchet can call it once it lands.

Checks are admitted side by side against the reservation ledger every server on this machine shares
(:mod:`thomas.server.capacity_ledger`): each reserves :data:`CHECK_DISK_BYTES` on the greens' drive, waits at most
:data:`ADMISSION_WAIT_S` for its turn and its room, and then runs within :data:`CHECK_DEADLINE_S`; one the ledger does
not admit is held without a strike. Their pytest shards take places in one pool shared by every check on this machine
(:mod:`~thomas.server.precard.pool`) and collect the tests folder with a selection file;
``THOMAS_PRECARD_PARALLEL=off`` runs them as before, one check at a time and only with room on the disk
(:mod:`~thomas.server.precard.slot`); both servers need the same setting. A check that runs out of time is
:data:`UNAVAILABLE`, never passed and never failed, and a strike unless its tests spent longer waiting for a place
in the pool than running (:func:`_out_of_time`). A check whose shard or re-run on its own the pool gave no
place (on either copy) is never passed: it
is held for another try (:data:`UNAVAILABLE`, cause ``busy``, no strike) unless something proven on its own fails it,
such as a regression re-run alone, a ruff finding or a size problem, which still send the change back.
:attr:`Checked.patch` is the exact patch that was checked. The hand-in hands in those bytes and no others
(:mod:`~thomas.server.precard.handover`).
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import hashlib
import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from thomas.core import cage_account, machine_capacity
from thomas.core.green_place import GREEN_AGENT_ID
from thomas.server import capacity_ledger, green_checkout, green_handoff
from thomas.server import proof as proofs
from thomas.server.precard import clocks, known, lint, pool, report, review_job, scratch, slot, workers

log = logging.getLogger(__name__)

PASSED, FAILED, UNAVAILABLE = "passed", "failed", "unavailable"
# Set to "off" or "0" to skip checks in local tests. This intentional skip is disclosed on the card.
# Also set inside the check's own sandbox, so nested tests do not start another check.
CHECK_ENV = "THOMAS_PRECARD_CHECK"
_OFF = frozenset({"off", "0", "false", "no"})
# The most one check may take, from its first copy of dev to its last ruff call. The real check measured on
# 2026-09-25 took 1,321 s for 60 test files. Before this the step limits added up to about 24,600 s.
CHECK_DEADLINE_S = (
    365 * 24 * 3600.0
)  # never: a check is not cut off for being slow (the owner: no time limits); elapsed time is shown
# Held checks are reused only in this format. Format 3 ran every covering file past the cap as well: from
# 2026-10-27 each check chose 1,892 to 1,961 files, close to the whole suite, and none finished inside its limit, so
# nothing reached your card. Format 4 runs the cap again and the card names the covering files it did not run.
CHECK_FORMAT = 4
MEASURED_CHECK_DISK_PEAK_BYTES = 484900864
# Dev's tracked files measured 0.12 GiB per scratch copy on 2026-09-25. The patched copy is
# always made; the unpatched dev baseline is made only when comparison is needed. Allow room for pytest's files.
CHECK_DISK_FLOOR_BYTES = 512 * 1024**2


def check_disk_bytes(measured_peak_bytes: int) -> int:
    """Reserve at least the scratch floor, or the measured peak plus a quarter, rounded up."""
    return max(CHECK_DISK_FLOOR_BYTES, (5 * measured_peak_bytes + 3) // 4)


# Reserve 1.25 times Step 0's measured peak (484,900,864 bytes), rounded up, or at least 512 MiB.
# Part 1 measured one check alone at 234,852,352 bytes with 57 test files and 331,620,352 with 44.
CHECK_DISK_BYTES = check_disk_bytes(MEASURED_CHECK_DISK_PEAK_BYTES)
NO_ROOM_PHRASE = "there was no room to check it"
# The longest a check waits for its turn and its room before it is held, unchecked, without a strike.
ADMISSION_WAIT_S = CHECK_DEADLINE_S
# The cap the earlier runner could carry within CHECK_DEADLINE_S; THOMAS_PRECARD_PARALLEL=off keeps it.
SERIAL_CAP = 120
# Checks side by side share the pool's P places. Admitted without a limit, six at once each got under three of sixteen,
# none finished within the hour, and all were tried again for hours (2026-10-23, up to 31 tries each). A check now
# waits for its turn until it can have about this many places, and two may always run side by side.
PLACES_PER_CHECK = 6


def check_limit(places: int) -> int:
    """How many checks may hold a turn at once beside a pool of *places*."""
    return max(2, int(places) // PLACES_PER_CHECK)


def _cap(shared: bool | None = None) -> int:
    """The covering-test cap: :data:`proofs.CAP` with the pool on, :data:`SERIAL_CAP` off (*shared* as read once)."""
    return proofs.CAP if (pool.parallel() if shared is None else shared) else SERIAL_CAP


def patch_sha256(patch: str) -> str:
    """The sha256 of *patch* as the bytes git wrote, which is also how the promoter's manifest hashes it."""
    return hashlib.sha256(patch.encode("utf-8", errors="surrogateescape")).hexdigest()


class ChangeFailedCheck(RuntimeError):
    """The check before your card found something real, so the change is not handed in."""


class ChangeDoesNotApply(ChangeFailedCheck):
    """The change will not apply to the dev it would land on: its repair round starts with dev merged in.

    Caught as a :class:`ChangeFailedCheck` everywhere that only needs to know the check failed.
    """


@dataclass(frozen=True)
class Checked:
    """What the check found: where it stands, the one line the card carries, and the findings for its team.

    ``patch`` is the change exactly as the check read it, and ``patch_sha256`` its hash. Both are "" when the
    check stopped before it read the change. ``dev_moved`` is True when it failed because the change will not
    apply to that dev. ``cause`` identifies why an unavailable check did not run; ``costly`` marks unavailable
    checks that should count as a strike, rather than an intentional skip, a low-disk deferral, a check, shard or
    re-run the ledger gave no turn or place, or a check out of time whose tests waited longer than they ran (``busy``),
    or a change whose own tests ran while dev itself is the
    problem (cause ``dev-side``: dev's own run did not finish, or fails what no re-run on its own could settle). The
    check's own machinery failing -- the change's copy, an interpreter or a pytest that would not start, the dev tip
    or a scratch copy of dev it could not get -- is ``incomplete`` and a strike, whatever dev does.
    """

    state: str
    line: str
    findings: str = ""
    patch: str = ""
    patch_sha256: str = ""
    dev_moved: bool = False
    cause: str = ""
    costly: bool = False
    dev_tip: str = ""
    format: int = CHECK_FORMAT  # held_check reuses only a check of the current format

    @property
    def failed(self) -> bool:
        return self.state == FAILED


def _unavailable(why: str, *, cause: str, costly: bool) -> Checked:
    return Checked(UNAVAILABLE, report.not_checked(why), cause=cause, costly=costly)


def turned_off() -> bool:
    return str(os.environ.get(CHECK_ENV) or "").strip().lower() in _OFF


def check_before_card(execution_id: str, *, files: list[str] | None = None) -> Checked:
    """Check the change in green *execution_id* against the dev it will land on. Blocking; never raises.

    Never raises on purpose. This runs inside ``settle_if_finished``; a failed check sends the change
    for repair, while an unavailable check is held before any card is created.

    Checks are admitted side by side against the machine-wide ledger (:func:`_admitted`, which times the wait for a
    turn and the turn itself); with ``THOMAS_PRECARD_PARALLEL=off`` one runs at a time (:func:`slot.one_at_a_time`) and
    a second caller waits here.
    """
    if turned_off():
        checked = _turned_off(execution_id)
        clocks.note("check_state", checked.state)
        return checked
    shared = pool.parallel()  # read once for the whole check, and passed on
    clocks.note("parallel", shared)
    try:
        if shared:
            checked = _decide(execution_id, files, shared)
        else:
            waiting, tick = time.time(), time.monotonic()
            with slot.one_at_a_time():
                clocks.span("slot_wait", waiting, time.time(), seconds=time.monotonic() - tick)
                with clocks.stage("in_slot"):
                    checked = _decide(execution_id, files, shared)
    except Exception as exc:
        # Broad catch: this hand-in boundary holds any ordinary checker fault for repair, never a card.
        log.exception("the check before the card for green %s could not run", execution_id)
        checked = _unavailable(f"it could not run: {exc}", cause="unexpected", costly=True)
    clocks.note("check_state", checked.state)
    clocks.note("check_cause", checked.cause)
    # The only lasting copy of why a check held a change: its hold row is dropped once the change settles.
    clocks.note("check_line", checked.line[:2000])
    return checked


def _turned_off(execution_id: str) -> Checked:
    """The intentional skip: the change's own bytes, read once, so what is handed in is what was read."""
    try:
        green = green_checkout.find_green(str(execution_id))
        patch = green_checkout.green_patch(green) if isinstance(green, green_checkout.Green) else ""
    except (green_checkout.GreenUnavailable, OSError, subprocess.SubprocessError) as exc:
        return _unavailable(f"the change itself could not be read: {exc}", cause="incomplete", costly=True)
    if green is None:
        why = f"it is turned off here ({CHECK_ENV}); the change's own copy is gone, so there is nothing to apply"
        return Checked(UNAVAILABLE, report.not_checked(why), cause="off")
    line = report.not_checked(f"it is turned off here ({CHECK_ENV})")
    return Checked(UNAVAILABLE, line, patch=patch, patch_sha256=patch_sha256(patch), cause="off")


def _decide(execution_id: str, files: list[str] | None, shared: bool | None = None) -> Checked:
    """Everything the check needs before it can start, then the check. *shared*: the pool switch, as read once."""
    shared = pool.parallel() if shared is None else shared
    found = green_checkout.find_green(str(execution_id))
    green = found if isinstance(found, green_checkout.Green) else None
    if green is None:
        why = "the change's own copy is gone, so there was nothing to apply"
        return _unavailable(why, cause="incomplete", costly=True)
    if not str(green.blue).strip() or not Path(green.blue).is_dir():
        # Never a relative "" here: `Path("") / ".venv"` would resolve against the server's own working
        # folder and look for an interpreter in whatever happens to be there.
        why = "the checkout this change was copied from could not be found"
        return _unavailable(why, cause="incomplete", costly=True)
    try:
        patch = green_checkout.green_patch(green)
        changed = list(files) if files is not None else green_checkout.changed_paths(green)
    except green_checkout.GreenUnavailable as exc:
        return _unavailable(f"the change itself could not be read: {exc}", cause="incomplete", costly=True)
    if not patch.strip() or not changed:
        return Checked(
            UNAVAILABLE, report.not_checked("the change is empty, so there is nothing to check"), cause="empty"
        )
    python = proofs.interpreter(green.blue)
    if not python:
        why = f"no interpreter to run the tests with (no .venv, and {proofs.PYTHON_ENV} names none)"
        return _unavailable(why, cause="incomplete", costly=True)
    if not (green.blue / proofs.TESTS_DIR).is_dir():
        return _unavailable(
            f"the running copy has no {proofs.TESTS_DIR}/ folder to run", cause="incomplete", costly=True
        )
    tip = green_handoff.dev_tip(str(execution_id))
    if not tip:
        return _unavailable("the commit this change would land on could not be read", cause="incomplete", costly=True)
    if shared:
        checked = _admitted(green, tip, patch, changed, python)
    else:
        checked = _against_dev(green, tip, patch, changed, python, False)
    # The tip the check ran against: _admitted reads it again once its turn comes.
    return dataclasses.replace(checked, patch=patch, patch_sha256=patch_sha256(patch), dev_tip=checked.dev_tip or tip)


def _free_disk() -> int | None:
    """Free disk on the greens' drive now, for the clocks; None when it cannot be read (it never fails a check)."""
    try:
        return capacity_ledger.measure(green_checkout.green_root()).free_disk
    except OSError:
        return None


def _admitted(green: green_checkout.Green, tip: str, patch: str, changed: list[str], python: str) -> Checked:
    """Wait for this check's turn and room in the machine-wide ledger, then check it.

    Its size is the files selected on the green's own tree (its place in line); the tests that run are still selected
    on the copy of dev with the change applied (:func:`_steps`). ``slot_wait`` is the wait for the turn and ``in_slot``
    the turn itself, as with the one-at-a-time lock. Only taking the turn is guarded here: a refusal holds the check
    without a strike, and a ledger that cannot be used gives no turn, as it gives a shard no place (``pool.runner``),
    so a check never runs without its reservation. Dev can move during the wait, so the tip is read again once the turn
    comes, as the one-at-a-time path reads it after the lock, and the answer records the tip it was checked against.
    """
    with clocks.stage("selection_before_admission"):
        files = len(proofs.select(green.work, changed, cap=_cap(True), bumps=proofs.version_bumps(patch)).files)
    clocks.note("admission_files", files)
    queued, tick = time.time(), time.monotonic()
    with contextlib.ExitStack() as turn:
        try:
            turn.enter_context(
                capacity_ledger.admitted(
                    f"check:{green.execution_id}",
                    kind="check",
                    files=files,
                    disk_bytes=CHECK_DISK_BYTES,
                    where=green_checkout.green_root(),
                    limit=check_limit(pool.size()),
                    wait_s=ADMISSION_WAIT_S,
                    watch=workers.stop_if_waiting,
                )
            )
        except capacity_ledger.NotAdmitted as why:  # a RuntimeError: caught here, before the broad handler's strike
            clocks.span("slot_wait", queued, time.time(), seconds=time.monotonic() - tick)
            cause = "busy" if why.waited else "low-disk"
            return _unavailable(f"{NO_ROOM_PHRASE}: {why}", cause=cause, costly=False)
        except OSError as why:  # the drive's free space, or a ledger unreadable, busy or locked too long
            clocks.span("slot_wait", queued, time.time(), seconds=time.monotonic() - tick)
            log.warning("a check was not started: the drive or the reservation ledger could not be read: %s", why)
            unread = f"the drive or the reservation ledger could not be read, so it did not start: {why}"
            return _unavailable(unread, cause="busy", costly=False)
        clocks.span("slot_wait", queued, time.time(), seconds=time.monotonic() - tick)
        clocks.note("free_disk_at_admission_bytes", _free_disk())
        now = green_handoff.dev_tip(green.execution_id)  # dev as it is when the turn comes
        if not now:
            why = "the commit this change would land on could not be read once its turn came"
            return _unavailable(why, cause="incomplete", costly=True)
        clocks.note("dev_moved_while_waiting", now != tip)
        with clocks.stage("in_slot"):
            checked = _against_dev(green, now, patch, changed, python, True)
        return dataclasses.replace(checked, dev_tip=now)


def _against_dev(
    green: green_checkout.Green, tip: str, patch: str, changed: list[str], python: str, shared: bool | None = None
) -> Checked:
    """Make the changed copy first; create dev's baseline on demand and clear up both."""
    with clocks.stage("leftovers"):
        slot.clear_leftovers(2 * CHECK_DEADLINE_S)  # a check that died took nothing with it; one that ran this long did
    no_room = slot.too_little_room(green_checkout.green_root(), disk_bytes=CHECK_DISK_BYTES if shared is False else 0)
    if no_room:
        return _unavailable(f"{NO_ROOM_PHRASE}: {no_room}", cause="low-disk", costly=False)
    deadline = proofs.Deadline(CHECK_DEADLINE_S)
    data = slot.run_folder(green.execution_id)
    with_change = None
    base_copies: list[green_checkout.Green] = []
    result = None
    try:
        with clocks.stage("copies"):
            with_change = scratch.copy_of_dev(green.blue, tip, green.execution_id, scratch.WITH_CHANGE)
        result = _steps(green, tip, patch, changed, python, None, with_change, data, deadline, shared, base_copies)
        return result
    except (green_checkout.GreenUnavailable, subprocess.SubprocessError) as exc:
        return _unavailable(f"a scratch copy of dev could not be made: {exc}", cause="incomplete", costly=True)
    except Exception as exc:
        # Broad catch: scratch work can fail in any checker component; hold it and still remove both copies.
        log.exception("the check before the card for green %s could not finish", green.execution_id)
        return _unavailable(f"it could not finish: {exc}", cause="unexpected", costly=True)
    finally:
        if result is None or result.state in {FAILED, UNAVAILABLE}:
            review_job.cancel_current()
        with clocks.stage("removal"):
            scratch.discard_all(*base_copies, with_change)
            shutil.rmtree(data, ignore_errors=True)


def _shard_workers() -> int:
    """The off path's allowance for the one run of the change: leave CPU and free RAM for Build and the OS."""
    cpus = max(1, os.cpu_count() or 1)
    total, available = machine_capacity._memory()
    clocks.note("total_ram_bytes", total)
    clocks.note("free_ram_bytes", available)
    # Pytest shards consume CPU: cap the machine's estimated run allowance at its CPU count. One run of the change.
    capacity = machine_capacity.estimate(
        cpus=cpus, total_ram_bytes=total, run_budget_mb=machine_capacity.DEFAULT_RUN_BUDGET_MB
    )
    cpu_limit = max(1, min(cpus, capacity))
    if available is None:
        return 1  # Without a free-memory reading, do not start extra pytest processes.
    usable = machine_capacity.usable_memory_bytes(total, available) or 0  # the reserve counted once (spec item 1)
    budget = machine_capacity.DEFAULT_RUN_BUDGET_MB * 1024**2
    memory_limit = max(1, usable // budget)
    return min(cpu_limit, memory_limit)


def _width(shared: bool | None = None) -> int:
    """How many pytest processes each run of this check may use.

    With the pool on, the machine-wide P (:func:`pool.size`): every shard still takes a place in the ledger first, so
    the checks of both servers together never run more than P. With it off, :func:`_shard_workers`.
    *shared* is whether the pool is on, as the caller read it once (:func:`pool.parallel` when not given).
    """
    if not (pool.parallel() if shared is None else shared):
        return _shard_workers()
    total, available = machine_capacity._memory()
    clocks.note("total_ram_bytes", total)
    clocks.note("free_ram_bytes", available)
    return pool.size(total_ram_bytes=total)


def _timed_tests(stage: str, *args: object, **kwargs: object) -> proofs.ProofRun:
    with clocks.stage(stage):
        return proofs.run_tests(*args, **kwargs)


def _dev_side(after: proofs.ProofRun, on_dev: proofs.ProofRun) -> str:
    """Why dev itself, not the change, stops the check; "" when dev ran and the change's trouble is its own."""
    if not on_dev.ran:
        where = "on dev itself" if after.ran else "with this change or on dev itself"
        return f"the same tests did not run to the end {where}: {on_dev.why}"
    if after.ran and len(after.failed) > proofs.RERUN_CAP and set(after.failed) <= set(on_dev.failed):
        return (
            f"{len(after.failed)} tests failed with this change, more than the {proofs.RERUN_CAP} a check settles "
            "one at a time, and dev itself fails every one of them"
        )
    return ""


def _only_unsettled(verdict: proofs.Verdict) -> bool:
    """Nothing was found against the change, and some failures could not be settled by a re-run on its own."""
    return bool(verdict.unconfirmed) and not (verdict.findings or verdict.added or verdict.timed_out)


def _only_dev_leftovers(verdict: proofs.Verdict, on_dev_failed: frozenset[str]) -> bool:
    """Nothing was found against the change, and every failure left unsettled fails in dev's own run too."""
    return _only_unsettled(verdict) and set(verdict.unconfirmed) <= on_dev_failed


def _after_a_refusal(
    tip: str,
    verdict: proofs.Verdict,
    linted: lint.LintResult,
    size: list[str],
    runs: tuple[tuple[str, proofs.ProofRun], ...],
) -> Checked:
    """The answer when the pool gave some shard or re-run no place, on either copy: what was proven alone still counts.

    A regression, a failing test the change adds, a ruff finding and a size problem come from tests re-run on their own
    on both copies and from the files themselves, never from the shard or re-run that did not start, so they still send
    the change back. What leans on the incomplete runs (a failure nobody could settle, a re-run that timed out, a run
    that broke) does not: with none of the first kind the check is held for another try (``busy``), never failed on it,
    never passed, and no strike.
    """
    sure = dataclasses.replace(verdict, unconfirmed=(), timed_out=(), not_started=())
    said = [f"{side}: {run.not_started_why or run.why}" for side, run in runs if run.not_started]
    if verdict.not_started:
        said.append(f"{len(verdict.not_started)} re-run(s) on their own got no place in the pool of test processes")
    refusals = "; ".join(said)
    count = len(sure.blocking) + len(linted.added) + len(linted.unformatted) + len(size)
    if count:
        note = f"Some of the tests could not be started ({refusals}), so only what was proven on its own is listed."
        findings = report.findings_text(tip, sure, linted, size, settled=report.rerun_words(verdict))
        return Checked(FAILED, report.line_failed(tip, count), f"{findings}\n\n{note}")
    why = f"some of the tests could not be started, so not everything could be compared ({refusals})"
    return _unavailable(why, cause="busy", costly=False)


def _held_for_dev(
    tip: str, why: str, settled: str, linted: lint.LintResult, size: list[str], *, costly: bool
) -> Checked:
    """The answer when the change's tests cannot be judged: dev itself is the problem (no strike), or the change's own
    pytest would not launch (*costly*: the check's own machinery, a strike).

    ruff and the size rule read the change's own files, never its tests, so what they find still sends the change back,
    as :func:`_after_a_refusal` does with what was proven on its own. *settled* says how far its failures got.
    """
    count = len(linted.added) + len(linted.unformatted) + len(size)
    if count:
        findings = report.findings_text(tip, proofs.Verdict((), (), (), (), ()), linted, size, settled=settled)
        return Checked(
            FAILED, report.line_failed(tip, count), f"{findings}\n\nIts tests were not counted against it: {why}."
        )
    return _unavailable(why, cause="incomplete" if costly else "dev-side", costly=costly)


def _out_of_time(deadline: proofs.Deadline, waits: pool.Waits | None) -> Checked:
    """The answer when the check's deadline passed: a strike when its tests had the time, none when they mostly waited.

    *waits* sums what the check's shards and re-runs spent waiting for a place and running (:class:`pool.Waits`). When
    its tests spent longer waiting for a place in the shared pool than running, the change is held for another try
    without a strike (cause ``busy``) instead of paying for a full pool. With the pool off nothing waits for a place.
    """
    if waits is not None:
        clocks.note("pool_wait_s", round(waits.waited_s, 3))  # summed over its test processes: it can pass the hour
        clocks.note("pool_run_s", round(waits.ran_s, 3))
        if waits.mostly_waited():
            why = f"{deadline.words()}: its tests spent longer waiting for a place in the shared pool than running"
            return _unavailable(why, cause="busy", costly=False)
    return _unavailable(deadline.words(), cause="deadline", costly=True)


def _steps(
    green: green_checkout.Green,
    tip: str,
    patch: str,
    changed: list[str],
    python: str,
    base: green_checkout.Green | None,
    with_change: green_checkout.Green,
    data: Path,
    deadline: proofs.Deadline,
    shared: bool | None = None,
    base_copies: list[green_checkout.Green] | None = None,
) -> Checked:
    """Apply the patch, run the covering tests once with it, confirm each failure alone on both copies, then lint.

    *shared* is the pool switch as the check read it once (:func:`pool.parallel` when not given)."""
    shared = pool.parallel() if shared is None else shared
    with clocks.stage("apply"):
        conflict = scratch.apply_change(with_change, patch)
    if conflict:
        return Checked(FAILED, report.line_failed(tip, 1), report.conflict_findings(tip, conflict), dev_moved=True)

    with clocks.stage("check_size_rule"):
        size = green_handoff.size_problems(green.execution_id)
    bumps = proofs.version_bumps(patch)
    with clocks.stage("selection"):
        chosen = proofs.select(with_change.work, changed, cap=_cap(shared), bumps=bumps)
    clocks.note("selected_files", len(chosen.files))
    clocks.note("version_bumps", sorted(bumps))
    # As the cage account the tests carry the green id, as check.run's do: tests/conftest.py then reports the caged
    # server's own writes to its data instead of failing the session for them, and still fails a test that opens it.
    # Without it every long check ended "pytest exit 1 contradicts its report" and was held (4b24de, 2026-10-27).
    as_green = {"THOMAS_AGENT_ID": GREEN_AGENT_ID} if cage_account.running_as_cage_account() else {}
    common = {"python": python, "extra_env": {CHECK_ENV: "off", **as_green}, "deadline": deadline}
    workers = _width(shared)
    clocks.note("shard_workers", workers)
    clocks.note("parallel", shared)
    # The pool and folder collection are on together, or neither: THOMAS_PRECARD_PARALLEL=off is the earlier runner.
    measurements: list[dict[str, object]] = []
    tests: dict[str, object] = {"shard_workers": workers, "folder": shared, "measurements": measurements, **common}
    waits = pool.Waits() if shared else None  # what its shards and re-runs spent waiting for places, and running
    if shared:
        tests["run"] = pool.runner(deadline, files=len(chosen.files), waits=waits)
    try:
        after = _timed_tests("change_run", with_change.work, chosen.files, data_dir=data / "change", **tests)
    finally:
        clocks.note("change_shards", sorted(measurements, key=lambda item: int(item["shard"])))
        if waits is not None:
            clocks.note("pool_wait_s", round(waits.waited_s, 3))
            clocks.note("pool_run_s", round(waits.ran_s, 3))
    clocks.note("change_tests_seen", after.seen)
    if not after.ran:
        # Dev is run in full only because of this, and the check's own sentence then names dev's trouble alone: on
        # 2026-11-10 eleven checks had ended "dev-side" and none of their records said why the change's run stopped.
        clocks.note("change_run_why", after.why[:2000])
    clocks.note("shards_per_side", after.shards)
    clocks.note("free_disk_after_run_bytes", _free_disk())

    def record_pool() -> None:
        if waits is not None:
            clocks.note("pool_wait_s", round(waits.waited_s, 3))
            clocks.note("pool_run_s", round(waits.ran_s, 3))

    record_pool()
    if after.out_of_time:
        return _out_of_time(deadline, waits)
    runs: list[tuple[str, proofs.ProofRun]] = [("with the change", after)]

    copy_context = contextvars.copy_context()
    copy_lock = threading.Lock()

    def make_base() -> green_checkout.Green:
        nonlocal base
        if base is None:
            with clocks.stage("base_copy"):
                base = scratch.copy_of_dev(green.blue, tip, green.execution_id, scratch.BASE)
            if base_copies is not None:
                base_copies.append(base)
        return base

    def dev_copy() -> green_checkout.Green:
        with copy_lock:
            return copy_context.run(make_base)

    def on_dev() -> tuple[Checked | None, str, frozenset[str]]:
        """The same tests on dev in full: an answer now (out of time), why dev itself is the problem, and what failed.

        A dev shard the pool gave no place says nothing about dev: no reason is given then, and the refusal holds the
        check (:func:`_after_a_refusal`).
        """
        dev_measurements: list[dict[str, object]] = []
        try:
            work = dev_copy().work
            # The change's own new test files are not on dev, and a missing file stops a run before it starts: every
            # such dev run "did not run to the end" and the check blamed dev (3603b9, 2026-10-27). Dev runs the rest.
            added = {rel for rel in changed if not (Path(work) / rel).is_file()}
            run = _timed_tests(
                "dev_run",
                work,
                tuple(rel for rel in chosen.files if rel not in added),
                data_dir=data / "base",
                **{**tests, "measurements": dev_measurements},
            )
        finally:
            clocks.note("dev_shards", sorted(dev_measurements, key=lambda item: int(item["shard"])))
            record_pool()
        clocks.note("dev_tests_seen", run.seen)
        if not run.ran:
            clocks.note("dev_run_why", run.why[:2000])
        runs.append(("on dev", run))
        if run.out_of_time:
            return _out_of_time(deadline, waits), "", frozenset()
        return None, ("" if run.not_started else _dev_side(after, run)), frozenset(run.failed)

    hint = known.key(dev_copy(), python, common["extra_env"]) if after.failed else ""
    known_on_dev: frozenset[str] = known.read(hint)  # an order only: it never excuses
    on_dev_failed: frozenset[str] | None = None
    # Why the change's tests are not judged ("" while they are): dev itself, or the check's own machinery.
    untested = ""
    if after.not_launched:  # its own pytest would not start: the check's machinery, a strike, whatever dev does
        untested = f"the change's own test process would not start: {after.why}"
    elif not after.not_started and (not after.ran or len(after.failed) > proofs.RERUN_CAP):
        # The change's run did not finish, or failed widely: dev in full tells a broken dev from a broken change. Not
        # when the pool gave the change's run no place: that holds the check whatever dev says (_after_a_refusal).
        stop, untested, on_dev_failed = on_dev()
        if stop is not None:
            return stop
        known_on_dev = known_on_dev | on_dev_failed

    def alone(work: Callable[[], Path], tag: str) -> Callable[[str], str]:
        one = {"run": pool.runner(deadline, files=1, record_peaks=False, waits=waits)} if shared else {}

        return lambda test: proofs.run_one(work(), test, data_dir=data / tag, **one, **common)

    verdict = proofs.Verdict((), (), (), (), ())
    settled = "Its failures were not re-run on their own."
    if not untested:  # with dev itself or the check's machinery the problem, no failure is settled against it
        try:
            with clocks.stage("confirm"):
                verdict = proofs.confirm(
                    after.failed,
                    rerun_with_change=alone(lambda: with_change.work, "one-change"),
                    rerun_on_base=alone(lambda: dev_copy().work, "one-base"),
                    known_on_dev=known_on_dev,  # an order only: nothing is excused by dev's run
                    workers=workers,
                    # an excuse found beside other re-runs is settled once more on dev, in a sandbox of its own
                    again_on_base=alone(lambda: dev_copy().work, "one-base-again"),
                )
        finally:
            record_pool()
        known.remember(hint, verdict.excused)  # each confirmed failing alone on this dev
        settled = report.rerun_words(verdict)
        no_place = bool(after.not_started or verdict.not_started)  # a shard or re-run with no place proved nothing
        if not no_place and on_dev_failed is None and _only_unsettled(verdict):  # failures no re-run settled: dev's?
            stop, untested, on_dev_failed = on_dev()
            if stop is not None:
                return stop
    refused = bool(after.not_started or verdict.not_started) or any(run.not_started for _side, run in runs)
    leftovers = after.ran and on_dev_failed is not None and _only_dev_leftovers(verdict, on_dev_failed)
    # What no re-run on its own settled, dev's own run fails too: dev's trouble, not the change's.
    if leftovers and not (untested or refused):
        untested = (
            f"{len(verdict.unconfirmed)} of the {len(after.failed)} tests that failed with this change could not be "
            "settled by a re-run on its own, and every one of them fails in dev's own run too"
        )
    with clocks.stage("ruff"):
        linted = lint.ruff_findings(lambda: dev_copy().work, with_change.work, changed, data_dir=data, **common)
    if deadline.passed:  # a verdict or a ruff answer cut short by the clock is not an answer
        return _out_of_time(deadline, waits)
    if untested:  # a change whose own pytest would not launch is the check's machinery, never dev's: a strike
        return _held_for_dev(tip, untested, settled, linted, size, costly=bool(after.not_launched))
    if refused:
        return _after_a_refusal(tip, verdict, linted, size, tuple(runs))
    broke_the_run = "" if after.ran else after.why
    problems = report.findings_text(tip, verdict, linted, size, broke_the_run, details=dict(after.details))
    if problems:
        count = len(verdict.blocking) + len(linted.added) + len(linted.unformatted) + len(size) + bool(broke_the_run)
        return Checked(FAILED, report.line_failed(tip, count), problems)
    return Checked(PASSED, report.line_passed(tip, chosen.files, after, verdict, linted, size, chosen.left_out))


__all__ = [
    "ADMISSION_WAIT_S",
    "CHECK_DEADLINE_S",
    "CHECK_DISK_BYTES",
    "CHECK_ENV",
    "CHECK_FORMAT",
    "FAILED",
    "MEASURED_CHECK_DISK_PEAK_BYTES",
    "PASSED",
    "PLACES_PER_CHECK",
    "UNAVAILABLE",
    "ChangeDoesNotApply",
    "ChangeFailedCheck",
    "Checked",
    "check_before_card",
    "check_limit",
    "patch_sha256",
]
