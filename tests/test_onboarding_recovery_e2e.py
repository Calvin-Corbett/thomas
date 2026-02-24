from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestOnboardingRecoveryE2E(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _emit_onboarding_event(
        self,
        *,
        event: str,
        onboarding_session_id: str,
        elapsed_ms: int,
        payload: dict | None = None,
    ) -> None:
        event_payload = {
            "onboarding_session_id": str(onboarding_session_id),
            "elapsed_ms": int(elapsed_ms),
        }
        if isinstance(payload, dict):
            event_payload.update(payload)

        resp = await self.client.post(
            "/api/onboarding/telemetry",
            json={"event": event, "payload": event_payload},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(bool(body.get("ok")))

    async def test_onboarding_repair_happy_path_passes_outcomes_gate(self):
        with tempfile.TemporaryDirectory() as runs_tmp:
            runs_db = Path(runs_tmp) / "runs.sqlite3"
            with patch.dict(os.environ, {"THOMAS_RUNS_DB_PATH": str(runs_db)}):
                bootstrap_resp = await self.client.get("/api/setup/bootstrap")
                self.assertEqual(bootstrap_resp.status, 200)
                bootstrap = await bootstrap_resp.json()
                self.assertIn("quick_start", bootstrap)

                onboarding_session_id = "happy-path"
                await self._emit_onboarding_event(
                    event="wizard.opened",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=0,
                    payload={"step": "choose_path", "path": "local"},
                )
                await self._emit_onboarding_event(
                    event="wizard.connection_tested",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=30_000,
                    payload={"verified": True, "path": "local"},
                )

                fake_output = "[thomas] Repair report: C:\\temp\\repair_report.txt\n"
                with patch("thomas.server.app.subprocess.run") as run_mock:
                    run_mock.return_value = type(
                        "Completed",
                        (),
                        {"returncode": 0, "stdout": fake_output, "stderr": ""},
                    )()
                    repair_resp = await self.client.post(
                        "/api/setup/repair",
                        json={
                            "auto_install_tools": True,
                            "skip_install": False,
                            "skip_doctor": False,
                        },
                    )
                self.assertEqual(repair_resp.status, 200)
                repair_payload = await repair_resp.json()
                self.assertTrue(bool(repair_payload.get("ok")))

                await self._emit_onboarding_event(
                    event="wizard.download_approved",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=90_000,
                    payload={"trigger": "repair"},
                )
                await self._emit_onboarding_event(
                    event="onboarding.completed",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=180_000,
                    payload={"connection_method": "local"},
                )

                outcomes_resp = await self.client.get(
                    "/api/onboarding/outcomes",
                    params={"days": "7", "db": str(runs_db)},
                )
                self.assertEqual(outcomes_resp.status, 200)
                outcomes = await outcomes_resp.json()
                summary = dict(outcomes.get("summary") or {})
                self.assertEqual(int(summary.get("wizard_opened", 0)), 1)
                self.assertEqual(int(summary.get("onboarding_completed", 0)), 1)
                self.assertAlmostEqual(float(summary.get("completion_rate", 0.0)), 1.0, places=6)
                self.assertEqual(int(summary.get("recovery_attempts", 0)), 1)
                self.assertEqual(int(summary.get("recovery_succeeded", 0)), 1)
                self.assertEqual(int(summary.get("completed_journeys_with_timing", 0)), 1)
                self.assertAlmostEqual(float(summary.get("median_time_to_ready_seconds", 0.0)), 180.0, places=3)

                gate_resp = await self.client.get(
                    "/api/onboarding/outcomes/gate",
                    params={
                        "days": "7",
                        "db": str(runs_db),
                        "min_events_for_quality_thresholds": "1",
                        "min_completion_rate": "0.9",
                        "min_recovery_success_rate": "0.8",
                        "max_median_time_to_ready_seconds": "480",
                    },
                )
                self.assertEqual(gate_resp.status, 200)
                gate_payload = await gate_resp.json()
                self.assertTrue(bool(gate_payload.get("ok")))
                self.assertFalse(list(gate_payload.get("errors") or []))
                self.assertTrue(bool((gate_payload.get("gate") or {}).get("ok")))

    async def test_onboarding_repair_failure_surfaces_gate_violations(self):
        with tempfile.TemporaryDirectory() as runs_tmp:
            runs_db = Path(runs_tmp) / "runs.sqlite3"
            with patch.dict(os.environ, {"THOMAS_RUNS_DB_PATH": str(runs_db)}):
                onboarding_session_id = "failed-repair"
                await self._emit_onboarding_event(
                    event="wizard.opened",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=0,
                    payload={"step": "choose_path", "path": "local"},
                )

                with patch("thomas.server.app.subprocess.run") as run_mock:
                    run_mock.return_value = type(
                        "Completed",
                        (),
                        {"returncode": 1, "stdout": "", "stderr": "installer blocked"},
                    )()
                    repair_resp = await self.client.post(
                        "/api/setup/repair",
                        json={
                            "auto_install_tools": True,
                            "skip_install": False,
                            "skip_doctor": False,
                        },
                    )
                self.assertEqual(repair_resp.status, 500)
                repair_payload = await repair_resp.json()
                self.assertFalse(bool(repair_payload.get("ok")))

                await self._emit_onboarding_event(
                    event="wizard.download_approval_failed",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=120_000,
                    payload={"error": "installer blocked"},
                )
                await self._emit_onboarding_event(
                    event="onboarding.completed",
                    onboarding_session_id=onboarding_session_id,
                    elapsed_ms=900_000,
                    payload={"connection_method": "local"},
                )

                gate_resp = await self.client.get(
                    "/api/onboarding/outcomes/gate",
                    params={
                        "days": "7",
                        "db": str(runs_db),
                        "min_events_for_quality_thresholds": "1",
                        "min_completion_rate": "0.5",
                        "min_recovery_success_rate": "0.8",
                        "max_median_time_to_ready_seconds": "480",
                    },
                )
                self.assertEqual(gate_resp.status, 200)
                gate_payload = await gate_resp.json()
                self.assertFalse(bool(gate_payload.get("ok")))
                errors = " | ".join(list(gate_payload.get("errors") or []))
                self.assertIn("recovery success rate below target", errors)
                self.assertIn("median time-to-ready above target", errors)


if __name__ == "__main__":
    unittest.main()

