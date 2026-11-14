"""Every check's shards share one pool of P pytest processes on this machine (spec 2026-10-12 Part 1 item 1).

Each side of a check ran one pytest process, because the worker formula subtracted the memory reserve from memory
that was already free; 12 processes at once gave 7.7 times the throughput of one. Now P comes from the machine's
threads and measured shard memory, each shard takes a place from the machine-wide ledger first, and
THOMAS_PRECARD_PARALLEL=off turns it all off.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import capacity_ledger
from thomas.server.precard import check, pool
from thomas.server.precard.lint import LintResult
from thomas.server.proof import ProofRun, Selection, runner
from thomas.server.proof.deadline import Deadline

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def ledger_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ledger"
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(root))
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    monkeypatch.setattr(capacity_ledger, "measure", lambda _where: capacity_ledger.Room(100 * GIB, 64 * GIB, 64 * GIB))
    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)
    return root


def _tests(work: Path, count: int) -> list[str]:
    files = [f"tests/test_{n}.py" for n in range(count)]
    for rel in files:
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return files


def _report(command: list[str]) -> Path:
    return Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))


def test_p_uses_all_threads_or_what_memory_holds_after_the_reserve() -> None:
    assert pool.size(cpus=16, total_ram_bytes=32 * GIB, shard_mb=800) == 16
    assert pool.size(cpus=16, total_ram_bytes=16 * GIB, shard_mb=1500) == 8
    assert pool.size(cpus=2, total_ram_bytes=32 * GIB, shard_mb=800) == 2


@pytest.mark.parametrize("word", ["off", "OFF", " off ", "0", "false", "no"])
def test_the_pool_is_turned_off_by_the_same_words_as_the_check(monkeypatch: pytest.MonkeyPatch, word: str) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, word)
    assert not pool.parallel()


@pytest.mark.parametrize("word", [None, "", "on", "1", "yes"])
def test_unset_or_on_keeps_the_pool(monkeypatch: pytest.MonkeyPatch, word: str | None) -> None:
    if word is None:
        monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    else:
        monkeypatch.setenv(pool.PARALLEL_ENV, word)
    assert pool.parallel()


def test_shards_never_exceed_p_across_checks(
    tmp_path: Path, ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool, "size", lambda **_kwargs: 3)
    active = peak = 0
    lock = threading.Lock()

    def measured(command: list[str], *, cwd: Path, env: dict, timeout_s: float, sample_s: float = 0.5) -> tuple:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            module = command[-1][:-3].replace("/", ".")
            _report(command).write_text(
                f'<testsuite><testcase file="{command[-1]}" classname="{module}" name="test_ok"/></testsuite>'
            )
            return 0, "", 0.0, 0.0
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(pool, "run_measured", measured)
    files = _tests(tmp_path, 8)
    results: list[runner.ProofRun] = []

    def one_check() -> None:
        data = tmp_path / f"d-{uuid.uuid4().hex[:6]}"
        run = pool.runner(None, files=len(files))
        results.append(runner.run_tests(tmp_path, files, python=sys.executable, data_dir=data, shard_files=1,
                                        shard_workers=4, run=run))  # fmt: skip

    checks = [threading.Thread(target=one_check) for _ in range(3)]
    for thread in checks:
        thread.start()
    for thread in checks:
        thread.join(60)
    assert len(results) == 3 and all(result.ran and result.seen == 8 for result in results)
    assert 1 < peak <= 3, f"three checks of four workers each ran {peak} shards at once"


SHARDS = r"""
import sys, threading, time
from pathlib import Path
from thomas.server import capacity_ledger
from thomas.server.precard import pool
root, log, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
capacity_ledger.POLL_S = 0.05
capacity_ledger.measure = lambda _w: capacity_ledger.Room(100 * 1024**3, None, None)
pool.size = lambda **_k: 3
pool.machine_capacity.check_shard_mb = lambda *_a: 100
pool.green_checkout.green_root = lambda: root
spans = []
def measured(command, *, cwd, env, timeout_s, sample_s=0.5):
    start = time.time(); time.sleep(0.3); spans.append(f"{name} {start} {time.time()}")
    return 0, "", 0.0, 0.0
