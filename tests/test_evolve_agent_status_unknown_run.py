"""Explicit missing runs are errors without changing existing status selection."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.praxis.startup import APP_PRAXIS_RECOVERY_REPORT
from thomas.server.routes.evolve_agent_run_state import (
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_RUNS,
    APP_EVOLVE_AGENT_SESSION,
)
from thomas.server.routes.evolve_agent_watch_routes import build_evolve_agent_watch_handlers
from thomas.server.routes.praxis_run_routes import APP_PRAXIS_RUN_CHANNELS

STATUS = "/api/evolve/agent/status"


def status_client(tmp_path, *, slots=None, session=None, drain=None, recovery=None, channels=None, authorize=None):
    app = web.Application()
    app[APP_EVOLVE_AGENT_RUNS] = slots or {}
    app[APP_EVOLVE_AGENT_SESSION] = session or {}
    app[APP_EVOLVE_AGENT_DRAIN] = drain
    app[APP_PRAXIS_RECOVERY_REPORT] = recovery or {}
    app[APP_PRAXIS_RUN_CHANNELS] = SimpleNamespace(_runs=channels or {})
    handlers = build_evolve_agent_watch_handlers(
        app,
        require_api_access=authorize or (lambda _: None),
        catalog_root=lambda: tmp_path,
        running=lambda: False,
    )
    app.router.add_get(STATUS, handlers["status"])
    return TestClient(TestServer(app))


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [{"run_id": "codex-missing-20261016T1650"}, {"run_id": " missing "}])
async def test_explicit_unknown_run_returns_404_not_an_idle_success(tmp_path, query):
    async with status_client(tmp_path, session={"run_id": "other-run"}) as client:
        response = await client.get(STATUS, params=query)
        payload = await response.json()
    assert response.status == 404
    assert payload["ok"] is False
    assert payload["code"] == "run_not_found"
    assert payload["run_id"] == query["run_id"].strip()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [{}, {"conversation_id": "before-first-run"}, {"run_id": " "}])
async def test_idle_and_conversation_only_polling_still_succeed(tmp_path, query):
    async with status_client(tmp_path) as client:
        response = await client.get(STATUS, params=query)
        payload = await response.json()
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["run_id"] == ""
    assert payload["running"] is False
    assert payload["persistence_state"] == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        {"run_id": "registered"},
        {"conversation_id": "conversation"},
        {"conversation_id": "conversation", "run_id": "different-run"},
    ],
)
@pytest.mark.parametrize("recording_state", ["recording", "persisted", "failed"])
async def test_registered_selection_preserves_recording_and_persistence(tmp_path, query, recording_state):
    drain = asyncio.get_running_loop().create_future()
    if recording_state != "recording":
        drain.set_result({"persistence_confirmed": recording_state == "persisted"})
    session = {"run_id": "registered", "conversation_id": "conversation", "proc": SimpleNamespace(returncode=0)}
    slots = {"conversation": {"session": session, "drain": {"task": drain}}}
    try:
        async with status_client(tmp_path, slots=slots, session={"run_id": "latest"}) as client:
            response = await client.get(STATUS, params=query)
            payload = await response.json()
        assert response.status == 200
        assert payload["ok"] is True
        assert payload["run_id"] == "registered"
        assert payload["session"]["conversation_id"] == "conversation"
        assert payload["running"] is False
        assert payload["recording"] is (recording_state == "recording")
        assert payload["persistence_state"] == recording_state
        assert payload["persistence_confirmed"] is (recording_state == "persisted")
        assert slots["conversation"]["drain"]["task"] is drain
    finally:
        if not drain.done():
            drain.cancel()


@pytest.mark.asyncio
async def test_default_status_keeps_legacy_session_and_active_run_list(tmp_path):
    session = {"run_id": "latest", "conversation_id": "latest-conversation"}
    slots = {
        "other": {
            "session": {"run_id": "other-run", "conversation_id": "other", "proc": SimpleNamespace(returncode=None)}
        }
    }
    async with status_client(tmp_path, slots=slots, session=session) as client:
        response = await client.get(STATUS)
        payload = await response.json()
    assert response.status == 200
    assert payload["run_id"] == "latest"
    assert payload["runs"][0]["run_id"] == "other-run"
    assert payload["runs"][0]["running"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [{"run_id": "recovered"}, {"conversation_id": "recovered-conversation"}])
async def test_genuinely_recovered_run_without_a_local_slot_still_resolves(tmp_path, query):
    recovery = {"resumed": [{"run_id": "recovered", "conversation_id": "recovered-conversation"}]}
    channel = SimpleNamespace(status=lambda: {"agents": [], "metrics": {}})
    async with status_client(tmp_path, recovery=recovery, channels={"recovered": channel}) as client:
        response = await client.get(STATUS, params=query)
        payload = await response.json()
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["run_id"] == "recovered"
    assert payload["praxis_recovered"]["lead_attached"] is False
    assert payload["session"]["conversation_id"] == "recovered-conversation"


@pytest.mark.asyncio
@pytest.mark.parametrize("has_report", [False, True])
async def test_recovery_needs_both_report_and_channel_to_resolve_a_missing_run(tmp_path, has_report):
    recovery = {"resumed": [{"run_id": "missing"}]} if has_report else {}
    channels = {} if has_report else {"missing": SimpleNamespace(status=lambda: {"agents": [], "metrics": {}})}
    async with status_client(tmp_path, recovery=recovery, channels=channels) as client:
        response = await client.get(STATUS, params={"run_id": "missing"})
        payload = await response.json()
    assert response.status == 404
    assert payload["code"] == "run_not_found"
    assert payload["run_id"] == "missing"


@pytest.mark.asyncio
async def test_authentication_still_precedes_unknown_run_lookup(tmp_path):
    def deny(_request):
        raise web.HTTPUnauthorized()

    async with status_client(tmp_path, authorize=deny) as client:
        response = await client.get(STATUS, params={"run_id": "missing"})
    assert response.status == 401


CLIENT_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const root = process.argv[1];
const reply = JSON.parse(process.argv[2]);
const scenario = process.argv[3];
const state = {
  runId: 'retired-run', contextEpoch: 1, running: true, activeId: 'conversation',
  liveEvents: [], artifacts: [], queuedSends: [], steeringBusy: scenario === 'steering',
};
let reopens = 0, refreshes = 0, loads = 0, released = 0, requests = 0;
global.window = {};
global.fetch = async () => {
  requests += 1;
  if (requests > 2) throw new Error('unexpected repeated poll');
  if (reply.networkError) throw new Error('offline');
  if (scenario === 'stale') state.contextEpoch += 1;
  return { ok: reply.http === 200, status: reply.http, json: async () => reply.body };
};
global.EventSource = class { constructor() { reopens += 1; } close() {} };
vm.runInThisContext(fs.readFileSync(root + '/thomas/server/web/js/unified_code_run_stream.js', 'utf8'));
const stream = window.ThomasCodeRunStream.create({
  state,
  host: () => ({ setBusy: value => { if (!value) released += 1; } }),
  codeProjects: () => ({ updateProjectButton() {} }),
  pushLiveEvent: event => state.liveEvents.push(event),
  render() {}, updateRunStatus() {}, errorText: error => error.message,
  loadConversation: async () => { loads += 1; return true; },
  refresh: async () => { refreshes += 1; },
  lifecycle: () => ({ runIsDurable: () => false, streamUrl: () => '/stream' }),
});
(async () => {
  if (scenario === 'stop') {
    const code = fs.readFileSync(root + '/thomas/server/web/js/unified_code_mode.js', 'utf8');
    const start = code.indexOf('  async function waitForRestartReady(');
    const end = code.indexOf('\n  // Codex-parity interrupt:', start);
    if (start < 0 || end < 0) throw new Error('stop poll function not found');
    const poll = new Function('state', 'fetch', 'window',
      code.slice(start, end) + '\nreturn waitForRestartReady();');
    try {
      const stopped = await poll(state, fetch, { setTimeout: fn => fn() });
      console.log(JSON.stringify({ stopped, requests }));
    } catch (error) { console.log(JSON.stringify({ error: error.message, requests })); }
  } else {
    const source = { close() {} };
    state.source = source;
    const handled = await stream.handleStreamError(source);
    console.log(JSON.stringify({ handled, running: state.running, reopens, refreshes, loads, released }));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def drive_status_client(http, body, scenario="stream", *, network_error=False):
    result = subprocess.run(
        [
            "node",
            "-e",
            CLIENT_HARNESS,
            str(Path(__file__).resolve().parents[1]),
            json.dumps({"http": http, "body": body, "networkError": network_error}),
            scenario,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("scenario", ["stream", "steering"])
def test_stream_releases_a_pruned_or_restart_lost_run(scenario):
    seen = drive_status_client(404, {"ok": False, "code": "run_not_found", "run_id": "retired-run"}, scenario)
    assert seen["handled"] is True
    assert seen["running"] is False
    assert seen["released"] == 1
    assert seen["reopens"] == 0
    assert seen["loads"] == seen["refreshes"] == (0 if scenario == "steering" else 1)


@pytest.mark.parametrize("body", [{"ok": True, "running": True}, {"ok": True, "recording": True}])
def test_stream_keeps_active_and_recording_runs_locked(body):
    seen = drive_status_client(200, body)
    assert seen["running"] is True
    assert seen["reopens"] == 1
    assert seen["loads"] == seen["released"] == 0


@pytest.mark.parametrize("scenario", ["stream", "stop"])
@pytest.mark.parametrize(
    ("http", "body", "network_error"),
    [
        (404, {"ok": False, "code": "other_error"}, False),
        (500, {"ok": False, "code": "run_not_found"}, False),
        (401, {"ok": False, "code": "unauthorized"}, False),
        (200, {"ok": True}, True),
    ],
)
def test_other_status_failures_do_not_confirm_completion(scenario, http, body, network_error):
    seen = drive_status_client(http, body, scenario, network_error=network_error)
    if scenario == "stop":
        assert "error" in seen
    else:
        assert seen["handled"] is False
        assert seen["running"] is True
        assert seen["reopens"] == 1
        assert seen["released"] == seen["loads"] == 0


def test_stream_ignores_missing_run_response_after_context_switch():
    seen = drive_status_client(404, {"ok": False, "code": "run_not_found", "run_id": "retired-run"}, "stale")
    assert seen["handled"] is False
    assert seen["running"] is True
    assert seen["released"] == seen["reopens"] == 0


def test_stop_poll_rejects_missing_run_answer_for_another_run():
    seen = drive_status_client(404, {"ok": False, "code": "run_not_found", "run_id": "another-run"}, "stop")
    assert "error" in seen
    assert "stopped" not in seen
    assert seen["requests"] == 1


def test_stop_poll_accepts_pruned_run_as_stopped():
    seen = drive_status_client(404, {"ok": False, "code": "run_not_found", "run_id": "retired-run"}, "stop")
    assert seen == {"stopped": True, "requests": 1}


def test_stop_poll_still_waits_for_recording():
    seen = drive_status_client(200, {"ok": True, "running": False, "recording": True}, "stop")
    assert seen["requests"] == 3
    assert "error" in seen
