"""Every Code task used to write into one shared folder, so they erased each other.

Measured on the live workspace before this change: 106 tasks bound to
``~/.thomas/code_scratch``, and ``index.html`` in it had been written by FIVE
different conversations, each silently replacing the last. Four of the owner's
builds are gone; the only surviving trace of one was ``haunted-arcade.css``, an
orphaned stylesheet whose page no longer exists.

These tests pin both directions: a NEW task lands in a folder of its own, and an
EXISTING conversation still opens the folder it was already bound to.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient

from tests.test_evolve_agent_routes import _drive, _GateInput, _init_repo, _new_repo
from thomas.forge.anvil import forge_code_projects as fcp
from thomas.server.routes import evolve_agent_routes


@pytest.fixture(autouse=True)
def _thomas_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every project this test makes out of the real ~/.thomas."""
    home = tmp_path / "thomas-home"
    monkeypatch.setattr(fcp, "thomas_owned_root", lambda: home)
    return home


def _as_thomas_source(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Make the catalog root be Thomas's own checkout, as it is in real life.

    ``_default_repo_root()`` is the directory holding the ``thomas`` package: the
    Thomas repo in a dev install, site-packages in a packaged one. Neither is a
    project the person chose, and both are what sent every task to the shared
    scratch drawer. The tests below are only honest if they start from that.
    """
    monkeypatch.setattr(fcp, "thomas_source_repo_root", lambda: repo.resolve())


def _mock_agent_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a run start without spawning the real builder subprocess."""

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        pid = 4242
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(_executable: str, *_args: str, **_kwargs: Any) -> _FinishedProcess:
        return _FinishedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)


# ── The fix: a new task owns its folder ──────────────────────────────────────


def test_two_new_tasks_do_not_land_in_the_same_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole bug in one assertion: two tasks, two folders.

    Both of these asked for the same thing, which is exactly the case that used
    to overwrite: the second build's index.html replaced the first's.
    """
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)
    _mock_agent_process(monkeypatch)

    async def _body(client: TestClient) -> None:
        first = await (
            await client.post("/api/evolve/agent/send", json={"message": "Build a haunted arcade page"})
        ).json()
        second = await (
            await client.post("/api/evolve/agent/send", json={"message": "Build a haunted arcade page"})
        ).json()

        one, two = Path(first["project_root"]), Path(second["project_root"])
        assert first["ok"] is True and second["ok"] is True
        assert one != two, "two tasks shared a folder; one of them will overwrite the other"
        assert one.name == "Build a haunted arcade page", "the folder should say what was asked for"
        assert two.name == "Build a haunted arcade page 2"
        assert "code_scratch" not in str(one), "a new task must not default into the shared drawer"
        assert "code_scratch" not in str(two)
        assert (one / ".git").is_dir(), "without history the task's edits cannot be reverted"

    _drive(repo, _body)


def test_a_new_task_does_not_start_in_the_shared_scratch_drawer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression guard: if the scratch fallback comes back, this fails."""
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)
    _mock_agent_process(monkeypatch)
    scratch = tmp_path / "shared-scratch"
    scratch.mkdir()
    _init_repo(scratch)
    monkeypatch.setattr(fcp, "default_scratch_project", lambda _root: scratch.resolve())

    async def _body(client: TestClient) -> None:
        payload = await (await client.post("/api/evolve/agent/send", json={"message": "make a snake game"})).json()
        assert Path(payload["project_root"]) != scratch.resolve()

    _drive(repo, _body)


