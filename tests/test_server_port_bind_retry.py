"""Regression test for server port bind retry behavior."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import tempfile
import unittest

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import serve_async


class TestServeAsyncPortBindRetry(unittest.IsolatedAsyncioTestCase):
    async def test_retry_does_not_reuse_registered_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AppConfig(
                models={"local": ModelConfig(name="local", model="dummy")},
                default_model="local",
                memory=MemoryConfig(root=tmpdir),
                server=ServerConfig(access_mode="local"),
            )

            blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            port = int(blocker.getsockname()[1])

            async def _release_port() -> None:
                await asyncio.sleep(0.30)
                with contextlib.suppress(OSError):
                    blocker.close()

            release_task = asyncio.create_task(_release_port())
            try:
                # Once the blocker releases, serve_async should bind and stay
                # alive (wait_for timeout), not crash with RuntimeError.
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        serve_async(cfg, host="127.0.0.1", port=port),
                        timeout=6.0,
                    )
            finally:
                with contextlib.suppress(OSError):
                    blocker.close()
                await release_task


if __name__ == "__main__":
    unittest.main()
