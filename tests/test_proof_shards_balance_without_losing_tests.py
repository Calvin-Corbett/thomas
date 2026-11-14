"""Balanced proof shards preserve selection, source-bound hints, and runner results."""

from __future__ import annotations

import math
import sys
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from thomas.server.proof import runner, scheduling


@pytest.fixture(autouse=True)
def isolated_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduling, "_costs", {})


def write_tests(tree: Path, counts: list[int]) -> list[str]:
    files = [f"tests/test_{index:02d}.py" for index in range(len(counts))]
    for rel, count in zip(files, counts):
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(f"def test_{index}():\n    pass\n" for index in range(count)),
            encoding="utf-8",
        )
    return files


def source_tests(monkeypatch: pytest.MonkeyPatch, counts: list[int]) -> list[str]:
    sources = {
        f"tests/test_{index:02d}.py": "".join(f"def test_{case}():\n    pass\n" for case in range(count)).encode()
        for index, count in enumerate(counts)
    }
    monkeypatch.setattr(scheduling, "_source", lambda _tree, rel: sources[rel])
    return list(sources)


def write_report(path: Path, cases: list[dict[str, str]]) -> None:
    root = ET.Element("testsuite")
    for attributes in cases:
        ET.SubElement(root, "testcase", attributes)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


@pytest.mark.parametrize("size,workers", [(2, 2), (3, 2), (5, 3)])
def test_parallel_shards_spread_consecutive_expensive_files_and_keep_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: int, workers: int
) -> None:
    files = source_tests(monkeypatch, [60] * 4 + [1] * 20)

    batches = scheduling.batches(tmp_path, files, size=size, workers=workers)

    assert Counter(rel for batch in batches for rel in batch) == Counter(files)
    assert all(0 < len(batch) <= size for batch in batches)
    expensive = set(files[:4])
    assert sum(bool(expensive.intersection(batch)) for batch in batches) == 4
    assert all(len(expensive.intersection(batch)) <= 1 for batch in batches)


@pytest.mark.parametrize("count", [1, 120])
def test_balancing_does_not_add_a_second_wave_of_pytest_startups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    files = source_tests(monkeypatch, [count] * 24)

    batches = scheduling.batches(tmp_path, files, size=12, workers=4)

    assert len(batches) == 4
    assert Counter(rel for batch in batches for rel in batch) == Counter(files)
    assert all(len(batch) == 6 for batch in batches)


def test_heaviest_completed_group_is_submitted_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = source_tests(monkeypatch, [100, 90, 80, 70, 60])

    batches = scheduling.batches(tmp_path, files, size=12, workers=4)
    costs = [sum(scheduling.estimate(tmp_path, rel) for rel in batch) for batch in batches]

    assert costs == sorted(costs, reverse=True)
    assert costs[0] == 130
    assert Counter(rel for batch in batches for rel in batch) == Counter(files)


@pytest.mark.parametrize("size", [1, 3, 12])
def test_one_worker_retains_legacy_contiguous_grouping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    files = [f"tests/test_{index:02d}.py" for index in range(7)]

    def no_estimate(*args: object) -> float:
        pytest.fail("serial shards must not rank files by cost")

    monkeypatch.setattr(scheduling, "estimate", no_estimate)
    assert scheduling.batches(tmp_path, files, size=size, workers=1) == [
        tuple(files[start : start + size]) for start in range(0, len(files), size)
    ]


