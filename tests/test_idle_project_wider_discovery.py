"""Idle project discovery uses additional evidence only when there is room."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server import page_response_timing, self_project_queue, self_project_queue_tick
from thomas.server import self_improvement_planner as planner


def _report(root: Path, body: str) -> None:
    folder = root / ".thomas" / "evolve" / "planner" / "reports"
    folder.mkdir(parents=True)
    (folder / "recent.xml").write_text(f"<testsuite>{body}</testsuite>", encoding="utf-8")


def test_wider_scan_books_slow_and_flaky_tests_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    _report(
        tmp_path,
        '<testcase file="tests/test_speed.py" name="test_slow" time="11"/>'
        '<testcase file="tests/test_speed.py" name="test_flaky" time="0.1"><flakyFailure/></testcase>',
    )
    assert planner.scan(tmp_path, 8888) == []
    first = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert {row["origin"] for row in first} == {"slow_test", "flaky_test"}
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []
    assert len(self_project_queue.read(tmp_path)["queued"]) == 2


def test_wider_scan_finds_repeated_slow_pages_without_query_strings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    (logs / "thomas.log").write_text(
        "Slow page response path=/settings elapsed_ms=2200\n"
        "Slow page response path=/settings elapsed_ms=3000\n"
        "Slow page response path=/mission elapsed_ms=2500\n"
        "Slow page response path=/other elapsed_ms=5000\n"
        "Slow page response path=/settings?token=secret elapsed_ms=5000\n",
        encoding="utf-8",
    )
    booked = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert len(booked) == 1
    assert booked[0]["origin"] == "slow_page"
    assert booked[0]["source_id"] == "/settings"
    assert "secret" not in str(booked)
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []


@pytest.mark.asyncio
async def test_page_timing_logs_only_slow_successful_known_pages(caplog) -> None:
    class Request:
        method = "GET"
        path = "/settings"
        query_string = "query=private"

    async def handler(_request):
        return web.Response(text="ok")

    clock = iter([0, 3, 0, 1])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(page_response_timing.time, "monotonic", lambda: next(clock))
        assert (await page_response_timing.page_response_timing(Request(), handler)).status == 200
        assert "Slow page response path=/settings elapsed_ms=" in caplog.text
        assert "private" not in caplog.text
        caplog.clear()
        assert (await page_response_timing.page_response_timing(Request(), handler)).status == 200
        assert not caplog.records
        request = SimpleNamespace(method="GET", path="/other")
        await page_response_timing.page_response_timing(request, handler)
        assert not caplog.records


def test_wider_scan_reads_configured_server_log_without_leaking_its_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    log_path = tmp_path / "outside" / "private-server.log"
    log_path.parent.mkdir()
    log_path.write_text("ERROR hidden server detail\n" * 2, encoding="utf-8")
    monkeypatch.setenv("THOMAS_LOG_FILE", str(log_path))

    booked = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert len(booked) == 1
    assert booked[0]["origin"] == "server_log"
    assert "private-server" not in booked[0]["source_id"]
    assert "hidden server detail" not in self_project_queue.read(tmp_path)["queued"][0]["request"]


def test_wider_scan_skips_existing_projects_and_uses_no_raw_log_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    (logs / "thomas.log").write_text(
        "ERROR private details should stay out of project requests\n" * 2, encoding="utf-8"
    )
    booked = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert len(booked) == 1
    ask = self_project_queue.read(tmp_path)["queued"][0]
    assert ask["origin"] == "server_log"
    assert "private details" not in json.dumps(ask)
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []


def test_wider_scan_uses_error_fingerprints_without_log_contents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    (logs / "thomas.log").write_text(
        "ERROR: failed at line 12: private data\nERROR: failed at line 13: private data\n",
        encoding="utf-8",
    )
    booked = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert len(booked) == 1
    assert booked[0]["origin"] == "server_log"
    row = self_project_queue.read(tmp_path)["queued"][0]
    assert "private data" not in row["request"]
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []


def test_wider_scan_reads_runtime_data_logs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "thomas.log").write_text("ERROR repeated failure\n" * 2, encoding="utf-8")
    booked = planner.scan(tmp_path, 8888, wider_when_empty=True)
    assert len(booked) == 1
    assert booked[0]["origin"] == "server_log"


def test_wider_scan_requires_repeated_errors_in_recent_log(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    log = logs / "thomas.log"
    log.write_text("ERROR single occurrence\n", encoding="utf-8")
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []
    log.write_text("ERROR repeated occurrence\nERROR repeated occurrence\n", encoding="utf-8")
    assert len(planner.scan(tmp_path, 8888, wider_when_empty=True)) == 1


def test_idle_tick_asks_planner_to_search_wider_only_with_room(tmp_path: Path, monkeypatch) -> None:
    from thomas.server import autopilot_hold_tick

    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setattr(autopilot_hold_tick, "port_of", lambda app: 8888)
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda *args: None)
    monkeypatch.setattr(self_project_queue_tick.self_project_routes, "running_projects", lambda app: set())
    monkeypatch.setattr(self_project_queue_tick, "_select", lambda *args: None)
    calls: list[bool] = []
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    monkeypatch.setattr(planner, "propose_wider", lambda *args: calls.append(True) or [])
    app = {self_project_queue_tick.APP_PRAXIS_START_CODE_RUN: object()}
    asyncio.run(self_project_queue_tick.tick(app, tmp_path))
    assert calls == [True]
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda *args: "busy")
    asyncio.run(self_project_queue_tick.tick(app, tmp_path))
    assert calls == [True]
    monkeypatch.setattr(self_project_queue_tick, "capacity_blocker", lambda *args: None)
    self_project_queue.enqueue(tmp_path, "existing work", {}, "", 8888)
    asyncio.run(self_project_queue_tick.tick(app, tmp_path))
    assert calls == [True]


def test_wider_scan_does_not_search_when_queue_has_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "propose", lambda *args, **kwargs: [])
    _report(tmp_path, '<testcase file="tests/test_speed.py" name="test_slow" time="11"/>')
    self_project_queue.change(
        tmp_path,
        lambda data: data["queued"].append(self_project_queue.new_entry("existing work", {}, "", 8888)),
    )
    assert planner.scan(tmp_path, 8888, wider_when_empty=True) == []
    assert len(self_project_queue.read(tmp_path)["queued"]) == 1
