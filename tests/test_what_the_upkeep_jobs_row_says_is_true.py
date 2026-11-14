"""What the words of ``thomas.server.rows.engine_actions`` say about a job, held on a real server through the live table.

No proof of a row can see these, and the route in ``thomas.server.routes.engine_actions_aiohttp`` has no test of its own
that reaches a job. Off waits for a running job, and the route goes while it waits. Stop now ends the wait and not the
job. ``force`` runs a job set not to run by itself. And the save takes new files and not changed ones, which is why the
words stop at new files.

Each builds its server in the test itself and never in a module-scoped fixture: a home of its own for each test comes
from a function-scoped fixture in ``tests/conftest_factories.py``, and a server built before that one runs reads the Work
apps in your real home, which the run's guard then fails.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.plugin_page_fixture import report_of
from tests.plugin_view_fixture import state_of, until
from thomas.core.workspace_sync_engine import WorkspaceSyncEngine
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, RuntimePlugins

ROW = "engine_actions"
ROUTE = "POST /api/engine-actions"
GETTERS = {
    "thomas.core.code_issue_engine": "get_code_issue_engine",
    "thomas.core.self_upgrade_engine": "get_self_upgrade_engine",
    "thomas.core.ui_workflow_engine": "get_ui_workflow_engine",
    "thomas.core.workspace_sync_engine": "get_workspace_sync_engine",
}


class _Held:
    """An upkeep job that waits to be let go, on the worker thread a real one runs on."""

    def __init__(self) -> None:
        self.began = threading.Event()
        self.let_go = threading.Event()
        self.ended = threading.Event()

    def run_cycle_once(self, *, reason: str, force: bool) -> dict[str, Any]:
        self.began.set()
        self.let_go.wait()
        self.ended.set()
        return {"ok": True}


class _Asked:
    """An upkeep job that counts the times it was started."""

    def __init__(self) -> None:
        self.times = 0

    def run_cycle_once(self, *, reason: str, force: bool) -> dict[str, Any]:
        self.times += 1
        return {"ok": True}


def _with_the_jobs(monkeypatch: pytest.MonkeyPatch, *jobs: Any) -> None:
    """In the order a run of all four takes them. After the app is built, or the server would start these in place."""
    for (module, getter), job in zip(GETTERS.items(), jobs, strict=True):
        monkeypatch.setattr(f"{module}.{getter}", lambda job=job: job)


def _server(tmp_path: Path) -> Any:
    return app_core.create_app(views.config_in(tmp_path))


async def _row_is_up(app: Any) -> RuntimePlugins:
    """Fails with the row's reason. Waiting for active alone would spin for ever on a row that reads failed."""
    runtime = app[APP_RUNTIME_PLUGINS]
    await until(lambda: state_of(runtime, ROW) != "loading")
    assert report_of(runtime, ROW)["state"] == "active", report_of(runtime, ROW)
    return runtime


