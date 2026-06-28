"""Tests for the self-recursive evolve loop -- control flow with injected fakes.

No real LLM passes or mirror mutation: the planner, session runner, and promoter
are all stubbed, so these assert the *orchestration* (planning, the autonomy
gate, promotion timing, budgets, persistence, and approvals).
"""

from __future__ import annotations

import itertools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from evolve_supervisor import WATCHDOG_RETURN_CODE

from thomas.forge.anvil.evolve_loop import (
    STATUS_DONE,
    STATUS_STOPPED,
    approve_pending,
    load_loop_state,
    reject_pending,
    run_evolve_loop,
)
from thomas.forge.anvil.evolve_loop_state import (
    EvolveLoopState,
    append_event,
    clear_control,
    read_control,
    save_loop_state,
)
from thomas.forge.anvil.evolve_planner import EvolveBacklog, EvolveGoal


def _goal(gid: str, category: str, risk: str) -> EvolveGoal:
    return EvolveGoal(
        id=gid,
        category=category,
        title=f"do {gid}",
        rationale="because",
        goal_prompt=f"improve {gid}",
        target_paths=[f"{gid}.py"],
        risk_tier=risk,
        leverage=0.7,
        source="test",
    )


def _promotable_session(session_id: str, changed: int = 2):
    return {
        "ok": True,
        "session": {
            "session_id": session_id,
            "status": "ready",
            "delta": {"changed_count": changed, "changed_files": [f"f{i}.py" for i in range(changed)]},
            "policy_violations": [],
            "verification": [{"command": "pytest", "returncode": 0}],
            "promotable": True,
            "diff_path": f"/tmp/{session_id}.patch",
        },
    }


class _Recorder:
    """A fake session runner + promoter that records calls."""

    def __init__(self, *, fail_goals=None, nonpromotable=None):
        self.runs = []
        self.run_kwargs = []
        self.promotions = []
        self.counter = itertools.count(1)
        self.fail_goals = set(fail_goals or [])
        self.nonpromotable = set(nonpromotable or [])

    def run(self, root, *, goal, **kwargs):
        self.runs.append(goal)
        self.run_kwargs.append(dict(kwargs))
        for token in self.fail_goals:
            if token in goal:
                raise RuntimeError("boom")
        sid = f"sess-{next(self.counter)}"
        session = _promotable_session(sid)
        for token in self.nonpromotable:
            if token in goal:
                session["session"]["promotable"] = False
                session["session"]["status"] = "no_change"
                session["session"]["delta"]["changed_count"] = 0
        return session

    def promote(self, root, *, session_id, **kwargs):
        self.promotions.append(session_id)
        return {"ok": True, "session": {"session_id": session_id}, "backup_path": "/tmp/backup"}


def _planner_returning(goals):
    """A planner stub that returns the given goals once, then nothing new."""

    def planner(root, *, focus="", categories=None):
        return EvolveBacklog(goals=list(goals), signals={"scanned_py_files": 1})

    return planner


def test_clear_control_logs_unlink_failure_and_keeps_nonfatal(tmp_path, monkeypatch, caplog):
    control = tmp_path / ".thomas" / "evolve" / "loop" / "control.json"
    control.parent.mkdir(parents=True)
    control.write_text('{"stop": true}', encoding="utf-8")
    original_unlink = Path.unlink

    def fail_control_unlink(self, *args, **kwargs):
        if self == control:
            raise OSError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_control_unlink)

    with caplog.at_level(logging.DEBUG, logger="thomas.forge.anvil.evolve_loop_state"):
        clear_control(tmp_path)

    assert control.exists()
    assert any(
        record.exc_info and record.message.startswith("evolve loop control file removal failed (non-fatal):")
        for record in caplog.records
    )


def test_read_control_logs_parse_failure_and_keeps_empty_fallback(tmp_path, caplog):
    control = tmp_path / ".thomas" / "evolve" / "loop" / "control.json"
    control.parent.mkdir(parents=True)
    control.write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="thomas.forge.anvil.evolve_loop_state"):
        assert read_control(tmp_path) == {}

    assert any(
        record.exc_info and record.message.startswith("evolve loop control file read failed (non-fatal):")
        for record in caplog.records
    )


