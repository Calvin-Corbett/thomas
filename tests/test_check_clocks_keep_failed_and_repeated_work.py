"""Clock records retain failed test runs and every repeated stage interval."""

import pytest

from thomas.server.precard import check, clocks
from thomas.server.proof import runner


def test_a_runner_exception_keeps_its_elapsed_stage(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("runner broke")

    monkeypatch.setattr(check.proofs, "run_tests", fail)
    with clocks.recording(tmp_path, "clock-test") as record:
        with pytest.raises(RuntimeError, match="runner broke"):
            check._timed_tests("change_run", tmp_path, ())
    assert "change_run" in record["stages"]
    assert record["stages"]["change_run"]["seconds"] >= 0


def test_a_failed_shard_keeps_its_elapsed_measurement(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    measurements = []

    def fail(*args, **kwargs):
        raise RuntimeError("shard broke")

    with pytest.raises(RuntimeError, match="shard broke"):
        runner.run_tests(
            tmp_path, ("test_ok.py",), python="python", data_dir=tmp_path / "data", run=fail, measurements=measurements
        )
    assert len(measurements) == 1
    assert measurements[0]["files"] == ["test_ok.py"]
    assert measurements[0]["seconds"] >= 0


def test_clock_serialization_failure_does_not_replace_the_result(tmp_path):
    cyclic = []
    cyclic.append(cyclic)
    with clocks.recording(tmp_path, "clock-test"):
        clocks.note("cyclic", cyclic)


def test_elapsed_clocks_survive_a_wall_clock_correction(tmp_path, monkeypatch):
    wall = iter([100.0, 101.0, 50.0, 51.0])
    ticks = iter([10.0, 11.0, 13.0, 15.0])
    monkeypatch.setattr(clocks.time, "time", lambda: next(wall))
    monkeypatch.setattr(clocks.time, "monotonic", lambda: next(ticks))
    with clocks.recording(tmp_path, "clock-test") as record:
        with clocks.stage("change_run"):
            pass
    assert record["seconds"] == 5
    assert record["stages"]["change_run"]["seconds"] == 2


def test_repeated_stage_keeps_each_interval_and_total(tmp_path):
    with clocks.recording(tmp_path, "clock-test") as record:
        clocks.span("base_copy", 10, 12)
        clocks.span("base_copy", 20, 23)
        clocks.span("base_copy", 30, 34)
    stage = record["stages"]["base_copy"]
    assert stage["seconds"] == 9
    assert [item["seconds"] for item in stage["intervals"]] == [2, 3, 4]
    assert stage["start"] == clocks._stamp(10)
    assert stage["end"] == clocks._stamp(34)
