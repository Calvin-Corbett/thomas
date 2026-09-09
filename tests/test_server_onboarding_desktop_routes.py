from __future__ import annotations

import tempfile
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class _StubHostService:
    def __init__(self) -> None:
        self.payload = {
            "enabled": False,
            "installation_state": "not_enabled",
            "session_target": "local_vm",
            "trust_mode": "ask_every_time",
            "reboot_required": False,
            "relogin_required": False,
            "next_action": "Enable isolated desktop mode in Thomas settings.",
            "viewer": {
                "available": False,
                "mode": "none",
                "label": "",
                "url": "",
                "command": "",
                "takeover_supported": False,
            },
        }

    class _Obj:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    def status(self):
        return self._Obj(self.payload)

    def request_opt_in(self, *, hidden_by_default: bool = True):
        self.payload.update(
            {
                "enabled": True,
                "installation_state": "host_service_not_installed",
                "next_action": "Request one Windows admin consent to install the isolated desktop host capability.",
            }
        )
        return self._Obj(self.payload)

    def install_host_capability(self, *, stage_only: bool = True):
        self.payload.update(
            {
                "enabled": True,
                "installation_state": "host_service_not_installed",
                "next_action": "Request one Windows admin consent to install the isolated desktop host capability.",
            }
        )
        return self._Obj(self.payload)

    def disable(self):
        self.payload.update({"enabled": False, "installation_state": "not_enabled"})
        return self._Obj(self.payload)

    def set_remote_trust_mode(self, trust_mode: str):
        self.payload["trust_mode"] = trust_mode
        return self._Obj(self.payload)

    def configure_local_vm_source(
        self, *, source_type: str, vm_name: str = "", template_vhdx: str = "", switch_name: str = ""
    ):
        self.payload["local_vm"] = {
            "source_type": source_type,
            "vm_name": vm_name or "ThomasDesktopVm",
            "template_vhdx": template_vhdx,
            "switch_name": switch_name,
            "configured": bool(vm_name or template_vhdx),
        }
        self.payload["next_action"] = "Validate the configured worker VM and bootstrap the guest helper."
        return self._Obj(self.payload)

    def launch_host_service_install(self):
        self.payload.update(
            {
                "enabled": True,
                "installation_state": "host_service_installing",
                "next_action": "Approve the Windows admin prompt to install isolated desktop mode.",
            }
        )
        return {"ok": True, "launched": True, "posture": dict(self.payload)}

    def launch_viewer(self):
        self.payload["viewer"] = {
            "available": True,
            "mode": "hyperv_console",
            "label": "Hyper-V Console",
            "url": "",
            "command": 'vmconnect.exe localhost "ThomasDesktopVm"',
            "takeover_supported": True,
        }
        return {"ok": True, "launched": True, "viewer": dict(self.payload["viewer"])}


class TestOnboardingDesktopRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._stub_service = _StubHostService()
        self._patcher = patch(
            "thomas.server.routes.onboarding_aiohttp.get_global_desktop_host_service",
            lambda: self._stub_service,
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={
                "local": ModelConfig(
                    name="local",
                    model="llama3",
                    provider="ollama",
                    base_url="http://127.0.0.1:11434/v1",
                )
            },
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_onboarding_desktop_status_route(self):
        resp = await self.client.get("/api/onboarding/desktop/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertIn("isolated_desktop", body)
        self.assertIn("installation_state", body["isolated_desktop"])

    async def test_onboarding_desktop_opt_in_route_updates_preferences(self):
        resp = await self.client.post("/api/onboarding/desktop/opt-in", json={"enabled": True})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["isolated_desktop"]["installation_state"], "host_service_not_installed")

        prefs_resp = await self.client.get("/api/preferences")
        prefs = await prefs_resp.json()
        runtime = (prefs.get("advanced") or {}).get("runtime") or {}
        self.assertTrue(bool(runtime.get("isolated_desktop_enabled")))

    async def test_onboarding_desktop_trust_route_updates_preferences(self):
        resp = await self.client.post("/api/onboarding/desktop/trust", json={"trust_mode": "remembered"})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["isolated_desktop"]["trust_mode"], "remembered")

    async def test_onboarding_desktop_vm_source_route_updates_state(self):
        resp = await self.client.post(
            "/api/onboarding/desktop/vm-source",
            json={
                "source_type": "template_disk",
                "vm_name": "ThomasDesktopVm",
                "template_vhdx": r"C:\VMs\ThomasDesktopTemplate.vhdx",
            },
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        local_vm = body["isolated_desktop"]["local_vm"]
        self.assertEqual(local_vm["source_type"], "template_disk")
        self.assertEqual(local_vm["vm_name"], "ThomasDesktopVm")
        self.assertEqual(local_vm["template_vhdx"], r"C:\VMs\ThomasDesktopTemplate.vhdx")

    async def test_onboarding_desktop_install_route_launches_prompt(self):
        resp = await self.client.post("/api/onboarding/desktop/install", json={"enabled": True})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(bool(body.get("install_launch", {}).get("launched")))
        self.assertEqual(body["isolated_desktop"]["installation_state"], "host_service_installing")

    async def test_onboarding_desktop_open_viewer_route_launches_viewer(self):
        self._stub_service.payload["enabled"] = True
        self._stub_service.payload["installation_state"] = "local_vm_ready"
        self._stub_service.payload["viewer"] = {
            "available": True,
            "mode": "hyperv_console",
            "label": "Hyper-V Console",
            "url": "",
            "command": 'vmconnect.exe localhost "ThomasDesktopVm"',
            "takeover_supported": True,
        }
        resp = await self.client.post("/api/onboarding/desktop/open-viewer")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(bool(body.get("viewer_launch", {}).get("launched")))
