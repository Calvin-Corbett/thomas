"""A server start notes in the step log when the server before it died without exiting, with its runs still going.

On 2026-11-06 Build runs were cut off at twelve moments in one day and nothing said why their server stopped.
Regression for thomas.server.server_lifetime and its calls in thomas.server.app_routes_init.
"""

from __future__ import annotations

import json
import os

import pytest

from thomas.server import server_lifetime


@pytest.fixture
def steps(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path / "steps"))
    monkeypatch.delenv("THOMAS_STEP_LOG", raising=False)

    def read() -> list[dict]:
        return [
            json.loads(line)
            for path in (tmp_path / "steps").glob("steps-*.jsonl")
            for line in path.read_text().splitlines()
        ]

    return read


def test_a_server_that_died_is_named_by_the_next_start(tmp_path, steps) -> None:
    marker = tmp_path / "server-lifetime.json"
    marker.write_text(json.dumps({"pid": os.getpid() + 1, "port": 8898, "started": 1000.0, "exited": False}))
    died = server_lifetime.started(8898, path=marker, now=4600.0)
    assert died is not None and died["pid"] == os.getpid() + 1
    rows = {row["step"]: row for row in steps()}
    assert rows["server_died"]["seconds"] == 3600.0 and rows["server_died"]["died_pid"] == os.getpid() + 1
    assert "server_start" in rows
    assert json.loads(marker.read_text())["pid"] == os.getpid()


def test_a_clean_exit_is_not_a_death(tmp_path, steps) -> None:
    marker = tmp_path / "server-lifetime.json"
    server_lifetime.started(8898, path=marker, now=100.0)
    server_lifetime.exited(path=marker, now=160.0)
    data = json.loads(marker.read_text())
    assert data["exited"] is True
    data["pid"] = os.getpid() + 1  # the next start is another process
    marker.write_text(json.dumps(data))
    assert server_lifetime.started(8898, path=marker, now=200.0) is None
    assert [row["step"] for row in steps()] == ["server_start", "server_exit", "server_start"]


def test_an_exit_never_closes_a_newer_servers_marker(tmp_path, steps) -> None:
    marker = tmp_path / "server-lifetime.json"
    marker.write_text(json.dumps({"pid": os.getpid() + 1, "started": 1.0, "exited": False}))
    server_lifetime.exited(path=marker)
    assert json.loads(marker.read_text())["exited"] is False and steps() == []


def test_the_first_start_ever_has_no_one_before_it(tmp_path, steps) -> None:
    assert server_lifetime.started(path=tmp_path / "none" / "server-lifetime.json") is None
    assert [row["step"] for row in steps()] == ["server_start"]
