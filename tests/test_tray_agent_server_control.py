"""What the tray agent does to the server it manages.

Covers: Stop Server staying stopped, the menu actions telling you when they fail, and
one agent per port. (The spawned server's environment is in
test_tray_agent_spawned_server.py.) Nothing here starts a real server or tray.
"""

from __future__ import annotations

import types

import pytest

from thomas.tray_agent import agent as tray


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point every tray state/log path at tmp_path so no test touches ~/.thomas."""
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "tray_state.json")
    monkeypatch.setattr(tray, "_LOG_FILE", tmp_path / "tray_agent.log")
    monkeypatch.setattr(tray, "_SERVER_LOG_FILE", tmp_path / "server.log")
    return tmp_path


class FakeServer:
    """Stands in for ServerProcess and records what the agent asked of it."""

    def __init__(self, running: bool = False, port_live: bool = False, works: bool = True) -> None:
        self.running = running
        self.port_live = port_live
        self.works = works  # False: start and restart fail
        self.calls: list[str] = []

    def start(self) -> bool:
        self.calls.append("start")
        self.running = self.works
        return self.works

    def stop(self) -> None:
        self.calls.append("stop")
        self.running = False

    def restart(self) -> bool:
        self.calls.append("restart")
        self.running = self.works
        return self.works

    def is_running(self) -> bool:
        return self.running

    def is_healthy(self) -> bool:
        return self.running

    def _port_is_live(self, timeout: float = 0.35) -> bool:
        return self.port_live


def _agent(port: int, server: FakeServer, monkeypatch) -> tray.ThomasTrayAgent:
    agent = tray.ThomasTrayAgent(port=port)
    agent.server = server
    monkeypatch.setattr(agent, "_notify", lambda message: None)
    monkeypatch.setattr(agent, "_setup_logging", lambda: None)
    return agent


def _run_healthcheck(agent: tray.ThomasTrayAgent, monkeypatch, passes: int, during_restart_delay=None) -> int:
    """Drive _healthcheck_loop for `passes` checks without real sleeping.

    `during_restart_delay` runs while the loop waits before restarting, as a click in
    the menu would. Returns how many waits between checks began: passes + 1 means the
    loop carried on to the next check; fewer means it ended itself.
    """
    seen = {"intervals": 0}

    def fake_sleep(seconds: float) -> None:
        if seconds == tray.HEALTHCHECK_INTERVAL_S:
            seen["intervals"] += 1
            if seen["intervals"] > passes:
                agent._stop_event.set()
        elif seconds == tray.RESTART_DELAY_S and during_restart_delay is not None:
            during_restart_delay()

    monkeypatch.setattr(tray, "time", types.SimpleNamespace(sleep=fake_sleep, time=tray.time.time))
    agent._healthcheck_loop()
    return seen["intervals"]


# --- Stop Server stays stopped -------------------------------------------------


def test_stop_server_from_the_menu_is_not_undone_by_the_healthcheck(state_dir, monkeypatch) -> None:
    agent = _agent(22040, FakeServer(running=True), monkeypatch)

    agent.user_stop_server()
    _run_healthcheck(agent, monkeypatch, passes=2)

    assert agent.server.calls == ["stop"]


def test_a_server_that_crashed_is_still_restarted(state_dir, monkeypatch) -> None:
    agent = _agent(22041, FakeServer(running=False), monkeypatch)

    _run_healthcheck(agent, monkeypatch, passes=1)

    assert agent.server.calls == ["restart"]


def test_start_server_hands_the_server_back_to_the_healthcheck(state_dir, monkeypatch) -> None:
    agent = _agent(22042, FakeServer(running=True), monkeypatch)

    agent.user_stop_server()
    agent.user_start_server()
    agent.server.running = False  # it crashes after the user started it again
    _run_healthcheck(agent, monkeypatch, passes=1)

    assert agent.server.calls == ["stop", "start", "restart"]


def test_restart_server_leaves_no_hold_on_the_healthcheck(state_dir, monkeypatch) -> None:
    agent = _agent(22043, FakeServer(running=True), monkeypatch)

    agent.user_stop_server()
    assert agent.user_restart_server() is True

    assert not agent._user_stopped.is_set()


def test_a_stopped_server_is_left_alone_even_when_another_process_holds_its_port(state_dir, monkeypatch) -> None:
    agent = _agent(22056, FakeServer(running=True, port_live=True), monkeypatch)

    agent.user_stop_server()
    agent.server.port_live = True  # someone else now answers on the port
    carried_on = _run_healthcheck(agent, monkeypatch, passes=1)

    # Without the hold at the top of the loop it would judge the port taken over and end the agent.
    assert carried_on == 2
    assert agent.server.calls == ["stop"]


def test_stop_server_clicked_during_the_restart_delay_is_not_undone(state_dir, monkeypatch) -> None:
    agent = _agent(22057, FakeServer(running=False), monkeypatch)

    carried_on = _run_healthcheck(agent, monkeypatch, passes=1, during_restart_delay=agent.user_stop_server)

    assert agent.server.calls == ["stop"]  # no "restart" behind the click
    assert carried_on == 2


def test_restart_server_clicked_during_the_restart_delay_is_not_followed_by_a_second_one(
    state_dir, monkeypatch
) -> None:
    agent = _agent(22058, FakeServer(running=False), monkeypatch)

    def restart_from_the_menu() -> None:
        agent.user_restart_server()
        agent.server.port_live = True  # the restarted server is listening now

    carried_on = _run_healthcheck(agent, monkeypatch, passes=1, during_restart_delay=restart_from_the_menu)

    # Its own live port must not read as "taken over by another process", which ended the agent.
    assert agent.server.calls == ["restart"]
    assert carried_on == 2


def test_a_restart_that_fails_tells_you(state_dir, monkeypatch) -> None:
    agent = _agent(22059, FakeServer(running=True, works=False), monkeypatch)
    told: list[str] = []
    monkeypatch.setattr(agent, "_notify", told.append)

    assert agent.user_restart_server() is False

    assert told == ["Thomas server did not restart (see the tray log)"]
    assert not agent._user_stopped.is_set()


def test_a_start_that_fails_tells_you(state_dir, monkeypatch) -> None:
    agent = _agent(22061, FakeServer(works=False), monkeypatch)
    told: list[str] = []
    monkeypatch.setattr(agent, "_notify", told.append)

    assert agent.user_start_server() is False

    assert told == ["Thomas server did not start (see the tray log)"]


def test_a_start_that_works_does_not_notify(state_dir, monkeypatch) -> None:
    agent = _agent(22062, FakeServer(), monkeypatch)
    told: list[str] = []
    monkeypatch.setattr(agent, "_notify", told.append)

    assert agent.user_start_server() is True

    assert told == []


def test_a_restart_that_works_does_not_notify(state_dir, monkeypatch) -> None:
    agent = _agent(22060, FakeServer(running=True), monkeypatch)
    told: list[str] = []
    monkeypatch.setattr(agent, "_notify", told.append)

    assert agent.user_restart_server() is True

    assert told == []


# --- One agent per port --------------------------------------------------------


def test_start_does_not_spawn_over_a_port_someone_else_serves(state_dir, monkeypatch) -> None:
    spawned: list = []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    server = tray.ServerProcess(port=22046)
    monkeypatch.setattr(server, "_port_is_live", lambda timeout=0.35: True)

    assert server.start() is False
    assert spawned == []


def test_a_second_agent_for_the_same_port_exits_without_starting_a_server(state_dir, monkeypatch) -> None:
    monkeypatch.setattr(tray, "HEALTHCHECK_INTERVAL_S", 0.01)
    first = _agent(22047, FakeServer(), monkeypatch)
    second = _agent(22047, FakeServer(), monkeypatch)
    other_port = _agent(22048, FakeServer(), monkeypatch)
    for agent in (second, other_port):
        agent.force_headless()
        agent._stop_event.set()  # a run that gets past the lock returns at once

    assert first._instance_lock.acquire()
    try:
        second.run()
        other_port.run()
    finally:
        first._instance_lock.release()

    assert second.server.calls == []
    assert other_port.server.calls == ["start", "stop"]


def _run_headless_once(agent: tray.ThomasTrayAgent, monkeypatch) -> None:
    monkeypatch.setattr(tray, "HEALTHCHECK_INTERVAL_S", 0.01)
    agent.force_headless()
    agent._stop_event.set()  # a run that gets past the start returns at once
    agent.run()


def test_a_port_someone_else_serves_is_named_on_the_console(state_dir, monkeypatch, capsys) -> None:
    agent = _agent(22053, FakeServer(port_live=True, works=False), monkeypatch)

    _run_headless_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "Port 22053 is already served by another process" in out
    assert "exit shortly" in out


def test_a_server_that_did_not_start_points_at_the_log(state_dir, monkeypatch, capsys) -> None:
    agent = _agent(22054, FakeServer(port_live=False, works=False), monkeypatch)

    _run_headless_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "did not start on port 22054" in out
    assert str(tray._LOG_FILE) in out
    assert "already served" not in out


def test_a_server_that_started_says_nothing_about_it(state_dir, monkeypatch, capsys) -> None:
    agent = _agent(22055, FakeServer(), monkeypatch)

    _run_headless_once(agent, monkeypatch)

    out = capsys.readouterr().out
    assert "already served" not in out
    assert "did not start" not in out


def test_the_lock_is_released_when_the_agent_stops(state_dir, monkeypatch) -> None:
    monkeypatch.setattr(tray, "HEALTHCHECK_INTERVAL_S", 0.01)
    first = _agent(22049, FakeServer(), monkeypatch)
    first.force_headless()
    first._stop_event.set()
    first.run()

    later = _agent(22049, FakeServer(), monkeypatch)
    assert later._instance_lock.acquire()
    later._instance_lock.release()