pool.run_measured = measured
run = pool.runner(None, files=1)
shard = lambda: run(["x"], cwd=root, env={}, timeout_s=60)
threads = [threading.Thread(target=shard) for _ in range(5)]
for thread in threads: thread.start()
for thread in threads: thread.join()
log.write_text("\n".join(spans), encoding="utf-8")
"""


def test_the_shards_of_two_server_processes_never_exceed_p(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    logs = {name: tmp_path / f"{name}.log" for name in ("a", "b")}
    env = {**os.environ, capacity_ledger.ROOT_ENV: str(root)}
    children = [
        subprocess.Popen([sys.executable, "-c", SHARDS, str(root), str(log), name], cwd=REPO, env=env)
        for name, log in logs.items()
    ]
    for child in children:
        assert child.wait(180) == 0
    spans = [line.split() for log in logs.values() for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(spans) == 10 and {name for name, _, _ in spans} == {"a", "b"}
    edges = sorted([(float(start), 1) for _, start, _ in spans] + [(float(end), -1) for _, _, end in spans])
    most = max(itertools.accumulate(step for _, step in edges))
    assert 2 <= most <= 3, "P is 3 in both processes: at most 3 shards at once across them"


def test_a_place_waited_for_past_the_deadline_is_out_of_time_not_a_failure(
    tmp_path: Path, ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool, "size", lambda **_kwargs: 1)
    files = _tests(tmp_path, 1)
    deadline = Deadline(0.2)
    with capacity_ledger.admitted("shard:held", kind=pool.SHARD_KIND, where=tmp_path, limit=1, root=ledger_root):
        result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_workers=2,
                                  deadline=deadline, run=pool.runner(deadline, files=1))  # fmt: skip
    assert result.out_of_time and not result.ran, "a shard that never got a place ran out of time; it never failed"


def test_a_shard_records_its_committed_and_working_set_peaks(
    tmp_path: Path, ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("psutil")
    hold = "import time; b = bytearray(80 * 2**20); time.sleep(1.5)"
    code, _output, committed, working = pool.run_measured(
        [sys.executable, "-c", hold], cwd=tmp_path, env=dict(os.environ), timeout_s=60, sample_s=0.2
    )
    assert code == 0 and committed >= 60 and working > 0
    recorded: list[tuple[float, float]] = []
    monkeypatch.setattr(pool.machine_capacity, "record_check_shard_peak", lambda c, w: recorded.append((c, w)))
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_k: (0, "", 123.0, 45.0))
    pool.runner(None, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10)
    pool.runner(None, files=1, record_peaks=False)(["x"], cwd=tmp_path, env={}, timeout_s=10)
    assert recorded == [(123.0, 45.0)], "a confirmation re-run is never counted as a shard"


def test_a_peak_that_cannot_be_written_never_costs_the_shard_its_result(
    tmp_path: Path, ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(_path: Path, _payload: dict) -> None:
        raise PermissionError(13, "Access is denied")  # another process has machine_capacity.json open

    monkeypatch.setattr(pool.machine_capacity, "_default_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(pool.machine_capacity, "_write_profile", busy)
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_k: (0, "1 passed", 123.0, 45.0))

    assert pool.runner(None, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10) == (0, "1 passed")


# Leaves a child holding the output pipe open, then ends the way pytest-timeout ends pytest.
STAYS = (
    "import os, subprocess, sys, time; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=sys.stdout); "
    "time.sleep(1.5); os._exit(1)"
)


def test_a_shard_out_of_time_takes_its_whole_tree_down(tmp_path: Path) -> None:
    pytest.importorskip("psutil")
    started = time.monotonic()

    code, output, _committed, _working = pool.run_measured(
        [sys.executable, "-c", STAYS], cwd=tmp_path, env=dict(os.environ), timeout_s=3, sample_s=0.2
    )

    assert code == pool.TIMED_OUT and "did not finish" in output
    assert time.monotonic() - started < 8, "a child left holding the output does not keep the shard's place"


def _steps_args(tmp_path: Path) -> tuple:
    return (
        SimpleNamespace(execution_id="example"),
        "abc123",
        "patch",
        ["pkg/adder.py"],
        sys.executable,
        SimpleNamespace(work=tmp_path / "base"),
        SimpleNamespace(work=tmp_path / "change"),
        tmp_path / "data",
        check.proofs.Deadline(10),
    )


def _quiet_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_a: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_a: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_ok.py",), ()))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: LintResult(True, "", (), ()))
    monkeypatch.setattr(check.machine_capacity, "check_shard_mb", lambda *_a: 100)  # never the saved profile


def test_a_checks_runs_use_the_pool_and_collect_from_the_tests_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    _quiet_steps(monkeypatch)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * GIB, 20 * GIB))
    seen: list[dict] = []

    def fake_tests(work: Path, files: tuple, **kwargs: object) -> ProofRun:
        seen.append(kwargs)
        return ProofRun(True, "", (), 1, 1)

    monkeypatch.setattr(check.proofs, "run_tests", fake_tests)

    assert check._steps(*_steps_args(tmp_path)).state == check.PASSED

    width = pool.size(total_ram_bytes=32 * GIB)
    assert seen and all(k["folder"] is True and callable(k["run"]) and k["shard_workers"] == width for k in seen)


def test_with_the_pool_off_a_check_runs_as_before_and_never_reads_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    _quiet_steps(monkeypatch)

    def never(*_a: object, **_k: object) -> None:
        raise AssertionError("the ledger was used with the pool turned off")

    monkeypatch.setattr(pool.capacity_ledger, "admitted", never)
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        calls.append(command)
        module = command[-1][:-3].replace("/", ".")
        _report(command).write_text(
            f'<testsuite><testcase file="{command[-1]}" classname="{module}" name="test_ok"/></testsuite>'
        )
        return 0, ""

    original = check.proofs.run_tests
    monkeypatch.setattr(
        check.proofs, "run_tests", lambda work, files, **kw: original(work, files, **{**kw, "run": fake_run})
    )
    for side in ("base", "change"):
        _tests(tmp_path / side, 1)
        (tmp_path / side / "tests" / "test_0.py").rename(tmp_path / side / "tests" / "test_ok.py")

    assert check._steps(*_steps_args(tmp_path)).state == check.PASSED

    assert calls and all(command[1:3] == ["-m", "pytest"] and command[-1] == "tests/test_ok.py" for command in calls)
