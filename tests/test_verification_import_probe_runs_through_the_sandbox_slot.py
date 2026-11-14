"""The post-edit import probe runs through the sandbox slot when it has a project folder.

Every sandbox here is a fake: posture, heartbeat, the cage call and the local call are injected, so no test reaches
the real cage.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.agent import verification as v
from thomas.tools import sandbox_slot as slot
from thomas.tools.cage_shell import CagedResult


def install(monkeypatch: pytest.MonkeyPatch, posture: str, alive: bool, reply: CagedResult | None = None):
    caged: list[tuple[str, str, float]] = []

    def cage(command: str, *, cwd: str, timeout_s: float) -> CagedResult:
        caged.append((command, cwd, timeout_s))
        return reply or CagedResult("ok", 0, "", "thomas-agent")

    box = slot.Sandbox(posture=lambda: posture, runner_alive=lambda: alive, cage_run=cage)
    monkeypatch.setattr(slot, "_sandbox", box)
    return caged


def make_module(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    mod = pkg / "mod.py"
    mod.write_text("x = 1\n", encoding="utf-8")
    return mod


class _RootFirstPath(type(Path())):
    """``verify_after_tool`` walks ``reversed(path.parents)`` and stops at the first folder without ``__init__.py``, which
    is the drive root, so the probe never finds a module name for a real path. That is an old bug and is left alone;
    this path lists its parents nearest-last so the walk reaches the package and the probe is exercised as intended."""

    @property
    def parents(self):
        return list(reversed(super().parents))


@pytest.fixture(autouse=True)
def _probe_reaches_the_package(monkeypatch) -> None:
    monkeypatch.setattr(v, "Path", _RootFirstPath)


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A folder under a temporary ``~/.thomas/projects``: the only kind of folder the cage can write in."""
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(tmp_path / "owned"))
    folder = tmp_path / "owned" / "projects" / "demo"
    folder.mkdir(parents=True)
    return folder


def run(project: Path, mod: Path, root: str | None) -> list[dict]:
    args = {"path": str(mod)}
    return asyncio.run(v.verify_after_tool("fs.write", args, True, root))


def test_import_probe_runs_in_the_cage_in_the_project_folder(monkeypatch, project: Path) -> None:
    caged = install(monkeypatch, "required", True)
    mod = make_module(project)
    assert run(project, mod, str(project)) == []
    assert len(caged) == 1
    command, cwd, timeout = caged[0]
    assert cwd == str(project) and timeout == 10 and "pkg.mod" in command


def test_a_failing_import_in_the_cage_is_still_reported(monkeypatch, project: Path) -> None:
    install(monkeypatch, "auto", True, CagedResult("ok", 1, "SyntaxError: bad", "thomas-agent"))
    issues = run(project, make_module(project), str(project))
    assert [i["check"] for i in issues] == ["import"] and "Import check failed" in issues[0]["message"]


def test_required_with_no_runner_reports_it_did_not_run(monkeypatch, project: Path) -> None:
    caged = install(monkeypatch, "required", False)
    issues = run(project, make_module(project), str(project))
    assert caged == []
    assert [i["check"] for i in issues] == ["import"] and "did not run" in issues[0]["message"]


def test_a_cage_timeout_adds_no_issue_like_the_local_timeout(monkeypatch, project: Path) -> None:
    install(monkeypatch, "auto", True, CagedResult("timeout", -1, "", "thomas-agent"))
    assert run(project, make_module(project), str(project)) == []


def test_posture_off_and_no_folder_run_here_not_in_the_cage(monkeypatch, project: Path) -> None:
    caged = install(monkeypatch, "off", True)
    seen: list[tuple] = []

    class Proc:
        returncode = 1

        async def communicate(self):
            return b"", b"ImportError: boom"

    async def fake_exec(*argv, **kw):
        seen.append((argv, kw.get("cwd")))
        return Proc()

    monkeypatch.setattr(v.asyncio, "create_subprocess_exec", fake_exec)
    mod = make_module(project)
    issues = run(project, mod, str(project))
    assert issues and seen[0][1] == str(project) and seen[0][0][0] == "python"
    install(monkeypatch, "required", True)
    seen.clear()
    run(project, mod, None)  # no project folder: never the cage
    assert seen and seen[0][1] == "."
    assert caged == []


def test_a_folder_outside_the_projects_follows_the_ladder_too(monkeypatch, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    mod = make_module(elsewhere)
    caged = install(monkeypatch, "required", True)
    assert run(elsewhere, mod, str(elsewhere)) == []
    assert [cwd for _, cwd, _ in caged] == [str(elsewhere)]
    caged = install(monkeypatch, "required", False)
    issues = run(elsewhere, mod, str(elsewhere))
    assert caged == [] and "did not run" in issues[0]["message"]
