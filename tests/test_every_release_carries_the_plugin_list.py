"""Every way of installing Thomas carries the plugin list, because a row on no list never loads.

The list sat in a folder of its own beside the package. The release bundle's allow-list left that folder out, the
Dockerfile copies only the package, and ``pip install .``, which install.cmd and install.sh run, copies only the package
into site-packages, where a path worked out from the file that reads the list leads nowhere. Each one started a server
with no rows: the goal routes and the companion apps answered 404, and the Plugins page had nothing to turn back on.

The list is now ``thomas/server/rows/default.toml``, inside the package, because the package is the one thing every
route carries. Shipping the old folder would have satisfied a check on the bundle and left the copies and the image as
they were. That name is also how a check finds this file when the list changes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests.row_proof_fixture import ROOT, ROWS
from thomas.core.plugin_manifest import load, scope
from thomas.core.plugin_proof import HARNESS
from thomas.server.runtime_plugins import PROFILE_PATH, read_profile

THE_LIST = PROFILE_PATH.relative_to(ROOT).as_posix()

# A start with no saved choices, which is what a new install is. Run as a process of its own in the bundle's folder, so
# the Thomas it imports is the bundle's.
_FRESH_START = """\
import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

import thomas
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core

memory, seen_at = sys.argv[1:]


async def run_the_server():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    async with TestClient(TestServer(app)) as client:
        report = await (await client.get("/api/plugins/thomas")).json()
        while any(row["state"] == "loading" for row in report["rows"]):  # startup hooks end after a start does
            await asyncio.sleep(0.05)
            report = await (await client.get("/api/plugins/thomas")).json()
        return {
            "thomas": str(Path(thomas.__file__).resolve()),
            "codes": report["note_codes"],
            "rows": {row["id"]: row["state"] for row in report["rows"]},
            "goals": (await client.get("/api/goals")).status,
            "goal_stats": (await client.get("/api/goals/stats")).status,
        }


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real bundle, built the way a release builds it: the allow-list is only the first of its filters."""
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
def started_from_bundle(bundle: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("bundle-start")
    home = folder / "home"
    seen_at = folder / "seen.json"
    started = subprocess.run(
        [sys.executable, "-c", _FRESH_START, str(folder / "memory"), str(seen_at)],
        cwd=bundle,
        env={
            **os.environ,
            "THOMAS_DATA_DIR": str(folder / "data"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "roaming"),
            "LOCALAPPDATA": str(home / "local"),
        },
        capture_output=True,
        text=True,
    )
    assert seen_at.is_file(), started.stderr[-1500:]
    return json.loads(seen_at.read_text(encoding="utf-8"))


def test_the_list_is_inside_the_package_so_a_copy_of_the_package_has_it() -> None:
    """pip copies the package and nothing else, so a list outside it is a path into site-packages that leads nowhere."""
    assert PROFILE_PATH.is_file()
    assert PROFILE_PATH.is_relative_to(ROOT / "thomas")


def test_there_is_one_list() -> None:
    """A second copy would be read by nothing, and a row added to it would just never load."""
    assert not (ROOT / "plugins" / "profiles" / "default.toml").exists()


def test_a_release_bundle_has_the_list_and_every_row_on_it(bundle: Path) -> None:
    shipped = read_profile(bundle / THE_LIST).entries
    assert shipped, "the bundle's list is empty"
    assert [row.id for row in shipped] == [row.id for row in ROWS]


def test_a_server_started_from_a_bundle_has_its_rows_and_answers_the_goal_routes(
    bundle: Path, started_from_bundle: dict[str, Any]
) -> None:
    """Every row up, not just listed: a row that reaches for a file no release ships fails only here."""
    assert Path(started_from_bundle["thomas"]).is_relative_to(bundle.resolve()), "this started some other Thomas"
    assert started_from_bundle["codes"] == []
    # Every row the list ships on is up. One it ships off, such as aliveness, is a row the bundle starts off by design.
    assert started_from_bundle["rows"] == {
        row.id: "active" if row.config["enabled"] else "off" for row in sorted(ROWS, key=lambda row: row.id)
    }
    assert (started_from_bundle["goals"], started_from_bundle["goal_stats"]) == (200, 200)


def test_manifest_in_names_the_lists_folder() -> None:
    """The wheel takes any file in the package that this names, and pyproject.toml is protected, so this is the line."""
    folder = PROFILE_PATH.parent.relative_to(ROOT).as_posix()
    assert f"recursive-include {folder} *.toml" in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()


def test_a_wheel_has_the_list(tmp_path: Path) -> None:
    """A wheel is what install.cmd, install.sh and pip install really put in place. Built from a slim tree for speed."""
    pytest.importorskip("setuptools")
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "MANIFEST.in", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, source / name)
    for package in ("thomas/__init__.py", "thomas/server/__init__.py", "evolve_supervisor/__init__.py"):
        (source / package).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / package, source / package)
    shutil.copytree(ROOT / "skills", source / "skills")  # pyproject.toml names each one, and a build stops without it
    shutil.copytree(PROFILE_PATH.parent, source / PROFILE_PATH.parent.relative_to(ROOT), dirs_exist_ok=True)
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "--no-index"]
        + ["--wheel-dir", str(tmp_path / "wheel"), "--quiet", "--disable-pip-version-check"],
        cwd=source,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stdout[-1500:] + built.stderr[-1500:]
    with zipfile.ZipFile(next((tmp_path / "wheel").glob("*.whl"))) as wheel:
        assert THE_LIST in wheel.namelist()


def test_the_docker_image_has_the_list() -> None:
    """The image copies the package and runs from it, and the Dockerfile is protected, so it must need nothing else."""
    assert "COPY thomas ./thomas" in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    assert THE_LIST.startswith("thomas/")
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    patterns = [line.strip().rstrip("/") for line in ignored if line.strip() and not line.startswith("#")]
    parts = THE_LIST.split("/")
    paths = ["/".join(parts[: depth + 1]) for depth in range(len(parts))]
    assert [pattern for pattern in patterns if any(fnmatch.fnmatch(path, pattern) for path in paths)] == []


def test_a_change_to_the_list_still_reaches_every_proof() -> None:
    """Moving it out of the folder these rules cover must not make a change to what every test loads look local."""
    assert scope(load(ROOT), [THE_LIST]) is None
    assert THE_LIST in HARNESS