def test_runner_passes_balanced_shards_and_records_every_file_and_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = write_tests(tmp_path, [40] * 4 + [1] * 8)
    expected = scheduling.batches(tmp_path, files, size=4, workers=2)
    assert expected != [tuple(files[start : start + 4]) for start in range(0, len(files), 4)]
    observed: dict[int, tuple[str, ...]] = {}
    lock = threading.Lock()
    measurements: list[dict[str, object]] = []

    # Keep all writable environment state in the fixture; never start a subprocess.
    monkeypatch.setattr(runner, "sandbox_env", lambda *args, **kwargs: {})

    def fake_run(command: list[str], **kwargs: object) -> tuple[int, str]:
        assert kwargs["cwd"] == tmp_path
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        number = int(report.stem.split("-")[-1])
        batch = tuple(arg for arg in command if arg in files)
        assert batch, "the command must name this shard's selected test files"
        if files[-1] in batch:
            (tmp_path / files[-1]).write_text("def test_changed():\n    pass\n", encoding="utf-8")
        with lock:
            assert number not in observed
            observed[number] = batch
        root = ET.Element("testsuite")
        failed = False
        for rel in batch:
            count = 40 if rel in files[:4] else 1
            for index in range(count):
                case = ET.SubElement(
                    root,
                    "testcase",
                    {
                        "file": rel,
                        "classname": rel[:-3].replace("/", "."),
                        "name": f"test_{index}",
                        "time": "0.25",
                    },
                )
                if rel == files[0] and index == 0:
                    ET.SubElement(case, "failure", {"message": "fixture failure"})
                    failed = True
        ET.ElementTree(root).write(report, encoding="utf-8")
        return (1 if failed else 0), "fake pytest JUnit"

    result = runner.run_tests(
        tmp_path,
        files,
        python=sys.executable,
        data_dir=tmp_path / "proof-data",
        shard_files=4,
        shard_workers=2,
        run=fake_run,
        folder=False,
        require_cases=True,
        strict_report=True,
        measurements=measurements,
    )

    assert [observed[number] for number in sorted(observed)] == expected
    assert Counter(rel for batch in observed.values() for rel in batch) == Counter(files)
    assert result.ran and result.why == ""
    assert result.seen == 4 * 40 + 8
    assert result.shards == len(expected) == len(measurements)
    assert result.failed == (f"{files[0]}::test_0",)
    assert not (result.unrun or result.not_started or result.not_launched)
    assert not (result.crashed or result.unexpected or result.out_of_time)
    ordered = sorted(measurements, key=lambda entry: entry["shard"])
    assert [entry["shard"] for entry in ordered] == list(range(1, len(expected) + 1))
    assert [tuple(entry["files"]) for entry in ordered] == expected
    assert all(math.isfinite(entry["seconds"]) and entry["seconds"] >= 0 for entry in ordered)
    # The fake reports exercise the runner -> learn seam as well as its measurements.
    assert all(scheduling.estimate(tmp_path, rel) == 10.0 for rel in files[:4])
    assert all(scheduling.estimate(tmp_path, rel) == 0.25 for rel in files[4:])
    changed_key = scheduling._key(files[-1], (tmp_path / files[-1]).read_bytes())
    assert changed_key not in scheduling._costs, "old execution time must not be learned for rewritten source"


def test_a_missing_selected_file_cannot_be_a_pass(tmp_path: Path) -> None:
    result = runner.run_tests(tmp_path, ["tests/test_missing.py"], data_dir=tmp_path / "data", python=sys.executable)
    assert not result.ran
    assert result.unrun == ("tests/test_missing.py",)


