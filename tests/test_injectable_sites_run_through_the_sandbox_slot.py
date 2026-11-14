"""The two injectable sites (subtask graph checks, acceptance contract commands) run through the sandbox slot.

Every sandbox here is a fake: posture, heartbeat, the cage call and the local call are all injected, so no test reaches
the real cage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from thomas.agent import sandboxed_runners as sr
from thomas.agent import subtask_graph as sg
from thomas.tools import sandbox_slot as slot
from thomas.tools.cage_shell import CagedResult


class Calls:
    def __init__(self, caged: CagedResult | None = None) -> None:
        self.caged_calls: list[tuple[str, str, float]] = []
        self.local_calls: list[tuple[str, str, float]] = []
        self._caged = caged or CagedResult("ok", 0, "caged output", "thomas-agent")

    def cage(self, command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        self.caged_calls.append((command, cwd, timeout_s))
        return self._caged

    def local(self, command: str, *, cwd: str, timeout: float) -> tuple[int | None, str, str]:
        self.local_calls.append((command, cwd, timeout))
        return 0, "local out", ""


def install(monkeypatch: pytest.MonkeyPatch, posture: str, alive: bool, calls: Calls) -> None:
    box = slot.Sandbox(posture=lambda: posture, runner_alive=lambda: alive, cage_run=calls.cage, local_run=calls.local)
    monkeypatch.setattr(slot, "_sandbox", box)


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A folder under a temporary ``~/.thomas/projects``: the only kind of folder the ladder is used for."""
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(tmp_path / "owned"))
    folder = tmp_path / "owned" / "projects" / "demo"
    folder.mkdir(parents=True)
    return folder


def test_contract_command_runs_in_the_cage_in_the_workspace(monkeypatch, project: Path) -> None:
    calls = Calls()
    install(monkeypatch, "required", True, calls)
    assert sr.contract_runner("python -m pytest", project, 42.0) == (0, "caged output")
    assert calls.caged_calls == [("python -m pytest", str(project), 42.0)]
    assert calls.local_calls == []


def test_contract_command_exit_code_and_timeout_come_through(monkeypatch, project: Path) -> None:
    install(monkeypatch, "auto", True, Calls(CagedResult("ok", 3, "bad", "thomas-agent")))
    assert sr.contract_runner("x", project, 5.0) == (3, "bad")
    install(monkeypatch, "auto", True, Calls(CagedResult("timeout", -1, "", "thomas-agent")))
    assert sr.contract_runner("x", project, 5.0) == (124, "timed out after 5s")


def test_required_with_no_runner_refuses_and_runs_nothing(monkeypatch, project: Path) -> None:
    calls = Calls()
    install(monkeypatch, "required", False, calls)
    code, text = sr.contract_runner("echo hi", project, 5.0)
    assert code != 0 and "nothing ran" in text
    assert calls.caged_calls == [] and calls.local_calls == []
    code, out, err = sg._default_command_runner(["pytest"], str(project), 5)
    assert code != 0 and out == "" and "nothing ran" in err
    assert calls.caged_calls == [] and calls.local_calls == []


def test_a_cage_error_is_a_failed_result_with_the_plain_text(monkeypatch, project: Path) -> None:
    install(monkeypatch, "required", True, Calls(CagedResult("error", -1, "the cage broke", "")))
    assert sr.contract_runner("x", project, 5.0) == (127, "the cage broke")


def test_a_cage_that_raises_is_a_failed_result(monkeypatch, project: Path) -> None:
    def boom(*a, **k):
        raise RuntimeError("down")

    box = slot.Sandbox(posture=lambda: "required", runner_alive=lambda: True, cage_run=boom)
    monkeypatch.setattr(slot, "_sandbox", box)
    code, text = sr.contract_runner("x", project, 5.0)
    assert code == 127 and "nothing ran" in text


def test_posture_off_uses_the_sites_own_local_runner(monkeypatch, project: Path) -> None:
    calls = Calls()
    install(monkeypatch, "off", True, calls)
    monkeypatch.setattr("thomas.core.acceptance_contract.default_runner", lambda c, d, t: (0, "own"))
    assert sr.contract_runner("x", project, 5.0) == (0, "own")
    seen = []
    monkeypatch.setattr(sg, "_local_command_runner", lambda a, c, t: seen.append(a) or (0, "o", ""))
    assert sg._default_command_runner(["pytest"], str(project), 5) == (0, "o", "")
    assert seen == [["pytest"]]
    assert calls.caged_calls == []


def test_subtask_check_runs_caged_with_pinned_python_and_same_timeout(monkeypatch, project: Path) -> None:
    calls = Calls()
    install(monkeypatch, "auto", True, calls)
    code, out, err = sg._default_command_runner(["python", "-m", "pytest", "-q"], str(project), 30)
    assert (code, out, err) == (0, "caged output", "")
    (command, cwd, timeout) = calls.caged_calls[0]
    assert cwd == str(project) and timeout == 30
    assert "pytest" in command and sys.executable in command


def test_the_verifier_fails_a_refused_check_never_passes_it(monkeypatch, project: Path) -> None:
    install(monkeypatch, "required", False, Calls())
    rubric = sg.Rubric(criteria=(sg.RubricCriterion(key="t", description="tests pass"),))
    verifier = sg.CommandRerunVerifier(commands={"t": "python -m pytest -q"}, cwd=str(project))
    node = sg.SubtaskNode(id="n", description="d", rubric=rubric, verifier=verifier)
    verdict = verifier.verify(node, None)
    assert not verdict.passed and "nothing ran" in verdict.checks[0].detail


