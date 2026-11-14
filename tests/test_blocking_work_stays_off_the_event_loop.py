"""Each measured hot spot now does less work, and does it off the loop.

Moving a slow call to a worker thread stops it freezing the server. It does not
make it fast, and four of the eleven places found in the 2026-09-24 sweep were
slow because they asked the same expensive question over and over:

* ``change_evidence`` read ``git status`` twice per file (50 files measured at
  9.7-13.3 s).
* ``conversation_roots`` re-resolved 213 registered folders on every call, four
  times per chat turn (433-505 ms each).
* ``session_active_delegations`` rewrote the whole 637-record execution board in
  order to read it, three times per chat turn (218-303 ms each). The route now
  asks once and the board memoizes the answer.
* ``code.find_definition`` walked ``runtime/`` and ``.thomas/`` because the skip
  list did not name them (227.5 s for ``path='.'``).

A deliverable's entry file is the same shape, found by following the delegations
endpoint into what it builds each row from: resolving one walks the whole
workspace, and the URL, the name and the kind of one deliverable each resolved it
again -- three walks per row of a board that is read on every chat turn, and
three per card in the projects catalogue. Serving the file walked it twice more,
on the loop, once for the preview check and once for the response.

Three more were found by following the same rule outwards rather than by the
sweep: the observability endpoints and Mission Control. ``/api/agents/activity``
awaited a ``git status`` with no timeout at all plus a PowerShell process
listing, and it, ``/api/task-bots/executions`` and Mission Control's snapshot
each re-derived the whole execution board, all on the loop -- and Mission
Control's stream re-runs its snapshot every couple of seconds for as long as the
page is open. Those are asserted by the thread the work actually ran on, which is
the most direct statement of "not on the loop" available.

The last group was found the same way, by following what a Build run does while
it runs: a run that changes Thomas measures itself by walking the whole private
copy and hashing every byte of it, once before each attempt and once after. That
ran on the loop, so the server went quiet for seconds at a time precisely while
it was working on itself.

These tests count the work rather than timing it, so they hold on any machine.

The exception is the pair about claiming a revert approval exactly once.
A race cannot be counted, so it is staged: eight threads are released into the
claim window together and the clock that window reads is slowed to widen it.
The control runs the identical race with the lock removed and requires it to be
lost, so the test beside it is measuring the lock and not the schedule.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from thomas.core.event_loop_offload import reset_offload_receipts, slowest_offloads
from thomas.forge.anvil import forge_code_conversations as conversations
from thomas.forge.anvil import forge_code_git, forge_code_projects
from thomas.server import chat_delegation_live_repo as live_repo
from thomas.server import chat_delegation_runner as runner
from thomas.server import chat_delegation_session as delegation
from thomas.server.routes import chat_v2_turn_inputs as turn_inputs
from thomas.server.routes import deliverable_aiohttp as deliverables
from thomas.server.routes import deliverable_listing, observability
from thomas.server.routes import evolve_agent_revert as revert
from thomas.server.routes import local_projects_generated as generated
from thomas.server.routes import mission_control_routes as mission_control
from thomas.tools import code_search_scan as scan

_FILES = [f"page{index}.html" for index in range(6)]


class _SlowClock:
    """A stand-in for the ``time`` module whose ``time()`` takes measurable time.

    A race that cannot be lost is not evidence of a lock. This widens the one
    window under test -- nothing else sees it, because it replaces the name
    ``time`` inside one module rather than the module itself -- and anything
    other than ``time()`` is served by the real module unchanged.
    """

    def __init__(self, *, delay_s: float) -> None:
        self._delay_s = delay_s

    def time(self) -> float:
        time.sleep(self._delay_s)
        return time.time()

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


def test_change_evidence_reads_git_status_once_for_the_whole_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """One status read, not two per file. That ratio was the whole cost."""
    subcommands: list[str] = []

    def fake_run_git(_root, args, timeout=30):
        subcommands.append(args[0])
        if args[0] == "status":
            return 0, "\0".join(f"?? {name}" for name in _FILES), ""
        return 0, f"+++ b/{args[-1]}\n+new\n", ""

    monkeypatch.setattr(forge_code_git, "_run_git", fake_run_git)
    rows = forge_code_git.change_evidence("/repo", list(_FILES))

    assert [row["file"] for row in rows] == _FILES
    assert all(row["untracked"] is True for row in rows)
    assert all(row["diff"] for row in rows), "the diffs must still be real git output"
    assert subcommands.count("status") == 1, f"status was read {subcommands.count('status')} times for 6 files"
    assert subcommands.count("diff") == len(_FILES), "a diff IS per file; only the status never was"


def test_conversation_roots_is_not_re_derived_for_every_caller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Four calls in one chat turn resolve the registry once."""
    catalog = tmp_path / "catalog"
    project = tmp_path / "project"
    for folder in (catalog, project):
        (folder / ".git").mkdir(parents=True)

    registry_dir = catalog / ".thomas" / "evolve" / "agent"
    registry_dir.mkdir(parents=True)
    (registry_dir / "project_registry.json").write_text(
        json.dumps({"conv-1": {"project_root": str(project)}}), encoding="utf-8"
    )

    resolved: list[str] = []
    real_validate = forge_code_projects.validate_project_root

    def counting_validate(value, **kwargs):
        resolved.append(str(value))
        return real_validate(value, **kwargs)

    monkeypatch.setattr(forge_code_projects, "validate_project_root", counting_validate)
    conversations.reset_conversation_roots_cache()

    first = conversations.conversation_roots(catalog)
    for _ in range(3):
        assert conversations.conversation_roots(catalog) == first

    assert set(first) == {catalog.resolve(), project.resolve()}
    assert len(resolved) == 2, f"resolved {len(resolved)} folders for four identical calls"


