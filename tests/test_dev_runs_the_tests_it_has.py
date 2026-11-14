"""The comparison on dev runs the selected test files dev has, not the change's own new ones (2026-10-27).

Since 2026-10-26 a selected file missing from a copy stops its run before it starts. The change's own new test files
are never on dev, so whenever the change's run did not finish cleanly the dev run "did not run to the end" too, and
the check blamed dev and held the hand-in: 3603b9 on 2026-10-27, "selected test files are missing", 0 tests on dev.
"""

from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline  # noqa: F401
from thomas.server.precard import check
from thomas.server.proof import Selection, runner

OLD, NEW = "tests/test_value.py", "tests/test_new.py"


def test_dev_runs_only_the_selected_files_it_has(pipeline, monkeypatch):
    made = pipeline.make

    def make(blue, tip, eid, part):
        copy = made(blue, tip, eid, part)
        (copy.work / "tests").mkdir()
        for rel in (OLD,) if part == check.scratch.BASE else (OLD, NEW):
            (copy.work / rel).write_text("def test_value():\n    pass\n", encoding="utf-8")
        return copy

    runs: list[tuple[str, list[str]]] = []

    def run_tests(work, files, **kwargs):
        where = "dev" if work == pipeline.base.work else "change"
        runs.append((where, list(files)))
        if any(not (work / rel).is_file() for rel in files):
            return runner.ProofRun(False, "selected test files are missing", (), 0, 0)
        if where == "change":
            return runner.ProofRun(False, "a shard did not finish", (), 12, 2)
        return runner.ProofRun(True, "", (), 1, 1)

    monkeypatch.setattr(check.scratch, "copy_of_dev", make)
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection((OLD, NEW), ()))
    monkeypatch.setattr(check.proofs, "run_tests", run_tests)
    result = check._against_dev(pipeline.green, "tip", "patch", ["pkg/value.py", NEW], "python", False)
    assert runs == [("change", [OLD, NEW]), ("dev", [OLD])]
    assert "selected test files are missing" not in result.line
    assert result.cause != "dev-side", result
