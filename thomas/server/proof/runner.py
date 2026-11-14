"""Run a proof set in a copy, in shards, and read the failures back by test id.

One pytest process per shard, each with its own JUnit report, each in the sandbox
:mod:`thomas.server.proof.environment` builds. Shards exist for two reasons: a report per shard survives a
process that dies on one file, and a shard is the unit the cage runner can carry when a proof runs as the
caged account. The ratchet's design asks for its candidates to be run the same way (§3: ``.venv`` Python,
``-p no:cacheprovider``, failing ids from a JUnit report), which is what this does. How a command is run is
the caller's to choose (``run``): the card check runs it here, and the ratchet can pass one that runs it in
the cage.

A run that could not happen is never reported as a pass. ``ProofRun.ran`` is False and ``why`` says what
stopped it -- an interpreter that would not start, a session that timed out, no report on disk, the whole
proof's :class:`~thomas.server.proof.deadline.Deadline` spent (``out_of_time``) -- and the caller decides
what that means: for the base copy it means nothing can be compared, for the copy with the change it means
the change broke the run, and out of time means the proof did not finish. A shard the pool gave no place
(:data:`~thomas.server.proof.environment.REFUSED`) is none of these: it never started, so it proved nothing about
the change. ``ProofRun.not_started`` names its files and the caller holds the check for another try.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from thomas.core import machine_load
from thomas.server.proof import deadline as clock
from thomas.server.proof import junit, scheduling
from thomas.server.proof.environment import NOT_STARTED, REFUSED, TIMED_OUT, run_quietly, sandbox_env
from thomas.server.proof.selection import TESTS_DIR

_log = logging.getLogger(__name__)
# Test files per pytest process.
SHARD_FILES = 12


def _cpu_busy() -> bool:
    """This PC's CPU is at or above its load limit by the last reading (no wait): split into only the shards needed.

    The CPU is read directly, also under the caged server's hard CPU cap, where ``machine_load.over_limit`` leaves CPU
    out: there extra shards share one fixed CPU budget. A limit of 0 (the test suite's own) never counts as busy.
    """
    cap = machine_load.limit()
    now = machine_load.latest()
    return cap > 0 and now is not None and now.cpu >= cap


# A guard against a shard that hangs, inside the check's own hour. At 900 s it cut shards that were only slow: the four
# test_a_shared_card_* files take about 250 s each (124 git calls a test) and sort into one shard, which then failed on
# dev too and held every change that selected it (2026-10-23).
SHARD_TIMEOUT_S = 1800.0
ONE_TEST_TIMEOUT_S = 180.0
# pytest's own exits that still mean "the session ran and said what it found": all passed, some failed,
# nothing was collected. Anything else (interrupted, internal error, usage error) is a run that did not
# happen, unless it still managed to write a report.
_RAN = (0, 1, 5)
_NOTHING_COLLECTED = 5
PASSED, FAILED, MISSING, UNKNOWN = "pass", "fail", "missing", "unknown"
# A test re-run on its own that did not finish in time. Not a failure and not a pass: nobody knows which it is.
TIMEOUT = "timeout"
# A test re-run on its own that the pool gave no place (:data:`REFUSED`): it never started, so it proved nothing. Apart
# from UNKNOWN, which is a re-run that started and could not answer.
NO_PLACE = "no place"
# How a command is run: ``run(command, cwd=..., env=..., timeout_s=...) -> (exit code, output)``, the shape of
# :func:`~thomas.server.proof.environment.run_quietly`, which is the default.
Run = Callable[..., tuple[int, str]]
# The collection plugin of spec 2026-10-12 Part 1 item 7: always the running server's own file, never the copy's.
PLUGIN_FILE = Path(__file__).resolve().parents[3] / "scripts" / "fast_tests_plugin.py"
SELECT_OPTION = "--fast-tests-select"
# ``python -c`` with the server's scripts folder first on sys.path for one plain import, then gone again, so the copy's
# own ``import fast_tests_plugin`` (its tests have one) still finds the copy's file. Single quotes only.
_BOOT = (
    "import os,sys;"
    "sys.path[0:1]=[os.getcwd()] if sys.path[:1]==[''] else sys.path[0:1];"
    "sys.modules.pop('fast_tests_plugin',None);sys.path.insert(0,sys.argv[1]);"
    "import fast_tests_plugin as m;"
    "sys.path.remove(sys.argv[1]);sys.modules.pop('fast_tests_plugin',None);"
    "import pytest;raise SystemExit(pytest.main(sys.argv[2:],plugins=[m]))"
)


def _plugin_bytes() -> bytes | None:
    try:
        return PLUGIN_FILE.read_bytes()
    except OSError:
        return None


# Read once, when this module is imported: every check this process runs collects with the plugin the server started
# with, so a change to scripts/fast_tests_plugin.py that lands reaches the checks only when the servers restart.
_PLUGIN = _plugin_bytes()


@dataclass(frozen=True)
class ProofRun:
    """What one proof of one copy found."""

    ran: bool
    why: str
    failed: tuple[str, ...]
    seen: int
    shards: int
    out_of_time: bool = False
    unrun: tuple[str, ...] = ()  # named files a folder shard's report holds no case for (never dropped silently)
    # Files of the shards the pool refused a place (:data:`REFUSED`: its ledger could not be used, so the shard never
    # started), and the words of that refusal. Such a shard proved nothing, so it is neither a failure of the change nor
    # a pass. A command that would not launch (``NOT_STARTED``) is not this: it keeps ``ran`` False and its ``why``.
    not_started: tuple[str, ...] = ()
    not_started_why: str = ""
    # Files of the shards whose command would not launch (``NOT_STARTED``): the machinery of whoever ran the proof
    # failed, never the tests of the copy and never the pool.
    not_launched: tuple[str, ...] = ()
    # Only under *strict_report* (the window's checker): a report the run cannot trust, because the test identity that
    # wrote it is the one whose change is being checked (review B1, Finding A). ``crashed`` names the shards whose
    # process did not exit as a completed pytest run (killed, crashed, a non-pytest exit) yet left a report -- a report
    # a crashed process left is never read as a pass. ``unexpected`` names modules a report carried cases for that were
    # not among the files the shard was asked to run -- a report that invents cases for files the checker did not
    # select. Either one makes the checker answer FAILED, never PASSED.
    crashed: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    # Each failed test's own words from its shard's report (``junit.Report.details``), for the send-back.
    details: tuple[tuple[str, str], ...] = ()


def _pytest(
    python: str,
    work: Path,
    report: Path,
    targets: Sequence[str],
    *,
    plugin: Path | None = None,
    select: Path | None = None,
    config: Path | None = None,
) -> list[str]:
    # ``xunit1`` keeps each case's ``file`` attribute (``xunit2`` drops it), and a fixed rootdir makes that
    # file and every node id relative to the copy itself -- the same string on the base and on the change.
    # *config*, when given, is the only config file pytest reads: without it pytest uses the nearest one it finds, and a
    # ``tests/.pytest.ini`` a change brings would govern the run (2026-10-14 review, B3).
    if plugin is None and select is not None:
        raise ValueError("a selection file needs the plugin that reads it; without one, name the files")
    head = [python, "-m", "pytest"] if plugin is None else [python, "-c", _BOOT, str(plugin.parent)]
    chosen = [f"{SELECT_OPTION}={select}"] if select is not None else []
    pinned = [f"--config-file={config}"] if config is not None else []
    return [
        *head,
        *pinned,
        "-p",
        "no:cacheprovider",
        "-q",
        "--no-header",
        f"--rootdir={work}",
        "-o",
        "addopts=",
        "-o",
        "junit_family=xunit1",
        "--continue-on-collection-errors",
        f"--junit-xml={report}",
        *chosen,
        *targets,
    ]


def collect_plugin(work: Path, data_dir: Path) -> Path | None:
    """The plugin as this process read it at import, pinned under ``<data_dir>/plugin/<sha256>/``; None without one.

    A copy already there is reused only when it is byte for byte what this process read; anything else (a copy cut
    short by a kill mid-write, another file) is replaced through a temporary name and ``os.replace``, so no run ever
    sees a partial file. None too when the server's own file lies inside the copy under test (the copy never supplies
    the plugin) and when the pin cannot be written: the shards then name their files, as for a plugin that could not
    be read, and the reason is logged.
    """
    if _PLUGIN is None:
        return None
    target = Path(data_dir) / "plugin" / hashlib.sha256(_PLUGIN).hexdigest()[:16] / PLUGIN_FILE.name
    scratch = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        if PLUGIN_FILE.resolve().is_relative_to(Path(work).resolve()):
            return None
        if not (target.is_file() and target.read_bytes() == _PLUGIN):
            target.parent.mkdir(parents=True, exist_ok=True)
            scratch.write_bytes(_PLUGIN)
            os.replace(scratch, target)
    except OSError as error:
        with contextlib.suppress(OSError):
            scratch.unlink(missing_ok=True)
        _log.warning(
            "the check's collection plugin could not be pinned under %s (%s); its shards name their files",
            data_dir,
            error,
        )
        return None
    return target


def _folder_holds(batch: Sequence[str]) -> bool:
    """Whether every file of *batch* is a plain ``tests/**/test_*.py`` the folder collects."""
    return all(
        rel.startswith(f"{TESTS_DIR}/") and "::" not in rel and rel.endswith(".py")
        and rel.rsplit("/", 1)[-1].startswith("test_")
        for rel in batch
    )  # fmt: skip


def _shards(files: Sequence[str], size: int) -> list[list[str]]:
    return [list(files[start : start + size]) for start in range(0, len(files), size)]


def _unexplained(output: str) -> str:
    """What pytest's own output gives for an exit its report does not explain: tests/conftest.py's real-data findings,
    else its last error line; "" when there is neither. d79480's hold said only "pytest exit 1 contradicts its report"
    (2026-10-28), and the reason was in the run's output, which no record kept."""
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "REAL THOMAS DATA ACCESS" in line:
            found = [item for item in lines[index + 1 : index + 4] if " was " in item][:2]
            return "; ".join(found)[:1600]
    errors = [line for line in lines if line.startswith(("INTERNALERROR", "ERROR")) or "Error:" in line]
    return errors[-1][:300] if errors else ""


