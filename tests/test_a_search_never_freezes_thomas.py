"""A search in a Chat turn never freezes Thomas.

Measured 2026-09-23: `fs.search` was `async` but never awaited. It walked the chat's
sandbox -- the repo, `runtime/` and `.thomas/` included -- on the server's event loop,
and one search that found nothing held that loop for 543 s over 259,348 files. Every
background worker reports through that loop and is judged by a watchdog that lives on
it, so four working self-fix workers froze with it and were failed together the moment
it came back. You asked: "make them fix ... performance".

Every tree here is built in a tmp dir; nothing walks the real repo or data dir.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thomas.server import chat_delegation_runner as runner
from thomas.tools import filesystem
from thomas.tools.filesystem import ListDirTool, SearchFilesTool


def _tree(root: Path, *, dirs: int, files_per_dir: int, text: str = "nothing to see\n") -> None:
    for d in range(dirs):
        folder = root / "src" / f"pkg{d:03d}"
        folder.mkdir(parents=True)
        for f in range(files_per_dir):
            (folder / f"mod{f:03d}.py").write_text(text, encoding="utf-8")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _longest_loop_gap(work) -> tuple[object, float]:  # noqa: ANN001 - any awaitable
    """Await *work* while a ticker records the longest stretch the loop could not run."""
    gaps: list[float] = []
    done = False

    async def ticker() -> None:
        last = time.perf_counter()
        while not done:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    ticking = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    result = await work
    done = True
    await ticking
    return result, max(gaps)


def _slow_per_file(monkeypatch, seconds: float) -> None:  # noqa: ANN001
    """Make every file the search looks at cost *seconds*, so a walk takes measurable time."""
    real = filesystem._is_read_protected_path

    def slow(root: Path, target: Path):  # noqa: ANN202
        time.sleep(seconds)
        return real(root, target)

    monkeypatch.setattr(filesystem, "_is_read_protected_path", slow)


def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    _tree(tmp_path, dirs=3, files_per_dir=20)
    _slow_per_file(monkeypatch, 0.01)  # 60 files -> about 0.6 s of walking

    result, gap = asyncio.run(_longest_loop_gap(SearchFilesTool(tmp_path).execute({"pattern": "zzqx_no_such"})))

    assert result.ok and "searched 60 files" in result.data
    assert gap < 0.25, f"the event loop could not run for {gap:.2f}s while the search walked"


def test_a_recursive_listing_runs_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    _tree(tmp_path, dirs=30, files_per_dir=1)
    real_scandir = os.scandir

    def slow_scandir(*args):  # noqa: ANN002, ANN202
        time.sleep(0.02)  # 30 directories -> at least 0.6 s of walking
        return real_scandir(*args)

    monkeypatch.setattr(os, "scandir", slow_scandir)
    result, gap = asyncio.run(_longest_loop_gap(ListDirTool(tmp_path).execute({"pattern": "**/*.py"})))

    assert result.ok and str(Path("src/pkg029/mod000.py")) in result.data
    assert gap < 0.25, f"the event loop could not run for {gap:.2f}s while the listing walked"


def test_a_walk_skips_thomas_data_and_dependency_dirs(tmp_path: Path) -> None:
    for rel in (
        "runtime/logs/today.log",
        ".thomas/runs/run.txt",
        ".git/HEAD",
        "node_modules/pkg/index.js",
        ".venv/lib/site.py",
        "src/__pycache__/keep.cpython-312.pyc",
    ):
        _write(tmp_path, rel, "needle\n")
    _write(tmp_path, "src/keep.py", "x = 1\nneedle = 2\n")
    # Deeper down, `runtime` is an ordinary source folder name (this repo has one).
    _write(tmp_path, "web/js/runtime/keep.js", "// needle\n")

    search = asyncio.run(SearchFilesTool(tmp_path).execute({"pattern": "needle"}))
    lines = search.data.splitlines()
    assert lines[0] == "Found 2 matches (searched 2 files):"
    assert sorted(lines[1:]) == sorted(
        [f"{Path('src/keep.py')}:2: needle = 2", f"{Path('web/js/runtime/keep.js')}:1: // needle"]
    )

    listing = asyncio.run(ListDirTool(tmp_path).execute({"pattern": "**/*", "max_results": 500}))
    assert listing.data.splitlines() == [
        f"{Path('src')}/",
        f"{Path('src/keep.py')}",
        f"{Path('web')}/",
        f"{Path('web/js')}/",
        f"{Path('web/js/runtime')}/",
        f"{Path('web/js/runtime/keep.js')}",
    ]


def test_a_search_stops_at_its_file_budget_and_says_so(tmp_path: Path) -> None:
    _tree(tmp_path, dirs=5, files_per_dir=10)

    result = asyncio.run(SearchFilesTool(tmp_path, max_files=20).execute({"pattern": "zzqx_no_such"}))

    assert result.ok
    assert result.data.startswith("No matches found (searched 20 files)")
    assert "Stopped early" in result.data and "20-file budget" in result.data


def test_a_search_stops_at_its_time_budget_and_says_so(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    _tree(tmp_path, dirs=2, files_per_dir=20)
    _slow_per_file(monkeypatch, 0.05)  # 40 files -> about 2 s unbudgeted

    started = time.perf_counter()
    result = asyncio.run(SearchFilesTool(tmp_path, max_seconds=0.3).execute({"pattern": "zzqx_no_such"}))
    took = time.perf_counter() - started

    assert "Stopped early" in result.data and "time budget" in result.data
    assert took < 1.0, f"a 0.3 s time budget let the search run {took:.2f}s"


def test_the_time_budget_holds_inside_one_huge_file(tmp_path: Path) -> None:
    """One read_text() of a big file is a single call nothing can interrupt, and while it
    decodes it holds the GIL, so the loop stalls too (a 116 MB build cache in this repo
    measured 0.4 s). Read in chunks, the budget is checked between them."""
    (tmp_path / "huge.log").write_text("line\n" * 4_000_000, encoding="utf-8")

    started = time.perf_counter()
    result = asyncio.run(SearchFilesTool(tmp_path, max_seconds=0.2).execute({"pattern": "zzqx_no_such"}))
    took = time.perf_counter() - started

    assert "Stopped early" in result.data and "time budget" in result.data
    assert took < 0.8, f"a 0.2 s time budget let one file take {took:.2f}s"


def test_chunked_reading_gives_the_lines_read_text_gives(tmp_path: Path) -> None:
    """Line numbers must not move: CRLF, lone CR, form feed and a missing final newline."""
    text = "a needle\r\nb\rc needle\x0cd\n\ne needle" + "x" * (filesystem._SEARCH_CHUNK_CHARS - 3) + "\nf needle"
    (tmp_path / "mixed.txt").write_bytes(text.encode("utf-8"))

    result = asyncio.run(SearchFilesTool(tmp_path).execute({"pattern": "needle"}))

    expected = [
        f"mixed.txt:{n}: {line}"
        for n, line in enumerate((tmp_path / "mixed.txt").read_text(encoding="utf-8").splitlines(), 1)
        if "needle" in line
    ]
    assert result.data.splitlines()[1:] == expected


def test_a_recursive_listing_stops_at_its_budget_and_says_so(tmp_path: Path) -> None:
    _tree(tmp_path, dirs=10, files_per_dir=10)

    result = asyncio.run(ListDirTool(tmp_path, max_files=25).execute({"pattern": "**/*.py", "max_results": 500}))

    assert result.ok and "Stopped early" in result.data and "25-file budget" in result.data


# ── The watchdog: a worker is judged by its own silence, not the server's ──
# The four workers above were not silent. Their progress waited on the frozen loop,
# the watchdog that judged them ran on it too, and when it came back every overdue
# check fired at once. A fifth worker's thread ran on after its card said failed and
# started "attempt 2 of 12".

EXECUTION_ID = "exec-judged-by-its-own-silence"
_TERMINAL = ("failed", "cancelled", "completed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Bot:
    id = "nova"
    name = "Nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


class _Store:
    """The task record the worker thread and the watchdog share, in memory and thread-safe."""

    def __init__(self, progress: str = "Reading files…") -> None:
        self._lock = threading.Lock()
        self.record = {
            "execution_id": EXECUTION_ID,
            "state": "executing",
            "progress_summary": progress,
            "last_heartbeat_at": _now_iso(),
        }
        self.writes: list[str] = []

    def get(self, *_args, **_kwargs) -> dict:  # noqa: ANN002, ANN003
        with self._lock:
            return dict(self.record)

    def update(self, _execution_id, *, progress_summary=None, state=None, blocker=None, **_kwargs):  # noqa: ANN001, ANN003, ANN201
        with self._lock:
            if progress_summary is not None:
                self.record["progress_summary"] = progress_summary
            if state is not None:
                self.record["state"] = state
            if blocker is not None:
                self.record["blocker"] = blocker
            if self.record["state"] not in _TERMINAL:
                self.record["last_heartbeat_at"] = _now_iso()
            self.writes.append(str(progress_summary))
            return dict(self.record)

    def fail(self, execution_id, *, summary="", blocker="", **_kwargs):  # noqa: ANN001, ANN003, ANN201
        return self.update(execution_id, state="failed", progress_summary=summary, blocker=blocker)


def _use_store(monkeypatch, store: _Store, *, window_s: float) -> None:  # noqa: ANN001
    """Point the runner at *store*, with a short watchdog window and no grace."""
    from thomas.core import task_bot_runtime

    monkeypatch.setattr(task_bot_runtime, "get_execution", store.get)
    monkeypatch.setattr(task_bot_runtime, "update_execution", store.update)
    monkeypatch.setattr(task_bot_runtime, "fail_execution", store.fail)
    monkeypatch.setattr(task_bot_runtime, "cancel_execution", lambda *_a, **_k: None)
    monkeypatch.setattr(task_bot_runtime, "is_cancel_requested", lambda *_a, **_k: False)
    monkeypatch.setattr(task_bot_runtime, "take_pending_instructions", lambda *_a, **_k: [])
    monkeypatch.setattr(runner, "record_issue", lambda **_k: None)
    monkeypatch.setattr(runner, "_WORKER_FIRST_EVENT_TIMEOUT_S", window_s)
    monkeypatch.setattr(runner, "_WORKER_IDLE_EVENT_TIMEOUT_S", window_s)
    monkeypatch.setattr(runner, "_WORKER_WATCHDOG_GRACE_S", 0.0)


def _emitter() -> SimpleNamespace:
    return SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())


async def _supervise(worker, store: _Store, tmp_path: Path, **worker_kwargs) -> None:  # noqa: ANN001, ANN003
    await runner._run_agent_worker_supervised(
        worker,
        {},
        execution_id=EXECUTION_ID,
        specialist_id="coding",
        bot=_Bot(),
        emitter=_emitter(),
        repo_root=tmp_path,
        worker_kwargs=worker_kwargs,
    )


def test_a_late_watchdog_blames_the_frozen_loop_not_the_worker(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # 1. The server loop freezes for 1 s -- longer than the 0.4 s window -- while the
    #    worker's heartbeat cannot move. When the loop comes back, the watchdog's first
    #    look sees a worker silent for the whole freeze, and it must not blame it.
    store = _Store()
    freeze = {"at": "", "show_once": False}
    fresh_get = store.get

    def get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        record = fresh_get(*args, **kwargs)
        # A worker that is alive: its heartbeat is fresh, except that the first look
        # after the freeze sees it stuck where the freeze began.
        record["last_heartbeat_at"] = freeze["at"] if freeze["show_once"] else _now_iso()
        freeze["show_once"] = False
        return record

    _use_store(monkeypatch, store, window_s=0.4)
    from thomas.core import task_bot_runtime

    monkeypatch.setattr(task_bot_runtime, "get_execution", get)

    async def worker(_app, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        await asyncio.sleep(1.8)

    async def freeze_the_loop() -> None:
        await asyncio.sleep(0.2)
        freeze["at"] = _now_iso()
        time.sleep(1.0)  # a synchronous walk on the server loop, like the old fs.search
        freeze["show_once"] = True

    async def main() -> None:
        blocker = asyncio.create_task(freeze_the_loop())
        await _supervise(worker, store, tmp_path)
        await blocker

    asyncio.run(main())
    assert store.record["state"] == "executing", f"failed a worker for the loop's freeze: {store.record}"

    # 2. The control: a worker that is genuinely silent is still failed, promptly.
    silent = _Store()
    _use_store(monkeypatch, silent, window_s=0.4)
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *_a, **_k: dict(silent.record))

    async def hung(_app, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        await asyncio.sleep(5)

    async def judged_in() -> float:
        started = time.perf_counter()
        await _supervise(hung, silent, tmp_path)
        return time.perf_counter() - started

    took = asyncio.run(judged_in())
    assert silent.record.get("blocker") == "provider_native_timeout"
    assert took < 2.0, f"a genuinely silent worker took {took:.1f}s to be failed"


@pytest.mark.parametrize("economy", ["cheap", "balanced", "diligent", "max"])
@pytest.mark.parametrize("reasoning", ["xhigh", "max"])
def test_the_window_follows_reasoning_effort(economy: str, reasoning: str) -> None:
    window = runner._supervisor_worker_timeout_s({"effort": economy, "reasoning_effort": reasoning}, has_progress=True)
    assert window == runner._MAX_EFFORT_IDLE_EVENT_TIMEOUT_S == 360.0


def test_ordinary_reasoning_keeps_the_ordinary_window() -> None:
    window = runner._supervisor_worker_timeout_s({"effort": "cheap", "reasoning_effort": "high"}, has_progress=True)
    assert window == runner._WORKER_IDLE_EVENT_TIMEOUT_S


def test_the_worker_itself_waits_as_long_as_its_reasoning_needs(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """The in-thread watchdog is the one that cancels the stream; it must get the same window."""
    store = _Store()
    _use_store(monkeypatch, store, window_s=120.0)
    calls: list[dict[str, object]] = []

    async def spy(_stream, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(kwargs)
        return {"type": "progress", "text": "thinking"} if len(calls) == 1 else None

    monkeypatch.setattr(runner, "_next_worker_event", spy)
    monkeypatch.setattr(runner, "run_agent_worker_events", lambda *_a, **_k: _no_events())
    asyncio.run(
        runner._run_agent_worker(
            {},
            execution_id=EXECUTION_ID,
            prompt="look into it",
            specialist_id="coding",
            bot=_Bot(),
            emitter=_emitter(),
            instructions="Do it.",
            repo_root=tmp_path,
            reasoning_effort="xhigh",
            effort="cheap",
            autonomy_level=1,
        )
    )
    after_first_event = calls[1]
    assert after_first_event.get("timeout_s") == 360.0
    assert after_first_event.get("execution_id") == EXECUTION_ID, "a helper's steps could not reach this window"


async def _no_events():  # noqa: ANN202
    return
    yield  # an async generator that yields nothing


def test_progress_does_not_wait_for_a_frozen_loop() -> None:
    from thomas.server.chat_delegation_emitter import _DelegationEmitter, _ThreadsafeDelegationEmitter

    async def main() -> tuple[dict[str, float], list[str]]:
        delivered: list[str] = []

        async def emit(event: dict) -> None:
            delivered.append(event["last_progress"])

        threadsafe = _ThreadsafeDelegationEmitter(_DelegationEmitter(emit), asyncio.get_running_loop())
        took: dict[str, float] = {}

        def worker_thread() -> None:
            async def report() -> None:
                started = time.perf_counter()
                for text in ("one", "two", "three"):
                    await threadsafe.progress({}, specialist_id="coding", bot=_Bot(), text=text)
                took["progress"] = time.perf_counter() - started

            asyncio.run(report())

        thread = threading.Thread(target=worker_thread, daemon=True)
        thread.start()
        time.sleep(0.6)  # the server loop is frozen while the worker reports
        thread.join(timeout=2.0)
        await asyncio.sleep(0.1)  # the loop is back: what was queued is delivered
        return took, delivered

    took, delivered = asyncio.run(main())
    assert "progress" in took, "the worker was held until the server loop came back"
    assert took["progress"] < 0.2
    assert delivered == ["one", "two", "three"], "progress must arrive, and in order"


def test_a_workers_reports_beat_its_heartbeat_without_the_loop() -> None:
    from thomas.server.chat_delegation_emitter import (
        WorkerHeartbeat,
        _DelegationEmitter,
        _ThreadsafeDelegationEmitter,
    )

    async def main() -> WorkerHeartbeat:
        heartbeat = WorkerHeartbeat(EXECUTION_ID)
        threadsafe = _ThreadsafeDelegationEmitter(
            _DelegationEmitter(AsyncMock()), asyncio.get_running_loop(), heartbeat
        )
        assert heartbeat.age_s() is None
        thread = threading.Thread(
            target=lambda: asyncio.run(threadsafe.progress({}, specialist_id="c", bot=_Bot(), text="x")),
            daemon=True,
        )
        thread.start()
        time.sleep(0.3)  # frozen loop: the beat must not need it
        thread.join(timeout=2.0)
        return heartbeat

    heartbeat = asyncio.run(main())
    age = heartbeat.age_s()
    assert age is not None and age < 1.0


def test_a_helpers_steps_count_as_its_leads_sign_of_life(monkeypatch) -> None:  # noqa: ANN001
    from thomas.server import agent_spawn_tool
    from thomas.server.chat_delegation_emitter import register_worker_heartbeat, release_worker_heartbeat

    monkeypatch.setattr(agent_spawn_tool, "record_line", lambda *_a, **_k: None)  # no Build transcript
    heartbeat = register_worker_heartbeat("exec-the-lead")
    try:

        async def helper(_title: str, _brief: str):  # noqa: ANN202
            for step in range(3):
                yield {"type": "progress", "text": f"step {step}"}
            yield {"type": "text", "text": "found it"}

        tool = agent_spawn_tool.SpawnAgentTool(execution_id="exec-the-lead", run_child=helper)
        assert heartbeat.age_s() is None
        result = asyncio.run(tool.execute({"title": "scout", "instructions": "look around"}))
        assert result.ok
        age = heartbeat.age_s()
        assert age is not None and age < 1.0, "the lead waiting on its helper looked silent"
    finally:
        release_worker_heartbeat(heartbeat)


def test_the_lead_keeps_waiting_while_its_helper_reports_in() -> None:
    from thomas.server.chat_delegation_deliverable import _WorkerRetry
    from thomas.server.chat_delegation_emitter import register_worker_heartbeat, release_worker_heartbeat

    heartbeat = register_worker_heartbeat("exec-waiting-lead")
    helper_done = threading.Event()

    def helper() -> None:  # task.spawn beats the lead from the lead's own thread
        while not helper_done.is_set():
            heartbeat.beat()
            time.sleep(0.02)

    threading.Thread(target=helper, daemon=True).start()
    try:
        event = asyncio.run(
            runner._next_worker_event(
                _SlowStream(0.5), saw_event=True, timeout_s=0.15, execution_id="exec-waiting-lead"
            )
        )
        assert event == {"type": "tool_output", "name": "task.spawn"}
    finally:
        helper_done.set()
    time.sleep(0.05)
    # Once the helper stops reporting in, the lead's silence is real again.
    with pytest.raises(_WorkerRetry):
        asyncio.run(
            runner._next_worker_event(
                _SlowStream(5.0), saw_event=True, timeout_s=0.15, execution_id="exec-waiting-lead"
            )
        )
    release_worker_heartbeat(heartbeat)


class _SlowStream:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self):  # noqa: ANN204
        await asyncio.sleep(self.delay)
        return {"type": "tool_output", "name": "task.spawn"}


def test_a_failed_worker_stops_and_starts_no_further_attempt(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """exec-a5ab521aff9c wrote "attempt 2 of 12" after its card said failed."""
    from thomas.server import chat_delegation_emitter

    store = _Store(progress="Provider-native worker is running.")
    _use_store(monkeypatch, store, window_s=0.3)
    streams: list[object] = []

    def events(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        lookup = getattr(chat_delegation_emitter, "worker_heartbeat", lambda _id: None)
        streams.append(lookup(EXECUTION_ID))

        async def stream():  # noqa: ANN202
            if len(streams) > 1:
                yield {"type": "error", "error": "a later attempt", "retryable": False}
                return
            yield {"type": "progress", "text": "Provider-native worker is initializing."}
            time.sleep(0.8)  # a step that holds this worker's own thread past its window
            raise RuntimeError("the step fell over")

        return stream()

    monkeypatch.setattr(runner, "run_agent_worker_events", events)

    async def main() -> int:
        await _supervise(
            runner._run_agent_worker,
            store,
            tmp_path,
            execution_id=EXECUTION_ID,
            prompt="fix it",
            specialist_id="coding",
            bot=_Bot(),
            instructions="Do it.",
            repo_root=tmp_path,
            autonomy_level=4,
        )
        failed_at = len(store.writes)
        await asyncio.sleep(1.5)  # room for a ghost attempt to show itself
        return failed_at

    failed_at = asyncio.run(main())
    assert store.record.get("blocker") == "provider_native_timeout"
    assert len(streams) == 1, "another attempt started after the card said failed"
    assert store.writes[failed_at:] == [], f"the worker kept writing after it was failed: {store.writes[failed_at:]}"
    assert streams[0] is not None and streams[0].stop_requested
