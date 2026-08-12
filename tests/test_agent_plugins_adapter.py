"""The Agent Plugins (agent-plugins.org 1.0.0) install contract.

An open-standard bundle installs as the UNVERIFIED community tier: the tree
lands beside desktop plugins through the real record pipeline, skills copy
into the user skills root with a provenance sidecar, and MCP servers are
registered DISABLED — nothing a community plugin ships may run until the
owner enables it. The signed desktop-plugin path must never be claimed by
the adapter, the MCP store keeps its canonical envelope, and reinstalls
never orphan extras.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from thomas.core.config import AppConfig, MemoryConfig
from thomas.server import agent_plugins_adapter as adapter
from thomas.server.agent_plugins_manifest import (
    MCP_SCHEMA_URL,
    PLUGIN_SCHEMA_URL,
    bundle_is_agent_plugin,
    parse_agent_plugin,
    validate_agent_plugin_name,
)
from thomas.server.agent_plugins_surface import about_surface_html
from thomas.tools.mcp_registry import _load_rows, registry_store_path


def _zip_bytes(files: dict[str, str], *, prefix: str = "", dir_entries: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if dir_entries and prefix:
            # Real GitHub archives carry explicit directory entries.
            archive.writestr(prefix, "")
        for name, content in files.items():
            archive.writestr(f"{prefix}{name}", content)
    return buffer.getvalue()


def _plugin_files(
    *, name: str = "demo-plugin", with_skill: bool = True, with_mcp: bool = True
) -> dict[str, str]:
    files = {
        "plugin.json": json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_URL,
                "name": name,
                "version": "1.2.3",
                "description": "A demo community plugin.",
                "author": {"name": "Random GitHub Person"},
            }
        )
    }
    if with_skill:
        files["skills/hello-notes/SKILL.md"] = (
            "---\nname: hello-notes\ndescription: Says hello to notes.\n---\n\nBody.\n"
        )
    if with_mcp:
        files["mcp.json"] = json.dumps(
            {
                "$schema": MCP_SCHEMA_URL,
                "mcpServers": {
                    "notes": {
                        "type": "stdio",
                        "command": "${PLUGIN_ROOT}/bin/runner",
                        "args": ["${PLUGIN_ROOT}/server.js"],
                        "env": {"NOTES_DATA": "${PLUGIN_DATA}"},
                    }
                },
            }
        )
        files["server.js"] = "// entry\n"
    return files


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(memory=MemoryConfig(root=str(tmp_path / "memory")))


@pytest.fixture()
def skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "user-skills"
    monkeypatch.setattr(adapter, "_user_skills_root", lambda: root)
    return root


def test_detection_prefers_the_signed_path() -> None:
    assert bundle_is_agent_plugin(_zip_bytes(_plugin_files()))
    assert bundle_is_agent_plugin(_zip_bytes(_plugin_files(), prefix="repo-main/"))
    with_manifest = _plugin_files()
    with_manifest["manifest.json"] = "{}"
    assert not bundle_is_agent_plugin(_zip_bytes(with_manifest))
    assert not bundle_is_agent_plugin(b"not a zip at all")
    assert not bundle_is_agent_plugin(_zip_bytes({"readme.md": "hi"}))


def test_detection_survives_github_directory_entries() -> None:
    """GitHub Download-ZIP archives include an explicit 'repo-main/' directory
    entry; it must not count as a top-level file and defeat detection."""
    assert bundle_is_agent_plugin(
        _zip_bytes(_plugin_files(), prefix="repo-main/", dir_entries=True)
    )
    signed = _plugin_files()
    signed["manifest.json"] = "{}"
    assert not bundle_is_agent_plugin(_zip_bytes(signed, prefix="repo-main/", dir_entries=True))


def test_name_rules() -> None:
    assert validate_agent_plugin_name("good-name.v2") == "good-name.v2"
    for bad in ("", "-lead", "trail-", "UPPER", "a--b", "a..b", "a" * 65):
        with pytest.raises(ValueError):
            validate_agent_plugin_name(bad)


def test_parse_rejects_wrong_schema_and_empty_plugins(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"$schema": "https://example.com/other.json", "name": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema"):
        parse_agent_plugin(root)

    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_URL, "name": "empty-plugin"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no installable components"):
        parse_agent_plugin(root)


def test_install_registers_the_unverified_tier(config: AppConfig, skills_root: Path) -> None:
    record = adapter.install_agent_plugin_bytes(
        config, _zip_bytes(_plugin_files()), source={"type": "test"}
    )

    # The adapter returns the NORMALIZED record — the same shape the signed
    # installer returns, so /api/marketplace/import has one contract.
    assert record["plugin_id"] == "demo-plugin"
    assert record["verified"] is False
    assert record["installed"] is True
    assert record["surface_url"], "normalized records carry the surface url"
    assert "source" not in record or "path" not in str(record.get("source"))
    assert record["agent_plugin"]["skills"] == ["hello-notes"]
    assert record["agent_plugin"]["mcp_servers"] == ["demo-plugin--notes"]

    plugin_dir = Path(config.memory.root_path) / ".thomas" / "plugins" / "demo-plugin"
    assert (plugin_dir / "web" / "about.html").is_file()
    manifest = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "desktop_plugin"
    assert manifest["signature"] == "unverified-community"

    skill_dir = skills_root / "hello-notes"
    assert (skill_dir / "SKILL.md").is_file()
    sidecar = json.loads((skill_dir / "THOMAS_SKILL.json").read_text(encoding="utf-8"))
    assert sidecar["source_plugin"] == "demo-plugin"

    # The MCP store keeps its canonical {"servers": [...]} envelope and the
    # canonical reader can see the row.
    store = json.loads(registry_store_path(config).read_text(encoding="utf-8"))
    assert isinstance(store, dict) and isinstance(store.get("servers"), list)
    (row,) = [r for r in _load_rows(registry_store_path(config)) if r["name"] == "demo-plugin--notes"]
    assert row["enabled"] is False, "community MCP servers must not auto-run"
    assert row["verified"] is False
    assert row["source_plugin"] == "demo-plugin"
    # Placeholder expansion is textual per the spec, so joined paths may mix
    # separators on Windows; compare resolved paths instead.
    assert Path(row["command"]) == plugin_dir / "bin" / "runner"
    assert Path(row["args"][0]) == plugin_dir / "server.js"
    assert "${PLUGIN_DATA}" not in row["env"]["NOTES_DATA"]
    assert ".plugin-data" in row["env"]["NOTES_DATA"]


def test_install_preserves_existing_mcp_servers(config: AppConfig, skills_root: Path) -> None:
    """Installing a community plugin must never clobber servers the owner
    registered before it (the store is shared)."""
    from thomas.tools.mcp_registry import _save_rows

    path = registry_store_path(config)
    _save_rows(path, [{"name": "owner-server", "transport": "stdio", "command": "srv", "enabled": True}])

    adapter.install_agent_plugin_bytes(config, _zip_bytes(_plugin_files()), source={"type": "test"})

    names = {r["name"] for r in _load_rows(path)}
    assert names == {"owner-server", "demo-plugin--notes"}


def test_reinstall_cleans_up_what_the_old_version_added(
    config: AppConfig, skills_root: Path
) -> None:
    """v2 drops a skill v1 shipped: the dropped skill must not outlive v1
    (uninstall only ever sees the latest record)."""
    v1 = _plugin_files()
    v1["skills/old-skill/SKILL.md"] = "---\nname: old-skill\n---\nOld.\n"
    adapter.install_agent_plugin_bytes(config, _zip_bytes(v1), source={"type": "test"})
    assert (skills_root / "old-skill").is_dir()

    adapter.install_agent_plugin_bytes(config, _zip_bytes(_plugin_files()), source={"type": "test"})

    assert not (skills_root / "old-skill").exists(), "reinstall must clean dropped extras"
    assert (skills_root / "hello-notes").is_dir()
    rows = [r for r in _load_rows(registry_store_path(config)) if r.get("source_plugin") == "demo-plugin"]
    assert [r["name"] for r in rows] == ["demo-plugin--notes"]


def test_skill_collision_prefixes_instead_of_overwriting(
    config: AppConfig, skills_root: Path
) -> None:
    foreign = skills_root / "hello-notes"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("---\nname: hello-notes\n---\nForeign.\n", encoding="utf-8")

    record = adapter.install_agent_plugin_bytes(
        config, _zip_bytes(_plugin_files()), source={"type": "test"}
    )

    assert record["agent_plugin"]["skills"] == ["demo-plugin--hello-notes"]
    assert (foreign / "SKILL.md").read_text(encoding="utf-8").endswith("Foreign.\n")
    assert (skills_root / "demo-plugin--hello-notes" / "SKILL.md").is_file()


def test_cleanup_removes_exactly_what_install_added(
    config: AppConfig, skills_root: Path
) -> None:
    record = adapter.install_agent_plugin_bytes(
        config, _zip_bytes(_plugin_files()), source={"type": "test"}
    )
    foreign = skills_root / "unrelated"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("---\nname: unrelated\n---\n", encoding="utf-8")

    adapter.cleanup_agent_plugin_extras(config, record)

    assert not (skills_root / "hello-notes").exists()
    assert foreign.is_dir(), "cleanup must not touch skills it did not install"
    assert not [
        r for r in _load_rows(registry_store_path(config)) if r.get("source_plugin") == "demo-plugin"
    ]
    assert not adapter._plugin_data_dir(config, "demo-plugin").exists()


def test_data_dir_namespace_is_disjoint_from_plugin_ids(config: AppConfig) -> None:
    """A plugin literally named '<other>.data' must not collide with another
    plugin's data directory (the name grammar permits dots)."""
    data_dir = adapter._plugin_data_dir(config, "notes")
    plugins_root = adapter._installed_plugins_root(config)
    assert data_dir != plugins_root / "notes.data"
    assert data_dir.parent.name == ".plugin-data"


