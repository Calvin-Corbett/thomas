"""Exercise task-record creation, deletion, cancellation, and checklist write races.

Forced schedules check that deletion leaves no phantom summary row or truncated record, cancellation is not overwritten
by completion, and concurrent checklist and execution updates retain both fields. A slow contract evaluation also must
not hold the record lock: cancellation finishes during evaluation and survives the subsequent evidence write.
"""

from __future__ import annotations

import builtins
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

from thomas.core import acceptance_contract as ac
from thomas.core import task_bot_runtime as rt

BLOCKED = object()  # the delete was still waiting on the record lock at the creation boundary


def _files_and_rows(root):
    files = {p.stem for p in rt.runtime_dir(root).glob("exec-*.json")}
    rows = {r["execution_id"] for r in rt.read_summary(root, refresh=False).get("executions", [])}
    return files, rows


def test_a_delete_between_creates_two_writes_leaves_no_phantom_summary_row(tmp_path, monkeypatch):
    original_write_summary = rt._write_summary
    fired = threading.Event()
    bystander = rt.create_execution(
        session_id="bystander", summary="keeps the cached summary non-empty", repo_root=tmp_path
    )["execution_id"]
    pool = ThreadPoolExecutor(max_workers=1)
    deleter: dict[str, object] = {}

    def forcing_write_summary(repo_root=None, **kwargs):
        changed = kwargs.get("changed")
        if changed is not None and str(changed.get("conversation_id") or "") == "victim" and not fired.is_set():
            fired.set()
            # the delete is submitted at the vulnerable boundary: after the record write, before the summary write, and given a
            # bounded wait there: an unlocked delete (the old implementation) finishes inside it and the row published next is
            # a phantom; a delete that takes the record lock cannot finish until the creator releases it, so it times out here
            deleter["future"] = pool.submit(rt.delete_session_executions, "victim", repo_root=tmp_path)
            try:
                deleter["at_boundary"] = deleter["future"].result(timeout=1.0)
            except FuturesTimeoutError:  # only this outcome is expected at the boundary from a locked delete
                deleter["at_boundary"] = BLOCKED
        return original_write_summary(repo_root, **kwargs)

    monkeypatch.setattr(rt, "_write_summary", forcing_write_summary)
    created = rt.create_execution(session_id="victim", summary="to be deleted", repo_root=tmp_path)
    monkeypatch.setattr(rt, "_write_summary", original_write_summary)
    assert fired.is_set(), "the forced schedule did not fire"
    removed = deleter["future"].result(timeout=30)  # a delete that failed or never ran cannot pass this test
    pool.shutdown(wait=True)
    assert deleter["at_boundary"] is BLOCKED, (
        f"the delete finished while the creator held the record: {deleter['at_boundary']!r}"
    )
    assert removed == 1, f"the forced delete removed {removed} records"
    files, rows = _files_and_rows(tmp_path)
    assert created["execution_id"] not in files, "the victim record survived its delete"
    assert created["execution_id"] not in rows, "phantom summary row for a deleted record"
    assert bystander in files and bystander in rows
    assert files == rows