def test_a_new_conversation_without_a_project_also_gets_its_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other entry point -- the New-task button, before any message."""
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)

    async def _body(client: TestClient) -> None:
        first = await (
            await client.post("/api/evolve/agent/conversations/new", json={"title": "Orbit simulator"})
        ).json()
        second = await (
            await client.post("/api/evolve/agent/conversations/new", json={"title": "Orbit simulator"})
        ).json()

        one = Path(first["conversation"]["project_root"])
        two = Path(second["conversation"]["project_root"])
        assert one != two
        assert one.name == "Orbit simulator"

    _drive(repo, _body)


def test_the_saved_scratch_root_coming_back_is_not_treated_as_a_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Code UI saves whatever root it was handed and sends it again on the
    next new task -- and until now that was always the shared drawer, so it is
    already in browsers. Observed live: the project chip read "code_scratch" and
    the request carried it as project_root. Honouring that as a pick would put
    every new task straight back in the drawer."""
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)
    _mock_agent_process(monkeypatch)
    scratch = tmp_path / "home" / ".thomas" / "code_scratch"
    scratch.mkdir(parents=True)
    _init_repo(scratch)
    monkeypatch.setattr(fcp, "shared_scratch_root", lambda: scratch)

    async def _body(client: TestClient) -> None:
        payload = await (
            await client.post(
                "/api/evolve/agent/send",
                json={"message": "build a starfield", "project_root": str(scratch)},
            )
        ).json()
        assert Path(payload["project_root"]) != scratch.resolve()
        assert Path(payload["project_root"]).name == "build a starfield"

    _drive(repo, _body)


# ── The constraints: nothing existing moves, and a real choice still wins ────


def test_an_existing_conversation_still_opens_the_folder_it_was_bound_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody's files move. A conversation already living in the shared scratch
    keeps living there -- the fix changes where NEW work starts, not where old
    work is."""
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)
    _mock_agent_process(monkeypatch)
    already_shared = tmp_path / "code_scratch"
    already_shared.mkdir()
    _init_repo(already_shared)

    async def _body(client: TestClient) -> None:
        created = await (
            await client.post(
                "/api/evolve/agent/conversations/new",
                json={"title": "older task", "project_root": str(already_shared)},
            )
        ).json()
        cid = created["conversation"]["id"]
        assert Path(created["conversation"]["project_root"]) == already_shared.resolve()

        resumed = await (
            await client.post(
                "/api/evolve/agent/send",
                json={"conversation_id": cid, "message": "carry on where we left off"},
            )
        ).json()
        assert Path(resumed["project_root"]) == already_shared.resolve()

    _drive(repo, _body)


def test_a_deliberately_chosen_project_is_still_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Picking a project from the library must still mean that project."""
    repo = _new_repo(tmp_path)
    _as_thomas_source(monkeypatch, repo)
    _mock_agent_process(monkeypatch)
    chosen = tmp_path / "FreedomFlappy"
    chosen.mkdir()
    _init_repo(chosen)

    async def _body(client: TestClient) -> None:
        payload = await (
            await client.post(
                "/api/evolve/agent/send",
                json={"message": "add a scoreboard", "project_root": str(chosen)},
            )
        ).json()
        assert Path(payload["project_root"]) == chosen.resolve()

    _drive(repo, _body)


# ── Naming: derived from the task, and never able to choose a location ───────


def test_the_folder_name_comes_from_the_task() -> None:
    assert fcp.project_name_for_task("make me a pacman game") == "make me a pacman game"
    # A whole paragraph is not a folder name; the first line, trimmed, is.
    long_task = "Build a haunted arcade landing page with an animated marquee\nand a leaderboard"
    assert fcp.project_name_for_task(long_task) == "Build a haunted arcade landing page with an"
    assert len(fcp.project_name_for_task(long_task)) <= 48


def test_a_task_that_names_nothing_still_gets_a_folder() -> None:
    """No name is not a reason to fall back into the shared drawer."""
    assert fcp.project_name_for_task("   ").startswith("Code task ")
    assert fcp.project_name_for_task("///").startswith("Code task ")


def test_a_task_name_cannot_choose_where_the_folder_is_created(_thomas_home: Path) -> None:
    base = (_thomas_home / "projects").resolve()
    for hostile in ("../../escape", r"..\..\escape", "C:/Windows/System32", "a/b/c", "..", ".", "~/elsewhere"):
        made = fcp.project_for_new_task(hostile)
        assert made.parent == base, f"{hostile!r} escaped to {made}"


