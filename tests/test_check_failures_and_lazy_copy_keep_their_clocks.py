"""Lazy dev copies stay observable and checks-off read failures remain held."""

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from thomas.server.precard import check, clocks
from thomas.server.precard.lint import LintResult
from thomas.server.proof import Selection, runner


@pytest.fixture
def world(tmp_path, monkeypatch):
    green = check.green_checkout.Green("clock-test", tmp_path / "change", tmp_path / "git", "base", tmp_path / "blue")
    green.work.mkdir()
    monkeypatch.setattr(check.green_checkout, "find_green", lambda _eid: green)
    return SimpleNamespace(green=green, catalog=tmp_path)


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("git diff", 1), OSError("unreadable patch")])
def test_checks_off_patch_read_failure_is_unavailable(world, monkeypatch, error):
    monkeypatch.setenv("THOMAS_PRECARD_CHECK", "off")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(check.green_checkout, "green_patch", fail)
    result = check.check_before_card(world.green.execution_id)
    assert result.state == check.UNAVAILABLE
    assert result.cause == "incomplete"
    assert result.costly
    assert result.patch == ""


def test_lazy_dev_copy_from_confirmation_worker_keeps_its_clock(world, monkeypatch):
    made_base = []
    start = threading.Barrier(2)
    test_id = "tests/test_value.py::test_value"

    def make(*args, **kwargs):
        assert args[3] == check.scratch.BASE
        with clocks.stage("worker_base_copy"):
            result = SimpleNamespace(work=world.catalog / "base")
            made_base.append(result)
        return result

    def confirm(failed, *, rerun_on_base, **kwargs):
        assert failed == (test_id,)

        def rerun():
            start.wait(timeout=10)
            return rerun_on_base("tests/test_value.py::test_value")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rerun) for _ in range(2)]
            assert [future.result() for future in futures] == ["passed", "passed"]
        return check.proofs.Verdict((), (), (), (), ())

    monkeypatch.setattr(check.scratch, "copy_of_dev", make)
    monkeypatch.setattr(check.proofs, "confirm", confirm)
    monkeypatch.setattr(check.proofs, "run_tests", lambda *args, **kwargs: runner.ProofRun(True, "", (test_id,), 1, 1))
    monkeypatch.setattr(check.known, "key", lambda *_: "test-key")
    monkeypatch.setattr(check.known, "read", lambda *_: frozenset())
    monkeypatch.setattr(check.known, "remember", lambda *_: None)
    monkeypatch.setattr(check.proofs, "run_one", lambda *args, **kwargs: "passed")
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_value.py",), ()))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_a, **_k: LintResult(True, "", (), ()))
    with clocks.recording(world.catalog, "lazy-clock") as record:
        result = check._steps(
            world.green,
            "tip",
            "patch",
            ["pkg/adder.py"],
            "python",
            None,
            world.green,
            world.catalog,
            check.proofs.Deadline(10),
            shared=False,
        )
    assert result.state == check.PASSED, result
    assert "base_copy" in record["stages"]
    assert "worker_base_copy" in record["stages"]
    assert len(made_base) == 1, "both confirmation workers share one baseline checkout"


@pytest.mark.parametrize("folder", [False, True])
def test_strict_report_cannot_omit_one_of_the_selected_files(tmp_path, monkeypatch, folder):
    files = ["tests/test_first.py", "tests/test_missing.py"]
    for rel in files:
        target = tmp_path / rel
        target.parent.mkdir(exist_ok=True)
        target.write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(runner, "sandbox_env", lambda *args, **kwargs: {})

    def run(command, **kwargs):
        report = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml="))
        from pathlib import Path

        Path(report).write_text(
            '<testsuite><testcase classname="tests.test_first" name="test_ok" time="1"/></testsuite>',
            encoding="utf-8",
        )
        return 0, "only one selected file reported"

    result = runner.run_tests(
        tmp_path,
        files,
        python="python",
        data_dir=tmp_path / "data",
        run=run,
        folder=folder,
        strict_report=True,
        require_cases=True,
    )
    assert not result.ran
    assert result.unrun == (files[1],)
