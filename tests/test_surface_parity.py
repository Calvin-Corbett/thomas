from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import scripts.check_surface_parity as mod


def test_extract_call_source_stops_at_matching_paren() -> None:
    text = 'await send({"type": "route"})\nobj = {"type": "noise"}\n'
    call = mod._extract_call_source(text, text.index("send"))
    assert '"type": "route"' in call
    assert '"type": "noise"' not in call


def test_extract_call_source_ignores_parentheses_inside_strings() -> None:
    text = (
        'await send({"type": "text", "text": "line with ) paren and \\"quote\\" inside"})\n' 'obj = {"type": "noise"}\n'
    )
    call = mod._extract_call_source(text, text.index("send"))
    assert '"type": "text"' in call
    assert '"type": "noise"' not in call


def test_extract_server_wire_events_from_stream_contexts_only() -> None:
    server_text = """
await send({"type": "route", "route": "planner"})
await resp.write(json.dumps({"type": "text", "text": "hello"}).encode("utf-8") + b"\\n")
payload = {"type": "ignored_without_context"}
await _record_swarm_event({"type": "done", "ok": true})
"""
    events = mod._extract_server_wire_events(server_text)
    assert {"route", "text", "done"}.issubset(events)
    assert "ignored_without_context" not in events


def test_extract_server_wire_events_handles_multiline_payloads() -> None:
    server_text = """
await send(
    {
        "type": "guardrails",
        "event": "approval_needed",
        "payload": {"tool": "shell"},
    }
)
"""
    events = mod._extract_server_wire_events(server_text)
    assert "guardrails" in events


def test_extract_server_wire_events_does_not_leak_across_calls() -> None:
    server_text = """
await send({"type": "route"})
x = {"type": "noise"}
await send({"type": "done"})
"""
    events = mod._extract_server_wire_events(server_text)
    assert "route" in events
    assert "done" in events
    assert "noise" not in events


def test_extract_web_wire_handlers_supports_event_and_evt_aliases() -> None:
    web_text = """
if (event.type === "route") {}
else if (evt.type == 'done') {}
"""
    assert mod._extract_web_wire_handlers(web_text) == {"route", "done"}


def test_read_server_sources_skips_missing_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    missing = tmp_path / "missing.py"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (missing, first, second))

    assert mod._read_server_sources() == "alpha\nbeta"


def test_read_server_sources_raises_when_none_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (missing,))

    with pytest.raises(FileNotFoundError):
        _ = mod._read_server_sources()


def test_read_web_sources_uses_chat_app_and_sorted_parts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    parts_dir = web_dir / "app_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    chat = web_dir / "chat.js"
    app = web_dir / "app.js"
    part_b = parts_dir / "part-010.js"
    part_a = parts_dir / "part-002.js"
    chat.write_text("chat-source", encoding="utf-8")
    app.write_text("app-source", encoding="utf-8")
    part_b.write_text("part-b", encoding="utf-8")
    part_a.write_text("part-a", encoding="utf-8")

    monkeypatch.setattr(mod, "WEB_CHAT", chat)
    monkeypatch.setattr(mod, "WEB_APP", app)
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", parts_dir)

    assert mod._read_web_sources() == "chat-source\napp-source\npart-a\npart-b"


def test_read_web_sources_raises_when_none_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.js"
    missing_dir = tmp_path / "missing_parts"
    monkeypatch.setattr(mod, "WEB_CHAT", missing_file)
    monkeypatch.setattr(mod, "WEB_APP", missing_file)
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", missing_dir)

    with pytest.raises(FileNotFoundError):
        _ = mod._read_web_sources()


def test_required_wire_events_are_present_in_real_sources() -> None:
    server_text = mod._read_server_sources()
    web_text = mod._read_web_sources()

    server_events = mod._extract_server_wire_events(server_text)
    web_events = mod._extract_web_wire_handlers(web_text)

    assert mod.REQUIRED_WIRE_EVENTS.issubset(server_events)
    assert mod.REQUIRED_WIRE_EVENTS.issubset(web_events)
    assert server_events.issubset(web_events)


def test_required_cli_events_are_present_in_real_cli_source() -> None:
    cli_text = mod._read(mod.CLI_MAIN)
    cli_events = mod._extract_cli_event_handlers(cli_text)
    assert mod.REQUIRED_CLI_EVENTS.issubset(cli_events)


def test_extract_cli_event_handlers_from_run_chat_block() -> None:
    cli_text = """
async def _run_chat():
    if event.type == EventType.AGENT_START:
        pass
    elif evt.type == EventType.AGENT_DONE:
        pass
@click.group
def cli():
    pass
"""
    handlers = mod._extract_cli_event_handlers(cli_text)
    assert handlers == {"AGENT_START", "AGENT_DONE"}


def test_extract_cli_event_handlers_falls_back_to_full_source() -> None:
    cli_text = """
def helper():
    if event.type == EventType.TEXT_DELTA:
        pass
"""
    handlers = mod._extract_cli_event_handlers(cli_text)
    assert handlers == {"TEXT_DELTA"}