def test_binding_a_conversation_invalidates_the_memoized_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Memoizing must never hide a folder somebody just bound."""
    catalog = tmp_path / "catalog"
    later = tmp_path / "added-later"
    for folder in (catalog, later):
        (folder / ".git").mkdir(parents=True)
    monkeypatch.setattr(forge_code_projects, "shield_thomas_dir", lambda _root: None)

    conversations.reset_conversation_roots_cache()
    assert conversations.conversation_roots(catalog) == [catalog.resolve()]

    conversations.bind_conversation(catalog, "conv-2", later)

    assert later.resolve() in conversations.conversation_roots(catalog)


def test_reading_the_execution_board_does_not_rewrite_it_every_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A read is a read. Rewriting the summary to read it cost 218-303 ms a turn."""
    board = tmp_path / "runtime" / "coordination" / "task_bots"
    board.mkdir(parents=True)
    (board / "exec-1.json").write_text(json.dumps({"execution_id": "exec-1"}), encoding="utf-8")

    refreshes: list[bool] = []

    def fake_list_executions(_root, *, refresh=True, **_kwargs):
        refreshes.append(bool(refresh))
        return [{"execution_id": "exec-1", "conversation_id": "sess-1", "updated_at": "2026-09-24T00:00:00+00:00"}]

    monkeypatch.setattr(delegation.task_bot_runtime, "runtime_dir", lambda _root=None: board)
    monkeypatch.setattr(delegation.task_bot_runtime, "list_executions", fake_list_executions)
    monkeypatch.setattr(delegation.task_bot_runtime, "get_execution", lambda _eid, _root=None: None)
    monkeypatch.setattr(delegation, "_resolve_repo_root", lambda repo_root=None: tmp_path)
    # Pinned so a slow machine cannot expire the window mid-test; the window's own
    # length is a judgement call, and what this test is about is the count.
    monkeypatch.setattr(delegation, "_BOARD_TTL_S", 60.0)
    delegation.reset_board_cache()

    # Repeated reads inside one window: the board is derived once and served.
    for _ in range(3):
        assert len(delegation.session_active_delegations("sess-1", repo_root=tmp_path)) == 1

    assert len(refreshes) == 1, f"the board was re-derived {len(refreshes)} times for three identical reads"