def test_append_event_logs_sink_failure_and_keeps_event_written(tmp_path, caplog):
    def broken_sink(_event):
        raise RuntimeError("sink offline")

    with caplog.at_level(logging.DEBUG, logger="thomas.forge.anvil.evolve_loop_state"):
        append_event(tmp_path, {"type": "probe"}, broken_sink)

    events_path = tmp_path / ".thomas" / "evolve" / "loop" / "events.jsonl"
    assert events_path.exists()
    assert '"type": "probe"' in events_path.read_text(encoding="utf-8")
    assert any(
        record.exc_info and record.message == "evolve loop event sink raised (non-fatal): sink offline"
        for record in caplog.records
    )


def test_autonomous_promotes_every_verified_goal(tmp_path):
    goals = [_goal("g1", "refactor", "low"), _goal("g2", "security", "high"), _goal("g3", "features", "medium")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=10,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    assert state["status"] == STATUS_DONE
    assert state["counters"]["promoted"] == 3
    assert len(rec.promotions) == 3
    assert state["pending_approvals"] == []
    assert len(state["history"]) == 3


def test_autonomous_holds_loop_file_candidate_for_human_approval(tmp_path):
    goals = [_goal("loop-risk", "refactor", "low")]
    rec = _Recorder()

    def session_runner(root, *, goal, **kwargs):
        _ = root, goal, kwargs
        return {
            "ok": True,
            "session": {
                "session_id": "loop-file-session",
                "status": "ready",
                "delta": {
                    "changed_count": 1,
                    "changed_files": ["thomas/forge/anvil/evolve_planner_detectors.py"],
                },
                "policy_violations": [],
                "session_rejections": [],
                "verification": [{"source": "generated", "returncode": 0}],
                "promotable": True,
            },
        }

    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=1,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=session_runner,
        promoter=rec.promote,
    )

    assert state["counters"]["promoted"] == 0
    assert state["counters"]["held"] == 1
    assert rec.promotions == []
    pending = [p for p in state["pending_approvals"] if p["status"] == "pending"]
    assert len(pending) == 1
    assert "evolve-loop file" in pending[0]["reason"]


def test_autonomous_holds_non_python_delta_for_human_approval(tmp_path):
    goals = [_goal("nonpy-risk", "refactor", "low")]
    rec = _Recorder()

    def session_runner(root, *, goal, **kwargs):
        _ = root, goal, kwargs
        return {
            "ok": True,
            "session": {
                "session_id": "nonpy-session",
                "status": "ready",
                "delta": {
                    "changed_count": 2,
                    "changed_files": ["thomas/__init__.py", "README.md"],
                },
                "policy_violations": [],
                "session_rejections": [],
                "verification": [{"source": "generated", "returncode": 0}],
                "promotable": True,
            },
        }

    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=1,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=session_runner,
        promoter=rec.promote,
    )

    assert state["counters"]["promoted"] == 0
    assert state["counters"]["held"] == 1
    assert rec.promotions == []
    pending = [p for p in state["pending_approvals"] if p["status"] == "pending"]
    assert len(pending) == 1
    assert "non-Python delta" in pending[0]["reason"]


def test_loop_refactor_first_only_for_refactor_goals(tmp_path):
    goals = [_goal("cleanup", "refactor", "low"), _goal("harden", "security", "low")]
    rec = _Recorder()

    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=2,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )

    assert state["status"] == STATUS_DONE
    assert [kwargs["refactor_first"] for kwargs in rec.run_kwargs] == [True, False]


