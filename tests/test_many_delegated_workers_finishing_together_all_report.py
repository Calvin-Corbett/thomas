"""More background workers than the shared thread pool holds, finishing together, all finish and all report.

Delegated workers used to run on the event loop's shared default thread pool (``asyncio.to_thread`` in
``_start_worker_thread``). A finishing worker waits for the server loop to deliver its "completed" notice,
and that notice's notification also needs a thread from the same pool (``asyncio.to_thread`` in
``_DelegationEmitter._notify_lifecycle``). With every pool thread holding a finishing worker, the notification
could never get a thread, so no worker could return and free one. The pool is ``min(32, cpu_count + 4)``
threads: 20 on a 16-core machine.

The scenario runs in a child process under a hard timeout, so a reproduced freeze fails this test instead
of hanging pytest. The child starts real provider-native delegations through
``chat_delegation._start_agent_worker_delegation``: the real supervisor, worker thread, runner, emitter and
execution records. Only the worker's event stream (it writes one file and finishes) and the notifier are
stand-ins. The streams hold until every worker has started, or, once every delegation has been started, until
no further worker has started for two seconds (the pool is full): they finish together however slowly the
delegations were started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POOL = min(32, (os.cpu_count() or 1) + 4)
WORKERS = max(21, DEFAULT_POOL + 1)
HOLD_S = 2.0
WINDOW_S = 30.0


def _child(out: Path, workers: int) -> None:
    """Run the scenario and write result.json. Always ends with os._exit: a frozen pool cannot be joined."""
    sys.path.insert(0, str(ROOT))
    import asyncio
    import threading
    import time
    from collections import Counter

    from thomas.core import task_bot_runtime
    from thomas.server import chat_delegation as cd
    from thomas.server.chat_delegation_emitter import _DelegationEmitter, worker_heartbeat

    repo = out / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    entered: list[str] = []
    last_entry: list[float] = [0.0]
    all_in = threading.Event()
    all_submitted = threading.Event()
    notices: list[tuple[str, str]] = []
    receipt = {
        "requested": {"profile": "p", "model": "m"},
        "active": {"profile": "p", "provider": "stand-in", "model": "m"},
        "attempts": [{"profile": "p", "provider": "stand-in", "model": "m", "status": "success"}],
    }

    async def stream(_app, *, work_dir, execution_id: str = "", **_kwargs):  # noqa: ANN001, ANN003, ANN202
        with lock:
            entered.append(execution_id)
            last_entry[0] = time.monotonic()
            if len(entered) >= workers:
                all_in.set()
        yield {"type": "model_runtime", "runtime": receipt}
        yield {"type": "tool_start", "name": "fs.write_file", "call_id": "c1"}
        Path(work_dir, "out.txt").write_text("done\n", encoding="utf-8")
        yield {"type": "tool_output", "name": "fs.write_file", "call_id": "c1", "ok": True, "result_text": "ok"}
        while not all_in.is_set() and not (all_submitted.is_set() and time.monotonic() - last_entry[0] >= HOLD_S):
            await asyncio.sleep(0.02)
        yield {"type": "text", "text": "Wrote out.txt."}
        yield {"type": "done"}

    def workspace(execution_id: str) -> Path:
        path = out / "workspaces" / execution_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def notifier(event: str, record: dict, *, text: str = "") -> None:
        with lock:
            notices.append((event, str(record.get("execution_id") or "")))

    async def emit_event(_event: dict) -> None:
        return None

    class Bot:
        id = name = "nova"

        def to_event_dict(self) -> dict:
            return {}

    cd.run_agent_worker_events = stream
    cd._ensure_task_workspace = workspace

    async def main() -> dict:
        emitter = _DelegationEmitter(emit_event, notifier=notifier)
        ids = []
        for index in range(workers):
            record = await cd._start_agent_worker_delegation(
                None, session_id="many-workers", prompt=f"Write out.txt, number {index}.", specialist_id="reasoning",
                bot=Bot(), emitter=emitter, repo_root=repo, profile="p", model_id="m", file_access=1,
            )  # fmt: skip
            ids.append(str(record["execution_id"]))
        all_submitted.set()  # every delegation has been started
        deadline = time.monotonic() + WINDOW_S
        while time.monotonic() < deadline:
            with lock:
                done = sum(1 for event, _ in notices if event == "completed")
            if done >= workers and all(worker_heartbeat(eid) is None for eid in ids):
                break
            await asyncio.sleep(0.1)
        try:  # anything else on this server that needs a pool thread
            await asyncio.wait_for(asyncio.to_thread(lambda: None), timeout=5.0)
            pool_answers = True
        except TimeoutError:
            pool_answers = False
        with lock:
            seen = list(notices)
        states = Counter(str((task_bot_runtime.get_execution(eid, repo) or {}).get("state") or "") for eid in ids)
        return {
            "workers": workers,
            "started_streams": len(entered),
            "record_states": dict(states),
            "completed_notices": sorted(eid for event, eid in seen if event == "completed"),
            "other_notices": sorted(f"{event}:{eid}" for event, eid in seen if event != "completed"),
            "ids": sorted(ids),
            "still_holding_a_thread": sorted(eid for eid in ids if worker_heartbeat(eid) is not None),
            "pool_answers": pool_answers,
        }

    loop = asyncio.new_event_loop()
    result: dict = {"child_error": "the scenario did not finish"}
    try:
        result = loop.run_until_complete(main())
    finally:  # whatever happened, report it and exit: a frozen pool cannot be joined
        raised = sys.exc_info()[1]
        if raised is not None:
            result = {"child_error": f"{type(raised).__name__}: {raised}"}
            traceback.print_exc()
        (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


def test_more_workers_than_the_default_pool_finish_together_and_every_one_reports(tmp_path: Path) -> None:
    out = tmp_path / "child"
    out.mkdir()
    env = dict(os.environ)
    for name in ("THOMAS_DATA_DIR", "THOMAS_HOME", "THOMAS_STATE_DIR", "THOMAS_OWNED_ROOT", "THOMAS_MEMORY_ROOT"):
        env[name] = str(tmp_path / "data" / name.lower())
    env["THOMAS_GREEN_ROOT"] = str(tmp_path / "green")
    env["THOMAS_SHARED_SECRET_STORE_DIR"] = str(tmp_path / "secrets")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(out), str(WORKERS)]
    try:
        finished = subprocess.run(
            command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=WINDOW_S + 120
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"the child did not finish within its hard timeout: {exc}") from exc
    result_file = out / "result.json"
    assert result_file.is_file(), (finished.stdout[-2000:], finished.stderr[-4000:])
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert "child_error" not in result, (result, finished.stderr[-4000:])
    seen = (
        f"workers={WORKERS}; streams started={result['started_streams']}; records={result['record_states']}; "
        f"completion notices={len(result['completed_notices'])}; other notices={result['other_notices']}; "
        f"still holding a thread={len(result['still_holding_a_thread'])}; shared pool answers={result['pool_answers']}"
    )

    assert result["started_streams"] == WORKERS, seen
    assert result["record_states"] == {"completed": WORKERS}, seen
    assert result["completed_notices"] == result["ids"], ("every completion notice arrives, once each", seen)
    assert result["other_notices"] == [], seen
    assert result["still_holding_a_thread"] == [], ("a finished worker never returned from its thread", seen)
    assert result["pool_answers"] is True, ("the server's shared thread pool stopped answering", seen)


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--child":
    _child(Path(sys.argv[2]), int(sys.argv[3]))