def test_a_report_from_a_crashed_process_is_incomplete_without_strict_mode(tmp_path, monkeypatch):
    files = write_tests(tmp_path, [1])

    monkeypatch.setattr(runner, "sandbox_env", lambda *args, **kwargs: {})

    def crashed(command, **kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        write_report(report, [{"file": files[0], "name": "test_case_0", "time": "1"}])
        return 3, "internal error"

    result = runner.run_tests(
        tmp_path, files, data_dir=tmp_path / "data", python=sys.executable, folder=True, run=crashed
    )
    assert not result.ran
    assert "pytest exited 3" in result.why
    assert not result.crashed, "crashed metadata remains exclusive to strict-report callers"


def test_check_records_shard_work_and_pool_wait_separately(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from tests.test_the_change_runs_once_and_dev_only_when_needed import _copies
    from thomas.server.precard import check

    copies = _copies(tmp_path, monkeypatch)
    notes: dict[str, object] = {}
    monkeypatch.setattr(check.clocks, "note", lambda name, value: notes.update({name: value}))
    monkeypatch.setattr(check.pool, "parallel", lambda: True)
    monkeypatch.setattr(check.pool, "Waits", lambda: SimpleNamespace(waited_s=7.125, ran_s=3.75))
    monkeypatch.setattr(check.pool, "runner", lambda *_a, **_k: lambda *_a, **_k: (0, ""))

    def run_tests(work: Path, files: tuple[str, ...], **kwargs: object) -> runner.ProofRun:
        measurements = kwargs["measurements"]
        assert isinstance(measurements, list)
        measurements.extend(
            [
                {"shard": 2, "files": ["tests/test_x.py"], "seconds": 3.0},
                {"shard": 1, "files": ["tests/test_y.py"], "seconds": 2.0},
            ]
        )
        return copies.run_tests(work, files, **kwargs)

    monkeypatch.setattr(check.proofs, "run_tests", run_tests)
    assert copies.check().state == check.PASSED
    assert notes["pool_wait_s"] == 7.125
    assert notes["pool_run_s"] == 3.75
    assert [entry["shard"] for entry in notes["change_shards"]] == [1, 2]


@pytest.mark.parametrize("incomplete", [False, True], ids=["failure-confirmation", "full-dev-run"])
def test_clocks_include_late_dev_copy_and_pool_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, incomplete: bool
) -> None:
    from types import SimpleNamespace

    from tests.test_the_change_runs_once_and_dev_only_when_needed import TEST, _copies
    from thomas.server.precard import check, pool

    copies = _copies(tmp_path, monkeypatch)
    notes: dict[str, object] = {}
    stages: list[str] = []
    waits = pool.Waits()
    monkeypatch.setattr(check.pool, "parallel", lambda: True)
    monkeypatch.setattr(check, "_width", lambda _shared: 4)
    monkeypatch.setattr(check.pool, "Waits", lambda: waits)
    monkeypatch.setattr(check.clocks, "note", lambda key, value: notes.__setitem__(key, value))
    real_stage = check.clocks.stage

    def stage(name: str):
        stages.append(name)
        return real_stage(name)

    monkeypatch.setattr(check.clocks, "stage", stage)
    monkeypatch.setattr(check.scratch, "copy_of_dev", lambda *_a: copies.base)
    copies.change_run = runner.ProofRun(not incomplete, "", (TEST,), 5, 1)
    copies.alone_change[TEST] = copies.alone_dev[TEST] = runner.FAILED

    def run_tests(work: Path, files: tuple[str, ...], **kwargs: object) -> runner.ProofRun:
        waits.add(waited=2.0, ran=3.0)
        kwargs["measurements"].append({"shard": 1, "files": list(files), "seconds": 3.0})
        return copies.run_tests(work, files, **kwargs)

    def run_one(work: Path, test: str, **kwargs: object) -> str:
        waits.add(waited=1.0, ran=2.0)
        return copies.run_one(work, test, **kwargs)

    monkeypatch.setattr(check.proofs, "run_tests", run_tests)
    monkeypatch.setattr(check.proofs, "run_one", run_one)
    green = SimpleNamespace(execution_id="example", blue=tmp_path)
    check._steps(
        green, "tip", "patch", ["pkg/x.py"], sys.executable, None, copies.change,
        tmp_path / "data", check.proofs.Deadline(60),
    )  # fmt: skip

    assert "base_copy" in stages
    assert notes["pool_wait_s"] == waits.waited_s > 2.0
    assert notes["pool_run_s"] == waits.ran_s > 3.0
    if incomplete:
        assert notes["dev_shards"] == [{"shard": 1, "files": ["tests/test_x.py"], "seconds": 3.0}]