def test_a_delete_that_cannot_lock_the_record_raises_and_leaves_it_intact(tmp_path, monkeypatch):
    eid = rt.create_execution(session_id="doomed", summary="keep me intact", repo_root=tmp_path)["execution_id"]
    before = rt.execution_path(eid, tmp_path).read_bytes()
    original_open = builtins.open

    def failing_open(path, *args, **kwargs):
        if str(path).endswith(f"{eid}.json.lock"):
            raise OSError("simulated lock sidecar failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)
    raised = None
    try:
        rt.delete_session_executions("doomed", repo_root=tmp_path)
    except OSError as error:
        raised = error
    monkeypatch.setattr(builtins, "open", original_open)
    assert raised is not None
    assert rt.execution_path(eid, tmp_path).read_bytes() == before, "the record was truncated by a fail-open delete"


def test_a_cancel_forced_after_completes_guard_read_is_not_overwritten(tmp_path, monkeypatch):
    eid = rt.create_execution(session_id="fixture", summary="running", repo_root=tmp_path)["execution_id"]
    rt.update_execution(eid, state="running", repo_root=tmp_path, force=True)
    rt.attach_proof(eid, artifacts=["out.txt"], summary="made a file", repo_root=tmp_path)
    original_get = rt.get_execution
    guard_read, cancel_done = threading.Event(), threading.Event()

    def canceller():
        try:
            rt.cancel_execution(eid, repo_root=tmp_path)
        finally:
            cancel_done.set()

    def forcing_get(execution_id, repo_root=None):
        row = original_get(execution_id, repo_root)
        if execution_id == eid and threading.current_thread().name == "completer" and not guard_read.is_set():
            guard_read.set()
            threading.Thread(target=canceller, name="canceller").start()
            cancel_done.wait(2.0)
        return row

    def completer():
        threading.current_thread().name = "completer"
        return rt.complete_execution(eid, summary="finished", repo_root=tmp_path, verified_success=True)

    monkeypatch.setattr(rt, "get_execution", forcing_get)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(completer).result(timeout=30)
    monkeypatch.setattr(rt, "get_execution", original_get)
    cancel_done.wait(10)
    final = original_get(eid, tmp_path)
    states = [t.get("state") for t in final.get("transitions", [])]
    assert guard_read.is_set() and "cancelled" in states
    after_cancel = states[states.index("cancelled") + 1 :]
    assert not any(s in {"completed", "verified"} for s in after_cancel), f"a completion overwrote the stop: {states}"
    assert final["state"] == "cancelled"


def test_a_checklist_writer_and_an_update_on_one_record_both_survive(tmp_path, monkeypatch):
    eid = rt.create_execution(session_id="fixture", summary="original", repo_root=tmp_path)["execution_id"]
    original_get = rt.get_execution
    both_read = threading.Barrier(2, timeout=5)
    a_finished = threading.Event()
    errors: dict[str, str] = {}

    def synchronized_read(execution_id, repo_root=None):
        row = original_get(execution_id, repo_root)
        name = threading.current_thread().name
        if execution_id == eid and name in {"writer-A", "writer-B"}:
            try:
                both_read.wait()
            except threading.BrokenBarrierError:
                pass
            if name == "writer-B":
                a_finished.wait(5)
        return row

    def run(name, fn):
        threading.current_thread().name = name
        try:
            fn()
        except (
            OSError,
            ValueError,
            RuntimeError,
        ) as error:  # the runtime raises these: file errors, invalid transitions, stale writes
            errors[name] = f"{type(error).__name__}: {error}"
        finally:
            if name == "writer-A":
                a_finished.set()

    monkeypatch.setattr(rt, "get_execution", synchronized_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(
                run, "writer-A", lambda: rt.update_execution(eid, claimed_owner="worker-A", repo_root=tmp_path)
            )
            b = pool.submit(run, "writer-B", lambda: rt.set_task_type(eid, "code_change", repo_root=tmp_path))
            a.result(timeout=20)
            b.result(timeout=20)
    finally:
        monkeypatch.setattr(rt, "get_execution", original_get)
        both_read.abort()
    final = original_get(eid, tmp_path)
    assert not errors
    assert final["claimed_owner"] == "worker-A"
    assert final["task_type"] == "code_change"


def test_cancel_does_not_wait_for_slow_contract_evaluation(tmp_path, monkeypatch):
    eid = rt.create_execution(session_id="fixture", summary="verify work", repo_root=tmp_path)["execution_id"]
    record = rt.get_execution(eid, tmp_path)
    record["workspace"] = str(tmp_path)
    record["acceptance_contract"] = ac.items_to_dicts(
        [ac.ContractItem(item_id="check-1", kind=ac.KIND_COMMAND, description="run check", target="check")]
    )
    rt._write_json(rt.execution_path(eid, tmp_path), record)
    evaluating = threading.Event()
    release = threading.Event()

    def slow_evaluation(items, **kwargs):
        assert kwargs["run_commands"] is True
        evaluating.set()
        assert release.wait(10), "contract evaluation never resumed"
        return items

    monkeypatch.setattr(ac, "evaluate_contract", slow_evaluation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        evidence = pool.submit(rt.record_checklist_evidence, eid, output_text="checked", repo_root=tmp_path)
        try:
            assert evaluating.wait(5), "contract evaluation was not reached"
            cancellation = pool.submit(rt.cancel_execution, eid, repo_root=tmp_path)
            try:
                cancelled = cancellation.result(timeout=1)
            except FuturesTimeoutError:
                pytest.fail("cancel_execution waited on slow contract evaluation")
            assert cancelled["state"] == "cancelled"
        finally:
            release.set()
        evidence.result(timeout=10)
    final = rt.get_execution(eid, tmp_path)
    assert final["state"] == "cancelled"
    assert final["acceptance_contract"]
