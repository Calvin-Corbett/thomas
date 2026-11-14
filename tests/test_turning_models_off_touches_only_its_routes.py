"""The models row, off: its seven routes answer 404, a server started that way never loads them, and the daily refresh stops.

These are the routes that list your models and test a connection: ``GET /api/models`` (the profiles, with the default and
your saved choice), ``/api/models/catalog`` and its ``refresh``, ``/api/models/capabilities`` and, for one profile,
``ids``, ``handshake`` and ``validate``. ``GET /api/version`` used to be registered beside them and is not part of the row:
the server answers it with every row off, which the first test below asks. The row also starts a loop that refreshes the
model list once a day, and only a test that names that task can see it stop, because the row reads off and every route
answers 404 whether or not it carries on. ``thomas.server.rows.models``, ``thomas.server.routes.models_aiohttp`` and
``thomas.models.catalog_refresh`` are the row, the routes and that loop. No test imports a row, so each is named here.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core
from thomas.server.app_keys import APP_MODEL_CATALOG
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "models"
# Written out, because a list worked out from the row would agree with whatever the row did. The fixture's one profile is
# called ``local`` and has no address, so the three that ask a provider answer 200 with "offline" and send nothing out.
ROUTES = {
    "GET /api/models": "GET /api/models",
    "GET /api/models/catalog": "GET /api/models/catalog",
    "POST /api/models/catalog/refresh": "POST /api/models/catalog/refresh",
    "GET /api/models/capabilities": "GET /api/models/capabilities",
    "GET /api/models/{profile}/ids": "GET /api/models/local/ids",
    "GET /api/models/{profile}/handshake": "GET /api/models/local/handshake",
    "GET /api/models/{profile}/validate": "GET /api/models/local/validate?tool_smoke=0",
}
VERSION = "GET /api/version"
OWN_CODE = (
    "thomas.server.rows.models",
    "thomas.server.routes.models_aiohttp",
    "thomas.models.catalog_refresh",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(name.replace("GET", "HEAD") for name in ROUTES if name.startswith("GET "))}

# Read at each of the three presses: the tasks on the loop that are the daily refresh. The test suite turns that refresh off
# for every server it starts, so this process turns it back on, and sends anything it asks for to a closed port.
DAILY_REFRESH = """\
import os

os.environ["THOMAS_MODEL_CATALOG_AUTOREFRESH"] = "1"
os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"


def reading():
    return sorted(
        task.get_coro().__qualname__ for task in asyncio.all_tasks() if "_run_daily" in task.get_coro().__qualname__
    )


"""


@dataclasses.dataclass
class KeyedModel(ModelConfig):
    """``ModelConfig`` has no field for the name of a stored key, and the lookup reads one if a config has it."""

    api_key_secret_name: str = ""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("models-off")
    started, found = start_with_one_row_off(ROW, [*ROUTES.values(), VERSION], folder, reading=DAILY_REFRESH)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("models-remote")
    started, found = ask_as_a_remote_caller(ROW, [*ROUTES.values(), VERSION], folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed_but_the_version_route_stays(
    seen: dict[str, Any],
) -> None:
    assert seen["off"] == {**dict.fromkeys(ROUTES.values(), 404), VERSION: 200}
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_seven_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """Each answer is the handler's, on the fixture's one profile, which has no address so nothing goes out."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys([*ROUTES.values(), VERSION], 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == {**dict.fromkeys(ROUTES.values(), 404), VERSION: 200}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_the_daily_refresh_runs_only_while_the_row_is_on(seen: dict[str, Any]) -> None:
    assert seen["read_off"] == []
    assert seen["read_on"] == ["CatalogRefresher._run_daily"]
    assert seen["read_off_again"] == []


