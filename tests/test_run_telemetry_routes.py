"""Tests for the CAP-137 live run telemetry HTTP surface.

Acceptance line under test:

    "Show always-visible live turns, tokens, rate, and completion projection."

Everything here is hermetic: no network, no wall clock. The route layer's
process-wide :class:`RunProjection` is replaced per test with a fresh instance
driven by an injected ``FakeClock``, and every event carries an explicit
timestamp, so all four rendered values are exactly predictable.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.observability.run_projection import RunTarget
from thomas.server.routes.run_telemetry_routes import (
    get_run_projection,
    register_run_telemetry_routes,
    reset_run_projection,
)

SNAPSHOT_URL = "/api/run-telemetry/snapshot"
EVENTS_URL = "/api/run-telemetry/events"
TARGET_URL = "/api/run-telemetry/target"
RESET_URL = "/api/run-telemetry/reset"

PANEL_PATH = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "run_telemetry_panel.js"


class FakeClock:
    """A controllable monotonic clock; ``now`` is advanced explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def set(self, value: float) -> None:
        self.value = float(value)


def _local_config() -> SimpleNamespace:
    return SimpleNamespace(server=SimpleNamespace(access_mode="local", api_token=""))


class RunTelemetryRoutesTestCase(AioHTTPTestCase):
    """Base: fresh projection + injected clock for every test."""

    config = _local_config()

    def setUp(self) -> None:
        self.clock = FakeClock()
        reset_run_projection(window_seconds=60.0, clock=self.clock, target=RunTarget())
        super().setUp()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            reset_run_projection()

    async def get_application(self) -> web.Application:
        app = web.Application()
        register_run_telemetry_routes(app, self.config)
        return app

    async def _snapshot(self) -> dict:
        resp = await self.client.get(SNAPSHOT_URL)
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        return body["snapshot"]

    async def _ingest(self, **payload) -> dict:
        resp = await self.client.post(EVENTS_URL, json=payload)
        self.assertEqual(resp.status, 201, await resp.text())
        body = await resp.json()
        return body["snapshot"]

    async def _seed_run(self) -> None:
        """Two finished turns and 200 tokens, on a deterministic timeline."""
        await self._ingest(kind="turn_started", timestamp=0.0)
        await self._ingest(kind="tokens", tokens=100, timestamp=10.0)
        await self._ingest(kind="turn_finished", timestamp=20.0)
        await self._ingest(kind="turn_started", timestamp=20.0)
        await self._ingest(kind="tokens", tokens=100, timestamp=30.0)
        await self._ingest(kind="turn_finished", timestamp=40.0)
        self.clock.set(40.0)


class TestLiveValues(RunTelemetryRoutesTestCase):
    """The four acceptance values are always present and always renderable."""

    async def test_empty_run_exposes_all_four_values(self) -> None:
        snap = await self._snapshot()
        for key in (
            "cumulative_turns",
            "cumulative_tokens",
            "tokens_per_min",
            "turns_per_min",
            "remaining_turns",
            "remaining_tokens",
            "eta_seconds",
            "projection_known",
        ):
            self.assertIn(key, snap)
        self.assertEqual(snap["cumulative_turns"], 0)
        self.assertEqual(snap["cumulative_tokens"], 0)
        self.assertIsNone(snap["tokens_per_min"])
        self.assertIsNone(snap["turns_per_min"])
        self.assertFalse(snap["rate_known"])

    async def test_turns_tokens_and_rate_update_as_events_are_ingested(self) -> None:
        await self._seed_run()
        snap = await self._snapshot()

        # turns + tokens
        self.assertEqual(snap["cumulative_turns"], 2)
        self.assertEqual(snap["cumulative_tokens"], 200)
        self.assertEqual(snap["turns_in_progress"], 0)

        # rate: 200 tokens over the 30s from the oldest in-window token event
        self.assertAlmostEqual(snap["tokens_per_min"], 400.0, places=6)
        # rate: 2 finished turns over the 20s from the oldest in-window turn
        self.assertAlmostEqual(snap["turns_per_min"], 6.0, places=6)
        self.assertTrue(snap["rate_known"])

    async def test_snapshot_reflects_each_ingest_in_place(self) -> None:
        first = await self._ingest(kind="tokens", tokens=25, timestamp=1.0)
        self.assertEqual(first["cumulative_tokens"], 25)

        second = await self._ingest(kind="tokens", tokens=75, timestamp=2.0)
        self.assertEqual(second["cumulative_tokens"], 100)

        self.clock.set(2.0)
        polled = await self._snapshot()
        self.assertEqual(polled["cumulative_tokens"], 100)

    async def test_turns_in_progress_tracks_open_turns(self) -> None:
        await self._ingest(kind="turn_started", timestamp=0.0)
        snap = await self._ingest(kind="turn_started", timestamp=1.0)
        self.assertEqual(snap["turns_in_progress"], 2)
        self.assertEqual(snap["cumulative_turns"], 0)

    async def test_timestamp_defaults_to_the_injected_clock(self) -> None:
        self.clock.set(12.5)
        snap = await self._ingest(kind="turn_finished")
        self.assertEqual(snap["cumulative_turns"], 1)
        self.assertAlmostEqual(snap["now"], 12.5, places=6)

    async def test_state_is_shared_across_requests(self) -> None:
        await self._ingest(kind="tokens", tokens=42, timestamp=1.0)
        self.assertEqual(get_run_projection().snapshot(1.0).cumulative_tokens, 42)
        again = await self._snapshot()
        self.assertEqual(again["cumulative_tokens"], 42)