def test_auto_safe_holds_high_risk_promotes_safe(tmp_path):
    goals = [
        _goal("low1", "refactor", "low"),
        _goal("high1", "security", "high"),
        _goal("med1", "efficiency", "medium"),
    ]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="auto_safe",
        max_iterations=10,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    # low + medium auto-promoted, high held for approval
    assert state["counters"]["promoted"] == 2
    assert state["counters"]["held"] == 1
    pending = [p for p in state["pending_approvals"] if p["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["risk_tier"] == "high"
    assert pending[0]["category"] == "security"


def test_propose_holds_everything(tmp_path):
    goals = [_goal("g1", "refactor", "low"), _goal("g2", "tests", "low")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="propose",
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    assert state["counters"]["promoted"] == 0
    assert rec.promotions == []
    assert len([p for p in state["pending_approvals"] if p["status"] == "pending"]) == 2


def test_max_iterations_budget_stops_loop(tmp_path):
    goals = [_goal(f"g{i}", "refactor", "low") for i in range(8)]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=2,
        max_promotions=100,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    assert state["iteration"] == 2
    assert len(rec.runs) == 2


def test_max_promotions_budget_stops_loop(tmp_path):
    goals = [_goal(f"g{i}", "refactor", "low") for i in range(8)]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=100,
        max_promotions=3,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    assert state["counters"]["promoted"] == 3


def test_wall_clock_budget_stops_loop(tmp_path):
    goals = [_goal(f"g{i}", "refactor", "low") for i in range(50)]
    rec = _Recorder()
    clock = itertools.count(0, 10)  # 0,10,20,... seconds per now() call

    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=0,
        max_promotions=0,
        max_wall_seconds=25,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
        now_fn=lambda: next(clock),
    )
    # start=0, then checks at 10,20 (<25) run, check at 30 (>=25) stops -> ~2 iterations
    assert state["iteration"] <= 3
    assert state["status"] in (STATUS_DONE,)


def test_spend_governor_stops_loop_before_dispatch(tmp_path):
    (tmp_path / "evolve_governor.toml").write_text(
        (
            "[spend_governor]\n"
            "enabled = true\n"
            'ledger_path = "thomas_spend.jsonl"\n'
            "daily_usd_cap = 1.0\n"
            "total_usd_cap = 10.0\n"
            "per_iteration_usd_reserve = 0.25\n"
        ),
        encoding="utf-8",
    )
    today = datetime.now(timezone.utc).date().isoformat()
    (tmp_path / "thomas_spend.jsonl").write_text(
        json.dumps(
            {
                "source": "blue_evolve_child_reserve",
                "day": "2000-01-01",
                "recorded_at": f"{today}T00:00:00+00:00",
                "usd_total": 0.9,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rec = _Recorder()
    planner_called = False

    def planner(root, *, focus="", categories=None):
        nonlocal planner_called
        planner_called = True
        return EvolveBacklog(goals=[_goal("expensive", "refactor", "low")], signals={})

    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        planner=planner,
        session_runner=rec.run,
        promoter=rec.promote,
    )

    assert state["status"] == STATUS_STOPPED
    assert "daily evolve spend cap" in state["last_error"]
    assert state["iteration"] == 0
    assert planner_called is False
    assert rec.runs == []


def test_spend_governor_rejection_inside_session_stops_loop(tmp_path):
    goals = [_goal("spendy1", "refactor", "low"), _goal("spendy2", "refactor", "low")]
    runs = []

    def session_runner(root, *, goal, **kwargs):
        _ = root, kwargs
        runs.append(goal)
        return {
            "ok": True,
            "session": {
                "session_id": "spend-stop",
                "status": "rejected",
                "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
                "policy_violations": [],
                "verification": [],
                "promotable": False,
                "diff_path": str(root / "spend-stop.patch"),
                "spend_governor_rejections": [
                    "spend governor blocked creative: daily evolve spend cap would be exceeded"
                ],
            },
        }

    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=10,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=session_runner,
        promoter=rec.promote,
    )

    assert state["status"] == STATUS_STOPPED
    assert "daily evolve spend cap would be exceeded" in state["last_error"]
    assert runs == ["improve spendy1"]
    assert rec.promotions == []
    assert len(state["history"]) == 1


def test_failed_session_is_recorded_and_loop_continues(tmp_path):
    goals = [_goal("good1", "refactor", "low"), _goal("boom2", "refactor", "low"), _goal("good3", "refactor", "low")]
    rec = _Recorder(fail_goals={"boom2"})
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=10,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    assert state["counters"]["failed"] == 1
    assert state["counters"]["promoted"] == 2  # the two good goals still promoted
    reasons = [h["decision"]["reason"] for h in state["history"]]
    assert any("session error" in r for r in reasons)


def test_spend_watchdog_session_emits_stop_event_and_stops_loop(tmp_path):
    goals = [_goal("expensive", "efficiency", "low"), _goal("later", "refactor", "low")]
    events = []
    runs = []

    def session_runner(root, *, goal, **kwargs):
        _ = root, kwargs
        runs.append(goal)
        return {
            "ok": False,
            "session": {
                "session_id": "watchdog-session",
                "status": "agent_failed",
                "delta": {"changed_count": 0, "changed_files": []},
                "policy_violations": [],
                "verification": [],
                "pass_results": [
                    {
                        "command": "chat",
                        "returncode": WATCHDOG_RETURN_CODE,
                        "stdout_tail": "",
                        "stderr_tail": "spend watchdog terminated process",
                        "timed_out": False,
                        "spend_watchdog_triggered": True,
                        "spend_watchdog_verdict": {
                            "code": "daily_cap_exceeded",
                            "message": "daily evolve spend cap would be exceeded",
                        },
                    }
                ],
                "promotable": False,
            },
        }

    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=10,
        planner=_planner_returning(goals),
        session_runner=session_runner,
        promoter=rec.promote,
        event_sink=events.append,
    )

    assert state["status"] == STATUS_STOPPED
    assert state["iteration"] == 1
    assert len(runs) == 1
    assert "daily evolve spend cap" in state["last_error"]
    assert any(event.get("type") == "spend_watchdog_stop" for event in events)


def test_resumed_loop_skips_history_tarpits(tmp_path):
    prior = EvolveLoopState()
    prior.history = [
        {
            "goal_id": "g1",
            "category": "refactor",
            "decision": {"action": "reject", "reason": "verification failed"},
            "promoted": False,
        },
        {
            "goal_id": "g1",
            "category": "refactor",
            "decision": {"action": "reject", "reason": "verification failed again"},
            "promoted": False,
        },
    ]
    save_loop_state(tmp_path, prior)

    goals = [_goal("g1", "refactor", "low"), _goal("g2", "security", "low")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="autonomous",
        max_iterations=1,
        max_promotions=10,
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
        reset=False,
    )

    assert rec.runs == ["improve g2"]
    assert state["counters"]["skipped_tarpit"] == 1
    assert state["counters"]["planned"] == 1


def test_state_is_persisted_and_reloadable(tmp_path):
    goals = [_goal("g1", "refactor", "low")]
    rec = _Recorder()
    run_evolve_loop(
        tmp_path,
        posture="autonomous",
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    reloaded = load_loop_state(tmp_path)
    assert reloaded.counters["promoted"] == 1
    assert reloaded.status == STATUS_DONE
    assert reloaded.history


def test_approve_pending_reruns_goal_and_promotes(tmp_path):
    # First, run in propose mode to generate a held approval.
    goals = [_goal("hold1", "security", "high")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="propose",
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    pending = [p for p in state["pending_approvals"] if p["status"] == "pending"]
    assert len(pending) == 1
    approval_id = pending[0]["id"]

    # Approve it: a fresh recorder re-derives + promotes.
    rec2 = _Recorder()
    result = approve_pending(tmp_path, approval_id, session_runner=rec2.run, promoter=rec2.promote)
    assert result["ok"] is True
    assert result["approval"]["status"] == "approved"
    assert len(rec2.promotions) == 1
    reloaded = load_loop_state(tmp_path)
    assert reloaded.counters["promoted"] == 1


def test_approve_pending_marks_failed_if_not_promotable(tmp_path):
    goals = [_goal("hold1", "security", "high")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="propose",
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    approval_id = [p for p in state["pending_approvals"] if p["status"] == "pending"][0]["id"]

    rec2 = _Recorder(nonpromotable={"hold1"})
    result = approve_pending(tmp_path, approval_id, session_runner=rec2.run, promoter=rec2.promote)
    assert result["ok"] is False
    assert result["approval"]["status"] == "failed"
    assert rec2.promotions == []


def test_reject_pending_dismisses_without_promoting(tmp_path):
    goals = [_goal("hold1", "security", "high")]
    rec = _Recorder()
    state = run_evolve_loop(
        tmp_path,
        posture="propose",
        planner=_planner_returning(goals),
        session_runner=rec.run,
        promoter=rec.promote,
    )
    approval_id = [p for p in state["pending_approvals"] if p["status"] == "pending"][0]["id"]
    result = reject_pending(tmp_path, approval_id, reason="not now")
    assert result["approval"]["status"] == "rejected"
    reloaded = load_loop_state(tmp_path)
    assert all(p["status"] != "pending" for p in reloaded.pending_approvals)