def test_the_ladder_is_read_once_so_a_dying_heartbeat_cannot_change_the_rung(monkeypatch, project: Path) -> None:
    calls = Calls()
    beats = iter([True, False, False, False])  # the runner answers once, then goes silent
    box = slot.Sandbox(
        posture=lambda: "auto", runner_alive=lambda: next(beats), cage_run=calls.cage, local_run=calls.local
    )
    monkeypatch.setattr(slot, "_sandbox", box)
    assert sr.contract_runner("echo hi", project, 5.0) == (0, "caged output")
    assert calls.caged_calls and calls.local_calls == []
    beats = iter([True, False, False, False])
    box._runner_alive = lambda: next(beats)
    calls.caged_calls.clear()
    assert sg._default_command_runner(["pytest"], str(project), 5) == (0, "caged output", "")
    assert calls.caged_calls and calls.local_calls == []


def _verify(project: Path, expected: int):
    rubric = sg.Rubric(criteria=(sg.RubricCriterion(key="t", description="tests pass"),))
    verifier = sg.CommandRerunVerifier(
        commands={"t": "python -m pytest -q"}, cwd=str(project), expected_returncode=expected
    )
    return verifier.verify(sg.SubtaskNode(id="n", description="d", rubric=rubric, verifier=verifier), None)


def test_a_command_that_did_not_run_never_passes_whatever_exit_code_is_expected(monkeypatch, project: Path) -> None:
    for expected in (0, 127, 124, -127, -124):
        install(monkeypatch, "required", False, Calls())  # refused
        verdict = _verify(project, expected)
        assert not verdict.passed and "did not run" in verdict.checks[0].detail, expected
        install(monkeypatch, "required", True, Calls(CagedResult("error", -1, "the cage broke", "")))
        assert not _verify(project, expected).passed, expected
        install(monkeypatch, "required", True, Calls(CagedResult("timeout", -1, "slow", "thomas-agent")))
        assert not _verify(project, expected).passed, expected


def test_a_command_that_really_exits_127_still_matches_an_expected_127(monkeypatch, project: Path) -> None:
    install(monkeypatch, "required", True, Calls(CagedResult("ok", 127, "not found", "thomas-agent")))
    assert _verify(project, 127).passed


def _both_sites(project: Path, cwd: Path):
    return (
        sr.contract_runner("x", cwd, 5.0),
        sg._default_command_runner(["pytest"], str(cwd), 5),
    )


def test_a_folder_outside_the_projects_still_goes_to_the_cage_when_it_answers(monkeypatch, project, tmp_path) -> None:
    calls = Calls()
    install(monkeypatch, "required", True, calls)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr("thomas.core.acceptance_contract.default_runner", lambda c, d, t: (0, "own"))
    monkeypatch.setattr(sg, "_local_command_runner", lambda a, c, t: (0, "o", ""))
    assert _both_sites(project, elsewhere) == ((0, "caged output"), (0, "caged output", ""))
    assert len(calls.caged_calls) == 2 and all(cwd == str(elsewhere) for _, cwd, _ in calls.caged_calls)
    assert calls.local_calls == []


def test_a_folder_outside_the_projects_runs_nothing_when_the_cage_is_required_and_silent(
    monkeypatch, project, tmp_path
) -> None:
    calls = Calls()
    install(monkeypatch, "required", False, calls)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    local_seen = []
    monkeypatch.setattr(
        "thomas.core.acceptance_contract.default_runner", lambda c, d, t: local_seen.append(c) or (0, "")
    )
    monkeypatch.setattr(sg, "_local_command_runner", lambda a, c, t: local_seen.append(a) or (0, "o", ""))
    (code, text), (rc, out, err) = _both_sites(project, elsewhere)
    assert code != 0 and "nothing ran" in text
    assert rc == sr.COMMAND_NOT_RUN and out == "" and "nothing ran" in err
    assert local_seen == [] and calls.caged_calls == [] and calls.local_calls == []


def test_a_folder_outside_the_projects_uses_the_local_runners_when_the_posture_is_off(
    monkeypatch, project, tmp_path
) -> None:
    calls = Calls()
    install(monkeypatch, "off", True, calls)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr("thomas.core.acceptance_contract.default_runner", lambda c, d, t: (0, "own"))
    monkeypatch.setattr(sg, "_local_command_runner", lambda a, c, t: (0, "o", ""))
    assert _both_sites(project, elsewhere) == ((0, "own"), (0, "o", ""))
    assert calls.caged_calls == []


def test_a_missing_folder_keeps_the_original_refusal_unless_the_ladder_says_local(monkeypatch, project) -> None:
    calls = Calls()
    for posture, alive in (("required", True), ("required", False)):
        install(monkeypatch, posture, alive, calls)
        rc, out, err = sg._default_command_runner(["pytest"], None, 5)
        assert rc == sr.COMMAND_NOT_RUN and "no project folder is given" in err
    monkeypatch.setattr(sg, "_local_command_runner", lambda a, c, t: (0, "o", ""))
    install(monkeypatch, "off", True, calls)
    assert sg._default_command_runner(["pytest"], None, 5) == (0, "o", "")
    assert calls.caged_calls == [] and calls.local_calls == []
