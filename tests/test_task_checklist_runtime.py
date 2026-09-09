"""Runtime + native-worker wiring for the task-completion checklist gate.

Covers the review/explain playbook end-to-end:
  * ``create_execution`` attaches the per-type checklist (flag on only),
  * ``complete_execution`` refuses to complete until the checklist is met,
  * the provider-native worker feeds REAL read events (never reply words) into the
    gate, so a task that only *claims* to have read source is held back.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thomas.core import task_bot_runtime
from thomas.server import chat_delegation


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "1")


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")


def _create(tmp_path, task_type="review_explain"):
    return task_bot_runtime.create_execution(
        session_id="sess-1",
        summary="Explain how dispatch routing works",
        intent="chat_task",
        task_type=task_type,
        repo_root=tmp_path,
    )


# ── create_execution attaches the checklist ──────────────────────────


def test_create_attaches_review_explain_checklist_when_on(on, tmp_path):
    rec = _create(tmp_path)
    assert rec["task_type"] == "review_explain"
    kinds = {row["kind"] for row in rec["checklist"]}
    assert kinds == {task_bot_runtime.task_checklist.KIND_EVIDENCE_READ, task_bot_runtime.task_checklist.KIND_CITATION}


def test_create_attaches_nothing_when_flag_off(off, tmp_path):
    rec = _create(tmp_path)
    # Flag off → today's behaviour: a label may be recorded but no checklist gates.
    assert rec["checklist"] == []


def test_blank_task_type_is_passthrough_even_when_on(on, tmp_path):
    # No label yet (the model labeller has not run) → no checklist, so turning the
    # flag on before the labeller ships never blocks anything.
    rec = _create(tmp_path, task_type="")
    assert rec["checklist"] == []


# ── complete_execution gate ──────────────────────────────────────────


def test_complete_blocked_without_a_real_read(on, tmp_path):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    # Claims a review but shows no read and no citation → must NOT complete.
    out = task_bot_runtime.complete_execution(
        eid,
        read_paths=[],
        output_text="I reviewed the routing thoroughly and it is correct.",
        repo_root=tmp_path,
    )
    assert out["state"] == "awaiting_proof"
    assert "Checklist not met" in out["blocker"]
    assert "read_source" in out["blocker"]


def test_complete_blocked_with_read_but_no_citation(on, tmp_path):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    out = task_bot_runtime.complete_execution(
        eid,
        read_paths=["thomas/agent/dispatch.py"],
        output_text="routing is a regex cascade",  # no file:line
        repo_root=tmp_path,
    )
    assert out["state"] == "awaiting_proof"
    assert "cite_file_line" in out["blocker"]


def test_complete_allowed_with_real_read_and_citation(on, tmp_path):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    out = task_bot_runtime.complete_execution(
        eid,
        read_paths=["thomas/agent/dispatch.py"],
        output_text="should_dispatch is a regex cascade — thomas/agent/dispatch.py:139",
        repo_root=tmp_path,
    )
    assert out["state"] == "completed"
    assert out["proof_status"] == "verified"
    assert out["blocker"] == ""


def test_words_alone_never_satisfy_evidence_read(on, tmp_path):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    # A citation in the text + a claim of reading, but NO real read event → blocked.
    out = task_bot_runtime.complete_execution(
        eid,
        read_paths=[],
        output_text="I read thomas/agent/dispatch.py:139 and it is a cascade",
        repo_root=tmp_path,
    )
    assert out["state"] == "awaiting_proof"
    assert "read_source" in out["blocker"]


def test_record_evidence_then_complete_without_repassing(on, tmp_path):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    # Evidence recorded incrementally...
    task_bot_runtime.record_checklist_evidence(
        eid,
        read_paths=["thomas/agent/dispatch.py"],
        output_text="see thomas/agent/dispatch.py:139",
        repo_root=tmp_path,
    )
    # ...then complete with NO fresh evidence must trust the stored result.
    out = task_bot_runtime.complete_execution(eid, repo_root=tmp_path)
    assert out["state"] == "completed"


def test_complete_passthrough_when_flag_off(off, tmp_path):
    # With the flag off the checklist gate never engages: a review_explain task
    # completes on the ordinary evidence rule alone (a confirmed success here),
    # exactly as it did before the feature existed.
    rec = task_bot_runtime.create_execution(
        session_id="s",
        summary="explain",
        task_type="review_explain",
        repo_root=tmp_path,
    )
    out = task_bot_runtime.complete_execution(rec["execution_id"], repo_root=tmp_path, verified_success=True)
    assert out["state"] == "completed"


# ── codex event → read_paths extraction ──────────────────────────────


def test_extract_read_paths_from_cat_command():
    ev = {"type": "tool_start", "name": "cat thomas/core/dispatch.py"}
    assert chat_delegation._extract_read_paths(ev) == ["thomas/core/dispatch.py"]


def test_extract_read_paths_from_sed_command():
    ev = {"type": "tool_start", "name": "sed -n 1,40p thomas/agent/dispatch.py"}
    assert chat_delegation._extract_read_paths(ev) == ["thomas/agent/dispatch.py"]


def test_extract_read_paths_from_edit_event():
    ev = {"type": "tool_start", "name": "edit:thomas/server/app.py"}
    assert chat_delegation._extract_read_paths(ev) == ["thomas/server/app.py"]


def test_text_event_is_never_a_read():
    ev = {"type": "text", "text": "I read thomas/core/dispatch.py:1 carefully"}
    assert chat_delegation._extract_read_paths(ev) == []


def test_echoing_a_path_is_not_a_read():
    # echo is not a read/inspect verb → a path printed by the model does not count.
    ev = {"type": "tool_start", "name": 'echo "thomas/core/dispatch.py is the file"'}
    assert chat_delegation._extract_read_paths(ev) == []


def test_non_path_command_yields_no_reads():
    ev = {"type": "tool_start", "name": "grep"}
    assert chat_delegation._extract_read_paths(ev) == []


# ── provider-native worker, end to end ───────────────────────────────


class _Bot:
    id = "nova"
    name = "Nova"


def _fake_bridge(events):
    """The worker now consumes ``run_agent_worker_events``; keep the event list."""
    return list(events)


async def _run_worker(monkeypatch, events, **kwargs):
    """Drive today's provider-native worker with a scripted event stream."""
    from thomas.server import chat_delegation_runner as runner

    async def _events(*_a, **_k):
        yield {"type": "model_runtime", "runtime": {"requested": {}, "active": {}}}
        for ev in events:
            yield ev

    monkeypatch.setattr(runner, "run_agent_worker_events", _events)
    monkeypatch.setattr(runner, "validate_model_runtime_receipt", lambda *a, **k: {"ok": True})
    await runner._run_agent_worker(SimpleNamespace(), **kwargs)


