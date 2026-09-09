"""The presence heartbeat monitor leases a claim to the agent's liveness.

It must: heartbeat while the agent's process is alive, stop the instant that
process exits (so the claim auto-expires offline), and stop if the session is
removed. This is what prevents phantom claims (agent powered off, claim lingers).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load_monitor():
    path = _REPO / "scripts" / "crew" / "brief" / "presence_monitor.py"
    spec = importlib.util.spec_from_file_location("presence_monitor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parent_alive_self_and_dead():
    m = _load_monitor()
    assert m._parent_alive(os.getpid()) is True
    assert m._parent_alive(0) is True  # 0 == "no parent to watch"
    assert m._parent_alive(2_000_000_000) is False  # implausible pid -> gone


def test_monitor_stops_when_parent_dies(monkeypatch):
    m = _load_monitor()
    import thomas.core.agent_presence as ap

    checks = {"n": 0}

    def fake_alive(_pid):
        checks["n"] += 1
        return checks["n"] <= 2  # alive for two loop iterations, then gone

    beats = {"n": 0}

    def fake_heartbeat(**_kw):
        beats["n"] += 1
        return {"state": "active"}

    monkeypatch.setattr(m, "_parent_alive", fake_alive)
    monkeypatch.setattr(ap, "heartbeat_session", fake_heartbeat)

    reason = m.run_monitor("sid", parent_pid=4321, interval=1, sleeper=lambda _s: None)
    assert reason == "parent_gone"
    assert beats["n"] == 2  # it heartbeat while the parent was alive, then stopped


def test_monitor_stops_when_session_removed(monkeypatch):
    m = _load_monitor()
    import thomas.core.agent_presence as ap

    monkeypatch.setattr(m, "_parent_alive", lambda _pid: True)
    monkeypatch.setattr(ap, "heartbeat_session", lambda **_kw: None)  # session gone

    reason = m.run_monitor("sid", parent_pid=4321, interval=1, sleeper=lambda _s: None)
    assert reason == "session_gone"


def test_monitor_respects_max_seconds(monkeypatch):
    m = _load_monitor()
    import thomas.core.agent_presence as ap

    monkeypatch.setattr(m, "_parent_alive", lambda _pid: True)
    monkeypatch.setattr(ap, "heartbeat_session", lambda **_kw: {"state": "active"})
    reason = m.run_monitor("sid", parent_pid=0, interval=1, max_seconds=-1, sleeper=lambda _s: None)
    assert reason == "max_seconds"


# NOTE: the offline->stale->claim-expiry classification is existing presence
# behavior (process-liveness + heartbeat age). In the real phantom-claim case the
# agent's processes are GONE (machine off), so it classifies stale; that can't be
# faithfully simulated in-process (the live test runner matches the heuristic
# process scan). The monitor above is the NEW code and is what these tests cover:
# it leases the heartbeat to the agent's process and stops the moment it dies.
