"""Child identity survives transcript framing, live ingestion, and saved replay."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil.forge_code_http_stream import IncrementalLineDecoder, line_to_sse_payload
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_SESSION
from thomas.server.routes.evolve_agent_watch_routes import build_evolve_agent_watch_handlers

METADATA = ("agent_id", "agent_title", "agent_mode", "model", "team_id")


def child_event(agent_id="child-a", **overrides):
    return {
        "fc": "say",
        "text": "[Reviewer] Reading ",
        "delta": True,
        "agent_id": agent_id,
        "agent_title": "Reviewer",
        "agent_mode": "read_only",
        "model": "gpt-5.6-luna",
        "team_id": "team-orange",
        **overrides,
    }


@pytest.mark.parametrize("kind", ["say", "tool", "tool_result", "meta"])
def test_child_metadata_and_existing_flags_survive_fragmented_transcript(kind):
    event = child_event(fc=kind, text="[Reviewer] read café", name="Reviewer > fs.read_file", is_error=True)
    raw = (json.dumps(event, ensure_ascii=False) + "\n").encode()
    decoder = IncrementalLineDecoder()
    lines = []
    for byte in raw:
        lines.extend(decoder.feed(bytes([byte])))
    lines.extend(decoder.flush())
    assert len(lines) == 1
    payload = line_to_sse_payload(lines[0])
    assert payload == {"type": "output", "kind": kind, **{key: value for key, value in event.items() if key != "fc"}}


@pytest.mark.parametrize("invalid", [None, False, 7, 1.25, [], {}, "", " \t"])
def test_child_metadata_rejects_invalid_values_without_forwarding_extra_fields(invalid):
    event = child_event(**dict.fromkeys(METADATA, invalid), secret={"token": "never-forward"}, count=42)
    payload = line_to_sse_payload(json.dumps(event))
    assert payload == {"type": "output", "kind": "say", "text": event["text"], "delta": True}


def test_lead_and_plain_output_remain_compatible():
    from thomas.server.routes.evolve_agent_routes import _line_to_sse_payload

    assert _line_to_sse_payload is line_to_sse_payload
    assert line_to_sse_payload('{"fc":"say","text":"Lead answer","delta":true}') == {
        "type": "output",
        "kind": "say",
        "text": "Lead answer",
        "delta": True,
    }
    assert line_to_sse_payload("plain progress") == {"type": "output", "text": "plain progress"}


@pytest.mark.asyncio
async def test_http_child_frames_keep_identity_in_real_live_and_restore_factories(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to verify the actual Build factories")
    events = [
        child_event(),
        child_event(text="source."),
        child_event("child-b"),
        child_event("child-b", text="source."),
        {"fc": "say", "text": "Lead ", "delta": True},
        {"fc": "say", "text": "answer", "delta": True},
        child_event("child-a", team_id="team-next", text="New team"),
        child_event("child-a", team_id="team-next", model="another-model", text="New model"),
        child_event("child-a", team_id="team-next", model="another-model", agent_mode="builder", text="New mode"),
        child_event("child-a", fc="meta", text="Finished", delta=False),
        child_event("child-b", fc="meta", text="Finished", delta=False),
        {"fc": "meta", "text": "Team ready", "team_id": "team-orange", "model": "gpt-5.6-luna"},
        {"fc": "meta", "text": "Malformed metadata", **dict.fromkeys(METADATA, {"bad": True}), "secret": "omit"},
    ]
    transcript = "\n".join(json.dumps(event) for event in events)
    transcript_path = tmp_path / "transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")
    app = web.Application()
    app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "offline-build", "transcript": str(transcript_path)}
    handlers = build_evolve_agent_watch_handlers(
        app, require_api_access=lambda _: None, catalog_root=lambda: tmp_path, running=lambda: False
    )
    app.router.add_get("/stream", handlers["stream"])
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/stream")
        assert response.status == 200 and response.content_type == "text/event-stream"
        frames = [json.loads(line[6:]) for line in (await response.text()).splitlines() if line.startswith("data: ")]
        response = await client.get("/stream?cursor=3")
        resumed = [json.loads(line[6:]) for line in (await response.text()).splitlines() if line.startswith("data: ")]
    assert frames[-1]["type"] == "done"
    assert frames[0]["agent_id"] == "child-a" and frames[2]["agent_id"] == "child-b"
    assert [frame["event_seq"] for frame in frames] == list(range(1, len(frames) + 1))
    assert resumed == frames[3:]
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(repo / "tests/web_node/code_child_stream_metadata.mjs"), str(repo)],
        input=json.dumps({"frames": frames, "transcript": transcript}),
        capture_output=True,
        text=True,
        timeout=20,
        cwd=repo,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["live_and_restore_identity"] is True