def test_run_passes_with_minimal_valid_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server = tmp_path / "server.py"
    web = tmp_path / "web.js"
    cli = tmp_path / "cli.py"

    server.write_text(
        "\n".join(f'await send({{"type": "{evt}"}})' for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    web.write_text(
        "\n".join(f"if (evt.type === '{evt}') {{}}" for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    cli.write_text(
        "async def _run_chat():\n"
        + "\n".join(f"    if event.type == EventType.{evt}:\n        pass" for evt in sorted(mod.REQUIRED_CLI_EVENTS))
        + "\n@click.group\ndef cli():\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (server,))
    monkeypatch.setattr(mod, "WEB_CHAT", web)
    monkeypatch.setattr(mod, "WEB_APP", tmp_path / "missing_app.js")
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", tmp_path / "missing_parts")
    monkeypatch.setattr(mod, "CLI_MAIN", cli)
    monkeypatch.setattr(sys, "argv", ["check_surface_parity.py"])

    assert mod.run() == 0


def test_run_fails_when_web_missing_required_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server = tmp_path / "server.py"
    web = tmp_path / "web.js"
    cli = tmp_path / "cli.py"

    server.write_text(
        "\n".join(f'await send({{"type": "{evt}"}})' for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    web_events = sorted(mod.REQUIRED_WIRE_EVENTS - {"guardrails"})
    web.write_text(
        "\n".join(f"if (event.type === '{evt}') {{}}" for evt in web_events),
        encoding="utf-8",
    )
    cli.write_text(
        "async def _run_chat():\n"
        + "\n".join(f"    if event.type == EventType.{evt}:\n        pass" for evt in sorted(mod.REQUIRED_CLI_EVENTS))
        + "\n@click.group\ndef cli():\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (server,))
    monkeypatch.setattr(mod, "WEB_CHAT", web)
    monkeypatch.setattr(mod, "WEB_APP", tmp_path / "missing_app.js")
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", tmp_path / "missing_parts")
    monkeypatch.setattr(mod, "CLI_MAIN", cli)
    monkeypatch.setattr(sys, "argv", ["check_surface_parity.py"])

    assert mod.run() == 1


def test_run_json_pass_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = tmp_path / "server.py"
    web = tmp_path / "web.js"
    cli = tmp_path / "cli.py"

    server.write_text(
        "\n".join(f'await send({{"type": "{evt}"}})' for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    web.write_text(
        "\n".join(f"if (evt.type === '{evt}') {{}}" for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    cli.write_text(
        "async def _run_chat():\n"
        + "\n".join(f"    if event.type == EventType.{evt}:\n        pass" for evt in sorted(mod.REQUIRED_CLI_EVENTS))
        + "\n@click.group\ndef cli():\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (server,))
    monkeypatch.setattr(mod, "WEB_CHAT", web)
    monkeypatch.setattr(mod, "WEB_APP", tmp_path / "missing_app.js")
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", tmp_path / "missing_parts")
    monkeypatch.setattr(mod, "CLI_MAIN", cli)
    monkeypatch.setattr(sys, "argv", ["check_surface_parity.py", "--json"])

    rc = mod.run()
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "surface_parity"
    assert payload["missing_server_required"] == []
    assert payload["missing_web_required"] == []
    assert payload["missing_cli_required"] == []
    assert payload["server_not_handled_by_web"] == []


def test_run_json_fail_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = tmp_path / "server.py"
    web = tmp_path / "web.js"
    cli = tmp_path / "cli.py"

    server.write_text(
        "\n".join(f'await send({{"type": "{evt}"}})' for evt in sorted(mod.REQUIRED_WIRE_EVENTS)),
        encoding="utf-8",
    )
    web.write_text(
        "\n".join(f"if (evt.type === '{evt}') {{}}" for evt in sorted(mod.REQUIRED_WIRE_EVENTS - {"guardrails"})),
        encoding="utf-8",
    )
    cli.write_text(
        "async def _run_chat():\n"
        + "\n".join(f"    if event.type == EventType.{evt}:\n        pass" for evt in sorted(mod.REQUIRED_CLI_EVENTS))
        + "\n@click.group\ndef cli():\n    pass\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "SERVER_EVENT_SOURCES", (server,))
    monkeypatch.setattr(mod, "WEB_CHAT", web)
    monkeypatch.setattr(mod, "WEB_APP", tmp_path / "missing_app.js")
    monkeypatch.setattr(mod, "WEB_APP_PARTS_DIR", tmp_path / "missing_parts")
    monkeypatch.setattr(mod, "CLI_MAIN", cli)
    monkeypatch.setattr(sys, "argv", ["check_surface_parity.py", "--json"])

    rc = mod.run()
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "surface_parity"
    assert "guardrails" in payload["missing_web_required"]
