"""A verification record must be evidence, not a receipt anyone can write.

Found 2026-09-19 in this repo: `.git/agent_verification.json` claimed a pass with
`"command": "python -c print(123)"`, `passed: 0`, and a regression check recorded as
`"command": "skipped"` with `"passed": true`, dated three months earlier. The gate that
reads it accepted all of that: any non-empty string counted as a test command, zero
tests counted as a run, a skipped regression counted as passed, and no age was checked.
The record creator wrote that false pass itself, because `--skip-regression` left
`regression_passed` at True.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load("verification_record_gate", "scripts/forge/gates/verification_record_gate.py")
creator = _load("create_verification_record", "scripts/create_verification_record.py")


def _record(**over: Any) -> dict[str, Any]:
    record = {
        "version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "claude",
        "task_summary": "real work",
        "tests_run": {
            "command": "python -m pytest tests/test_thing.py -q",
            "exit_code": 0,
            "passed": 12,
            "failed": 0,
            "output_hash": "sha256:abc",
        },
        "regression_check": {"command": "python -m pytest tests/test_architecture.py -q", "passed": True},
        "shrinkage": {"deletions_justified": ""},
        "scope_justification": "",
    }
    record.update(over)
    return record


def test_a_real_record_passes() -> None:
    assert gate._check_tests_run(_record()) == []
    assert gate._check_regression(_record()) == []
    assert gate._check_freshness(_record()) == []


def test_a_trivial_command_is_not_a_test_run() -> None:
    errors = gate._check_tests_run(_record(tests_run={"command": "python -c print(123)", "passed": 0, "failed": 0}))

    assert errors and any("test runner" in e for e in errors)


def test_zero_tests_is_not_evidence() -> None:
    errors = gate._check_tests_run(
        _record(tests_run={"command": "python -m pytest tests/ -q", "passed": 0, "failed": 0})
    )

    assert errors and any("no tests" in e.lower() for e in errors)


def test_a_skipped_regression_is_not_a_pass() -> None:
    errors = gate._check_regression(_record(regression_check={"command": "skipped", "passed": True}))

    assert errors and any("skipped" in e.lower() for e in errors)


def test_a_regression_with_no_command_is_not_a_pass() -> None:
    errors = gate._check_regression(_record(regression_check={"command": "", "passed": True}))

    assert errors


def test_an_old_record_does_not_cover_todays_commit() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    errors = gate._check_freshness(_record(timestamp=stale))

    assert errors and any("old" in e.lower() for e in errors)


def test_a_record_without_a_timestamp_is_refused() -> None:
    assert gate._check_freshness(_record(timestamp=""))


@pytest.mark.parametrize("skip", [True, False])
def test_the_creator_never_writes_a_pass_it_did_not_see(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip: bool
) -> None:
    def _fake_run(command: str, timeout: int = 120) -> tuple[int, str]:
        return 0, "1 passed"

    monkeypatch.setattr(creator, "_run_command", _fake_run)
    monkeypatch.setattr(creator, "RECORD_PATH", tmp_path / "agent_verification.json")
    argv = ["--test-command", "python -m pytest tests/test_thing.py -q", "--task", "t"]
    if skip:
        argv.append("--skip-regression")

    creator.run(argv)

    written = json.loads((tmp_path / "agent_verification.json").read_text(encoding="utf-8"))
    regression = written["regression_check"]
    if skip:
        assert regression["passed"] is False, "a skipped regression must not be recorded as passed"
        assert gate._check_regression(written), "the gate must refuse a skipped regression"
    else:
        assert regression["passed"] is True


# ---- review fixes (2026-10-04): a record has to name a real runner invocation, and a bad record is a refusal, not a crash ----


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest tests/test_thing.py -q",
        "python3 -m pytest -x",
        "C:\\repo\\.venv\\Scripts\\python.exe -m pytest tests/a.py tests/b.py -q -p no:cacheprovider",
        "py -m unittest discover",
        "pytest -q",
        "npm test",
        "npx vitest run",
        "cargo test --lib",
        "go test ./...",
    ],
)
def test_real_runner_invocations_are_accepted(command: str) -> None:
    assert gate._names_a_test_runner(command), command
    assert gate._check_tests_run(_record(tests_run={"command": command, "passed": 3, "failed": 0})) == []


@pytest.mark.parametrize(
    "command",
    [
        "echo pytest",
        "true # pytest",
        "python -c print('pytest')",
        "python -m pytest -q; echo done",
        "python -m pytest -q || true",
        "echo ok && echo pytest",
        "cat pytest.ini",
        "$(echo pytest)",
    ],
)
def test_a_command_that_only_mentions_a_runner_is_not_a_test_run(command: str) -> None:
    assert not gate._names_a_test_runner(command), command
    errors = gate._check_tests_run(_record(tests_run={"command": command, "passed": 3, "failed": 0}))
    assert errors and any("test runner" in e for e in errors)


def test_the_regression_command_must_be_a_runner_invocation_too() -> None:
    errors = gate._check_regression(_record(regression_check={"command": "echo pytest", "passed": True}))

    assert errors and any("not a test-runner invocation" in e for e in errors)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "just text",
        {"tests_run": []},
        {"tests_run": {"command": "python -m pytest -q", "passed": "many", "failed": 0}},
        {"tests_run": {"command": "python -m pytest -q", "passed": True, "failed": 0}},
        {"tests_run": {"command": "python -m pytest -q", "passed": 3, "failed": None}},
        {"tests_run": {"command": "python -m pytest -q", "passed": 3, "failed": 0}, "regression_check": []},
        {"tests_run": {"command": "python -m pytest -q", "passed": 3, "failed": 0}, "regression_check": {"command": 7}},
    ],
)
def test_a_malformed_record_is_refused_without_a_traceback(
    payload: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record_path = tmp_path / "agent_verification.json"
    record_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(gate, "RECORD_PATH", record_path)
    monkeypatch.setattr(gate, "_staged_files", lambda: ["a.py", "b.py", "c.py", "d.py"])

    code = gate.run([])

    out = capsys.readouterr().out
    assert code == 1, out
    assert "Traceback" not in out
    assert "SAFETY GATE FAILED" in out


def test_a_record_for_a_linked_worktree_is_written_and_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In a linked worktree .git is a file: the record lives in the worktree's own git dir, for the creator and the gates."""
    import subprocess

    main = tmp_path / "main"
    main.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=main, check=True, capture_output=True)
    (main / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=main, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=main, check=True, capture_output=True)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", str(linked)], cwd=main, check=True, capture_output=True)
    assert (linked / ".git").is_file()

    monkeypatch.setattr(creator, "ROOT", linked)
    where = creator._record_path()
    where.parent.mkdir(parents=True, exist_ok=True)  # what the creator does before writing
    where.write_text("{}", encoding="utf-8")
    assert where.is_file() and "worktrees" in where.parts
    for name in ("verification_record_gate", "commit_scope_gate", "shrinkage_gate", "dependency_gate"):
        module = gate if name == "verification_record_gate" else _load(name, f"scripts/forge/gates/{name}.py")
        assert module._record_path(linked) == where, name
    # an ordinary checkout still uses .git/
    assert gate._record_path(main) == main / ".git" / "agent_verification.json"


