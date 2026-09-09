"""Tests for CAP-068: MCP registry / discovery.

Acceptance line: "Add a searchable MCP catalog with one-step install and
task-triggered server suggestions."

Covers:
- the bundled catalog is well-formed,
- search finds servers by concept and ranks relevant ones first,
- one-step install writes a valid compat_mcp row that round-trips through the
  CAP-067 loader and client, and is idempotent,
- suggest_for_task returns relevant servers for a task and nothing for an
  unrelated one.

Hermetic: the store path is redirected to a temp file via the
``THOMAS_MCP_REGISTRY_PATH`` env var (and the config-derived path is exercised
too); no network, no live model, no subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.cli.parity_support import load_mcp_registry
from thomas.core.config import AppConfig, MemoryConfig
from thomas.tools.mcp_client import client_from_server_row
from thomas.tools.mcp_registry import (
    CATALOG,
    REGISTRY_PATH_ENV,
    CatalogEntry,
    McpRegistryError,
    catalog,
    get_entry,
    install,
    registry_store_path,
    search,
    suggest_for_task,
)


# --- catalog well-formedness --------------------------------------------------
def test_catalog_entries_are_well_formed() -> None:
    assert len(CATALOG) >= 5
    names = [entry.name for entry in CATALOG]
    assert len(names) == len(set(names)), "catalog names must be unique"
    expected = {"filesystem", "git", "sqlite", "fetch", "memory"}
    assert expected.issubset(set(names))
    for entry in CATALOG:
        assert isinstance(entry, CatalogEntry)
        assert entry.name and entry.name == entry.name.strip().lower()
        assert entry.description.strip()
        assert entry.transport == "stdio"
        assert entry.command.strip(), f"{entry.name} needs a command"
        assert entry.keywords, f"{entry.name} needs keywords"
        assert entry.categories, f"{entry.name} needs categories"
        assert entry.homepage.startswith("https://")


def test_catalog_accessor_and_get_entry() -> None:
    assert catalog() == CATALOG
    assert get_entry("SQLite") is get_entry("sqlite")
    assert get_entry("sqlite").name == "sqlite"
    assert get_entry("does-not-exist") is None


# --- search -------------------------------------------------------------------
def test_search_finds_by_concept_and_ranks() -> None:
    # Concept: "database" is not the server's name but is a keyword/category.
    results = search("store data in a relational database")
    assert results, "database concept should match a server"
    assert "database" in results[0].categories
    assert results[0].name == "sqlite"

    files = search("read and write files on disk")
    assert files[0].name == "filesystem"

    web = search("download a web page over http")
    assert web[0].name == "fetch"

    notes = search("remember notes and facts across sessions")
    assert notes[0].name == "memory"


def test_search_ranks_exact_name_first() -> None:
    results = search("git commit and diff")
    assert results[0].name == "git"


def test_search_unrelated_query_returns_nothing() -> None:
    assert search("photosynthesis chlorophyll sunlight") == []


def test_search_limit_caps_results() -> None:
    results = search("file database web git memory time", limit=2)
    assert len(results) == 2


# --- suggest_for_task ---------------------------------------------------------
def test_suggest_for_task_returns_relevant_servers() -> None:
    suggestions = suggest_for_task("I need to run a SQL query against my database")
    names = [entry.name for entry in suggestions]
    assert "sqlite" in names
    assert suggestions[0].name == "sqlite"

    git_task = suggest_for_task("commit my changes to the repository and show the diff")
    assert git_task[0].name == "git"


def test_suggest_for_task_unrelated_returns_empty() -> None:
    assert suggest_for_task("compose a poem about autumn leaves") == []
    assert suggest_for_task("") == []


# --- one-step install ---------------------------------------------------------
def _temp_config(tmp_path: Path) -> AppConfig:
    return AppConfig(memory=MemoryConfig(root=str(tmp_path)))


def test_install_writes_valid_compat_row_and_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _temp_config(tmp_path)
    # Point the env override at exactly the config-derived path so both the
    # registry writer and the compat reader resolve the same file.
    store = registry_store_path(config)
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(store))

    row = install("sqlite", config=config)
    assert row["name"] == "sqlite"
    assert row["transport"] == "stdio"
    assert row["command"] == "uvx"
    assert "mcp-server-sqlite" in row["args"]
    assert row["enabled"] is True
    assert row["created_at"] and row["updated_at"]

    # Round-trips through the exact compat loader the CAP-067 client reads.
    stored_rows = load_mcp_registry(config)
    stored = next((r for r in stored_rows if r["name"] == "sqlite"), None)
    assert stored is not None
    assert stored["command"] == "uvx"

    # The stored row is directly consumable by the CAP-067 client builder.
    client = client_from_server_row(stored)
    assert client.name == "sqlite"
    assert not client.running


def test_install_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _temp_config(tmp_path)
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(registry_store_path(config)))

    first = install("filesystem", config=config)
    second = install("filesystem", config=config)

    rows = load_mcp_registry(config)
    fs_rows = [r for r in rows if r["name"] == "filesystem"]
    assert len(fs_rows) == 1, "re-install must not duplicate the row"
    # created_at is preserved across re-install; updated_at is refreshed.
    assert second["created_at"] == first["created_at"]


def test_install_unknown_server_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _temp_config(tmp_path)
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(registry_store_path(config)))
    with pytest.raises(McpRegistryError):
        install("not-a-real-server", config=config)


def test_registry_store_path_prefers_env_then_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REGISTRY_PATH_ENV, raising=False)
    config = _temp_config(tmp_path)
    derived = registry_store_path(config)
    assert derived == tmp_path / ".thomas" / "cli" / "mcp_servers.json"

    override = tmp_path / "custom" / "servers.json"
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(override))
    assert registry_store_path(config) == override

    monkeypatch.delenv(REGISTRY_PATH_ENV, raising=False)
    with pytest.raises(McpRegistryError):
        registry_store_path(None)