def test_a_task_named_after_a_windows_device_gets_a_usable_folder(_thomas_home: Path) -> None:
    """A folder called CON can be created and then cannot be used: git init in it
    fails with ".git: Invalid argument", and it cannot even be a subprocess
    working directory. Harmless while names came from a name box -- not harmless
    now that "con" is something someone can type as their task."""
    made = fcp.project_for_new_task("con")

    assert (made / ".git").is_dir(), "the project has no history, so nothing in it can be reverted"
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(made),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0, f"the agent cannot run in its own project folder: {probe.stderr.strip()}"


def test_a_folder_taken_between_the_look_and_the_create_is_not_shared(
    _thomas_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thomas runs Code tasks in parallel, so two tasks can claim one name at the
    same instant. Losing that race must mean the next number, not a shared
    folder and not a failure."""
    base = (_thomas_home / "projects").resolve()
    real_mkdir = Path.mkdir
    stolen: list[Path] = []

    def _steal_first_claim(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.parent == base and not stolen:
            stolen.append(self)
            real_mkdir(self, *args, **kwargs)  # the "other task" wins the race
            raise FileExistsError(17, "File exists", str(self))
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _steal_first_claim)
    made = fcp.project_for_new_task("Snake game")

    assert stolen and made != stolen[0], "the loser of the race reused the winner's folder"
    assert made.name == "Snake game 2"


# ── The cost of one folder per task ──────────────────────────────────────────


def test_a_known_project_is_resolved_without_spawning_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One folder per task means this runs once per project every time the Code
    history is listed. Each git spawn measured 0.3-0.7s here -- 14 known roots
    cost 18.6s before this, which would only grow. A directory holding .git IS
    its own toplevel, so there is nothing to ask."""
    project = tmp_path / "project"
    project.mkdir()
    _init_repo(project)

    def _no_git(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("git was spawned to learn what .git already answered")

    monkeypatch.setattr(fcp, "_git", _no_git)
    assert fcp.validate_project_root(project, fallback=project) == project.resolve()


def test_a_folder_inside_a_repository_still_resolves_to_the_repository(tmp_path: Path) -> None:
    """The other direction: with no .git here, git still has to be asked, because
    the answer is a PARENT directory."""
    project = tmp_path / "project"
    (project / "src" / "deep").mkdir(parents=True)
    _init_repo(project)

    assert fcp.validate_project_root(project / "src" / "deep", fallback=project) == project.resolve()


def test_a_folder_with_no_repository_anywhere_above_it_still_asks_for_a_choice(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(fcp.ForgeCodeHistoryRequired):
        fcp.validate_project_root(plain, fallback=plain)


def test_a_catalog_root_that_is_a_real_repository_is_still_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing Thomas at a repository IS a choice, and stays one. Only the
    absence of a choice stopped meaning "the shared drawer"."""
    elsewhere = tmp_path / "someproject"
    elsewhere.mkdir()
    _init_repo(elsewhere)
    monkeypatch.setattr(fcp, "thomas_source_repo_root", lambda: None)

    assert evolve_agent_routes._new_task_project_root(elsewhere, "build a thing") == elsewhere.resolve()


def test_a_project_that_cannot_be_created_falls_back_rather_than_blocking_the_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task that cannot start at all is worse than one that shares."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _init_repo(scratch)

    def _cannot(_task: str) -> Path:
        raise fcp.ForgeCodeProjectError("project folder could not be created")

    monkeypatch.setattr(fcp, "project_for_new_task", _cannot)
    monkeypatch.setattr(fcp, "default_scratch_project", lambda _root: scratch.resolve())
    monkeypatch.setattr(fcp, "thomas_source_repo_root", lambda: tmp_path.resolve())

    assert evolve_agent_routes._new_task_project_root(tmp_path, "anything") == scratch.resolve()