def test_the_creator_passes_its_test_timeout_to_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def _fake_run(command: str, timeout: int = 120) -> tuple[int, str]:
        seen.append(timeout)
        return 0, "1 passed"

    monkeypatch.setattr(creator, "_run_command", _fake_run)
    monkeypatch.setattr(creator, "RECORD_PATH", tmp_path / "agent_verification.json")

    creator.run(["--test-command", "python -m pytest -q", "--task", "t", "--test-timeout", "777"])
    creator.run(["--test-command", "python -m pytest -q", "--task", "t"])

    assert seen[0] == 777 and seen[-1] == 120, seen


# ---- 2026-11-06: a run that timed out printed "Record is clean. You can now commit your changes." ----


@pytest.mark.parametrize(
    ("code", "output"),
    [(1, "Command timed out after 120s"), (1, "'.venv' is not recognized as an internal or external command"), (2, "")],
)
def test_a_test_run_that_did_not_finish_is_never_called_clean(
    code: int, output: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _fake_run(command: str, timeout: int = 120) -> tuple[int, str]:
        return (code, output) if "test_thing" in command else (0, "1 passed")

    monkeypatch.setattr(creator, "_run_command", _fake_run)
    monkeypatch.setattr(creator, "RECORD_PATH", tmp_path / "agent_verification.json")

    status = creator.run(["--test-command", "python -m pytest tests/test_thing.py -q", "--task", "t"])

    printed = capsys.readouterr().out
    assert status == 1
    assert "Record is clean" not in printed
    assert f"exit code {code}" in printed
