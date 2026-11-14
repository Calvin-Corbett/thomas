"""Read-only Background Thomas menu, independent polls, and tray lifecycle."""

from __future__ import annotations

import ast
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.tray_agent import agent as tray
from thomas.tray_agent import background_thomas as background

PROJECTS = [
    {"state": "running", "title": "Working", "updated_at": "2026-10-19T09:00:00+00:00"},
    {"state": "repair round 2", "title": "Repair", "updated_at": "2026-10-19T10:00:00+00:00"},
    {"state": "awaiting verdict", "title": "Review", "updated_at": "2026-10-19T11:00:00+00:00"},
    {"state": "landed", "title": "Old landing", "updated_at": "2026-10-18T09:00:00+00:00"},
    {"state": "landed", "title": "New landing", "updated_at": "2026-10-19T12:00:00+00:00"},
]


class Answer:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return json.dumps(self.body).encode()


@pytest.fixture(autouse=True)
def _the_tray_keeps_its_state_in_the_test(monkeypatch, tmp_path):
    """The agent finds your real ~/.thomas from the home folder when it is imported, not from any THOMAS_ variable."""
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "tray_state.json")


@pytest.fixture
def requests(monkeypatch):
    seen = []
    answers = {background.HEALTH_URL: {"status": "ok"}, background.PROJECTS_URL: {"projects": PROJECTS}}

    def build(*handlers):
        assert any(isinstance(h, urllib.request.ProxyHandler) and not h.proxies for h in handlers)
        assert any(
            isinstance(h, urllib.request.HTTPRedirectHandler)
            and h.redirect_request(None, None, 302, "redirect", {}, background.BASE_URL) is None
            for h in handlers
        )

        def open_request(request, timeout):
            assert request.get_method() == "GET"
            assert request.full_url in (background.HEALTH_URL, background.PROJECTS_URL)
            assert timeout == (5 if request.full_url == background.HEALTH_URL else 600)
            seen.append(request.full_url)
            answer = answers[request.full_url]
            if isinstance(answer, Exception):
                raise answer
            return Answer(answer)

        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(background.urllib.request, "build_opener", build)
    return seen, answers


def test_on_counts_and_newest_landing_in_local_time(requests):
    seen, _ = requests
    monitor = background.BackgroundThomas()
    monitor.poll_health_once()
    monitor.poll_projects_once()
    lines = monitor.lines(now=monitor.last_listing_at + 185)
    assert "Background Thomas: on" in lines
    assert "2 Build teams running" in lines
    assert "1 hand-in waiting for your card" in lines
    assert any(
        "New landing" in line
        and datetime.fromisoformat(PROJECTS[-1]["updated_at"]).astimezone().strftime("%H:%M") in line
        for line in lines
    )
    assert not any("Old landing" in line for line in lines)
    assert any("3 minutes" in line for line in lines)
    assert seen == [background.HEALTH_URL, background.PROJECTS_URL]


def test_last_landing_uses_instant_not_timestamp_text(requests):
    _, answers = requests
    answers[background.PROJECTS_URL] = {
        "projects": [
            {"state": "landed", "title": "Earlier", "updated_at": "2026-10-19T13:00:00+02:00"},
            {"state": "landed", "title": "Later", "updated_at": "2026-10-19T12:00:00+00:00"},
        ]
    }
    monitor = background.BackgroundThomas()
    monitor.poll_projects_once()
    last_landing = next(line for line in monitor.lines() if line.startswith("Last landing:"))
    assert "Later" in last_landing
    assert "Earlier" not in last_landing
    assert datetime.fromisoformat("2026-10-19T12:00:00+00:00").astimezone().strftime("%Y-%m-%d %H:%M") in last_landing


@pytest.mark.parametrize("error", [TimeoutError("slow"), OSError("closed")])
def test_health_failure_is_off_but_previous_listing_remains(requests, error):
    _, answers = requests
    monitor = background.BackgroundThomas()
    monitor.poll_projects_once()
    monitor.poll_health_once()
    answers[background.HEALTH_URL] = error
    answers[background.PROJECTS_URL] = TimeoutError("slow listing")
    monitor.poll_health_once()
    monitor.poll_projects_once()
    lines = monitor.lines(now=monitor.last_listing_at + 125)
    assert "Background Thomas: off" in lines
    assert "2 Build teams running" in lines
    assert any("2 minutes" in line for line in lines)


