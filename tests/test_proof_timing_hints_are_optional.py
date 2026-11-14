"""Incomplete timing hints cannot prevent or mislead proof scheduling."""

from pathlib import Path

import pytest

from tests.test_proof_shards_balance_without_losing_tests import write_report, write_tests
from thomas.server.proof import scheduling


@pytest.fixture(autouse=True)
def clear_costs():
    with scheduling._lock:
        scheduling._costs.clear()
    yield
    with scheduling._lock:
        scheduling._costs.clear()


def test_source_estimation_recursion_does_not_prevent_scheduling(tmp_path, monkeypatch):
    files = write_tests(tmp_path, [1, 1])

    def too_deep(*args, **kwargs):
        raise RecursionError("AST depth")

    with monkeypatch.context() as patch:
        patch.setattr(scheduling.ast, "parse", too_deep)
        groups = scheduling.batches(tmp_path, files, size=12, workers=2)
    assert groups == [(files[0],), (files[1],)]


@pytest.mark.parametrize("missing", [None, "", "not-a-number"])
def test_incomplete_file_does_not_replace_hint_or_discard_another_file(tmp_path: Path, missing):
    partial, complete = write_tests(tmp_path, [1, 1])
    report = tmp_path / "times.xml"
    write_report(report, [{"file": partial, "time": "20"}])
    scheduling.learn(tmp_path, [partial, complete], report)
    bad_case = {"file": partial}
    if missing is not None:
        bad_case["time"] = missing
    write_report(
        report,
        [{"file": partial, "time": "3"}, bad_case, {"file": complete, "time": "37"}],
    )
    scheduling.learn(tmp_path, [partial, complete], report)
    assert scheduling.estimate(tmp_path, partial) == 20
    assert scheduling.estimate(tmp_path, complete) == 37
