"""The Build engine's test run and static check go through the sandbox slot, in any folder.

Every sandbox here is a fake: posture, heartbeat, the cage call and the local call are injected, so no test reaches
the real cage. The projects folder is a temporary one named by THOMAS_OWNED_ROOT.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import build_verify as bv
from thomas.tools import sandbox_slot as slot
from thomas.tools.cage_shell import CagedResult


def install(monkeypatch: pytest.MonkeyPatch, posture: str, alive: bool, reply: CagedResult | None = None):
    caged: list[tuple[str, str, float]] = []

    def cage(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        caged.append((command, cwd, timeout_s))
        return reply or CagedResult("ok", 0, "1 passed", "thomas-agent")

    box = slot.Sandbox(posture=lambda: posture, runner_alive=lambda: alive, cage_run=cage)
    monkeypatch.setattr(slot, "_sandbox", box)
    return caged


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(tmp_path / "owned"))
    folder = tmp_path / "owned" / "projects" / "demo"
    folder.mkdir(parents=True)
    (folder / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    return folder


@pytest.fixture
def local_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "local ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def verify(folder: Path, files: list[str]):
    events: list[dict] = []
    return bv.verify_python_changes(folder, files, events.append, timeout=30), events


def test_tests_in_a_project_folder_run_in_the_cage(monkeypatch, project, local_calls) -> None:
    caged = install(monkeypatch, "required", True)
    (ok, rc, _), _ = verify(project, ["test_a.py"])
    assert ok and rc == 0 and local_calls == []
    command, cwd, timeout = caged[0]
    assert cwd == str(project) and timeout == 30 and "pytest" in command and "test_a.py" in command


def test_a_failing_cage_run_still_fails(monkeypatch, project, local_calls) -> None:
    install(monkeypatch, "auto", True, CagedResult("ok", 1, "1 failed", "thomas-agent"))
    (ok, rc, detail), _ = verify(project, ["test_a.py"])
    assert not ok and rc == 1 and "1 failed" in detail and local_calls == []


def test_required_with_no_runner_is_a_clean_failure_not_a_local_run(monkeypatch, project, local_calls) -> None:
    caged = install(monkeypatch, "required", False)
    (ok, rc, detail), events = verify(project, ["test_a.py"])
    assert not ok and rc == 1 and "could not run" in detail
    assert caged == [] and local_calls == []
    assert events[-1]["is_error"] is True


def test_off_and_auto_without_a_runner_run_here(monkeypatch, project, local_calls) -> None:
    caged = install(monkeypatch, "off", True)
    assert verify(project, ["test_a.py"])[0][0] is True
    install(monkeypatch, "auto", False)
    assert verify(project, ["test_a.py"])[0][0] is True
    assert caged == [] and len(local_calls) == 2


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    (folder / "test_b.py").write_text("def test_b():\n    pass\n", encoding="utf-8")
    (folder / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return folder


def test_a_folder_outside_the_projects_still_goes_to_the_cage_when_the_ladder_says_caged(
    monkeypatch, project, elsewhere, local_calls
) -> None:
    caged = install(monkeypatch, "required", True)
    assert verify(elsewhere, ["test_b.py"])[0][0] is True
    assert verify(elsewhere, ["mod.py"])[0][0] is True
    assert len(caged) == 2 and all(cwd == str(elsewhere) for _, cwd, _ in caged)
    assert local_calls == [] and list(elsewhere.glob(".thomas_verify_*")) == []


def test_a_folder_outside_the_projects_is_refused_not_run_here_when_the_cage_is_silent(
    monkeypatch, project, elsewhere, local_calls
) -> None:
    caged = install(monkeypatch, "required", False)
    for name in ("test_b.py", "mod.py"):
        (ok, rc, detail), _ = verify(elsewhere, [name])
        assert not ok and rc == 1 and "could not run" in detail
    assert caged == [] and local_calls == [] and list(elsewhere.glob(".thomas_verify_*")) == []


def test_a_folder_outside_the_projects_runs_here_when_the_posture_is_off(
    monkeypatch, project, elsewhere, local_calls
) -> None:
    caged = install(monkeypatch, "off", True)
    assert verify(elsewhere, ["test_b.py"])[0][0] is True
    assert verify(elsewhere, ["mod.py"])[0][0] is True
    assert caged == [] and len(local_calls) == 2 and list(elsewhere.glob(".thomas_verify_*")) == []


def test_the_static_check_in_a_project_folder_runs_in_the_cage_as_a_script(monkeypatch, project, local_calls) -> None:
    seen: list[tuple[str, str]] = []

    def cage(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        script = next(project.glob(".thomas_verify_*.py"))  # it exists while the cage runs
        seen.append((command, script.read_text(encoding="utf-8")))
        return CagedResult("ok", 0, "checked", "thomas-agent")

    box = slot.Sandbox(posture=lambda: "required", runner_alive=lambda: True, cage_run=cage)
    monkeypatch.setattr(slot, "_sandbox", box)
    (project / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (ok, rc, _), _ = verify(project, ["mod.py"])
    assert ok and rc == 0 and local_calls == []
    ((command, source),) = seen
    assert ".thomas_verify_" in command and "\n" not in command
    assert source.startswith("import sys\nsys.argv = ['-c', '[\"mod.py\"]'") and bv._VERIFY_SRC in source
    assert list(project.glob(".thomas_verify_*")) == []  # and it is gone afterwards


def test_the_static_check_with_no_cage_runner_is_a_clean_failure_and_leaves_no_script(
    monkeypatch, project, local_calls
) -> None:
    caged = install(monkeypatch, "required", False)
    (project / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (ok, rc, detail), events = verify(project, ["mod.py"])
    assert not ok and rc == 1 and "could not run" in detail and events[-1]["is_error"] is True
    assert caged == [] and local_calls == [] and list(project.glob(".thomas_verify_*")) == []


def test_the_static_check_stays_here_when_the_posture_is_off(monkeypatch, project, local_calls) -> None:
    caged = install(monkeypatch, "off", True)
    (project / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert verify(project, ["mod.py"])[0][0] is True
    assert caged == [] and len(local_calls) == 1
    assert local_calls[0][1] == "-c" and local_calls[0][2] == bv._VERIFY_SRC  # the same program, as before
    assert list(project.glob(".thomas_verify_*")) == []


def test_the_script_does_what_the_dash_c_program_did(project) -> None:
    import sys

    (project / "good.py").write_text("x = 1\n", encoding="utf-8")
    (project / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    for name, passes in (("good.py", True), ("bad.py", False)):
        cmd = [sys.executable, "-c", bv._VERIFY_SRC, json.dumps([name]), json.dumps([]), json.dumps([])]
        script = bv._static_check_script(project, cmd)
        try:
            as_script = subprocess.run([sys.executable, str(script)], cwd=project, capture_output=True, text=True)
            as_dash_c = subprocess.run(cmd, cwd=project, capture_output=True, text=True)
        finally:
            script.unlink()
        assert (as_script.returncode == 0) is passes
        assert as_script.returncode == as_dash_c.returncode
