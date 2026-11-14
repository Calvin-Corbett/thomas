"""Opt-in offline scale gate through Build, Praxis, and real HTTP sockets.

The scripted endpoint is not a billable model or accepted Build artifact.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from thomas.core.llm_request_admission import admitted_stream
from thomas.core.llm_transport_pool import close_http_client, get_http_client
from thomas.forge.anvil.build_agent_scheduler import BuildTeamScheduler
from thomas.server.praxis.recovery import PraxisRunJournal
from thomas.server.praxis.run_channel import RunChannel
from thomas.tools.base import ToolResult


class _FaultEndpoint(BaseHTTPRequestHandler):
    attempts: Counter[str] = Counter()
    lock = threading.Lock()

    def do_GET(self) -> None:
        child = self.path.rsplit("/", 1)[-1]
        with self.lock:
            self.attempts[child] += 1
            attempt = self.attempts[child]
        if attempt == 1 and int(child.rsplit("-", 1)[-1]) % 5 == 0:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        status = 429 if attempt == 1 else 200
        body = b"retry" if status == 429 else b"review complete"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        if status == 429:
            self.send_header("Retry-After", "0.01")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        pass


async def _run_build(
    run_number: int,
    count: int,
    base_url: str,
    project: Path,
    provider: str,
    barrier: threading.Barrier | None = None,
) -> Counter[str]:
    """One production task.team scheduler drives one Praxis child per assignment."""
    first_attempt: set[str] = set()
    owner = SimpleNamespace(
        config=SimpleNamespace(provider="openai", extra_headers={}, api_key="", timeout_s=10),
        _client=None,
        _request_admission=None,
    )

    async def child(agent_id: str, _kind: str, title: str, _brief: str):
        if title not in first_attempt:
            first_attempt.add(title)
            if barrier is not None:
                await asyncio.to_thread(barrier.wait, 60)
        client = await get_http_client(owner)
        try:
            async with admitted_stream(owner, client, "GET", f"{base_url}/{title}") as response:
                body = await response.aread()
                if response.status_code == 429:
                    outcome = {
                        "type": "error",
                        "error": "HTTP 429",
                        "retryable": True,
                        "provider_status": 429,
                        "response_headers": dict(response.headers),
                    }
                elif response.status_code == 200 and body == b"review complete":
                    outcome = {"type": "done", "text": body.decode(), "model_used": "local-socket-fixture"}
                else:
                    outcome = {"type": "error", "error": f"unexpected HTTP {response.status_code}"}
            yield outcome
        except httpx.TransportError as exc:
            yield {
                "type": "error",
                "error": type(exc).__name__,
                "retryable": True,
                "transport_failure": True,
            }

    channel = RunChannel(f"fault-run-{run_number}", child)
    lifecycle = RunChannel(
        f"build-run-{run_number}",
        child,
        journal=PraxisRunJournal(project / "praxis-runs.sqlite3"),
        project_root=project,
    )

    class BridgeClient:
        async def call(self, action, payload):
            if action == "admit_builder":
                return {"agent": await lifecycle.admit_external_builder(**payload)}
            if action == "report_builder":
                return await lifecycle.report_external_builder(payload["agent_id"], payload["event"])
            raise AssertionError(f"unexpected Build bridge action: {action}")

    class Writer:
        async def execute_assigned(self, job, *, request_admission, observe):
            owner._request_admission = request_admission
            title = job["title"]
            handle = (
                await channel.spawn(
                    [
                        {
                            "id": title,
                            "kind": "review",
                            "title": title,
                            "brief": job["instructions"],
                        }
                    ]
                )
            )[0]
            observe({"child_id": handle["agent_id"]})
            await channel._tasks[handle["agent_id"]]
            row = channel.status([handle["agent_id"]])["agents"][0]
            if row["state"] != "completed":
                return ToolResult(ok=False, error=f"child {title}: {row['state']}")
            (project / job["path"]).write_text(title + "\n", encoding="utf-8")
            return ToolResult(ok=True, data="integrated local fixture file")

    jobs = [
        {
            "title": f"run-{run_number}-child-{index}",
            "instructions": "Inspect a separate bounded component",
            "path": f"component-{index}.txt",
        }
        for index in range(count)
    ]
    scheduler = BuildTeamScheduler(
        Writer(),
        project=project,
        model="local-socket-fixture",
        provider=provider,
        emit=lambda _event: None,
        deadline=asyncio.get_running_loop().time() + 120,
        channel_client=BridgeClient(),
    )
    try:
        result = await scheduler.execute({"assignments": jobs})
        assert result.ok, result.error
        assert result.data["integrated"] == result.data["total"] == count
        rows = channel.status()["agents"]
        assert len(rows) == count
        assert all(row["state"] == "completed" and row["attempts"] == 2 for row in rows)
        assert all([event["type"] for event in row["events"]] == ["error", "retry", "done"] for row in rows)
        assert all(row["model_used"] == "local-socket-fixture" for row in rows)
        builder_rows = lifecycle.status()["agents"]
        assert len(builder_rows) == count
        assert all(
            row["state"] == "completed" and row["execution_origin"] == "external_builder" for row in builder_rows
        )
        assert all([event["type"] for event in row["events"]] == ["started", "done"] for row in builder_rows)
        assert channel.status()["metrics"]["peak"] >= 2
        admission = result.data["admission"]
        assert admission["admitted"] == admission["settled"] == count * 2
        reset_count = len(range(0, count, 5))
        assert admission["refusals"] == count - reset_count
        assert admission["failed"] == reset_count
        assert admission["inflight"] == 0
        return Counter(
            children=len(rows),
            integrated=result.data["integrated"],
            completed=sum(row["state"] == "completed" for row in rows),
            refusals=admission["refusals"],
            resets=admission["failed"],
        )
    finally:
        await channel.close()
        await lifecycle.close()
        await close_http_client(owner)


@pytest.fixture
def local_fault_endpoint():
    _FaultEndpoint.attempts = Counter()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FaultEndpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_two_child_local_socket_smoke(tmp_path, monkeypatch, local_fault_endpoint) -> None:
    monkeypatch.setenv("THOMAS_RUNTIME_DIR", str(tmp_path / "runtime"))
    project = tmp_path / "build-0"
    project.mkdir()
    totals = asyncio.run(_run_build(0, 2, local_fault_endpoint, project, f"local-fault-{local_fault_endpoint}"))
    assert totals == {"children": 2, "integrated": 2, "completed": 2, "refusals": 1, "resets": 1}


@pytest.mark.skipif(
    os.environ.get("THOMAS_RUN_PRAXIS_SCALE_100") != "1",
    reason="Run explicitly after integrated Praxis path is ready",
)
def test_five_runs_of_twenty_children_complete_under_429_storm(
    tmp_path,
    monkeypatch,
    local_fault_endpoint,
) -> None:
    """Five real Build schedulers settle 100 child lifecycles across five loops."""
    monkeypatch.setenv("THOMAS_RUNTIME_DIR", str(tmp_path / "runtime"))
    projects = [tmp_path / f"build-{index}" for index in range(5)]
    for project in projects:
        project.mkdir()
    totals: Counter[str] = Counter()
    barrier = threading.Barrier(100)
    provider = f"local-fault-{local_fault_endpoint}"
    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = [
            pool.submit(asyncio.run, _run_build(index, 20, local_fault_endpoint, projects[index], provider, barrier))
            for index in range(5)
        ]
        for run in runs:
            totals.update(run.result(timeout=150))
    assert totals == {
        "children": 100,
        "integrated": 100,
        "completed": 100,
        "refusals": 80,
        "resets": 20,
    }
    assert len(_FaultEndpoint.attempts) == 100
    assert set(_FaultEndpoint.attempts.values()) == {2}
    assert all(len(list(project.glob("component-*.txt"))) == 20 for project in projects)
