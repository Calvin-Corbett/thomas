import json
import tempfile
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes.chat_v2_request_support import _foreground_runtime_policy
from thomas.server.routes.chat_v2_usage import UsageReceiptDispatcher


def _parse_ndjson(blob: str):
    out = []
    for raw in str(blob or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class _FakeOrchestratorBrainTokenEconomy:
    last_mode: str | None = None
    last_max_iterations: int | None = None
    last_token_economy: str | None = None

    def __init__(self, *args, runtime_policy=None, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        self.runtime_policy = runtime_policy

    async def process_message(  # noqa: ANN001
        self,
        session_id,
        conversation,
        prompt,
        dispatcher,
        *,
        mode="auto",
        token_economy="optimal",
        display_prompt=None,
        **kwargs,
    ):
        _ = kwargs
        _FakeOrchestratorBrainTokenEconomy.last_mode = str(mode)
        _FakeOrchestratorBrainTokenEconomy.last_token_economy = str(token_economy)
        quality = getattr(self.runtime_policy, "quality", None)
        _FakeOrchestratorBrainTokenEconomy.last_max_iterations = int(getattr(quality, "max_agent_iterations", 0) or 0)
        await dispatcher.emit_text("TOKEN_ECONOMY_OK")
        updated = conversation.append_message("user", display_prompt or prompt).append_message(
            "assistant", "TOKEN_ECONOMY_OK"
        )
        await dispatcher.emit_done(
            session_id=session_id,
            conversation_version=updated.version,
            iterations=1,
            tool_calls=0,
            token_report={"mode": str(mode)},
        )
        return updated


@dataclass(frozen=True)
class _QualityPolicy:
    max_agent_iterations: int = 0


@dataclass(frozen=True)
class _RuntimePolicy:
    quality: _QualityPolicy


class TestForegroundTokenEconomyPolicy(unittest.TestCase):
    def test_foreground_scaling_does_not_mutate_background_policy(self):
        worker_policy = _RuntimePolicy(quality=_QualityPolicy())
        applied, foreground_policy, metadata = _foreground_runtime_policy(
            worker_policy,
            SimpleNamespace(max_agent_iterations=10),
            "max",
            requested_token_economy="max",
        )

        self.assertEqual(applied, "max")
        self.assertEqual(foreground_policy.quality.max_agent_iterations, 25)
        self.assertEqual(worker_policy.quality.max_agent_iterations, 0)
        self.assertEqual(metadata, {"requested": "max", "applied": "max"})


class TestTokenEconomyReceiptDispatcher(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_existing_token_report_is_replaced_safely(self):
        class _Capture:
            fields: dict | None = None

            async def emit_done(self, *args, **kwargs):  # noqa: ANN002, ANN003
                _ = args
                self.fields = kwargs

        capture = _Capture()
        dispatcher = UsageReceiptDispatcher(
            capture,
            SimpleNamespace(session_usage=None),
            token_economy={"requested": "turbo", "applied": "optimal"},
        )

        await dispatcher.emit_done(token_report="malformed")

        self.assertEqual(
            capture.fields["token_report"],
            {"token_economy": {"requested": "turbo", "applied": "optimal"}},
        )


class TestServerTokenEconomy(AioHTTPTestCase):
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
            max_agent_iterations=10,
        )
        return create_app(cfg)

    async def _new_session_id(self) -> str:
        sess_resp = await self.client.post("/api/session/new")
        self.assertEqual(sess_resp.status, 200)
        sid = str((await sess_resp.json()).get("session_id") or "")
        self.assertTrue(sid)
        return sid

    def _assert_balanced_receipts(self, events):  # noqa: ANN001
        """One route, one done, one balanced receipt stamped on all three carriers.

        ``orchestrator`` is the only path Chat V2 emits: ``UsageReceiptDispatcher.emit_route``
        hard-codes it as the canonical entry route. Asserting it here keeps this helper from
        silently accepting a stream that routed somewhere unexpected.
        """
        expected = {"requested": "balanced", "applied": "optimal"}
        routes = [event for event in events if event.get("type") == "route"]
        done_events = [event for event in events if event.get("type") == "done"]
        self.assertEqual(len(routes), 1, events)
        self.assertEqual(len(done_events), 1, events)
        self.assertEqual((routes[0].get("route") or {}).get("path"), "orchestrator")
        self.assertEqual(routes[0].get("token_economy"), expected)
        self.assertEqual(done_events[0].get("token_economy"), expected)
        self.assertEqual((done_events[0].get("token_report") or {}).get("token_economy"), expected)
        seqs = [int(event.get("seq")) for event in events]
        self.assertEqual(seqs, sorted(set(seqs)))

    async def test_max_profile_keeps_mode_and_raises_iteration_budget(self):
        sid = await self._new_session_id()
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeOrchestratorBrainTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "fast",
                    "token_economy": "max",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "fast")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_mode, "fast")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_token_economy, "max")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_max_iterations, 25)
        self.assertEqual((route.get("token_economy") or {}).get("applied"), "max")
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "max")
        self.assertEqual(
            ((done.get("token_report") or {}).get("token_economy") or {}).get("applied"),
            "max",
        )

    async def test_cheap_profile_keeps_mode_and_lower_iteration_budget(self):
        sid = await self._new_session_id()
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeOrchestratorBrainTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "thinking",
                    "token_economy": "cheap",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "thinking")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_mode, "thinking")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_token_economy, "cheap")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_max_iterations, 3)
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "cheap")

    async def test_optimal_profile_keeps_requested_mode_and_default_iterations(self):
        sid = await self._new_session_id()
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeOrchestratorBrainTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "auto",
                    "token_economy": "optimal",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        self.assertEqual(str(route.get("mode") or ""), "auto")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_mode, "auto")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_token_economy, "optimal")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_max_iterations, 10)
        done = [e for e in events if e.get("type") == "done"][0]
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "optimal")

    async def test_balanced_alias_maps_to_optimal(self):
        sid = await self._new_session_id()
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeOrchestratorBrainTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "auto",
                    "token_economy": "balanced",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        self.assertTrue(events)
        route = [e for e in events if e.get("type") == "route"][0]
        done = [e for e in events if e.get("type") == "done"][0]
        expected = {"requested": "balanced", "applied": "optimal"}
        self.assertEqual(route.get("token_economy"), expected)
        self.assertEqual((done.get("token_economy") or {}).get("requested"), "balanced")
        self.assertEqual((done.get("token_economy") or {}).get("applied"), "optimal")
        self.assertEqual((done.get("token_report") or {}).get("token_economy"), expected)
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_token_economy, "optimal")

    async def test_unknown_token_economy_falls_back_to_optimal_with_receipt(self):
        sid = await self._new_session_id()
        with patch("thomas.server.routes.chat_v2.OrchestratorBrain", _FakeOrchestratorBrainTokenEconomy):
            resp = await self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "profile": "local",
                    "mode": "auto",
                    "token_economy": "turbo",
                    "text": "run",
                },
            )

        self.assertEqual(resp.status, 200)
        events = _parse_ndjson(await resp.text())
        route = [event for event in events if event.get("type") == "route"][0]
        done = [event for event in events if event.get("type") == "done"][0]
        expected = {"requested": "turbo", "applied": "optimal"}
        self.assertEqual(route.get("token_economy"), expected)
        self.assertEqual(done.get("token_economy"), expected)
        self.assertEqual((done.get("token_report") or {}).get("token_economy"), expected)
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_token_economy, "optimal")
        self.assertEqual(_FakeOrchestratorBrainTokenEconomy.last_max_iterations, 10)

    async def test_prose_that_used_to_skip_the_model_still_gets_balanced_receipts(self):
        """Prose the retired classifiers answered without a model now routes to the
        orchestrator, and still carries its balanced token-economy receipt.

        Before: this was two tests asserting route paths ``control`` and ``static``. Commit
        69bbbab0 retired natural-language UI control and Discord prose interception and
        deleted both emitters -- ``chat_v2_ui_control.py`` kept only the header helper, and
        ``discord_channels_support.py`` was removed whole. On dev, ``git grep '"path":
        "control"'`` and ``'"path": "static"'`` both return nothing, so the two tests failed
        ``'orchestrator' != 'control'`` and ``'orchestrator' != 'static'``. Stubbing no model,
        they also reached a real provider and logged ``Reasoning failed: Request URL is
        missing an 'http://' or 'https://' protocol`` -- a missing model endpoint reported
        under the name of a receipt guarantee.

        After: measured on dev before this test was written, both inputs already emit
        ``{"requested": "balanced", "applied": "optimal"}`` on ``route``, on ``done``, and
        inside ``done.token_report`` -- unchanged by the failed provider call. The receipts
        were never unbalanced; only the two route names were dead. The brain is stubbed here
        so the guarantee can neither pass nor fail for a network reason, and the stubbed
        reply is asserted first so a turn that died early cannot look like a pass.
        """
        for text in ("set mode to fast", "show discord status"):
            with self.subTest(text=text):
                sid = await self._new_session_id()
                with patch(
                    "thomas.server.routes.chat_v2.OrchestratorBrain",
                    _FakeOrchestratorBrainTokenEconomy,
                ):
                    resp = await self.client.post(
                        "/api/v2/chat",
                        json={
                            "session_id": sid,
                            "profile": "local",
                            "token_economy": "balanced",
                            "text": text,
                        },
                    )

                self.assertEqual(resp.status, 200)
                events = _parse_ndjson(await resp.text())
                self.assertIn(
                    "TOKEN_ECONOMY_OK",
                    [event.get("text") for event in events if event.get("type") == "text"],
                    events,
                )
                self._assert_balanced_receipts(events)


if __name__ == "__main__":
    unittest.main()