def _why(code: int, output: str) -> str:
    if code in (TIMED_OUT, NOT_STARTED, REFUSED):
        return output
    return f"pytest exited {code}: {output.strip()[-400:]}"


def run_tests(
    work: Path,
    files: Sequence[str],
    *,
    python: str,
    data_dir: Path,
    shard_files: int = SHARD_FILES,
    shard_workers: int = 1,
    timeout_s: float = SHARD_TIMEOUT_S,
    extra_env: Mapping[str, str] | None = None,
    deadline: clock.Deadline | None = None,
    run: Run = run_quietly,
    folder: bool = False,
    config: Path | None = None,
    require_cases: bool = False,
    strict_report: bool = False,
    measurements: list[dict[str, object]] | None = None,
) -> ProofRun:
    """Run *files* in the copy at *work* and collect failing ids; default to serial shards.

    With *folder*, each shard names the tests folder and a selection file instead of each file, and a shard whose
    report holds no case for a file it named did not run that file: the run did not complete (:attr:`ProofRun.unrun`).
    *config* is the one pytest config file every shard reads (:func:`_pytest`). With *require_cases*, a shard that
    collected no test (pytest's exit 5, or a report with no case) did not run: the run did not complete. The window's
    checker asks for both, so a run that tested nothing is never read as a pass (2026-10-14 review, B3).

    A shard whose process did not exit as a completed pytest run (killed, crashed, any exit outside pytest's own)
    yet left a report is incomplete. With *strict_report*, it is also recorded in :attr:`ProofRun.crashed`, and a
    report carrying cases for files the shard was not asked to run is recorded in :attr:`ProofRun.unexpected`. Neither a crashed
    process's report nor a selected file missing before launch is evidence the change passed.
    """
    selected = list(dict.fromkeys(files))
    missing = tuple(rel for rel in selected if not (Path(work) / rel).is_file())
    if missing:
        return ProofRun(False, "selected test files are missing", (), 0, 0, unrun=missing)
    present = selected
    if not present:
        return ProofRun(True, "", (), 0, 0)
    if shard_workers <= 1:
        env = sandbox_env(Path(work), Path(data_dir), extra_env)
    reports = Path(data_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    batches = scheduling.batches(
        Path(work), present, size=max(1, shard_files), workers=shard_workers, spread=not _cpu_busy()
    )
    pinned = collect_plugin(Path(work), Path(data_dir)) if folder else None  # once per run, before shards start

    def shard(number: int, batch: list[str]) -> tuple[junit.Report | None, int, str, bool]:
        if clock.passed(deadline):
            return None, NOT_STARTED, deadline.words(), True
        report = reports / f"shard-{number}.xml"
        report.unlink(missing_ok=True)
        plugin = pinned if pinned is not None and _folder_holds(batch) else None
        if plugin is not None:
            select = reports / f"shard-{number}.select.json"
            listed = [str(Path(work).absolute() / rel) for rel in batch]
            select.write_text(json.dumps({"files": listed, "dirs": []}), encoding="utf-8")
            command = _pytest(python, Path(work), report, [TESTS_DIR], plugin=plugin, select=select, config=config)
        else:
            command = _pytest(python, Path(work), report, batch, config=config)
        shard_env = sandbox_env(Path(work), Path(data_dir) / f"shard-{number}", extra_env) if shard_workers > 1 else env
        sources = scheduling.snapshot(Path(work), batch)
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                code, output = run(command, cwd=Path(work), env=shard_env, timeout_s=clock.cap(deadline, timeout_s))
            finally:
                if measurements is not None:
                    measurements.append(
                        {"shard": number, "files": list(batch), "seconds": round(time.perf_counter() - started, 3)}
                    )
            read = junit.read_report(report, Path(work))
            # A process that ended and left no report at all died (the test timeout kills it); it proved nothing
            # either way, so it is run once more. On 2026-11-10 one such death on a full PC cost a 59-minute check
            # its answer. A refusal, a launch that failed and a shard out of its own time are not run again here.
            died = read is None and code not in (TIMED_OUT, NOT_STARTED, REFUSED)
            if not died or attempt == 2 or clock.passed(deadline):
                break
            report.unlink(missing_ok=True)
        if read is not None and code in _RAN:
            scheduling.learn(Path(work), batch, report, sources=sources)
        return read, code, output, read is None and code == TIMED_OUT and clock.passed(deadline)

    # Consume in shard order, not completion order: failure ids and trouble summaries remain deterministic.
    if shard_workers > 1:
        with ThreadPoolExecutor(max_workers=min(shard_workers, len(batches))) as pool:
            results = [pool.submit(shard, number, batch) for number, batch in enumerate(batches, start=1)]
            outcomes = [result.result() for result in results]
    else:
        outcomes = []
        for number, batch in enumerate(batches, start=1):
            outcomes.append(shard(number, batch))
            if outcomes[-1][3]:
                break

    failed: list[str] = []
    unrun: list[str] = []
    never: list[str] = []
    refusals: list[str] = []
    unlaunched: list[str] = []
    crashed: list[str] = []
    unexpected: list[str] = []
    seen = 0
    troubles: list[str] = []
    texts: dict[str, str] = {}

    def incomplete(why: str, out_of_time: bool) -> ProofRun:
        found = tuple(dict.fromkeys(failed))
        said = "; ".join(list(dict.fromkeys(refusals))[:3])
        return ProofRun(
            False, why, found, seen, len(batches), out_of_time, tuple(unrun), tuple(never), said, tuple(unlaunched),
            crashed=tuple(dict.fromkeys(crashed)), unexpected=tuple(dict.fromkeys(unexpected)),
            details=tuple(texts.items()),
        )  # fmt: skip

    for number, ((read, code, output, timed_out), batch) in enumerate(zip(outcomes, batches), start=1):
        if read is not None:
            failed.extend(read.failed)
            for test, said in read.details:
                texts.setdefault(test, said)
            seen += len(read.seen)
            if strict_report:
                unexpected.extend(junit.unexpected_modules(read, batch))
            if code not in _RAN:  # a report from a process that did not finish as a pytest run is not trusted
                if strict_report:
                    crashed.extend(batch)
                troubles.append(f"shard {number} of {len(batches)}: {_why(code, output)}")
            elif code == _NOTHING_COLLECTED or (code == 1 and not read.failed):
                said = _unexplained(output)
                troubles.append(
                    f"shard {number} of {len(batches)}: pytest exit {code} contradicts its report"
                    + (f" ({said})" if said else "")
                )
        if timed_out:
            if code == TIMED_OUT:
                return incomplete(f"shard {number} of {len(batches)} was stopped: {deadline.words()}", True)
            left = len(batches) - number + 1
            return incomplete(f"{left} of {len(batches)} shard(s) never started: {deadline.words()}", True)
        if read is None and code not in _RAN:
            troubles.append(f"{', '.join(batch[:3])}: {_why(code, output)}")
            if folder:
                unrun.extend(batch)
            if code == REFUSED:  # the pool gave it no place: it proved nothing, which is not a failure
                never.extend(batch)
                refusals.append(output)
            if code == NOT_STARTED:  # its pytest would not launch: the runner's own machinery
                unlaunched.extend(batch)
            continue
        if require_cases and (code == _NOTHING_COLLECTED or (read is not None and not read.seen)):
            troubles.append(f"shard {number} of {len(batches)}: pytest collected no test from {', '.join(batch[:3])}")
            continue
        lost = tuple(batch) if read is None else junit.without_cases(read, batch)
        if lost:
            unrun.extend(lost)
            more = f" and {len(lost) - 3} more" if len(lost) > 3 else ""
            said = f" (no report; pytest said: {output.strip()[-300:]})" if read is None and output.strip() else ""
            troubles.append(
                f"shard {number} of {len(batches)}: its report has no test case for {', '.join(lost[:3])}{more}{said}"
            )
    if clock.passed(deadline) and shard_workers > 1:
        return incomplete(deadline.words(), True)
    if troubles:
        return incomplete("; ".join(troubles[:3]), False)
    return ProofRun(
        True, "", tuple(dict.fromkeys(failed)), seen, len(batches),
        crashed=tuple(dict.fromkeys(crashed)), unexpected=tuple(dict.fromkeys(unexpected)),
        details=tuple(texts.items()),
    )  # fmt: skip


def _one_slot(node_id: str) -> str:
    """A folder and report name for one test's re-runs, so re-runs of other tests beside it never share them."""
    return "one-" + hashlib.sha256(node_id.encode("utf-8", errors="surrogateescape")).hexdigest()[:12]


def run_one(
    work: Path,
    node_id: str,
    *,
    python: str,
    data_dir: Path,
    timeout_s: float = ONE_TEST_TIMEOUT_S,
    extra_env: Mapping[str, str] | None = None,
    deadline: clock.Deadline | None = None,
    run: Run = run_quietly,
    config: Path | None = None,
) -> str:
    """Run one test on its own in the copy at *work*: ``pass``, ``fail``, ``missing``, ``timeout`` or ``unknown``.

    ``missing`` is the honest answer for a test the copy does not have -- a test the change itself adds is
    not a test the base could ever have passed, and saying so is not the same as saying it passed.
    ``timeout`` is the honest answer for a test that did not finish: it used to be read as a failure, and a
    failure on the base copy excuses the change, so a base re-run that hung for 180 s let a regression through
    as "confirmed on its own". Once the proof's deadline has passed, nothing is started and the answer is
    ``timeout`` too. ``no place`` is a re-run the pool refused a place: it never started. *config* is the one pytest
    config file the re-run reads, as for :func:`run_tests`.
    """
    file = node_id.split("::", 1)[0]
    if not (Path(work) / file).is_file():
        return MISSING
    if "::" not in node_id and not node_id.endswith(".py"):
        return UNKNOWN  # a report with no ``file`` gave a dotted name, which pytest will not take back
    if clock.passed(deadline):
        return TIMEOUT
    # A bare file id is a file that could not be collected; running the file alone is its re-run.
    slot = _one_slot(node_id)
    env = sandbox_env(Path(work), Path(data_dir) / slot, extra_env)
    report = Path(data_dir) / "reports" / f"{slot}.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    command = _pytest(python, Path(work), report, [node_id], config=config)
    code, _ = run(command, cwd=Path(work), env=env, timeout_s=clock.cap(deadline, timeout_s))
    read = junit.read_report(report, Path(work))
    with contextlib.suppress(OSError):  # a refused delete (a scanner holding the file) must not lose the answer
        report.unlink(missing_ok=True)
    if code == TIMED_OUT:
        return TIMEOUT
    if code == REFUSED:
        return NO_PLACE
    if read is None or code not in _RAN:
        return UNKNOWN
    if not read.seen:
        return MISSING
    if "::" in node_id:
        if read.seen != (node_id,):
            return UNKNOWN
    elif any(seen.split("::", 1)[0] != file for seen in read.seen):
        return UNKNOWN
    if code == _NOTHING_COLLECTED or (code == 1 and not read.failed):
        return UNKNOWN
    return FAILED if read.failed else UNKNOWN if read.skipped else PASSED


__all__ = [
    "FAILED",
    "MISSING",
    "NO_PLACE",
    "ONE_TEST_TIMEOUT_S",
    "PASSED",
    "PLUGIN_FILE",
    "SELECT_OPTION",
    "SHARD_FILES",
    "SHARD_TIMEOUT_S",
    "TIMEOUT",
    "UNKNOWN",
    "ProofRun",
    "Run",
    "collect_plugin",
    "run_one",
    "run_tests",
]
