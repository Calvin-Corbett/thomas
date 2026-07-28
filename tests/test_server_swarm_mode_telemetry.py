"""RETIRED 2026-07-28: the swarm chat engine this file tested no longer exists.

What used to be here: five tests that sabotaged Chat V2 registration with
``RuntimeError("legacy-chat-required")``, patched
``thomas.server.routes.chat_aiohttp.AgentLoop`` with a fake swarm loop, and
asserted the ndjson telemetry the legacy V1 handler streamed back. They had been
failing with 404 for a long time, because Chat V2 is the ONLY registrar of
``POST /api/chat`` -- sabotaging it left the route unclaimed rather than falling
back to anything.

They were not fixable, because the engine they drive is gone. What replaces them
is a pin on that absence, so the sabotage pattern cannot be reintroduced by
someone reading the old file and assuming a fallback used to work.

The endpoint-level contract those tests were reaching for now lives in
``tests/test_server_chat_endpoint_registration.py``: a healthy boot serves real
Chat V2, and a failed one answers 503 instead of 404.
"""

from __future__ import annotations

import importlib
import unittest

from thomas.server.routes.chat_modes import maybe_handle_swarm_mode


class TestSwarmChatEngineStaysRetired(unittest.IsolatedAsyncioTestCase):
    def test_swarm_engine_module_does_not_exist(self):
        # ``maybe_handle_swarm_mode`` bridges to this module. It has no
        # implementation anywhere in the tree, which is why no chat route --
        # legacy or V2 -- can execute a swarm turn.
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("thomas.server.routes.chat_swarm")

    async def test_swarm_bridge_declines_instead_of_running_an_engine(self):
        # The bridge swallows the missing import and returns None, so the caller
        # falls through to the normal path. A future module that made this
        # return a response would resurrect a parallel chat engine.
        self.assertIsNone(await maybe_handle_swarm_mode())

    def test_chat_v2_treats_swarm_as_a_token_economy_alias(self):
        from thomas.server.routes.chat_v2 import _LEGACY_MODE_MIGRATIONS

        self.assertEqual(_LEGACY_MODE_MIGRATIONS.get("swarm"), "max")
        self.assertEqual(_LEGACY_MODE_MIGRATIONS.get("batch"), "max")


if __name__ == "__main__":
    unittest.main()
