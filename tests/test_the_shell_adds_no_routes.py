"""The shell adds no routes: what it registers itself may only go down, and a new route is a row.

You asked for every feature to be a plugin row. A route the shell registers directly, in ``app_routes_families.py``,
``app_routes_init.py``, ``parity_routes.py`` and the like, is one that is not a row yet. This test counts them. The
frozen router holds exactly the shell's routes (``LiveRouter.server_routes``), since a row's routes join the live table
beside it, so the count needs no list of rows to be right.

Two things are held. The shell's routes must all be in ``tests/shell_routes_recorded.txt``, so a new route is named in
the failure. And their count must not exceed ``CEILING``, and ``CEILING`` must not sit above it by more than ``SLACK``.

Every wave that moves routes into a row lowers CEILING, and drops the same lines from shell_routes_recorded.txt, in the
same commit. Without the second test a wave could leave room under the ceiling, and a new shell route would fit in it.

What is left, and why each group stays in the shell (the 53 in ``shell_routes_recorded.txt``). You said that where speed,
ease of editing and being friendly pull against security, security wins, and that the routes the boot scripts poll stay open.

* The pages Thomas opens with: ``/``, ``/classic``, ``/mission``, ``/settings``, ``/companion``, ``/my-stuff``, ``/my_stuff``,
  ``/agent-ops``, ``/favicon.ico`` and ``/static/{path}``. The Plugins page is one of them, so it cannot be a row it turns off.
* What the boot scripts and the watchdog poll: ``/api/health``, ``/api/version``, ``/health/ready``, ``/healthz`` and the
  ``/api/bootdoctor`` reports. With these gone from a server that is up, nothing could tell whether it started.
* The switches themselves: ``/api/plugins/kernel/*`` and ``/api/plugins/thomas/*``. A row cannot carry the route that turns it on.
* The walls: ``/api/security/*``, ``/api/guardrails/policy``, ``/api/approvals/*`` and ``/api/server/restart``. A plugin that
  can be turned off cannot be what asks you for a card or stops a change.
* Preferences and your saved chats: ``/api/preferences`` and ``/api/chats``. Every page reads them before it draws.
* The core of Thomas projects: ``/api/self/projects`` with its stop, send back and hand in again. Build and the cage depend on it.

Nothing else belongs here. A route that is not in these groups is a row, and this test fails until it is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.row_page_fixture import _settings
from tests.row_proof_fixture import ROOT

# Measured, not chosen: the number of (method, path) the shell registers itself. Lower it with every wave.
CEILING = 53
# What CEILING may sit above the measured count. Zero: the last wave that moved routes is done, so a wave that removes a
# route and forgets the ceiling, or adds one, fails at once.
SLACK = 0
LIST = Path(__file__).with_name("shell_routes_recorded.txt")
FIX = (
    "FIX: make it a row with docs/superpowers/plans/2026-10-31-moving-a-feature-into-a-row.md, "
    "do not raise the ceiling."
)

_LIST_THEM = """\
import json
import sys

from aiohttp.web_urldispatcher import UrlDispatcher

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core

models = {"local": ModelConfig(name="local", model="dummy")}
app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=sys.argv[1])))
router = app.router
routes = router.server_routes() if hasattr(router, "server_routes") else UrlDispatcher.routes(router)
# aiohttp adds a HEAD beside every GET unasked, so it says nothing the GET does not.
print(json.dumps(sorted({f"{r.method} {r.resource.canonical}" for r in routes if r.resource and r.method != "HEAD"})))
"""


@pytest.fixture(scope="module")
def shell_routes(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    folder = tmp_path_factory.mktemp("shell-routes")
    done = subprocess.run(
        [sys.executable, "-c", _LIST_THEM, str(folder / "memory")],
        cwd=ROOT,
        env=_settings(folder),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _recorded() -> list[str]:
    return [line for line in LIST.read_text(encoding="utf-8").splitlines() if line]


def test_the_shell_registers_no_route_that_is_not_already_recorded(shell_routes: list[str]) -> None:
    new = sorted(set(shell_routes) - set(_recorded()))
    assert new == [], f"The shell registered {len(new)} new route(s) outside a row:\n" + "\n".join(new) + f"\n{FIX}"


def test_the_shell_registers_no_more_routes_than_the_ceiling(shell_routes: list[str]) -> None:
    assert len(shell_routes) <= CEILING, f"{len(shell_routes)} shell routes, ceiling {CEILING}. {FIX}"


def test_the_ceiling_is_lowered_with_every_route_that_moves_into_a_row(shell_routes: list[str]) -> None:
    assert CEILING - len(shell_routes) <= SLACK, (
        f"CEILING is {CEILING} and the shell registers {len(shell_routes)}. Lower CEILING to {len(shell_routes)} "
        "and drop the moved routes from tests/shell_routes_recorded.txt, so no room is left for a new shell route."
    )
    stale = sorted(set(_recorded()) - set(shell_routes))
    assert stale == [], "recorded but no longer registered by the shell, so drop them from the list:\n" + "\n".join(
        stale
    )