def test_about_surface_neutralizes_hostile_homepage() -> None:
    from thomas.server.agent_plugins_manifest import AgentPluginInfo

    hostile = AgentPluginInfo(
        name="evil",
        version="1.0.0",
        description='desc" onmouseover="alert(1)',
        author_name="x",
        homepage='https://x.example/" onmouseover="alert(1)',
        skills=["a"],
    )
    html = about_surface_html(hostile)
    # No raw double quote from plugin.json may survive into markup, so an
    # attribute breakout like onmouseover="..." cannot form.
    assert 'onmouseover="alert' not in html
    assert "&quot;" in html  # the quotes were escaped, not dropped

    no_link = AgentPluginInfo(
        name="evil2",
        version="1.0.0",
        description="d",
        author_name="x",
        homepage="javascript:alert(1)",
        skills=["a"],
    )
    assert "<a " not in about_surface_html(no_link)


def test_traversal_paths_are_rejected(config: AppConfig, skills_root: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps({"$schema": PLUGIN_SCHEMA_URL, "name": "evil"}))
        archive.writestr("skills/x/SKILL.md", "---\nname: x\n---\n")
        archive.writestr("../escape.txt", "boom")
    with pytest.raises(ValueError):
        adapter.install_agent_plugin_bytes(config, buffer.getvalue(), source={"type": "test"})