@pytest.mark.asyncio
async def test_worker_holds_task_that_only_claims_to_read(on, tmp_path, monkeypatch):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    bridge = _fake_bridge(
        [
            {"type": "text", "text": "I reviewed routing — thomas/agent/dispatch.py:139"},
            {"type": "done"},
        ]
    )
    await _run_worker(
        monkeypatch,
        bridge,
        execution_id=eid,
        prompt="explain routing",
        specialist_id="coding",
        bot=_Bot(),
        emitter=emitter,
        instructions="work it",
        repo_root=tmp_path,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["state"] == "awaiting_proof"  # citation present but NO real read
    emitter.completed.assert_not_awaited()
    emitter.progress.assert_awaited()


@pytest.mark.asyncio
async def test_worker_completes_when_it_actually_reads_and_cites(on, tmp_path, monkeypatch):
    rec = _create(tmp_path)
    eid = rec["execution_id"]
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    bridge = _fake_bridge(
        [
            {"type": "tool_start", "name": "cat thomas/agent/dispatch.py"},
            {"type": "tool_output"},
            {"type": "text", "text": "should_dispatch is a regex cascade — thomas/agent/dispatch.py:139"},
            {"type": "done"},
        ]
    )
    await _run_worker(
        monkeypatch,
        bridge,
        execution_id=eid,
        prompt="explain routing",
        specialist_id="coding",
        bot=_Bot(),
        emitter=emitter,
        instructions="work it",
        repo_root=tmp_path,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["state"] == "completed"
    emitter.completed.assert_awaited_once()


# ── Step 1: the worker labels its OWN task type (no extra model call) ─


def _create_unlabeled(tmp_path):
    # Real flow: the task is created with no type; the worker declares it mid-run.
    return task_bot_runtime.create_execution(
        session_id="sess-1",
        summary="do the thing",
        intent="chat_task",
        task_type="",
        repo_root=tmp_path,
    )


def test_extract_task_type_label_reads_the_models_declared_label():
    assert chat_delegation._extract_task_type_label("TASK_TYPE: review_explain\nnow...") == "review_explain"
    assert chat_delegation._extract_task_type_label("task_type = code_change") == "code_change"
    assert chat_delegation._extract_task_type_label("no label in here") == ""


@pytest.mark.asyncio
async def test_worker_self_labels_review_and_is_gated(on, tmp_path, monkeypatch):
    rec = _create_unlabeled(tmp_path)
    eid = rec["execution_id"]
    assert rec["checklist"] == []  # nothing attached at create — label comes later
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    bridge = _fake_bridge(
        [
            {"type": "text", "text": "TASK_TYPE: review_explain"},
            {"type": "text", "text": " routing is a cascade. thomas/agent/dispatch.py:139"},
            {"type": "done"},
        ]
    )
    await _run_worker(
        monkeypatch,
        bridge,
        execution_id=eid,
        prompt="how does routing work",
        specialist_id="coding",
        bot=_Bot(),
        emitter=emitter,
        instructions="work it",
        repo_root=tmp_path,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["task_type"] == "review_explain"
    assert final["checklist"]  # attached mid-flight from the worker's own label
    assert final["state"] == "awaiting_proof"  # cited but never really read → held
    emitter.completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_self_labels_code_change_passes_through(on, tmp_path, monkeypatch):
    rec = _create_unlabeled(tmp_path)
    eid = rec["execution_id"]
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    bridge = _fake_bridge(
        [
            {"type": "text", "text": "TASK_TYPE: code_change\n"},
            {"type": "tool_start", "name": "fs.write_file"},
            {"type": "tool_output", "name": "fs.write_file", "ok": True, "result_text": "wrote app/button.py"},
            {"type": "text", "text": "added the button"},
            {"type": "done"},
        ]
    )
    await _run_worker(
        monkeypatch,
        bridge,
        execution_id=eid,
        prompt="add a button",
        specialist_id="coding",
        bot=_Bot(),
        emitter=emitter,
        instructions="work it",
        repo_root=tmp_path,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["task_type"] == "code_change"
    assert final["checklist"] == []  # pass-through type → not gated
    assert final["state"] == "completed"  # ordinary evidence rule: a real tool success
    emitter.completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_with_no_label_fails_closed_to_review(on, tmp_path, monkeypatch):
    rec = _create_unlabeled(tmp_path)
    eid = rec["execution_id"]
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    # Forgets to declare a type and does no real read → must not slip through.
    bridge = _fake_bridge(
        [
            {"type": "text", "text": "the system just works, trust me"},
            {"type": "done"},
        ]
    )
    await _run_worker(
        monkeypatch,
        bridge,
        execution_id=eid,
        prompt="how does it work",
        specialist_id="coding",
        bot=_Bot(),
        emitter=emitter,
        instructions="work it",
        repo_root=tmp_path,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["task_type"] == "review_explain"  # failed closed to strictest
    assert final["state"] == "awaiting_proof"
    emitter.completed.assert_not_awaited()