def test_a_remote_caller_with_no_token_is_refused_on_every_route_and_the_version_route_is_open(
    remote: dict[str, Any],
) -> None:
    """``/api/version`` answers with no token unless ``allow_unauthenticated_version`` is turned off, which is not this row's."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {**dict.fromkeys(ROUTES.values(), 401), VERSION: 200}
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_routes_ask_the_guard_the_server_hands_the_row(tmp_path: Path) -> None:
    """The test above cannot see the guard go on the refresh route, because the server refuses any POST under ``/api/`` first.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the routes.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    config = views.config_in(tmp_path)
    service = SimpleNamespace(view=lambda _ctx: app, require_api_access=refuse, config=config, app=app)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> dict[str, int]:
        async with TestClient(TestServer(app)) as client:
            found = {}
            for ask in ROUTES.values():
                method, path = ask.split()
                found[ask] = (await client.request(method, path, json=None if method == "GET" else {})).status
            return found

    assert asyncio.run(asked()) == dict.fromkeys(ROUTES.values(), 403)


def test_turned_off_the_row_takes_its_refresher_off_the_app_and_turned_on_it_puts_a_new_one_back(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ChatGPT model list reads this key and copes with its absence, so off must really remove it."""
    monkeypatch.setenv("THOMAS_MODEL_CATALOG_AUTOREFRESH", "0")

    async def scenario() -> tuple[bool, bool, bool, bool]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await _until_started(app)
            first = app.get(APP_MODEL_CATALOG)
            await client.post(f"/api/plugins/thomas/{ROW}/off")
            gone = APP_MODEL_CATALOG not in app
            await client.post(f"/api/plugins/thomas/{ROW}/on")
            await _until_started(app)
            second = app.get(APP_MODEL_CATALOG)
            return first is not None, gone, second is not None, second is not first

    assert asyncio.run(scenario()) == (True, True, True, True)


async def _until_started(app: web.Application) -> None:
    while any(row["state"] == "loading" for row in app[APP_RUNTIME_PLUGINS].report()["rows"]):
        await asyncio.sleep(0.05)


def test_the_profile_routes_get_your_saved_key_and_an_unknown_profile_is_a_key_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the shell's block did: look the profile up in the server's config, then embed the key from the secret store."""
    from thomas.server.app_keys import APP_SECRETS

    taken: dict[str, Any] = {}
    fake = SimpleNamespace(register_models_routes=lambda _app, **kwargs: taken.update(kwargs))
    monkeypatch.setitem(sys.modules, "thomas.server.routes.models_aiohttp", fake)
    store = SimpleNamespace(get=lambda name, default=None: "sk-stored" if name == "saved" else default)
    app = web.Application()
    app[APP_SECRETS] = store
    config = AppConfig(
        models={"p": KeyedModel(name="p", model="m", api_key_secret_name="saved")},
        default_model="p",
        memory=MemoryConfig(root=str(tmp_path)),
    )
    service = SimpleNamespace(view=lambda _ctx: app, require_api_access=lambda _r: None, config=config, app=app)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    resolved = taken["model_cfg_with_secrets"]("p")
    assert resolved.api_key == "sk-stored"
    assert config.models["p"].api_key == ""  # the config itself is not changed
    with pytest.raises(KeyError):
        taken["model_cfg_with_secrets"]("nobody")


def test_a_row_that_cannot_register_reads_failed_and_not_active_with_no_routes(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``tests/test_server_app_routes_init.py`` pins the log line, and would pass with the raise after it gone."""

    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise KeyError("a reason you can read")

    fake = SimpleNamespace(register_models_routes=fails)
    monkeypatch.setitem(sys.modules, "thomas.server.routes.models_aiohttp", fake)
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.models"):
        app = app_core.create_app(views.config_in(tmp_path))
    row = next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == ROW)

    assert row["state"] == "failed", row
    assert "a reason you can read" in row["error"]
    assert "Models routes unavailable:" in caplog.text


def test_a_server_with_no_access_guard_gets_no_model_routes(caplog: pytest.LogCaptureFixture) -> None:
    from thomas.server.rows.models import plugin

    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.models"):
        with pytest.raises(RuntimeError, match="no access guard"):
            plugin.apply({"web": SimpleNamespace(require_api_access=None)}, {})

    assert "Models route registration skipped: missing runtime dependencies" in caplog.text


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/models.py",
        "thomas/server/routes/models_aiohttp.py",
        "thomas/models/catalog_refresh.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_models_off_touches_only_its_routes.py" in chosen
    assert "tests/test_model_catalog_routes.py" in chosen
    if changed != "thomas/models/catalog_refresh.py":
        assert "tests/test_server_models_routes.py" in chosen