def test_a_new_execution_record_is_never_served_from_the_memo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Freshness is the point of the board; the memo must yield to a written record."""
    board = tmp_path / "runtime" / "coordination" / "task_bots"
    board.mkdir(parents=True)
    (board / "exec-1.json").write_text("{}", encoding="utf-8")

    rows = [{"execution_id": "exec-1", "conversation_id": "sess-1", "updated_at": ""}]

    monkeypatch.setattr(delegation.task_bot_runtime, "runtime_dir", lambda _root=None: board)
    monkeypatch.setattr(delegation.task_bot_runtime, "list_executions", lambda _root, **_kw: list(rows))
    monkeypatch.setattr(delegation.task_bot_runtime, "get_execution", lambda _eid, _root=None: None)
    monkeypatch.setattr(delegation, "_resolve_repo_root", lambda repo_root=None: tmp_path)
    monkeypatch.setattr(delegation, "_BOARD_TTL_S", 60.0)
    delegation.reset_board_cache()

    assert len(delegation.session_active_delegations("sess-1", repo_root=tmp_path)) == 1

    (board / "exec-2.json").write_text("{}", encoding="utf-8")
    rows.append({"execution_id": "exec-2", "conversation_id": "sess-1", "updated_at": ""})

    assert len(delegation.session_active_delegations("sess-1", repo_root=tmp_path)) == 2, (
        "a written record must invalidate the memo"
    )


def test_a_chat_turn_gathers_its_blocking_reads_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The turn's reads, gathered in one place before the reply stream opens.

    The board used to be read once for the prompt and again beside the brain
    call, for the same answer. The catalog is skipped entirely when the turn
    cannot dispatch work, because then nothing reads it.
    """
    reads: list[str] = []

    def fake_delegations(_session_id: str) -> list[dict[str, Any]]:
        reads.append("board")
        return [{"execution_id": "exec-1"}]

    def fake_digest(_session_id: str) -> str:
        reads.append("digest")
        return "one task running"

    def fake_catalog(_prompt: str) -> str:
        reads.append("catalog")
        return "\n[projects]"

    monkeypatch.setattr(turn_inputs, "session_active_delegations", fake_delegations)
    monkeypatch.setattr(turn_inputs, "build_active_task_digest", fake_digest)
    monkeypatch.setattr(turn_inputs, "build_project_catalog_context", fake_catalog)

    builder = asyncio.run(turn_inputs.gather_turn_inputs("sess-1", "ship it", can_build=True))

    assert reads == ["board", "digest", "catalog"]
    assert builder.task_digest == "one task running"
    assert builder.project_catalog == "\n[projects]"

    reads.clear()
    talker = asyncio.run(turn_inputs.gather_turn_inputs("sess-1", "hello", can_build=False))

    assert reads == ["board", "digest"], "a turn that cannot build must not pay for the catalog"
    assert talker.project_catalog == ""


_WORKERS = 8


def _race_eight_reverts_for_one_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Put eight concurrent authorizations inside the claim window at once.

    Two things together make this able to see a missing lock. The barrier lines
    every thread up at the hash, immediately before the window; and the clock
    the window itself reads is slowed, because the window is a handful of
    bytecodes long and the GIL will not interrupt it on its own. ``time.time()``
    is called inside it -- between reading ``state == "approved"`` and writing
    ``"executing"`` -- so a slow clock holds every thread there together. Only
    ``revert``'s own reference to the module is replaced, not the module.
    """
    approvals: dict[str, dict[str, Any]] = {
        "approval-1": {
            "id": "approval-1",
            "state": "approved",
            "action_hash": "fixed-hash",
            "expires_at": 4_102_444_800.0,  # year 2100
        }
    }
    gate = threading.Barrier(_WORKERS)

    def hash_at_the_same_moment(*_args, **_kwargs):
        gate.wait(timeout=5)
        return "fixed-hash"

    monkeypatch.setattr(revert, "_revert_action_hash", hash_at_the_same_moment)
    monkeypatch.setattr(revert.forge_code_git, "file_is_dirty", lambda _root, _file: True)
    monkeypatch.setattr(revert, "time", _SlowClock(delay_s=0.005))

    claims: list[bool] = []
    claims_lock = threading.Lock()

    def attempt() -> None:
        _file, error, _status = revert._authorize_conversation_revert(
            root=tmp_path,
            conversation_id="conv-1",
            file="notes.md",
            conversation={"turns": [{"role": "agent", "changed_files": ["notes.md"]}]},
            metadata=None,
            approvals=approvals,
            approval_id="approval-1",
        )
        with claims_lock:
            claims.append(error is None)

    threads = [threading.Thread(target=attempt) for _ in range(_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    return sum(claims), approvals


def test_without_the_claim_lock_the_same_approval_is_claimed_twice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The control. Without it, the test below could be passing on timing alone."""
    monkeypatch.setattr(revert, "_CLAIM_LOCK", contextlib.nullcontext())

    claimed, _approvals = _race_eight_reverts_for_one_approval(monkeypatch, tmp_path)

    assert claimed > 1, f"the race did not reproduce: {claimed} of {_WORKERS} claimed it, so the lock proves nothing"


