"""Tray follow-ups exercised with a fake listing, pystray and Windows task."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from thomas.tray_agent import agent as tray
from thomas.tray_agent import autostart
from thomas.tray_agent import background_thomas as background


@pytest.fixture
def listing(monkeypatch):
    projects = []
    monkeypatch.setattr(background, "_get_json", lambda url, timeout: {"projects": projects})
    monitor = background.BackgroundThomas()
    monitor.poll_projects_once()
    return monitor, projects


@pytest.mark.parametrize(
    ("count", "label"), [(1, "1 Build team running"), (2, "2 Build teams running"), (0, "0 Build teams running")]
)
def test_running_team_grammar(listing, count, label):
    monitor, projects = listing
    projects.extend({"state": "running"} for _ in range(count))
    assert label in monitor.lines()


@pytest.mark.parametrize(("seconds", "label"), [(61, "1 minute old"), (185, "3 minutes old")])
def test_listing_age_grammar(listing, seconds, label):
    monitor, _ = listing
    assert f"Project listing: {label}" in monitor.lines(now=monitor.last_listing_at + seconds)


def test_last_landing_labels_hand_in_in_local_time(listing):
    monitor, projects = listing
    projects.extend(
        [
            {"state": "landed", "title": "Old", "updated_at": "2026-10-19T13:00:00+02:00"},
            {"state": "landed", "title": "New project", "updated_at": "2026-10-19T18:02:00+00:00"},
        ]
    )
    line = next(line for line in monitor.lines() if line.startswith("Last landing:"))
    local = datetime.fromisoformat(projects[-1]["updated_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
    assert line.startswith("Last landing: New project")
    assert "Old" not in line
    assert local in line
    assert "handed in" in line


@pytest.fixture
def menu_rig(monkeypatch, tmp_path):
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    clock = SimpleNamespace(seconds=0.0, age=0)
    monkeypatch.setattr(tray.time, "monotonic", lambda: clock.seconds)
    task = SimpleNamespace(present=True, accepts=True, calls=[])

    def schtasks(args, timeout):
        task.calls.append(args[0])
        if args[0] == "/Query":
            ok = task.present
        else:
            ok = task.accepts
            if ok:
                task.present = args[0] == "/Create"
        return SimpleNamespace(returncode=0 if ok else 1, stdout="", stderr="ERROR: Access is denied.")

    monkeypatch.setattr(autostart, "_run_schtasks", schtasks)
    menus = []

    class Item:
        def __init__(self, text, action, **options):
            self.text = text
            self.action = action
            self.checked = options.get("checked")
            self.is_checked = False

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items
            for item in items:
                if isinstance(item, Item) and item.checked:
                    item.is_checked = item.checked(item)
            menus.append(self)

    class Icon:
        def __init__(self, name, image, title, menu):
            self.menu = menu

        def run(self):
            return None

    monkeypatch.setattr(tray, "_make_icon", lambda status: status)
    monkeypatch.setattr(tray.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    agent = tray.ThomasTrayAgent()
    agent._pystray = SimpleNamespace(Menu=Menu, MenuItem=Item, Icon=Icon)
    monkeypatch.setattr(agent, "_tray_status", lambda: "active")
    monkeypatch.setattr(agent, "_notify", lambda message: None)
    monkeypatch.setattr(
        agent,
        "background_thomas_lines",
        lambda: (f"Project listing: {clock.age} minute{'s' if clock.age != 1 else ''} old",),
    )
    agent._run_with_tray()

    def checked():
        return next(
            item.is_checked
            for item in agent._icon.menu.items
            if isinstance(item, Item) and item.text == "Auto-start with Windows"
        )

    return agent, clock, task, menus, checked


def test_ten_changed_age_lines_do_not_read_windows_on_menu_build(menu_rig):
    agent, clock, task, menus, checked = menu_rig
    assert task.calls == ["/Query"]
    for minute in range(1, 11):
        clock.seconds = minute * 59
        clock.age = minute
        before = len(task.calls)
        agent._refresh_background_menu(agent._icon)
        assert len(menus) == minute + 1
        assert len(task.calls) == before
        assert checked() is True


def test_hour_of_ticks_queries_at_most_once_per_ten_minutes_and_notices_removal(menu_rig):
    agent, clock, task, _, checked = menu_rig
    task.present = False
    seen_unchecked_at = None
    for tick in range(1, 721):
        clock.seconds = tick * 5
        clock.age = int(clock.seconds // 60)
        agent._refresh_background_menu(agent._icon)
        if checked() is False and seen_unchecked_at is None:
            seen_unchecked_at = clock.seconds
    assert task.calls.count("/Query") <= 7
    assert seen_unchecked_at is not None and seen_unchecked_at <= 600


def test_task_removed_with_unchanged_lines_rebuilds_only_on_changed_check(menu_rig):
    agent, clock, task, menus, checked = menu_rig
    task.present = False
    for second in range(5, 600, 5):
        clock.seconds = second
        agent._refresh_background_menu(agent._icon)
    assert len(menus) == 1
    assert task.calls == ["/Query"]
    clock.seconds = 600
    agent._refresh_background_menu(agent._icon)
    assert task.calls == ["/Query", "/Query"]
    assert len(menus) == 2
    assert checked() is False
    agent._refresh_background_menu(agent._icon)
    assert len(menus) == 2


def test_changed_lines_rebuild_once_and_remember(menu_rig):
    agent, clock, _, menus, _ = menu_rig
    old = agent._icon.menu
    clock.seconds = 60
    clock.age = 1
    agent._refresh_background_menu(agent._icon)
    assert agent._icon.menu is menus[-1] and agent._icon.menu is not old
    assert any(item.text == "Project listing: 1 minute old" for item in menus[-1].items if hasattr(item, "text"))
    assert agent._last_background_lines == ("Project listing: 1 minute old",)
    agent._refresh_background_menu(agent._icon)
    assert agent._icon.menu is menus[-1]
    assert len(menus) == 2


@pytest.mark.parametrize("accepts", [True, False])
def test_toggle_checks_fresh_task_once_then_displays_outcome(menu_rig, accepts):
    agent, _, task, menus, checked = menu_rig
    task.accepts = accepts
    before = len(task.calls)
    auto_item = next(item for item in menus[-1].items if getattr(item, "text", None) == "Auto-start with Windows")
    auto_item.action(agent._icon, auto_item)
    assert task.calls[before:].count("/Query") == 1
    assert task.calls[before:] == ["/Query", "/Delete"]
    assert checked() is (not accepts)
    assert agent._icon.menu is menus[-1]
