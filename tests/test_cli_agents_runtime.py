from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import thomas.cli.agents_runtime as mod


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(root_path=tmp_path),
        server=SimpleNamespace(api_token=""),
    )


def test_start_payload_detached_records_gateway_state(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    monkeypatch.setattr(mod, "_resolve_bind_port", lambda host, port, auto_port: int(port))
    monkeypatch.setattr(mod, "_is_pid_running", lambda pid: int(pid) == 4242)
    call_state = {"count": 0}

    def _fake_probe_gateway(host: str, port: int, token: str = "") -> dict[str, object]:
        call_state["count"] += 1
        if call_state["count"] == 1:
            return {"healthy": False, "engines": {"ok": False, "payload": {}}}
        return {
            "healthy": True,
            "engines": {
                "ok": True,
                "payload": {"running": True, "engines": {"workspace_sync_engine": {"running": True}}},
            },
        }

    monkeypatch.setattr(mod, "_probe_gateway", _fake_probe_gateway)
    monkeypatch.setattr(mod, "_gateway_spawn", lambda **_kwargs: SimpleNamespace(pid=4242))
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    payload = mod.start_payload(
        cfg,
        config_path="",
        detach=True,
        host="127.0.0.1",
        port=8899,
        auto_port=False,
    )
    assert payload["ok"] is True
    assert payload["mode"] == "gateway_detached"
    assert payload["pid"] == 4242

    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    assert state_path.exists()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert int(saved["pid"]) == 4242


def test_status_payload_prefers_detached_runtime_when_gateway_running(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8899, "log_file": str(tmp_path / "gateway.log")}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "_is_pid_running", lambda pid: int(pid) == 4242)
    monkeypatch.setattr(
        mod,
        "_probe_gateway",
        lambda host, port, token="": {
            "healthy": True,
            "engines": {
                "ok": True,
                "payload": {"running": True, "engines": {"workspace_sync_engine": {"running": True}}},
            },
        },
    )

    payload = mod.status_payload(cfg)
    assert payload["running"] is True
    assert payload["source"] == "gateway_detached"
    assert "workspace_sync_engine" in payload["engines"]


def test_start_payload_detects_external_untracked_runtime(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    monkeypatch.setattr(
        mod,
        "_probe_gateway",
        lambda host, port, token="": {
            "healthy": True,
            "engines": {"ok": True, "payload": {"running": True, "engines": {}}},
        },
    )

    payload = mod.start_payload(
        cfg,
        config_path="",
        detach=True,
        host="127.0.0.1",
        port=8899,
        auto_port=True,
    )
    assert payload["ok"] is True
    assert payload["already_running"] is True
    assert payload["external_runtime"] is True
    assert payload["pid"] == 0


def test_stop_payload_detached_kills_pid_and_clears_state(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    state_path = tmp_path / ".thomas" / "cli" / "gateway_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8899}), encoding="utf-8")

    state = {"running": True}

    def _fake_is_pid_running(pid: int) -> bool:
        return bool(int(pid) == 4242 and state["running"])

    def _fake_kill_pid(pid: int) -> bool:
        if int(pid) == 4242:
            state["running"] = False
            return True
        return False

    monkeypatch.setattr(mod, "_is_pid_running", _fake_is_pid_running)
    monkeypatch.setattr(mod, "_kill_pid", _fake_kill_pid)

    payload = mod.stop_payload(cfg, detach=True)
    assert payload["ok"] is True
    assert payload["mode"] == "gateway_detached"
    assert payload["pid"] == 4242
    assert payload["killed"] is True
    assert not state_path.exists()


def test_stop_payload_reports_external_untracked_runtime(tmp_path: Path, monkeypatch) -> None:
    cfg = _fake_config(tmp_path)
    monkeypatch.setattr(
        mod,
        "_probe_gateway",
        lambda host, port, token="": {"healthy": True, "engines": {"ok": True, "payload": {}}},
    )

    payload = mod.stop_payload(cfg, detach=True)
    assert payload["ok"] is False
    assert payload["mode"] == "gateway_detached"
    assert "external/untracked" in str(payload["error"])
