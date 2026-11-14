"""The switch on the real app: every companion route survives the move, and off means the code did not load."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core
from thomas.server.app_keys import APP_CONFIG
from thomas.server.app_routes_companion import register_companion_route_family
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROOT = Path(__file__).resolve().parents[1]
COMPANION_ROUTE = "/api/companion/v1/status"


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
    )


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _table(routes) -> set[tuple[str, str]]:
    return {(route.method, route.resource.canonical) for route in routes if route.resource is not None}


def test_every_companion_route_is_there_after_the_move(tmp_path: Path, own_data_dir: Path) -> None:
    config = _config(tmp_path)
    bare = web.Application()
    bare[APP_CONFIG] = config

    async def read_json(request: web.Request) -> dict:
        return {}

    register_companion_route_family(
        bare, config, require_api_access=lambda request: None, read_json=read_json, log=logging.getLogger(__name__)
    )
    expected = _table(bare.router.routes())
    assert len(expected) >= 60  # an empty compare would pass

    found = _table(app_core.create_app(config).router.routes())

    assert expected - found == set()


def test_a_real_server_turns_companion_off_and_on(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(_config(tmp_path))
        async with TestClient(TestServer(app)) as client:
            before = await client.get(COMPANION_ROUTE)
            assert before.status != 404

            runtime = app[APP_RUNTIME_PLUGINS]
            await runtime.turn_off("companion")
            assert (await client.get(COMPANION_ROUTE)).status == 404

            await runtime.turn_on("companion")
            assert (await client.get(COMPANION_ROUTE)).status == before.status

    asyncio.run(scenario())


def test_the_sweep_is_a_running_plugin_on_a_real_server(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        app = app_core.create_app(_config(tmp_path))
        async with TestClient(TestServer(app)):
            rows = {row["id"]: row for row in app[APP_RUNTIME_PLUGINS].report()["rows"]}

            assert rows["companion"]["state"] == "active"
            assert rows["consolidation"]["state"] == "active"

    asyncio.run(scenario())


def test_with_companion_off_its_code_never_loads(tmp_path: Path, own_data_dir: Path) -> None:
    """In a process of its own: in this one, any earlier test may already have imported it."""
    choices = own_data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True)
    choices.write_text('{"companion": {"enabled": false}}', encoding="utf-8")
    start = (
        "import sys\n"
        "from thomas.core.config import AppConfig, MemoryConfig, ModelConfig\n"
        "from thomas.server import app_core\n"
        "models = {'local': ModelConfig(name='local', model='dummy')}\n"
        "memory = MemoryConfig(root=sys.argv[1])\n"
        "app_core.create_app(AppConfig(models=models, default_model='local', memory=memory))\n"
        "loaded = [name for name in sys.modules if name.startswith('thomas.companion')]\n"
        "assert not loaded, loaded\n"
    )

    started = subprocess.run(
        [sys.executable, "-c", start, str(tmp_path / "memory")], cwd=ROOT, capture_output=True, text=True, timeout=120
    )

    assert started.returncode == 0, started.stderr[-1500:]
