"""A code task sent from chat has to open a Build session you can watch.

Observed 2026-09-20 by driving the UI: "build me a live clock page" was
dispatched, the worker wrote a good `index.html` inside
``~/.thomas/workspaces/exec-<id>``, and chat said "Started the task card ...
Follow progress there." Opening Build showed an empty pane -- no session, no
activity, no agent -- for the whole twelve minutes the run was alive.

Nothing was broken in the renderer. Build lists conversations under the project
roots in ``forge_code_projects.conversation_roots()``, and chat dispatch never
created one: it ran the task in a bare workspace that is not a project and is
not a git repo. The two halves never met, which is why a green suite could not
see it -- each half is correct on its own.

The same class of bug was already fixed for the Build-initiated path, and the
comment left in ``evolve_agent_conversation_routes`` says so: "Everything Thomas
builds lands in ~/.thomas/workspaces/<exec-id>, which is never a git repo -- so
every app Thomas made for the user was unopenable until now." The chat-dispatched
path never got that fix.

These tests pin the wiring in both directions: a coding task opens a Build
session in a project of its own, and a task that is not code does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects as fcp
from thomas.forge.anvil import forge_code_store
from thomas.server.chat_delegation_build_session import (
    WorkspacePlan,
    open_build_session,
    prepare_workspace,
    prepare_workspace_async,
)


@pytest.fixture(autouse=True)
def _thomas_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every project these tests make out of the real ~/.thomas."""
    home = tmp_path / "thomas-home"
    monkeypatch.setattr(fcp, "thomas_owned_root", lambda: home)
    return home


@pytest.fixture()
def catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_a_coding_task_gets_a_project_of_its_own(catalog_root: Path, _thomas_home: Path) -> None:
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build live dark-theme clock webpage",
        catalog_root=catalog_root,
    )

    assert session is not None, "a coding task must open a Build session"
    project_root = Path(session["project_root"])
    assert project_root.is_dir()
    # Its OWN folder under Thomas's data dir, not the shared workspaces drawer.
    assert "workspaces" not in project_root.parts


def test_the_build_session_is_where_build_actually_looks(catalog_root: Path) -> None:
    """The one that proves the bug is fixed.

    Build's listing walks ``conversation_roots(catalog_root)`` and lists the
    conversations under each. A session that is not reachable that way is a
    session the person cannot open, however real the run behind it is.
    """
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build live dark-theme clock webpage",
        catalog_root=catalog_root,
    )
    assert session is not None
    cid = session["conversation_id"]
    project_root = Path(session["project_root"])

    roots = [Path(r).resolve() for r in fcp.conversation_roots(catalog_root)]
    assert project_root.resolve() in roots, "Build does not walk the project this task runs in"

    listed = [row.get("id") for row in forge_code_store.list_conversations(project_root)]
    assert cid in listed, "the Build session exists but Build would not list it"


def test_a_writing_task_does_not_open_a_build_session(catalog_root: Path) -> None:
    """A PDF or a document is not something you watch get built."""
    assert (
        open_build_session(
            specialist_id="writing",
            targets_live_repo=False,
            title="Write the launch note",
            catalog_root=catalog_root,
        )
        is None
    )


def test_a_task_on_the_live_repo_does_not_open_a_build_session(catalog_root: Path) -> None:
    """Self-edit runs in the checkout itself and is gated separately; it must not
    mint a project folder as a side effect of this wiring."""
    assert (
        open_build_session(
            specialist_id="coding",
            targets_live_repo=True,
            title="Add a --json flag to the changelog check",
            catalog_root=catalog_root,
        )
        is None
    )


def test_two_coding_tasks_do_not_land_on_each_other(catalog_root: Path) -> None:
    """The shared-drawer bug: 106 tasks once bound to one folder, index.html
    written by five of them. Two different tasks get two different projects."""
    first = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build live dark-theme clock webpage",
        catalog_root=catalog_root,
    )
    second = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a snake game in one html file",
        catalog_root=catalog_root,
    )
    assert first is not None and second is not None
    assert Path(first["project_root"]).resolve() != Path(second["project_root"]).resolve()
    assert first["conversation_id"] != second["conversation_id"]


# --- where the task actually runs -------------------------------------------