def test_one_approval_can_only_be_claimed_by_one_concurrent_revert(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Moving authorization off the loop removed what made the claim atomic.

    Approving a revert is a check-then-set on a dict every handler shares. While
    it ran on the single event loop that was atomic for free. It now runs in a
    worker thread because it hashes a file and reads git, so the one-time
    guarantee has to be held by a lock instead -- the one the control above
    removes, and the same race then loses.
    """
    claimed, approvals = _race_eight_reverts_for_one_approval(monkeypatch, tmp_path)

    assert claimed == 1, f"{claimed} of {_WORKERS} concurrent requests claimed the same approval"
    assert approvals["approval-1"]["state"] == "executing"


def test_a_code_scan_never_descends_thomas_own_state_directories(tmp_path: Path) -> None:
    """The 227.5-second walk, in the two directories that caused it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    for hidden in (".thomas", "runtime", "node_modules"):
        (tmp_path / hidden).mkdir()
        (tmp_path / hidden / "buried.py").write_text("x = 2\n", encoding="utf-8")

    found = {
        path.relative_to(tmp_path).as_posix()
        for path in scan.iter_source_files(tmp_path, exts={".py"}, budget=scan.ScanBudget())
    }

    assert found == {"src/app.py"}


def test_runtime_is_only_skipped_where_it_is_thomas_state(tmp_path: Path) -> None:
    """``runtime/`` deeper in a tree is ordinary source -- this repo has one."""
    nested = tmp_path / "web" / "js" / "runtime"
    nested.mkdir(parents=True)
    (nested / "module.js").write_text("// real source\n", encoding="utf-8")

    found = {
        path.relative_to(tmp_path).as_posix()
        for path in scan.iter_source_files(tmp_path, exts={".js"}, budget=scan.ScanBudget())
    }

    assert found == {"web/js/runtime/module.js"}


def test_a_projects_own_folders_at_its_root_are_still_searched(tmp_path: Path) -> None:
    """``runtime/`` is the only name skipped at a root, the same as ``fs.search``.

    A name skipped there is a whole directory of somebody's project made
    invisible to a search that reports no matches, so the list stays at the one
    name that was measured.
    """
    for name in ("output", "artifacts"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "generate.py").write_text("x = 3\n", encoding="utf-8")

    found = {
        path.relative_to(tmp_path).as_posix()
        for path in scan.iter_source_files(tmp_path, exts={".py"}, budget=scan.ScanBudget())
    }

    assert found == {"artifacts/generate.py", "output/generate.py"}
    assert set(scan.ROOT_SKIP_DIRS) == {"runtime"}


def test_a_scan_that_runs_out_of_budget_says_so(tmp_path: Path) -> None:
    """A partial answer that reads as a complete one is worse than a slow one."""
    for index in range(5):
        (tmp_path / f"file{index}.py").write_text("needle\n", encoding="utf-8")

    budget = scan.ScanBudget(max_files=2)
    list(scan.iter_source_files(tmp_path, exts={".py"}, budget=budget))

    assert budget.stopped
    assert "partial" in budget.note()


# Neither handler below reads its request, so this is the whole of what they
# need. A fixture server would only put a client between the test and the one
# thing it measures: which thread the blocking call ran on.
_NO_REQUEST: Any = None


def test_agent_activity_gathers_presence_in_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """``collect_presence`` runs git and lists processes; neither belongs on the loop."""
    ran_on: list[threading.Thread] = []

    def record_presence() -> dict[str, Any]:
        ran_on.append(threading.current_thread())
        return {"agents": []}

    monkeypatch.setattr(observability.agent_presence, "collect_presence", record_presence)
    reset_offload_receipts()

    response = asyncio.run(observability.api_agents_activity(_NO_REQUEST))

    assert response.status == 200
    assert ran_on, "collect_presence was never called"
    assert ran_on[0] is not threading.main_thread(), (
        f"collect_presence ran on {ran_on[0].name}, the thread the event loop runs on"
    )
    assert any(row["label"] == "observability.agent_presence" for row in slowest_offloads())


def _count_entry_resolutions(monkeypatch: pytest.MonkeyPatch, answer: str) -> list[str]:
    """Count every walk of a workspace, wherever the walk is reached from.

    ``deliverable_entry`` is defined in ``deliverable_listing`` and re-exported by
    ``deliverable_aiohttp``, and both names are live: ``deliverable_kind`` calls
    the first, ``deliverable_url`` the second. Replacing one and not the other
    would count half the walks.
    """
    resolved: list[str] = []

    def counting_entry(execution_id: str) -> str:
        resolved.append(str(execution_id))
        return answer

    monkeypatch.setattr(deliverable_listing, "deliverable_entry", counting_entry)
    monkeypatch.setattr(deliverables, "deliverable_entry", counting_entry)
    return resolved


def test_a_delegation_row_walks_its_workspace_once_not_three_times(monkeypatch: pytest.MonkeyPatch) -> None:
    """The URL, the name and the kind are three readings of one resolved entry."""
    resolved = _count_entry_resolutions(monkeypatch, "game.html")

    row = delegation._normalize_record(
        {
            "execution_id": "exec-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"artifacts": [{"path": "game.html"}]},
        }
    )

    assert len(resolved) == 1, f"one finished row walked its workspace {len(resolved)} times"
    # Unchanged answers: the point is the count, not a different reading.
    assert row["artifact_url"] == "/deliverable/exec-1/game.html"
    assert row["artifact_name"] == "game.html"
    assert row["artifact_kind"] == "web"


def test_a_generated_project_card_walks_its_workspace_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The same three readings, in the catalogue a project picker opens with."""
    resolved = _count_entry_resolutions(monkeypatch, "report.pdf")

    def counting_entry(execution_id: str, *, record: dict[str, Any] | None = None) -> str:
        resolved.append(str(execution_id))
        return "report.pdf"

    # This module holds its own reference to the name, so it gets the same counter.
    monkeypatch.setattr(generated, "deliverable_entry", counting_entry)
    monkeypatch.setattr(generated, "_workspace_dir", lambda _eid: tmp_path)

    card = generated._generated_deliverable_project({"execution_id": "exec-2", "state": "completed"})

    assert card is not None, "a finished run with a deliverable must still be listed"
    assert card["framework"] == "Generated PDF"
    assert len(resolved) == 1, f"one card walked its workspace {len(resolved)} times"


class _DeliverableRouter:
    """Just enough of ``app.router`` to keep the handler that gets registered."""

    def __init__(self) -> None:
        self.gets: dict[str, Any] = {}

    def add_get(self, path: str, handler: Any) -> None:
        self.gets[path] = handler


class _DeliverableApp(dict):
    """An application is a mapping plus a router, and that is all this needs."""

    def __init__(self) -> None:
        super().__init__()
        self.router = _DeliverableRouter()


class _LoopbackTransport:
    def get_extra_info(self, name: str) -> Any:
        return ("127.0.0.1", 12345) if name == "peername" else None


class _DeliverableRequest:
    """``GET /deliverable/exec-1`` -- no tail, so the entry has to be resolved."""

    transport = _LoopbackTransport()
    match_info = {"execution_id": "exec-1"}
    query: dict[str, str] = {}


def test_serving_a_deliverable_resolves_its_entry_once_and_off_the_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Opening a task card's result must not walk the workspace on the loop."""
    (tmp_path / "report.txt").write_text("done\n", encoding="utf-8")
    ran_on: list[threading.Thread] = []

    def record_entry(_execution_id: str) -> str:
        ran_on.append(threading.current_thread())
        return "report.txt"

    monkeypatch.setattr(deliverables, "deliverable_entry", record_entry)
    # Resolved, because the handler's path-traversal guard compares a resolved
    # target against this and a temp directory can be reached by another name.
    monkeypatch.setattr(deliverables, "_workspace_dir", lambda _eid: tmp_path.resolve())
    reset_offload_receipts()

    app = _DeliverableApp()
    deliverables.register_deliverable_routes(app, require_api_access=lambda _request: None)
    handler = app.router.gets["/deliverable/{execution_id}"]

    response = asyncio.run(handler(_DeliverableRequest()))

    assert response.status == 200
    assert len(ran_on) == 1, f"one request walked the workspace {len(ran_on)} times"
    assert ran_on[0] is not threading.main_thread(), (
        f"the workspace was walked on {ran_on[0].name}, the thread the event loop runs on"
    )
    assert any(row["label"] == "deliverable.entry" for row in slowest_offloads())


def test_the_task_bot_endpoint_does_not_rebuild_the_board_on_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """``read_summary(refresh=True)`` rewrites the whole board: 218-303 ms, measured."""
    ran_on: list[threading.Thread] = []

    def record_summary(**_kwargs: Any) -> dict[str, Any]:
        ran_on.append(threading.current_thread())
        return {"active_count": 0}

    monkeypatch.setattr(observability.task_bot_runtime, "read_summary", record_summary)

    response = asyncio.run(observability.api_task_bot_executions(_NO_REQUEST))

    assert response.status == 200
    assert ran_on, "read_summary was never called"
    assert ran_on[0] is not threading.main_thread(), (
        f"the board was re-derived on {ran_on[0].name}, the thread the event loop runs on"
    )


class _MissionApp(dict):
    """The application the Mission Control builders read their stores out of."""


class _MissionRequest:
    """No handler below reads anything but the query string."""

    query: dict[str, str] = {}


class _RecordingAutonomyStore:
    """Every list the snapshot asks for, recording which thread asked."""

    def __init__(self, ran_on: list[threading.Thread]) -> None:
        self._ran_on = ran_on

    def _record(self) -> list[Any]:
        self._ran_on.append(threading.current_thread())
        return []

    def list_jobs(self, **_kwargs: Any) -> list[Any]:
        return self._record()

    def list_objectives(self, **_kwargs: Any) -> list[Any]:
        return self._record()

    def list_audit(self, **_kwargs: Any) -> list[Any]:
        return self._record()

    def list_approvals(self, **_kwargs: Any) -> list[Any]:
        return self._record()


def _mission_handler(monkeypatch: pytest.MonkeyPatch, ran_on: list[threading.Thread]) -> Any:
    """The /api/mission-control handler, with its stores replaced by recorders."""

    def record_executions(*_args: Any, **_kwargs: Any) -> list[Any]:
        ran_on.append(threading.current_thread())
        return []

    monkeypatch.setattr(mission_control.task_bot_runtime, "list_executions", record_executions)

    def no_desktop_operator() -> Any:
        # The desktop operator asks the host service for its posture. Not this
        # test's subject, and the builder already treats an unavailable one as
        # "no desktop work" rather than an error.
        raise RuntimeError("no desktop operator in a test")

    monkeypatch.setattr(
        "thomas.desktop_operator.manager.get_global_desktop_operator_manager",
        no_desktop_operator,
    )
    app = _MissionApp()
    app["autonomy_store"] = _RecordingAutonomyStore(ran_on)
    handler, _stream, _approvals = mission_control.build_mission_control_routes(
        app,
        require_api_access=lambda _request: None,
        run_store_enabled_key="run_store_enabled",
        run_store_module_key="run_store_module",
    )
    return handler


def test_the_mission_control_snapshot_is_built_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The board that shows the work must not be the thing that stops it.

    Every read here is disk: the execution summary is rebuilt from scratch
    (``list_executions(refresh=True)``, measured at 218-303 ms on a 637-record
    board) and the autonomy store is four SQLite queries behind one lock. The
    stream re-runs all of it about every two seconds for as long as anyone has
    Mission Control open, which is exactly while builds and cards are running.
    """
    ran_on: list[threading.Thread] = []
    handler = _mission_handler(monkeypatch, ran_on)
    reset_offload_receipts()

    response = asyncio.run(handler(_MissionRequest()))

    assert response.status == 200
    assert ran_on, "the snapshot read none of its stores"
    on_the_loop = [thread.name for thread in ran_on if thread is threading.main_thread()]
    assert not on_the_loop, f"{len(on_the_loop)} of the snapshot's reads ran on the event loop thread"
    labels = {row["label"] for row in slowest_offloads()}
    assert {"mission_control.snapshot", "mission_control.approvals"} <= labels, (
        f"the snapshot and its approvals must each be recorded as kept off the loop: {sorted(labels)}"
    )


def test_an_attempt_measures_its_change_baseline_in_a_worker_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The baseline opens and hashes every file in the work copy before a run starts.

    Measured on this checkout: 8,446 files and 98.2 MB, 1.67 s for a native
    read-and-hash alone. It ran at the top of every attempt of a run in which
    Thomas changes Thomas -- on the loop, so the whole server went quiet for it.
    """
    ran_on: list[threading.Thread] = []

    def record_mtimes(root: Path, **_kwargs: Any) -> dict[str, tuple[int, str]]:
        ran_on.append(threading.current_thread())
        return {"thomas/core/config.py": (12, "abc")}

    monkeypatch.setattr(live_repo, "_live_repo_workspace_mtimes", record_mtimes)
    monkeypatch.setattr(live_repo, "_changed_in_green", lambda _root: ["thomas/core/config.py"])
    reset_offload_receipts()

    green, baseline = asyncio.run(live_repo.attempt_change_baseline(tmp_path, tmp_path, in_live_repo=True, attempt=1))

    assert green == ["thomas/core/config.py"], "the green diff the replan prompt reads was lost"
    assert baseline == {"thomas/core/config.py": (12, "abc")}
    assert ran_on, "the baseline was never measured"
    assert ran_on[0] is not threading.main_thread(), (
        f"the baseline was measured on {ran_on[0].name}, the thread the event loop runs on"
    )
    assert any(row["label"] == "delegation.attempt_baseline" for row in slowest_offloads())


def test_a_workspace_run_pays_for_no_green_diff_on_its_first_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``_changed_in_green`` is a git diff. An ordinary first attempt has nothing to ask it."""
    asked: list[Path] = []

    def record_green(root: Path) -> None:
        asked.append(root)
        return None

    monkeypatch.setattr(live_repo, "_changed_in_green", record_green)
    monkeypatch.setattr(live_repo, "_workspace_mtimes", lambda _root, **_kwargs: {})

    green, baseline = asyncio.run(live_repo.attempt_change_baseline(tmp_path, tmp_path, in_live_repo=False, attempt=1))

    assert green is None
    assert baseline == {}
    assert asked == [], f"a first workspace attempt ran {len(asked)} git diffs it cannot use"


def test_the_end_of_an_attempt_scans_for_changed_files_off_the_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The finish of a live-repo attempt walks and hashes the work copy a second time."""
    ran_on: list[threading.Thread] = []

    def record_scan(_root: Path, _baseline: dict[str, Any], **_kwargs: Any) -> list[str]:
        ran_on.append(threading.current_thread())
        return []

    monkeypatch.setattr(runner, "_live_repo_files_changed_since", record_scan)
    reset_offload_receipts()

    with pytest.raises(runner._WorkerRetry):
        asyncio.run(
            runner._finalize_live_repo_completion(
                None, "exec-off-loop", tmp_path, "Fix it.", {}, ["done"], [], [], [], None, "coding"
            )
        )

    assert ran_on, "the change scan never ran"
    assert ran_on[0] is not threading.main_thread(), (
        f"the change scan ran on {ran_on[0].name}, the thread the event loop runs on"
    )
    assert any(row["label"] == "delegation.changed_since" for row in slowest_offloads())


class _RecordingClient:
    def __init__(self, ran_on: list[threading.Thread], **_kwargs: Any) -> None:
        ran_on.append(threading.current_thread())
        self.is_closed = False

    async def aclose(self) -> None:
        self.is_closed = True


def test_a_model_calls_http_client_is_built_off_the_loop() -> None:
    """Found by the lag watcher: loading the CA bundle held a chat turn for 0.4-0.8 s."""
    from types import SimpleNamespace

    from thomas.core import llm_transport_pool

    ran_on: list[threading.Thread] = []
    fake_httpx = SimpleNamespace(
        AsyncClient=lambda **kwargs: _RecordingClient(ran_on, **kwargs),
        Timeout=lambda **_kwargs: None,
    )
    owner = SimpleNamespace(
        _client=None,
        config=SimpleNamespace(extra_headers={}, api_key="", provider="openai", timeout_s=30.0),
    )
    reset_offload_receipts()

    client = asyncio.run(llm_transport_pool.get_http_client(owner, httpx_module=fake_httpx))

    assert owner._client is client
    assert ran_on and ran_on[0] is not threading.main_thread(), (
        f"the HTTP client was built on {ran_on[0].name}, the thread the event loop runs on"
    )
    assert any(row["label"] == "llm.http_client" for row in slowest_offloads())