def _live_routes(app: Any) -> set[str]:
    return {f"{route.method} {route.resource.canonical}" for route in app.router._live.routes()}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_off_waits_for_a_running_job_and_its_answer_arrives(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _Held()

    async def scenario() -> None:
        app = _server(tmp_path)
        _with_the_jobs(monkeypatch, job, _Asked(), _Asked(), _Asked())
        async with TestClient(TestServer(app)) as client:
            runtime = await _row_is_up(app)
            try:
                running = asyncio.create_task(client.post("/api/engine-actions", json={"engine": "issues"}))
                await until(job.began.is_set)
                pressing = asyncio.create_task(client.post(f"/api/plugins/thomas/{ROW}/off"))
                await until(lambda: state_of(runtime, ROW) == "unloading")

                assert report_of(runtime, ROW)["waiting_for"] == 1
                # The row reads unloading before your choice is saved, and the route leaves after that, so this waits for it.
                await until(lambda: ROUTE not in _live_routes(app))
                arriving_now = await client.post("/api/engine-actions", json={"engine": "issues"})
                assert arriving_now.status == 404  # the route has gone while the job it started is still waited for
            finally:
                job.let_go.set()
            answer = await running
            assert answer.status == 200
            assert (await pressing).status == 200
            assert state_of(runtime, ROW) == "off"

    asyncio.run(scenario())


def test_stop_now_ends_the_wait_and_not_the_job_and_the_jobs_not_yet_begun_never_start(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's Stop now words say so. A job cannot be cut short, because a thread cannot be, and this one may be saving."""
    job, not_begun = _Held(), _Asked()

    async def scenario() -> None:
        app = _server(tmp_path)
        _with_the_jobs(monkeypatch, job, not_begun, not_begun, not_begun)
        async with TestClient(TestServer(app)) as client:
            runtime = await _row_is_up(app)
            try:
                running = asyncio.create_task(client.post("/api/engine-actions", json={"engine": "all"}))
                await until(job.began.is_set)
                pressing = asyncio.create_task(client.post(f"/api/plugins/thomas/{ROW}/off"))
                await until(lambda: state_of(runtime, ROW) == "unloading")

                stopped = await client.post(f"/api/plugins/thomas/{ROW}/off", params={"force": "1"})

                assert stopped.status == 200
                assert (await pressing).status == 200
                assert state_of(runtime, ROW) == "off"
                with pytest.raises(aiohttp.ClientError):  # whoever asked gets no answer
                    await running
                assert not job.ended.is_set()  # the row reads off with the job still going
            finally:
                job.let_go.set()
            await until(job.ended.is_set)
            assert not_begun.times == 0

    asyncio.run(scenario())


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _a_repository(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    for name in ("kept.txt", "gone.txt"):
        (repo / name).write_text("first\n", encoding="utf-8")
    _git(repo, "add", "kept.txt", "gone.txt")
    _git(repo, "commit", "-m", "start")


def _settled(repo: Path, *names: str) -> None:
    """Dated well past the wait a server's job gives a file before it will take it."""
    long_ago = time.time() - 300
    for name in names:
        os.utime(repo / name, (long_ago, long_ago))


def test_a_forced_save_takes_new_files_leaves_out_changed_ones_and_stops_at_a_deleted_or_staged_one(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words promise new files, say what a file already in git does to that, and that a program can force it.

    This is the job a server builds, with the wait a server gives it, set off as every launcher sets it. Only its folder,
    its log, the claim it would take and the push are its own here. The wait matters: with none, which no server has, a
    changed file stops the whole save, and that is what these words first said.

    The words stop at new files because of what happens today. The job strips each line of ``git status``, so
    `` M kept.txt`` loses the space its columns are counted from and the name comes out as ``ept.txt``. Nothing has that
    name, so it counts as just written and is left out, and the new file beside it is saved. A deleted file's name skips
    the wait, so ``git add`` gets ``one.txt`` for ``gone.txt``, refuses it, and nothing is saved. That is a fault in the job,
    left for a change of its own. When it is mended this fails, and the words can promise changed files.
    """
    repo = tmp_path / "repo"
    _a_repository(repo)
    monkeypatch.setenv("THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED", "0")
    job = WorkspaceSyncEngine(
        repo_root=repo, coordination_enabled=False, auto_push=False, log_path=tmp_path / "sync.jsonl"
    )
    forced = {"engine": "sync", "force": True}
    found: dict[str, Any] = {}

    async def ask(client: TestClient, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        answer = await client.post("/api/engine-actions", json=body)
        return answer.status, (await answer.json())["result"]

    async def scenario() -> None:
        app = _server(tmp_path)
        monkeypatch.setattr("thomas.core.workspace_sync_engine.get_workspace_sync_engine", lambda: job)
        async with TestClient(TestServer(app)) as client:
            runtime = await _row_is_up(app)
            found["words"] = report_of(runtime, ROW)["about"]

            (repo / "new.txt").write_text("new\n", encoding="utf-8")
            found["asked"] = await ask(client, {"engine": "sync"})
            found["just_written"] = await ask(client, forced)
            _settled(repo, "new.txt")
            found["a_new_file"] = await ask(client, forced)

            (repo / "kept.txt").write_text("changed\n", encoding="utf-8")
            (repo / "second.txt").write_text("new\n", encoding="utf-8")
            _settled(repo, "kept.txt", "second.txt")
            found["a_changed_file"] = await ask(client, forced)
            found["after_a_changed_file"] = _git(repo, "status", "--porcelain").splitlines()

            (repo / "gone.txt").unlink()
            (repo / "third.txt").write_text("new\n", encoding="utf-8")
            _settled(repo, "third.txt")
            found["a_deleted_file"] = await ask(client, forced)

            (repo / "gone.txt").write_text("first\n", encoding="utf-8")
            _git(repo, "add", "kept.txt")
            found["a_staged_file"] = await ask(client, forced)

    asyncio.run(scenario())

    def outcome(case: str) -> tuple[int, bool, str]:
        status, result = found[case]
        return status, result["committed"], result["skip_reason"]

    assert found["asked"] == (503, {"ok": False, "reason": "engine_disabled"})
    assert outcome("just_written") == (200, False, "changes_not_stable_yet")  # so the wait here is a server's wait
    assert outcome("a_new_file") == (200, True, ""), found["a_new_file"][1]
    assert outcome("a_changed_file") == (200, True, ""), found["a_changed_file"][1]
    assert found["a_changed_file"][1]["details"]["files"] == ["second.txt"]
    assert " M kept.txt" in found["after_a_changed_file"]
    assert outcome("a_deleted_file") == (200, False, "git_add_failed"), found["a_deleted_file"][1]
    assert "one.txt" in found["a_deleted_file"][1]["details"]["stderr"]
    assert outcome("a_staged_file") == (200, False, "staged_changes_present"), found["a_staged_file"][1]
    subjects = _git(repo, "log", "--format=%s").splitlines()
    assert len(subjects) == 3  # the first commit and the two new files, and nothing since
    assert subjects[0].startswith("chore(thomas): auto-sync workspace")
    assert "?? third.txt" in _git(repo, "status", "--porcelain").splitlines()
    # What the Plugins page says of those last four runs, so the page and the job cannot part without this failing.
    assert "which leaves out changes to files already in git" in found["words"]
    assert "saves nothing if one of those files was deleted or a change is already waiting" in found["words"]