def _workspace_for(tmp_path: Path):
    """Stand-in for ``ensure_task_workspace``: the bare per-execution folder."""

    def _make(execution_id: str) -> Path:
        target = tmp_path / "workspaces" / execution_id
        target.mkdir(parents=True, exist_ok=True)
        return target

    return _make


def test_a_coding_task_runs_inside_its_build_project(tmp_path: Path, catalog_root: Path) -> None:
    plan = prepare_workspace(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build live dark-theme clock webpage",
        catalog_root=catalog_root,
        repo_root=tmp_path / "repo",
        execution_id="exec-1",
        task_workspace=_workspace_for(tmp_path),
    )

    assert plan.is_project is True
    assert plan.conversation_id
    assert Path(plan.work_dir).resolve() == Path(plan.project_root).resolve()
    assert "workspaces" not in Path(plan.work_dir).parts


def test_a_writing_task_still_runs_in_a_plain_workspace(tmp_path: Path, catalog_root: Path) -> None:
    plan = prepare_workspace(
        specialist_id="writing",
        targets_live_repo=False,
        title="Write the launch note",
        catalog_root=catalog_root,
        repo_root=tmp_path / "repo",
        execution_id="exec-2",
        task_workspace=_workspace_for(tmp_path),
    )

    assert plan.is_project is False
    assert plan.conversation_id == ""
    assert Path(plan.work_dir).parts[-2:] == ("workspaces", "exec-2")


def test_a_live_repo_task_never_runs_in_the_checkout(tmp_path: Path, catalog_root: Path) -> None:
    """Self-development used to run here, in the live checkout. It now runs in
    green (tests/test_self_development_works_in_green.py); a folder green cannot
    be made from is refused rather than used."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    plan = prepare_workspace(
        specialist_id="coding",
        targets_live_repo=True,
        title="Add a --json flag to the changelog check",
        catalog_root=catalog_root,
        repo_root=repo,
        execution_id="exec-3",
        task_workspace=_workspace_for(tmp_path),
    )

    assert plan.is_project is False
    assert plan.refusal, "a non-repo cannot give a self-fix its private copy"
    assert Path(plan.work_dir).resolve() != repo.resolve()


def test_a_failed_build_session_does_not_take_the_task_down(
    tmp_path: Path, catalog_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 0: a task never dies because of something nobody engineered past.

    If the project cannot be minted -- a full disk, a locked folder, git missing
    -- the work still has to run. It runs in the plain workspace, exactly as it
    did before this wiring existed, and the reason is reported rather than
    swallowed.
    """

    def _boom(_task: str) -> Path:
        raise fcp.ForgeCodeProjectError("no room to mint a project")

    monkeypatch.setattr(fcp, "project_for_new_task", _boom)

    plan = prepare_workspace(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build live dark-theme clock webpage",
        catalog_root=catalog_root,
        repo_root=tmp_path / "repo",
        execution_id="exec-4",
        task_workspace=_workspace_for(tmp_path),
    )

    assert plan.is_project is False
    assert Path(plan.work_dir).parts[-2:] == ("workspaces", "exec-4")
    assert "no room to mint a project" in plan.build_session_error


def test_minting_the_project_does_not_block_the_event_loop(tmp_path: Path, catalog_root: Path) -> None:
    """Minting a project shells out to git, and dispatch is a coroutine.

    Run inline, a git init stalls every other request the server is serving --
    which is why the Build route hands the same work to an executor. The async
    entry point has to keep the loop free while it happens.
    """
    import asyncio

    loop_was_free = False

    async def _exercise() -> WorkspacePlan:
        nonlocal loop_was_free

        async def _tick() -> None:
            nonlocal loop_was_free
            # Only reachable if prepare_workspace_async yielded to the loop.
            await asyncio.sleep(0)
            loop_was_free = True

        ticker = asyncio.create_task(_tick())
        plan = await prepare_workspace_async(
            specialist_id="coding",
            targets_live_repo=False,
            title="Build live dark-theme clock webpage",
            catalog_root=catalog_root,
            repo_root=tmp_path / "repo",
            execution_id="exec-5",
            task_workspace=_workspace_for(tmp_path),
        )
        await ticker
        return plan

    plan = asyncio.run(_exercise())

    assert loop_was_free, "prepare_workspace_async blocked the loop while minting the project"
    assert plan.is_project is True
    assert plan.conversation_id