def test_no_listing_answer_yet(requests):
    monitor = background.BackgroundThomas()
    monitor.poll_health_once()
    lines = monitor.lines()
    assert "Background Thomas: on" in lines
    assert any("has not answered yet" in line for line in lines)
    assert not any("Build teams running" in line for line in lines)


def test_slow_listing_does_not_block_health(requests, monkeypatch):
    _, answers = requests
    entered = threading.Event()
    release = threading.Event()
    original = background.urllib.request.build_opener

    def slow_build(*handlers):
        opener = original(*handlers)
        old_open = opener.open

        def open_request(request, timeout):
            if request.full_url == background.PROJECTS_URL:
                entered.set()
                release.wait(2)
            return old_open(request, timeout)

        opener.open = open_request
        return opener

    monkeypatch.setattr(background.urllib.request, "build_opener", slow_build)
    monitor = background.BackgroundThomas()
    worker = threading.Thread(target=monitor.poll_projects_once)
    worker.start()
    try:
        assert entered.wait(1)
        monitor.poll_health_once()
        assert "Background Thomas: on" in monitor.lines()
        assert any("has not answered yet" in line for line in monitor.lines())
    finally:
        release.set()
        worker.join(timeout=2)
    assert answers[background.HEALTH_URL] == {"status": "ok"}


def test_redirect_is_failed_without_follow_up(requests):
    seen, answers = requests
    answers[background.HEALTH_URL] = urllib.error.HTTPError(background.HEALTH_URL, 302, "redirect", {}, None)
    monitor = background.BackgroundThomas()
    monitor.poll_health_once()
    assert "Background Thomas: off" in monitor.lines()
    assert seen == [background.HEALTH_URL]


def test_open_background_uses_browser_and_matching_keepalive_port(monkeypatch, requests):
    opened = []
    monkeypatch.setattr(tray.webbrowser, "open", opened.append)
    agent = tray.ThomasTrayAgent()
    agent.open_background_thomas()
    assert opened == ["http://127.0.0.1:8898/"]
    path = Path(__file__).resolve().parents[1] / "scripts/cage/cage_keepalive.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    port = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "SERVER_PORT" for name in node.targets)
    )
    assert port == background.BACKGROUND_PORT


def test_headless_does_not_start_background_requests(requests, monkeypatch, tmp_path):
    seen, _ = requests
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "state.json")
    agent = tray.ThomasTrayAgent()
    agent.force_headless()
    agent.server = SimpleNamespace(start=lambda: True, stop=lambda: None)
    monkeypatch.setattr(agent, "_setup_logging", lambda: None)
    monkeypatch.setattr(agent, "_healthcheck_loop", lambda: None)
    monkeypatch.setattr(agent, "_run_headless", lambda: None)
    monkeypatch.setattr(agent._instance_lock, "acquire", lambda: True)
    monkeypatch.setattr(agent._instance_lock, "release", lambda: None)
    agent.run()
    assert seen == []
    assert not agent._background.running


def test_unchanged_icon_ticks_do_not_rebuild_menu_or_query_autostart(requests, monkeypatch):
    agent = tray.ThomasTrayAgent()
    agent._background.poll_health_once()
    agent._background.poll_projects_once()
    queries = []
    monkeypatch.setattr(tray, "is_auto_start_enabled", lambda: queries.append("query") or False)
    icon = SimpleNamespace(icon=None, title=None, menu=None)

    def rebuild(lines):
        tray.is_auto_start_enabled()
        return tuple(lines)

    agent._background_menu_builder = rebuild
    agent._last_background_lines = agent.background_thomas_lines()
    monkeypatch.setattr(tray, "_make_icon", lambda status: status)
    monkeypatch.setattr(agent, "_tray_status", lambda: "active")
    for _ in range(5):
        agent._update_icon(icon)
        agent._refresh_background_menu(icon)
    assert queries == []
    assert icon.menu is None
    agent._background.poll_health_once()
    agent._update_icon(icon)
    agent._refresh_background_menu(icon)
    assert queries == []


def test_polling_stops_with_agent(requests, monkeypatch, tmp_path):
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "state.json")
    agent = tray.ThomasTrayAgent()
    agent.server = SimpleNamespace(stop=lambda: None)
    agent._background.start()
    assert agent._background.running
    agent.stop()
    assert not agent._background.running
