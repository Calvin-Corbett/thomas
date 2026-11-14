"""Preparation waits without time limits; real faults fail and old failure notices recover with the queue."""

import asyncio
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import self_project_queue_tick as queue
from thomas.server import thomas_project
from thomas.server import thomas_project_start as start


def _quick(monkeypatch, stall=0.3):
    # Exercise the former limit when this test is run against the old implementation.
    monkeypatch.setattr(start, "STALL_S", stall, raising=False)
    monkeypatch.setattr(start, "_POLL_S", 0.02)


def test_explicit_cancellation_releases_admission(monkeypatch):
    _quick(monkeypatch)

    async def scenario():
        cancelled = []

        async def stuck(*args, progress, **kwargs):
            progress.touch("copying Thomas's source")
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        monkeypatch.setattr(start, "_start_thomas_project", stuck)
        app = {}
        task = asyncio.create_task(start.start_thomas_project(app, request="fix", settings={}, port=1))
        await asyncio.sleep(0.1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert cancelled == [True]
        assert app["self_project_listing_slot"]["pending_starts"] == 0

    asyncio.run(scenario())


def test_a_slow_start_that_keeps_moving_is_never_cut_off(monkeypatch):
    """The old fixed eight-second wait (asyncio.wait_for) is gone: a start that keeps moving outlasts any clock."""
    _quick(monkeypatch)

    async def real_deadline(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(start.asyncio, "wait_for", real_deadline)

    async def slow_but_moving(*args, progress, **kwargs):
        for step in range(12):
            await asyncio.sleep(0.1)
            progress.touch(f"step {step}")
        return {"conversation_id": "c", "execution_id": "e"}

    monkeypatch.setattr(start, "_start_thomas_project", slow_but_moving)

    async def scenario():
        app = {}
        result = await start.start_thomas_project(app, request="fix", settings={}, port=1)
        assert result["conversation_id"] == "c"
        assert app["self_project_listing_slot"]["pending_starts"] == 0

    asyncio.run(scenario())


def test_a_busy_start_waits_through_silent_stages(monkeypatch):
    _quick(monkeypatch, stall=0.05)

    async def scenario():
        release = asyncio.Event()

        async def slow(*args, progress, **kwargs):
            progress.touch("registering the project")
            await release.wait()
            progress.touch("starting Build's team")
            await asyncio.sleep(0.1)
            return {"conversation_id": "slow"}

        monkeypatch.setattr(start, "_start_thomas_project", slow)
        app = {}
        task = asyncio.create_task(start.start_thomas_project(app, request="fix", settings={}, port=1))
        try:
            await asyncio.sleep(0.15)
            assert not task.done(), "a busy preparation must keep waiting, not refuse the start"
            assert app["self_project_listing_slot"]["pending_starts"] == 1
        finally:
            release.set()
            result = await task
        assert result["conversation_id"] == "slow"
        assert app["self_project_listing_slot"]["pending_starts"] == 0

    asyncio.run(scenario())


def _stub_copy(monkeypatch, tmp_path, write):
    """A green copy whose files appear (or do not) as ``write(work)`` says, seen by the start's own watcher."""
    work, git_dir = tmp_path / "work" / "thomas-aaaaaaaaaaaa", tmp_path / "git" / "thomas-aaaaaaaaaaaa"
    work.mkdir(parents=True)
    git_dir.mkdir(parents=True)
    monkeypatch.setattr(start.green_checkout, "_paths", lambda _id: (work, git_dir))

    def create(blue, execution_id):
        write(work)
        return SimpleNamespace(execution_id=execution_id, work=work, git_dir=git_dir)

    monkeypatch.setattr(start.green_checkout, "create_green", create)
    monkeypatch.setattr(start.green_checkout, "remove_green", lambda green: None)

    async def copy_only(app, *, progress, **kwargs):
        progress.touch("copying Thomas's source")
        await start._create_green(tmp_path, "thomas-aaaaaaaaaaaa", progress)
        return {"conversation_id": "c", "execution_id": "e"}

    monkeypatch.setattr(start, "_start_thomas_project", copy_only)


def test_a_copy_whose_folder_keeps_growing_is_progress_even_past_the_window(monkeypatch, tmp_path):
    _quick(monkeypatch, stall=0.25)

    def writing(work):
        import time

        for index in range(15):  # 0.9s of steady file creation against a 0.25s window
            (work / f"f{index}.txt").write_text("x")
            time.sleep(0.06)

    _stub_copy(monkeypatch, tmp_path, writing)

    async def scenario():
        app = {}
        result = await start.start_thomas_project(app, request="fix", settings={}, port=1)
        assert result["execution_id"] == "e"

    asyncio.run(scenario())


def test_a_silent_copy_waits_until_its_real_failure(monkeypatch, tmp_path):
    _quick(monkeypatch, stall=0.25)

    def silent(work):
        import time

        time.sleep(0.4)
        raise PermissionError("source is unreadable")

    _stub_copy(monkeypatch, tmp_path, silent)

    async def scenario():
        app = {}
        with pytest.raises(PermissionError, match="source is unreadable"):
            await start.start_thomas_project(app, request="fix", settings={}, port=1)
        assert app["self_project_listing_slot"]["pending_starts"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_stage", ["registration", "conversation"])
def test_slow_registration_or_conversation_waits_then_submits_once(tmp_path, monkeypatch, blocked_stage):
    import threading

    from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    submitted = []
    green = SimpleNamespace(execution_id="slow", work=tmp_path, git_dir=tmp_path / "absent")
    monkeypatch.setattr(start.forge_code_projects, "thomas_source_repo_root", lambda: tmp_path)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(start.forge_code_store, "new_conversation", lambda *a, **k: {"id": "slow"})
    monkeypatch.setattr(start.forge_code_projects, "forget_conversation", lambda *a: None)

    def bind(*args, **kwargs):
        entered.set()
        release.wait(2)
        finished.set()

    if blocked_stage == "conversation":

        def create(*args, **kwargs):
            bind()
            return {"id": "slow"}

        monkeypatch.setattr(start.forge_code_store, "new_conversation", create)
        monkeypatch.setattr(start.forge_code_projects, "bind_conversation", lambda *a, **k: None)
    else:
        monkeypatch.setattr(start.forge_code_projects, "bind_conversation", bind)

    async def submit(*args, **kwargs):
        submitted.append(True)
        return 200, {}

    async def scenario():
        _quick(monkeypatch, stall=0.15)
        app = {APP_PRAXIS_START_CODE_RUN: submit}
        try:
            task = asyncio.create_task(start.start_thomas_project(app, request="fix", settings={}, port=1, green=green))
            assert await asyncio.to_thread(entered.wait, 2)
            await asyncio.sleep(0.3)
            assert not task.done()
            assert submitted == []
            assert app["self_project_listing_slot"]["pending_starts"] == 1
        finally:
            release.set()
            result = await task
        assert result["conversation_id"] == "slow"
        assert finished.is_set()
        assert submitted == [True]
        assert app["self_project_listing_slot"]["pending_starts"] == 0

    asyncio.run(scenario())


def test_legacy_unconfirmed_notice_retries_but_validation_failure_stays():
    legacy = {"id": "old", "failed_at": 100, "reason": "its start could not be confirmed"}
    permanent = {"id": "invalid", "failed_at": 100, "reason": "invalid settings"}
    data = {"queued": [], "given_up": [legacy, permanent]}
    queue._retry_failures(data, [], 100 + queue.RETRY_AFTER_S)
    assert data["given_up"] == [permanent]
    assert [row["id"] for row in data["queued"]] == ["old"]
    assert "could not be confirmed" not in str(data["queued"][0])


def test_failures_have_a_time_and_clear_after_success_or_retry(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    row = {"id": "retry", "tries": queue.MAX_START_TRIES - 1}
    queue._record_failure(row, "disk full", 100)
    assert row["failed_at"] == 100
    data = {"queued": [row], "given_up": [{"id": "done", "failed_at": 100}]}
    queue._retry_failures(data, [{"queue_id": "done"}], 100 + queue.RETRY_AFTER_S)
    assert data["given_up"] == []
    assert row["given_up"] is True
    assert data["queued"][0]["tries"] == queue.MAX_START_TRIES
    queue._retry_failures(data, [{"queue_id": "retry"}], 100 + queue.RETRY_AFTER_S)
    assert data["queued"] == []
    # A registered success clears an exhausted failure without another start attempt.
    data = {
        "queued": [],
        "given_up": [
            {
                "id": "old",
                "failed_at": 100,
                "reason": "The server stopped before this project registered a start. It will retry.",
            }
        ],
    }
    queue._retry_failures(data, [], 100 + queue.RETRY_AFTER_S)
    assert not data["given_up"]
    assert data["queued"][0]["id"] == "old"


class LocalizedDiskFull(OSError):
    def __str__(self):
        return "disque plein"


@pytest.mark.parametrize(
    "reason", ["disk full", "[WinError 112] disque plein", LocalizedDiskFull(errno.ENOSPC, "plein")]
)
def test_exhausted_disk_failure_rearms_only_after_space_recovers(tmp_path, monkeypatch, reason):
    from types import SimpleNamespace

    from tests.test_a_self_project_queue import CLAUDE, _room
    from thomas.server import self_project_queue as store

    _room(monkeypatch)

    async def run():
        app = {"self_project_listing_slot": {"snapshot": {"projects": [], "unreadable": []}}}
        port = 8899
        disk = {"free": 0}
        monkeypatch.setattr(queue.shutil, "disk_usage", lambda _path: SimpleNamespace(free=disk["free"]))
        row = store.enqueue(tmp_path, "repair", CLAUDE, "", port)
        clock = {"now": 1000.0}
        monkeypatch.setattr(queue.time, "time", lambda: clock["now"])

        async def start_project(*_args, **_kwargs):
            if not disk["free"]:
                if isinstance(reason, Exception):
                    raise reason
                raise thomas_project.ThomasProjectError(reason)
            return {"conversation_id": "recovered", "execution_id": "exec_recovered"}

        monkeypatch.setattr(thomas_project, "start_thomas_project", start_project)
        for _ in range(queue.MAX_START_TRIES):
            stored = store.read(tmp_path)["queued"][0]
            await queue._start(app, tmp_path, stored, port)
            clock["now"] += queue.RETRY_AFTER_S
        exhausted = store.read(tmp_path)["queued"][0]
        assert exhausted["given_up"] and exhausted["failed_at"]
        app["self_project_listing_slot"].pop("dirty", None)
        assert queue._select(tmp_path, app, port, queue.time.time()) is None
        disk["free"] = 1024**3
        selected = queue._select(tmp_path, app, port, queue.time.time())
        assert selected and selected["id"] == row["id"], store.read(tmp_path)
        assert not selected.get("given_up")
        assert not selected.get("last_reason")
        assert not selected.get("failed_at")
        await queue._start(app, tmp_path, selected, port)
        assert store.read(tmp_path)["queued"] == []

    asyncio.run(run())


def test_failure_time_is_rendered_in_existing_queue_panel():
    source = Path("thomas/server/web/js/self_edit_controls.js").read_text(encoding="utf-8")
    assert "<time>" in source
    assert "row.failed_at || row.last_tried_at || row.queued_at" in source


def test_permission_failure_rearms_only_after_denied_path_is_writable(tmp_path, monkeypatch):
    from thomas.server import self_project_queue as store

    denied = tmp_path / "project.json"
    denied.write_text("{}")
    enqueued = store.enqueue(tmp_path, "repair", {}, "", 1)
    row = next(row for row in store.read(tmp_path)["queued"] if row["id"] == enqueued["id"])
    original = Path.open
    blocked = True

    def access(path, *args, **kwargs):
        if path == denied and blocked and args and "+" in args[0]:
            raise PermissionError(13, "access denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", access)

    async def refused(*args, **kwargs):
        with denied.open("r+b"):
            pass
        return {"conversation_id": "started", "execution_id": "run"}

    monkeypatch.setattr(queue.thomas_project, "start_thomas_project", refused)
    monkeypatch.setattr(queue.time, "time", lambda: 100.0)
    app = {"self_project_listing_slot": {}}
    for _ in range(queue.MAX_START_TRIES):
        asyncio.run(queue._start(app, tmp_path, row, 1))
    data = store.read(tmp_path)
    assert data["queued"][0]["given_up"]
    queue._retry_failures(data, [], 100 + queue.RETRY_AFTER_S + 1)
    assert data["queued"][0]["given_up"]
    blocked = False
    queue._retry_failures(data, [], 100 + queue.RETRY_AFTER_S + 1)
    recovered = data["queued"][0]
    assert recovered["tries"] == 0
    assert not recovered.get("given_up")
    assert not recovered.get("failed_at")
    asyncio.run(queue._start(app, tmp_path, recovered, 1))
    assert store.read(tmp_path)["started"][0]["conversation_id"] == "started"


def test_legacy_given_up_does_not_retry_an_unresolved_failure():
    row = {"id": "retry", "given_up": True, "last_reason": "still broken", "tries": 5, "failed_at": 1}
    data = {"given_up": [row], "queued": []}
    queue._retry_failures(data, [], queue.RETRY_AFTER_S + 2)
    assert data["given_up"] == [row]
    assert data["queued"] == []


def _registered_start(tmp_path, monkeypatch, submitted):
    """A start whose conversation and registry steps are instant, so only what the test slows down can hold it."""
    from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN

    green = SimpleNamespace(execution_id="slow", work=tmp_path, git_dir=tmp_path / "absent")
    monkeypatch.setattr(start.forge_code_projects, "thomas_source_repo_root", lambda: tmp_path)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(start.forge_code_store, "new_conversation", lambda *a, **k: {"id": "c"})
    monkeypatch.setattr(start.forge_code_projects, "bind_conversation", lambda *a, **k: None)
    monkeypatch.setattr(start.forge_code_projects, "forget_conversation", lambda *a: None)

    async def submit(body, **kwargs):
        submitted.append(body["message"])
        return 200, {}

    return {APP_PRAXIS_START_CODE_RUN: submit}, green


@pytest.mark.parametrize("slow", ["siblings", "lessons"])
def test_a_slow_advisory_note_never_refuses_a_start(tmp_path, monkeypatch, slow):
    """Slow advisory reads finish before the start proceeds; elapsed time never skips their result."""
    import threading

    release = threading.Event()
    submitted: list[str] = []
    app, green = _registered_start(tmp_path, monkeypatch, submitted)
    monkeypatch.setattr(start, "NOTE_S", 0.1, raising=False)

    def stuck(*args):
        release.wait(3)
        return {} if slow == "siblings" else ""

    monkeypatch.setattr(start.green_handoff, "sibling_changes", stuck if slow == "siblings" else lambda _id: {})
    monkeypatch.setattr(start.repair_ledger, "lessons_note", stuck if slow == "lessons" else lambda: "")

    async def scenario():
        _quick(monkeypatch, stall=0.4)
        task = asyncio.create_task(start.start_thomas_project(app, request="fix", settings={}, port=1, green=green))
        try:
            await asyncio.sleep(0.6)
            assert not task.done()
            assert submitted == []
        finally:
            release.set()
            result = await task
        assert result["conversation_id"] == "c"

    asyncio.run(scenario())
    assert len(submitted) == 1


def test_a_waiting_note_reports_its_stage_and_elapsed_time(tmp_path, monkeypatch, caplog):
    """A quiet wait reports its own stage and elapsed seconds without refusing the start."""
    import threading

    release = threading.Event()
    app, green = _registered_start(tmp_path, monkeypatch, [])
    caplog.set_level("INFO", logger="thomas.server.thomas_project_stall")

    def siblings(_id):
        release.wait(3)
        return {}

    monkeypatch.setattr(start.green_handoff, "sibling_changes", siblings)

    async def scenario():
        _quick(monkeypatch, stall=0.2)
        task = asyncio.create_task(start.start_thomas_project(app, request="fix", settings={}, port=1, green=green))
        try:
            await asyncio.sleep(0.4)
            assert not task.done()
            messages = [record.getMessage() for record in caplog.records]
            assert any("seconds elapsed while reading what the other projects" in message for message in messages)
        finally:
            release.set()
            await task

    asyncio.run(scenario())
