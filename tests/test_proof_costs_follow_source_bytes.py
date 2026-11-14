"""Source-bound JUnit costs guide ordering without changing selection."""

import math
from collections import Counter
from pathlib import Path

import pytest

from tests.test_proof_shards_balance_without_losing_tests import write_report, write_tests
from thomas.server.proof import scheduling


@pytest.fixture(autouse=True)
def clear_costs() -> None:
    with scheduling._lock:
        scheduling._costs.clear()
    yield
    with scheduling._lock:
        scheduling._costs.clear()


@pytest.mark.parametrize("identity", ["file", "classname"])
def test_junit_costs_sum_per_file_and_only_follow_identical_source_bytes(tmp_path: Path, identity: str) -> None:
    files = write_tests(tmp_path, [3, 2])
    other, measured = files
    original = (tmp_path / measured).read_bytes()
    report = tmp_path / "learn.xml"
    attributes = (
        {"file": measured.replace("/", "\\")}
        if identity == "file"
        else {"classname": measured[:-3].replace("/", ".") + ".TestGroup"}
    )
    write_report(
        report,
        [
            {**attributes, "name": "test_a", "time": "7.5"},
            {**attributes, "name": "test_b", "time": "8.5"},
            {"file": "tests/test_unselected.py", "name": "test_other", "time": "999"},
        ],
    )
    assert scheduling.estimate(tmp_path, measured) == 2.0
    assert scheduling.batches(tmp_path, files, size=2, workers=2)[0] == (other,)
    scheduling.learn(tmp_path, [measured], report)
    assert scheduling.estimate(tmp_path, measured) == 16.0
    assert scheduling.estimate(tmp_path, other) == 24.0
    assert scheduling.batches(tmp_path, files, size=2, workers=2)[0] == (other,)
    copy = tmp_path / "another-copy"
    (copy / measured).parent.mkdir(parents=True)
    (copy / measured).write_bytes(original)
    assert scheduling.estimate(copy, measured) == 16.0
    # A comment preserves the AST test count but invalidates the byte-bound hint.
    (tmp_path / measured).write_bytes(original + b"# changed source\n")
    assert scheduling.estimate(tmp_path, measured) == 16.0
    assert scheduling.batches(tmp_path, files, size=2, workers=2)[0] == (other,)
    (tmp_path / measured).write_bytes(original)
    assert scheduling.estimate(tmp_path, measured) == 16.0


def test_inherited_test_cost_belongs_to_collection_module(tmp_path: Path) -> None:
    helper, collected = write_tests(tmp_path, [1, 1])
    report = tmp_path / "inherited.xml"
    write_report(
        report,
        [{"file": helper, "classname": collected[:-3].replace("/", ".") + ".TestInherited", "time": "29"}],
    )
    scheduling.learn(tmp_path, [helper, collected], report)
    assert scheduling.estimate(tmp_path, collected) == 29
    assert scheduling._key(helper, (tmp_path / helper).read_bytes()) not in scheduling._costs
    assert scheduling.estimate(tmp_path, helper) == 29


@pytest.mark.parametrize("seconds", ["not-a-number", "-5", "inf", "-inf", "nan", "1e999"])
def test_invalid_junit_times_never_become_scheduling_weights(tmp_path: Path, seconds: str) -> None:
    files = write_tests(tmp_path, [4, 2])
    report = tmp_path / "invalid-time.xml"
    write_report(report, [{"file": files[0], "name": "test_0", "time": seconds}])
    scheduling.learn(tmp_path, files, report)
    # Bad numeric values may be ignored or leave the scheduler's minimum hint.
    assert scheduling.estimate(tmp_path, files[0]) in (1.0, 4.0)
    assert all(math.isfinite(value) and value >= 1 for value in scheduling._costs.values())
    batches = scheduling.batches(tmp_path, files, size=2, workers=2)
    assert Counter(rel for batch in batches for rel in batch) == Counter(files)


@pytest.mark.parametrize("contents", [None, "<testsuite><testcase"])
def test_missing_or_malformed_junit_keeps_source_estimates(tmp_path: Path, contents: str | None) -> None:
    files = write_tests(tmp_path, [4])
    report = tmp_path / "unreadable.xml"
    if contents is not None:
        report.write_text(contents, encoding="utf-8")
    scheduling.learn(tmp_path, files, report)
    assert scheduling.estimate(tmp_path, files[0]) == 4.0


def test_mixed_cache_cheap_definitions_use_measured_scale_not_raw_counts(tmp_path: Path) -> None:
    files = write_tests(tmp_path, [1, 120])
    report = tmp_path / "report.xml"
    write_report(report, [{"file": files[0], "time": "0.01"}])
    scheduling.learn(tmp_path, files, report)

    assert scheduling.estimate(tmp_path, files[0]) == 0.01
    assert scheduling.estimate(tmp_path, files[1]) == pytest.approx(1.2)
    assert Counter(rel for batch in scheduling.batches(tmp_path, files, size=2, workers=2) for rel in batch) == Counter(
        files
    )


def test_zero_duration_hints_still_fill_each_available_worker(tmp_path: Path) -> None:
    files = write_tests(tmp_path, [1] * 8)
    report = tmp_path / "zero.xml"
    write_report(report, [{"file": rel, "time": "0"} for rel in files])
    scheduling.learn(tmp_path, files, report)

    batches = scheduling.batches(tmp_path, files, size=12, workers=4)

    assert len(batches) == 4
    assert all(len(batch) == 2 for batch in batches)
    assert Counter(rel for batch in batches for rel in batch) == Counter(files)


def test_partial_or_overflowed_timings_preserve_an_existing_hint(tmp_path: Path) -> None:
    files = write_tests(tmp_path, [1])
    report = tmp_path / "report.xml"
    write_report(report, [{"file": files[0], "time": "20"}])
    scheduling.learn(tmp_path, files, report)
    for times in ([], ["nan"], ["1", "nan"], ["1", "-5"], ["1", "inf"], ["1e308", "1e308"]):
        write_report(report, [{"file": files[0], "time": value} for value in times])
        scheduling.learn(tmp_path, files, report)
        assert scheduling.estimate(tmp_path, files[0]) == 20.0
