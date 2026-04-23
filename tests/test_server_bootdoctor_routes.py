from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core import boot_doctor as boot_doctor_core
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app_core import create_app
from thomas.server.app_keys import APP_BOOT_DOCTOR_ROOT
from thomas.server.boot_recovery import write_boot_doctor_status, write_boot_recovery_notice
from thomas.tools.registry import ToolRegistry


class TestBootDoctorRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        with patch("thomas.server.app_core._build_tools", return_value=ToolRegistry()):
            app = create_app(cfg)
        app[APP_BOOT_DOCTOR_ROOT] = Path(self._tmpdir.name)
        report_path = Path(self._tmpdir.name) / "runtime" / "boot_doctor" / "boot_doctor_test.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("boot report", encoding="utf-8")
        write_boot_doctor_status(
            Path(self._tmpdir.name),
            status="degraded",
            phase="repairing",
            message="Boot Doctor is investigating.",
            reason="Missing models route",
            port=8899,
            severity="degraded",
            recovered=True,
            blocking=False,
            report_path=report_path,
            repairs=["Diagnostics only"],
            ai_summary="Core UI is up; important route failed.",
            recommended_actions=["view_report", "retry_repair", "restart"],
            probe_results=[{"id": "models", "class": "important", "ok": False, "detail": "HTTP 404 at /api/models"}],
        )
        write_boot_recovery_notice(
            Path(self._tmpdir.name),
            reason="Missing models route",
            report_path=report_path,
            repairs=["Diagnostics only"],
            recovered=True,
            severity="degraded",
            ai_summary="Core UI is up; important route failed.",
            recommended_actions=["view_report", "retry_repair", "restart"],
            probe_results=[{"id": "models", "class": "important", "ok": False, "detail": "HTTP 404 at /api/models"}],
        )
        return app

    async def test_status_returns_status_and_notice(self):
        resp = await self.client.get("/api/bootdoctor/status")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["status"]["severity"], "degraded")
        self.assertEqual(body["notice"]["severity"], "degraded")
        self.assertIn("retry_repair", body["status"]["recommended_actions"])

    async def test_report_returns_plain_text(self):
        resp = await self.client.get("/api/bootdoctor/report")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("boot report", text)

    async def test_status_reconciles_stale_fatal_state_when_runtime_is_up(self):
        report_path = Path(self._tmpdir.name) / "runtime" / "boot_doctor" / "boot_doctor_test.txt"
        write_boot_doctor_status(
            Path(self._tmpdir.name),
            status="attention",
            phase="report_complete",
            message="Boot Doctor finished, but Thomas still has a fatal startup issue.",
            reason="Old failed launch",
            port=8926,
            severity="fatal",
            recovered=False,
            blocking=True,
            report_path=report_path,
            repairs=["Known startup repair applied"],
            ai_summary="Old fatal state.",
            recommended_actions=["view_report", "retry_repair", "restart", "open_rescue"],
            probe_results=[{"id": "health", "class": "core", "ok": False, "detail": "port not listening"}],
        )
        write_boot_recovery_notice(
            Path(self._tmpdir.name),
            reason="Old failed launch",
            report_path=report_path,
            repairs=["Known startup repair applied"],
            recovered=False,
            severity="fatal",
            blocking=True,
            ai_summary="Old fatal state.",
            recommended_actions=["view_report", "retry_repair", "restart", "open_rescue"],
            probe_results=[{"id": "health", "class": "core", "ok": False, "detail": "port not listening"}],
        )

        with patch.object(
            boot_doctor_core,
            "probe_boot_runtime",
            return_value={
                "ready": True,
                "severity": "degraded",
                "listening": True,
                "probe_results": [
                    {"id": "root", "class": "core", "path": "/", "ok": True, "status": 200, "detail": "HTTP 200 at /"},
                    {
                        "id": "health",
                        "class": "core",
                        "path": "/api/health",
                        "ok": True,
                        "status": 200,
                        "detail": "HTTP 200 at /api/health",
                    },
                    {
                        "id": "models",
                        "class": "important",
                        "path": "/api/models",
                        "ok": False,
                        "status": 404,
                        "detail": "HTTP 404 at /api/models",
                    },
                ],
            },
        ):
            resp = await self.client.get("/api/bootdoctor/status")

        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["status"]["severity"], "degraded")
        self.assertTrue(body["status"]["recovered"])
        self.assertFalse(body["status"]["blocking"])
        self.assertEqual(body["status"]["phase"], "runtime_reconciled")
        self.assertEqual(body["notice"]["severity"], "degraded")
        self.assertTrue(body["notice"]["recovered"])
        self.assertFalse(body["notice"]["blocking"])


if __name__ == "__main__":
    unittest.main()