class TestCompletionProjection(RunTelemetryRoutesTestCase):
    """Remaining work + ETA, and the explicit unknown state."""

    async def test_projection_reports_remaining_and_eta(self) -> None:
        await self._seed_run()
        resp = await self.client.post(TARGET_URL, json={"turns": 4, "tokens": 1000})
        self.assertEqual(resp.status, 200)
        snap = (await resp.json())["snapshot"]

        self.assertEqual(snap["remaining_turns"], 2)
        self.assertEqual(snap["remaining_tokens"], 800)
        # turns: 2 / (6/min) = 20s; tokens: 800 / (400/min) = 120s; bottleneck wins
        self.assertAlmostEqual(snap["eta_seconds_turns"], 20.0, places=6)
        self.assertAlmostEqual(snap["eta_seconds_tokens"], 120.0, places=6)
        self.assertAlmostEqual(snap["eta_seconds"], 120.0, places=6)
        self.assertTrue(snap["projection_known"])
        self.assertTrue(snap["eta_known"])

    async def test_projection_is_unknown_without_enough_data(self) -> None:
        resp = await self.client.post(TARGET_URL, json={"turns": 5})
        self.assertEqual(resp.status, 200)
        snap = (await resp.json())["snapshot"]

        self.assertEqual(snap["remaining_turns"], 5)
        self.assertIsNone(snap["turns_per_min"])
        self.assertIsNone(snap["eta_seconds"])
        self.assertFalse(snap["projection_known"])
        self.assertFalse(snap["eta_known"])

    async def test_projection_is_unknown_when_rate_falls_to_zero(self) -> None:
        await self._ingest(kind="turn_finished", timestamp=1.0)
        await self.client.post(TARGET_URL, json={"turns": 10})

        # Advance far past the rolling window: all activity ages out, rate -> unknown.
        self.clock.set(5000.0)
        snap = await self._snapshot()
        self.assertIsNone(snap["turns_per_min"])
        self.assertIsNone(snap["eta_seconds"])
        self.assertFalse(snap["eta_known"])

    async def test_met_target_projects_zero_not_unknown(self) -> None:
        await self._seed_run()
        resp = await self.client.post(TARGET_URL, json={"turns": 2})
        snap = (await resp.json())["snapshot"]
        self.assertEqual(snap["remaining_turns"], 0)
        self.assertEqual(snap["eta_seconds"], 0.0)
        self.assertTrue(snap["projection_known"])

    async def test_json_never_contains_nan_or_infinity(self) -> None:
        # unknown state
        raw = await (await self.client.get(SNAPSHOT_URL)).text()
        self.assertNotIn("NaN", raw)
        self.assertNotIn("Infinity", raw)
        json.loads(raw)  # strict parse: NaN/Infinity would be re-emitted as floats

        # known state
        await self._seed_run()
        await self.client.post(TARGET_URL, json={"turns": 4, "tokens": 1000})
        raw2 = await (await self.client.get(SNAPSHOT_URL)).text()
        self.assertNotIn("NaN", raw2)
        self.assertNotIn("Infinity", raw2)
        parsed = json.loads(raw2)
        self.assertTrue(parsed["ok"])
        for key in ("tokens_per_min", "turns_per_min", "eta_seconds"):
            value = parsed["snapshot"][key]
            self.assertTrue(value is None or isinstance(value, (int, float)))


class TestReset(RunTelemetryRoutesTestCase):
    async def test_reset_clears_the_aggregate(self) -> None:
        await self._seed_run()
        resp = await self.client.post(RESET_URL, json={})
        self.assertEqual(resp.status, 200)
        snap = (await resp.json())["snapshot"]
        self.assertEqual(snap["cumulative_turns"], 0)
        self.assertEqual(snap["cumulative_tokens"], 0)
        self.assertIsNone(snap["tokens_per_min"])


