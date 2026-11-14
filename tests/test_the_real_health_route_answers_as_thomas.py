"""BootDoctor's identity check is tested against Thomas's real /api/health, not only against fakes.

``answers_as_thomas`` wants a JSON object with "status" and "version". The fake servers in the other BootDoctor tests
agree with that by construction, so if the route stopped returning either key, every test would pass while BootDoctor
took the running Thomas for another program. This serves the real route on a real socket and asks it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer

from tests._bootdoctor_fakes import free_port, isolate_offline_checks
from thomas.core.boot_checks import answers_as_thomas
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.forge.anvil.forge_code_projects import thomas_owned_root
from thomas.integrations.discord_bridge_runtime_support import _default_shared_secret_root
from thomas.server.app import create_app


def test_isolating_the_offline_checks_keeps_a_test_out_of_your_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)

    assert _default_shared_secret_root().is_relative_to(tmp_path)
    assert thomas_owned_root().is_relative_to(tmp_path)


def test_the_real_health_route_passes_the_identity_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    port = free_port()
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        server=ServerConfig(access_mode="local"),
        memory=MemoryConfig(root=str(tmp_path / "mem")),
    )

    async def ask() -> bool:
        server = TestServer(create_app(config), host="127.0.0.1", port=port)
        await server.start_server()
        try:
            # answers_as_thomas is a blocking urllib call; run it off the loop the server is answering on.
            return await asyncio.get_running_loop().run_in_executor(None, answers_as_thomas, "127.0.0.1", port)
        finally:
            await server.close()

    assert asyncio.run(ask()) is True
