from datetime import datetime, timedelta, timezone

from thomas.core import agent_monitor

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def _agent(status, minutes_ago, key="updated_at"):
    return {"id": "job:1", "status": status, key: (NOW - timedelta(minutes=minutes_ago)).isoformat()}


def test_a_running_task_idle_past_the_limit_is_stalled():
    [out] = agent_monitor.mark_stalled([_agent("running", 11)], NOW)
    assert out["stalled"] is True
    assert out["idle_s"] == 660


def test_a_running_task_inside_the_limit_is_not_stalled():
    [out] = agent_monitor.mark_stalled([_agent("running", 2)], NOW)
    assert out["stalled"] is False


def test_only_running_tasks_can_stall():
    for status in ("queued", "awaiting_approval", "done", "failed"):
        [out] = agent_monitor.mark_stalled([_agent(status, 120)], NOW)
        assert out["stalled"] is False, status


def test_a_task_with_no_readable_time_is_not_called_stalled():
    [out] = agent_monitor.mark_stalled([{"id": "x", "status": "running", "updated_at": "garbage"}], NOW)
    assert out["stalled"] is False
    assert out["idle_s"] is None


def test_a_z_suffixed_time_is_read_as_utc():
    ts = (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    [out] = agent_monitor.mark_stalled([{"id": "x", "status": "running", "updated_at": ts}], NOW)
    assert out["stalled"] is True


def test_the_limit_reads_the_environment_and_ignores_nonsense(monkeypatch):
    monkeypatch.setenv("THOMAS_STALLED_AFTER_S", "30")
    assert agent_monitor.stalled_after_s() == 30
    monkeypatch.setenv("THOMAS_STALLED_AFTER_S", "soon")
    assert agent_monitor.stalled_after_s() == 600
    monkeypatch.delenv("THOMAS_STALLED_AFTER_S")
    assert agent_monitor.stalled_after_s() == 600


def test_the_input_dicts_are_not_changed():
    src = _agent("running", 20)
    agent_monitor.mark_stalled([src], NOW)
    assert "stalled" not in src
