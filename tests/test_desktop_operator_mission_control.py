from __future__ import annotations

import json

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.server.routes.mission_control_routes import build_mission_control_routes


class _StubManager:
    def status_snapshot(self) -> dict:
        return {
            "service_id": "desktop.operator",
            "running": True,
            "vm": {"vm_id": "vm-magic-01", "isolated": True},
            "viewer": {
                "available": True,
                "mode": "hyperv_console",
                "label": "Hyper-V console",
                "url": "",
                "command": 'vmconnect.exe localhost "ThomasWorker"',
                "takeover_supported": True,
            },
            "host_posture": {
                "installation_state": "local_vm_ready",
                "session_target": "local_vm",
                "trust_mode": "ask_every_time",
                "next_action": "Start an isolated desktop session.",
                "viewer": {
                    "available": True,
                    "mode": "hyperv_console",
                    "label": "Hyper-V console",
                    "url": "",
                    "command": 'vmconnect.exe localhost "ThomasWorker"',
                    "takeover_supported": True,
                },
            },
            "quality_bar": {"criteria": ["verification_quality"]},
            "workflow_profiles": [{"workflow_profile": "browser-session", "adapter_name": "browser"}],
            "active_session": {
                "session": {
                    "session_id": "desktop-session-123",
                    "workflow_profile": "browser-session",
                    "adapter_name": "browser",
                    "verification_status": "passed",
                    "step_count": 4,
                    "session_state": "paused_for_approval",
                    "risk_level": "high",
                    "magic_ready": False,
                    "pending_approval_reason": "domain_not_allowlisted",
                },
                "window": {"handle": 303, "title": "Example - Google Chrome", "monitor_id": "DISPLAY2"},
            },
        }


def test_mission_control_payload_includes_desktop_operator(monkeypatch) -> None:
    monkeypatch.setattr(
        "thomas.desktop_operator.manager.get_global_desktop_operator_manager",
        lambda: _StubManager(),
    )

    app = web.Application()
    run_store_enabled_key = web.AppKey("run_store_enabled_test", bool)
    run_store_module_key = web.AppKey("run_store_module_test", object)
    app[run_store_enabled_key] = False
    app[run_store_module_key] = None

    api_mission_control, _stream, _approvals = build_mission_control_routes(
        app,
        require_api_access=lambda _request: None,
        run_store_enabled_key=run_store_enabled_key,
        run_store_module_key=run_store_module_key,
    )

    request = make_mocked_request("GET", "/api/mission/control", app=app)
    response = __import__("asyncio").run(api_mission_control(request))
    payload = json.loads(response.text)

    assert payload["desktop_operator"]["service_id"] == "desktop.operator"
    assert payload["desktop_operator"]["vm"]["vm_id"] == "vm-magic-01"
    desktop_agents = [agent for agent in payload["agents"] if agent.get("id") == "desktop:operator"]
    assert desktop_agents
    assert desktop_agents[0]["module_id"] == "desktop.operator"
    assert desktop_agents[0]["workflow_profile"] == "browser-session"
    assert desktop_agents[0]["vm_id"] == "vm-magic-01"
    assert desktop_agents[0]["session_state"] == "paused_for_approval"
    assert desktop_agents[0]["risk_level"] == "high"
    assert desktop_agents[0]["magic_ready"] is False
    assert desktop_agents[0]["viewer_available"] is True
    assert desktop_agents[0]["viewer_mode"] == "hyperv_console"
    assert "vmconnect.exe" in desktop_agents[0]["viewer_command"]
    assert desktop_agents[0]["installation_state"] == "local_vm_ready"
    assert desktop_agents[0]["trust_mode"] == "ask_every_time"
