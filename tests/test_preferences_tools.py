"""Integration tests for the registered preferences tools.

Regression guard for prefs-system-skills-integrations-01: the preferences
tools are registered into the live tool registry, so every tool's execute()
must succeed against the real PreferencesStore.
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on PYTHONPATH when running tests standalone.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thomas.preferences.tools import (
    PreferencesGetTool,
    PreferencesListTool,
    PreferencesResetTool,
    PreferencesSetTool,
)


@pytest.fixture()
def tmp_db(tmp_path: Path):
    db = tmp_path / "prefs_tools_test.db"
    os.environ["THOMAS_DB_PATH"] = str(db)
    yield db
    os.environ.pop("THOMAS_DB_PATH", None)


@pytest.mark.asyncio
async def test_set_get_roundtrip(tmp_db):
    set_res = await PreferencesSetTool().execute({"key": "color", "value": "blue"})
    assert set_res.ok is True, set_res.error

    get_res = await PreferencesGetTool().execute({"key": "color"})
    assert get_res.ok is True, get_res.error
    assert get_res.data["value"] == "blue"


@pytest.mark.asyncio
async def test_get_returns_default_when_unset(tmp_db):
    res = await PreferencesGetTool().execute({"key": "missing", "default": "fallback"})
    assert res.ok is True, res.error
    assert res.data["value"] == "fallback"


@pytest.mark.asyncio
async def test_list_reflects_sets(tmp_db):
    await PreferencesSetTool().execute({"key": "a", "value": 1})
    await PreferencesSetTool().execute({"key": "b", "value": {"nested": True}})

    res = await PreferencesListTool().execute({})
    assert res.ok is True, res.error
    assert res.data["preferences"] == {"a": 1, "b": {"nested": True}}


@pytest.mark.asyncio
async def test_reset_single_key(tmp_db):
    await PreferencesSetTool().execute({"key": "a", "value": 1})
    await PreferencesSetTool().execute({"key": "b", "value": 2})

    res = await PreferencesResetTool().execute({"key": "a"})
    assert res.ok is True, res.error

    listing = await PreferencesListTool().execute({})
    assert listing.data["preferences"] == {"b": 2}


@pytest.mark.asyncio
async def test_reset_all(tmp_db):
    await PreferencesSetTool().execute({"key": "a", "value": 1})

    res = await PreferencesResetTool().execute({})
    assert res.ok is True, res.error

    listing = await PreferencesListTool().execute({})
    assert listing.data["preferences"] == {}
