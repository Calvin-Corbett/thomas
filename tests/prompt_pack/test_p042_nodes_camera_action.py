import json

import pytest
from typer.testing import CliRunner

from thomas.nodes.p042_nodes_camera_action import (
    HttpResponse,
    NodesCameraActionError,
    NodesCameraActionErrorCode,
    NodesCameraActionRequest,
    execute_nodes_camera_action,
    parse_nodes_camera_action_request,
)
from thomas.cli.commands.nodes import p042_nodes_camera_action as cli_mod
import thomas.nodes.p042_nodes_camera_action as nodes_mod


def test_parse_rejects_missing_node_id():
    with pytest.raises(NodesCameraActionError) as exc:
        parse_nodes_camera_action_request({"action": "capture"})
    assert exc.value.code == NodesCameraActionErrorCode.INVALID_INPUT


def test_parse_rejects_unknown_action():
    with pytest.raises(NodesCameraActionError) as exc:
        parse_nodes_camera_action_request({"node_id": "node-1", "action": "explode"})
    assert exc.value.code == NodesCameraActionErrorCode.INVALID_INPUT


def test_parse_accepts_alias_action():
    req = parse_nodes_camera_action_request({"node_id": "node-1", "action": "photo"})
    assert req.action == "capture"


def test_execute_success_capture():
    def fake_post(url, payload, headers=None, timeout_s=None):  # type: ignore[unused-argument]
        assert url == "http://nodes.local/nodes/node-1/camera/action"
        assert payload["action"] == "capture"
        assert payload["camera"] == 0
        return HttpResponse(
            status=200,
            headers={},
            text=json.dumps({"artifact_url": "http://cdn.local/photo.jpg", "echo": payload}),
            json_data={"artifact_url": "http://cdn.local/photo.jpg", "echo": payload},
        )

    req = NodesCameraActionRequest(node_id="node-1", action="capture", camera=0, options={"format": "jpeg"}, timeout_s=5.0)
    resp = execute_nodes_camera_action(req, base_url="http://nodes.local", http_post=fake_post)
    assert resp.ok is True
    assert resp.node_id == "node-1"
    assert resp.action == "capture"
    assert resp.camera == 0
    assert resp.artifact == "http://cdn.local/photo.jpg"
    assert resp.payload["echo"]["options"]["format"] == "jpeg"


def test_execute_remote_error_status_is_deterministic():
    def fake_post(url, payload, headers=None, timeout_s=None):  # type: ignore[unused-argument]
        return HttpResponse(status=500, headers={}, text="boom", json_data=None)

    req = NodesCameraActionRequest(node_id="node-1", action="capture")
    with pytest.raises(NodesCameraActionError) as exc:
        execute_nodes_camera_action(req, base_url="http://nodes.local", http_post=fake_post)
    assert exc.value.code == NodesCameraActionErrorCode.REMOTE_ERROR
    assert exc.value.details["status"] == 500


def test_execute_remote_ok_false_is_deterministic():
    def fake_post(url, payload, headers=None, timeout_s=None):  # type: ignore[unused-argument]
        return HttpResponse(
            status=200,
            headers={},
            text=json.dumps({"ok": False, "error": {"code": "NO_CAMERA"}}),
            json_data={"ok": False, "error": {"code": "NO_CAMERA"}},
        )

    req = NodesCameraActionRequest(node_id="node-1", action="capture")
    with pytest.raises(NodesCameraActionError) as exc:
        execute_nodes_camera_action(req, base_url="http://nodes.local", http_post=fake_post)
    assert exc.value.code == NodesCameraActionErrorCode.REMOTE_ERROR
    assert "remote_error" in exc.value.details


def test_execute_missing_config_is_deterministic(monkeypatch):
    # Clear env vars so config resolution fails deterministically.
    for key in (
        "THOMAS_NODES_URL",
        "THOMAS_NODES_BASE_URL",
        "THOMAS_NODE_SERVICE_URL",
        "NODES_URL",
        "NODES_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    req = NodesCameraActionRequest(node_id="node-1", action="capture")
    with pytest.raises(NodesCameraActionError) as exc:
        execute_nodes_camera_action(req, base_url=None, http_post=lambda *_a, **_k: None)  # type: ignore[arg-type]
    assert exc.value.code == NodesCameraActionErrorCode.MISSING_CONFIG


def test_cli_json_success(monkeypatch):
    def fake_post(url, payload, headers=None, timeout_s=None):  # type: ignore[unused-argument]
        return HttpResponse(
            status=200,
            headers={},
            text=json.dumps({"artifact_url": "http://cdn.local/photo.jpg"}),
            json_data={"artifact_url": "http://cdn.local/photo.jpg"},
        )

    monkeypatch.setattr(nodes_mod, "_http_post_json", fake_post)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.app,
        ["camera-action", "node-1", "capture", "--nodes-url", "http://nodes.local", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["node_id"] == "node-1"
    assert payload["data"]["artifact"] == "http://cdn.local/photo.jpg"


def test_cli_json_failure_missing_config(monkeypatch):
    for key in (
        "THOMAS_NODES_URL",
        "THOMAS_NODES_BASE_URL",
        "THOMAS_NODE_SERVICE_URL",
        "NODES_URL",
        "NODES_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["camera-action", "node-1", "capture", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == NodesCameraActionErrorCode.MISSING_CONFIG.value