class TestInputValidation(RunTelemetryRoutesTestCase):
    """Bad input is a 4xx with a message -- never a 500."""

    async def _assert_bad_request(self, resp) -> None:
        self.assertEqual(resp.status, 400, await resp.text())
        self.assertLess(resp.status, 500)

    async def test_body_must_be_a_json_object(self) -> None:
        await self._assert_bad_request(await self.client.post(EVENTS_URL, json=[1, 2, 3]))

    async def test_malformed_json_is_rejected(self) -> None:
        resp = await self.client.post(
            EVENTS_URL,
            data="{not json",
            headers={"Content-Type": "application/json"},
        )
        await self._assert_bad_request(resp)

    async def test_missing_kind_is_rejected(self) -> None:
        await self._assert_bad_request(await self.client.post(EVENTS_URL, json={"timestamp": 1.0}))

    async def test_unknown_kind_is_rejected(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "explode"})
        self.assertEqual(resp.status, 400)
        self.assertIn("turn_started", await resp.text())

    async def test_non_string_kind_is_rejected(self) -> None:
        await self._assert_bad_request(await self.client.post(EVENTS_URL, json={"kind": 7}))

    async def test_tokens_event_requires_tokens(self) -> None:
        await self._assert_bad_request(await self.client.post(EVENTS_URL, json={"kind": "tokens"}))

    async def test_negative_tokens_is_rejected(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "tokens", "tokens": -5})
        await self._assert_bad_request(resp)

    async def test_fractional_tokens_is_rejected(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "tokens", "tokens": 1.5})
        await self._assert_bad_request(resp)

    async def test_oversized_tokens_is_rejected(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "tokens", "tokens": 10**12})
        await self._assert_bad_request(resp)

    async def test_non_numeric_timestamp_is_rejected(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "turn_finished", "timestamp": "later"})
        await self._assert_bad_request(resp)

    async def test_empty_target_is_rejected(self) -> None:
        await self._assert_bad_request(await self.client.post(TARGET_URL, json={}))

    async def test_negative_target_is_rejected(self) -> None:
        await self._assert_bad_request(await self.client.post(TARGET_URL, json={"turns": -1}))

    async def test_fractional_target_is_rejected(self) -> None:
        await self._assert_bad_request(await self.client.post(TARGET_URL, json={"tokens": 10.25}))

    async def test_rejected_input_leaves_state_untouched(self) -> None:
        await self._ingest(kind="tokens", tokens=10, timestamp=1.0)
        await self.client.post(EVENTS_URL, json={"kind": "tokens", "tokens": -1})
        self.clock.set(1.0)
        snap = await self._snapshot()
        self.assertEqual(snap["cumulative_tokens"], 10)


class TestRemoteAccessControl(RunTelemetryRoutesTestCase):
    config = SimpleNamespace(server=SimpleNamespace(access_mode="remote", api_token="test-token"))

    async def test_snapshot_requires_a_token(self) -> None:
        self.assertEqual((await self.client.get(SNAPSHOT_URL)).status, 401)

    async def test_snapshot_accepts_a_valid_token(self) -> None:
        resp = await self.client.get(SNAPSHOT_URL, headers={"Authorization": "Bearer test-token"})
        self.assertEqual(resp.status, 200)

    async def test_ingest_requires_a_token(self) -> None:
        resp = await self.client.post(EVENTS_URL, json={"kind": "turn_finished", "timestamp": 1.0})
        self.assertEqual(resp.status, 401)


class TestPanelContract(unittest.TestCase):
    """The shipped panel is the surface that renders the four values."""

    def setUp(self) -> None:
        self.source = PANEL_PATH.read_text(encoding="utf-8")

    def test_panel_defines_the_documented_mount_global(self) -> None:
        self.assertTrue(PANEL_PATH.is_file(), f"missing panel: {PANEL_PATH}")
        self.assertIn("window.mountRunTelemetryPanel = function (containerEl", self.source)

    def test_panel_is_a_classic_script_not_a_module(self) -> None:
        self.assertNotIn("export default", self.source)
        self.assertNotIn("\nexport ", self.source)
        self.assertNotIn("import ", self.source)

    def test_panel_renders_all_four_acceptance_values(self) -> None:
        for label in ("'Turns'", "'Tokens'", "'Rate'", "'Projection'"):
            self.assertIn(label, self.source)
        for field in ("cumulative_turns", "cumulative_tokens", "tokens_per_min", "turns_per_min", "eta_seconds"):
            self.assertIn(field, self.source)

    def test_panel_polls_the_snapshot_endpoint(self) -> None:
        self.assertIn("/api/run-telemetry", self.source)
        self.assertIn("setInterval(refresh", self.source)

    def test_panel_renders_unknown_instead_of_nan(self) -> None:
        self.assertIn("var UNKNOWN = 'unknown';", self.source)
        # Every formatter is finite-guarded and falls back to the unknown token.
        self.assertIn("return typeof v === 'number' && isFinite(v);", self.source)
        for formatter in ("function formatCount", "function formatRate", "function formatDuration"):
            body = self.source.split(formatter, 1)[1].split("\n  }", 1)[0]
            self.assertIn("return UNKNOWN;", body, f"{formatter} lacks an unknown fallback")

    def test_panel_guards_against_double_mount(self) -> None:
        self.assertIn("containerEl.__runTelemetryPanel", self.source)


if __name__ == "__main__":
    unittest.main()
