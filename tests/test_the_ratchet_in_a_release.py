"""What a release shows for the ratchet row: on, answering, and with no way to start a run.

A release carries the package and not ``scripts/cage``, where the promoter's checks live. The shell's block logged ``No
module named scripts.cage``, so a release had no routes at all, and every other server had them. A row cannot do that:
one that fails on every install reads failed on a page you can do nothing about, and one that catches its own failure
reads active with no routes. So the code loads in a release, the two checks that need ``scripts/cage`` are read only by a
run, and ``host_refusal`` is what keeps a run from getting there. A release answers ``GET /api/ratchet`` from its empty
records, with the reason in ``host``, and refuses ``POST /api/ratchet/run``.

The row's words hold in a release because of that: it is a copy of Thomas that is not the caged one, so it never starts a
run. ``tests/test_every_release_carries_the_plugin_list.py`` holds the row's state, and this file holds what ``active``
means there. ``thomas.server.rows.ratchet`` is named here so that a check of the row finds this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.row_proof_fixture import ROOT

_THE_REASON = "this install has none of the checks a run needs"

# Names this account and turns the daily run on, so that only the release's own lack of scripts/cage can be what stops a
# run. The stand-in is in place first, so that a broken check here records a run and cannot start a real one.
_A_RELEASE_AS_THE_CAGED_THOMAS = """\
import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

import thomas
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core
from thomas.server.ratchet.service import RatchetService

memory, seen_at = sys.argv[1:]
ran = []


async def a_stand_in_for_a_run(self, **_options):
    ran.append("a run")
    return {"status": "ran", "proven": []}


RatchetService.run_once = a_stand_in_for_a_run


async def run_the_server():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    async with TestClient(TestServer(app)) as client:
        report = await (await client.get("/api/plugins/thomas")).json()
        read = await client.get("/api/ratchet")
        asked = await client.post("/api/ratchet/run", json={})
        await asyncio.sleep(0)
        return {
            "thomas": str(Path(thomas.__file__).resolve()),
            "row": next(row for row in report["rows"] if row["id"] == "ratchet"),
            "read": [read.status, await read.json()],
            "asked": [asked.status, await asked.json()],
            "tasks": sorted(task.get_name() for task in asyncio.all_tasks()),
            "ran": ran,
        }


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("bundle")
    built = subprocess.run(
        [sys.executable, "scripts/package_release.py", "--out-dir", str(out), "--no-zip", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr[-1500:]
    return Path(json.loads(built.stdout.splitlines()[-1])["output_dir"])


@pytest.fixture(scope="module")
def seen(bundle: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("bundle-start")
    home = folder / "home"
    seen_at = folder / "seen.json"
    started = subprocess.run(
        [sys.executable, "-c", _A_RELEASE_AS_THE_CAGED_THOMAS, str(folder / "memory"), str(seen_at)],
        cwd=bundle,
        env={
            **os.environ,
            "THOMAS_DATA_DIR": str(folder / "data"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "roaming"),
            "LOCALAPPDATA": str(home / "local"),
            "THOMAS_RATCHET_ACCOUNT": getpass.getuser(),
            "THOMAS_RATCHET_AUTORUN": "1",
        },
        capture_output=True,
        text=True,
    )
    assert seen_at.is_file(), started.stderr[-1500:]
    return json.loads(seen_at.read_text(encoding="utf-8"))


def test_it_is_a_release_with_no_cage_code_at_all(bundle: Path, seen: dict[str, Any]) -> None:
    assert Path(seen["thomas"]).is_relative_to(bundle.resolve()), "this started some other Thomas"
    assert not (bundle / "scripts" / "cage").exists()


def test_the_row_is_on_there(seen: dict[str, Any]) -> None:
    assert (seen["row"]["state"], seen["row"]["error"]) == ("active", "")


def test_the_routes_answer_there_and_say_why_no_run_will_start(seen: dict[str, Any]) -> None:
    status, read = seen["read"]
    assert status == 200 and read["candidates"] == [] and read["running"] is False
    assert _THE_REASON in read["host"]


def test_a_run_is_refused_there_and_none_starts(seen: dict[str, Any]) -> None:
    status, asked = seen["asked"]
    assert (status, asked["code"]) == (409, "ratchet_not_here") and _THE_REASON in asked["error"]
    assert seen["ran"] == []


def test_the_daily_run_never_starts_there_even_as_the_caged_account(seen: dict[str, Any]) -> None:
    assert [task for task in seen["tasks"] if "ratchet" in task] == []
