"""Install Agent Plugins (agent-plugins.org 1.0.0) into the Thomas runtime.

Maps the standard's two component types onto machinery Thomas already has:
the plugin tree installs beside desktop plugins through the SAME
installed-record pipeline (a manifest is synthesized and run through the
real validator), skills are copied into the always-discovered user skills
root with a provenance sidecar, and MCP servers are registered DISABLED
with provenance — an Agent Plugin carries no signature, so nothing it
ships may run until the owner enables it.

Trust model: every Agent Plugin install is the UNVERIFIED community tier
(``signature: "unverified-community"``, ``verified: False``). Verified
remains the signed desktop-plugin pipeline only, which is untouched.
Detection/validation lives in ``agent_plugins_manifest``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.server.agent_plugins_manifest import (
    UNVERIFIED_SIGNATURE,
    AgentPluginInfo,
    detect_agent_plugin_root,
    parse_agent_plugin,
)
from thomas.server.agent_plugins_surface import about_surface_html
from thomas.server.desktop_plugins_manifest import (
    _safe_text,
    _utc_now_iso,
    load_desktop_plugin_manifest_from_data,
)
from thomas.server.desktop_plugins_runtime import (
    _build_installed_record,
    _copy_plugin_tree,
    _extract_bundle_zip,
    _installed_plugin_dir,
    _installed_plugins_root,
    _normalize_installed_record,
    _replace_installed_record,
    _write_json_file,
    get_installed_plugin,
)
from thomas.tools.mcp_registry import (
    _load_rows,
    _save_rows,
    _utc_iso,
    registry_store_path,
)

log = logging.getLogger(__name__)


def _expand_placeholders(value: str, *, plugin_root: Path, plugin_data: Path) -> str:
    return value.replace("${PLUGIN_ROOT}", str(plugin_root)).replace(
        "${PLUGIN_DATA}", str(plugin_data)
    )


def _user_skills_root() -> Path:
    return Path.home() / ".thomas" / "skills"


def _plugin_data_dir(config: AppConfig, name: str) -> Path:
    # ".plugin-data" can never equal a plugin id (ids start alphanumeric),
    # so a plugin literally named "<other>.data" cannot collide with another
    # plugin's data directory.
    return _installed_plugins_root(config) / ".plugin-data" / name


def _install_skills(plugin_dir: Path, info: AgentPluginInfo) -> list[str]:
    """Copy each skill into the user skills root with a provenance sidecar.
    On a name collision with a skill we did not install, the copy is prefixed
    with the plugin name instead of overwriting someone else's skill."""
    installed: list[str] = []
    root = _user_skills_root()
    root.mkdir(parents=True, exist_ok=True)
    for skill_name in info.skills:
        source = plugin_dir / "skills" / skill_name
        target_name = skill_name
        target = root / target_name
        if target.exists() and not _sidecar_owned_by(target, info.name):
            target_name = f"{info.name}--{skill_name}"
            target = root / target_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        _write_json_file(
            target / "THOMAS_SKILL.json",
            {
                "source": "agent-plugin",
                "source_plugin": info.name,
                "installed_at": _utc_now_iso(),
            },
        )
        installed.append(target_name)
    return installed


def _sidecar_owned_by(skill_dir: Path, plugin_name: str) -> bool:
    try:
        payload = json.loads((skill_dir / "THOMAS_SKILL.json").read_text(encoding="utf-8"))
        return payload.get("source_plugin") == plugin_name
    except (OSError, ValueError):
        return False


def _register_mcp_servers(
    config: AppConfig, plugin_dir: Path, info: AgentPluginInfo
) -> list[str]:
    """Register the plugin's MCP servers DISABLED with provenance. An Agent
    Plugin is unverified by definition, so nothing it ships may launch until
    the owner flips the server on. Rows go through the canonical registry
    load/save helpers so the store keeps its {"servers": [...]} envelope."""
    if not info.mcp_servers:
        return []
    plugin_data = _plugin_data_dir(config, info.name)
    plugin_data.mkdir(parents=True, exist_ok=True)
    path = registry_store_path(config)
    rows = _load_rows(path)

    def expand(value: str) -> str:
        return _expand_placeholders(value, plugin_root=plugin_dir, plugin_data=plugin_data)

    now = _utc_iso()
    registered: list[str] = []
    for server_name, cfg in info.mcp_servers.items():
        row_name = f"{info.name}--{server_name}"
        row: dict[str, Any] = {
            "name": row_name,
            "transport": _safe_text(cfg.get("type")) or "stdio",
            "command": expand(_safe_text(cfg.get("command"))),
            "args": [expand(_safe_text(a)) for a in cfg.get("args", []) if _safe_text(a)],
            "url": _safe_text(cfg.get("url")),
            "env": {
                _safe_text(k): expand(_safe_text(v))
                for k, v in (cfg.get("env") or {}).items()
                if _safe_text(k)
            },
            "enabled": False,
            "source": "agent-plugin",
            "source_plugin": info.name,
            "verified": False,
            "created_at": now,
            "updated_at": now,
        }
        cwd = _safe_text(cfg.get("cwd"))
        if cwd:
            row["cwd"] = expand(cwd)
        rows = [r for r in rows if _safe_text(r.get("name")) != row_name]
        rows.append(row)
        registered.append(row_name)

    _save_rows(path, rows)
    return registered


def _synthesize_manifest(info: AgentPluginInfo) -> dict[str, Any]:
    capabilities = ["agent-plugin"]
    if info.skills:
        capabilities.append("skills")
    if info.mcp_servers:
        capabilities.append("mcp-servers")
    return {
        "kind": "desktop_plugin",
        "plugin_id": info.name,
        "display_name": info.name,
        "version": info.version,
        "publisher_id": "community",
        "publisher_name": info.author_name or "Community (unverified)",
        "marketplace_type": "plugin",
        "mode_id": "agent_plugin_" + info.name.replace("-", "_").replace(".", "_"),
        "description": info.description or "Agent Plugin (community standard bundle).",
        "subtitle": "Agent Plugin — community, unverified",
        "capabilities": capabilities,
        "categories": ["community"],
        "tags": ["agent-plugin"],
        "left_nav_behavior": "none",
        "surface": {"entry_html": "web/about.html", "title": info.name, "surface_mode": "immersive"},
        "signature": UNVERIFIED_SIGNATURE,
        "agent_plugin_standard": "1.0.0",
    }


def install_agent_plugin_bytes(
    config: AppConfig, bundle_bytes: bytes, *, source: dict[str, Any]
) -> dict[str, Any]:
    """Install an Agent Plugins 1.0.0 bundle and return the normalized
    installed record (the same shape the signed installer returns). Raises
    ValueError when the bundle is not a valid Agent Plugin."""
    actual_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    plugins_root = _installed_plugins_root(config)
    plugins_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(plugins_root.parent)) as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        _extract_bundle_zip(bundle_bytes, tmp_dir)

        plugin_root = detect_agent_plugin_root(tmp_dir)
        if plugin_root is None:
            raise ValueError("Bundle is not an Agent Plugin (no plugin.json)")
        info = parse_agent_plugin(plugin_root)

        # A reinstall must not orphan extras the previous version added:
        # skills or MCP servers dropped between versions would otherwise
        # outlive the plugin forever (uninstall only sees the latest record).
        previous = get_installed_plugin(config, info.name)
        if isinstance(previous, dict) and previous.get("agent_plugin"):
            cleanup_agent_plugin_extras(config, previous)

        # The about surface must exist before the manifest validator runs.
        web_dir = plugin_root / "web"
        web_dir.mkdir(exist_ok=True)
        (web_dir / "about.html").write_text(about_surface_html(info), encoding="utf-8")

        manifest_data = _synthesize_manifest(info)
        manifest = load_desktop_plugin_manifest_from_data(
            manifest_data, plugin_dir=plugin_root, require_signature=False
        )

        destination_dir = _installed_plugin_dir(config, manifest.plugin_id)
        _copy_plugin_tree(plugin_root, destination_dir)
        manifest_payload = dict(manifest_data)
        manifest_payload["sha256"] = actual_sha256
        _write_json_file(destination_dir / "manifest.json", manifest_payload)

        installed_skills = _install_skills(destination_dir, info)
        registered_servers = _register_mcp_servers(config, destination_dir, info)

        record = _build_installed_record(manifest, actual_sha256=actual_sha256, source=source)
        record["verified"] = False
        record["agent_plugin"] = {
            "standard": "1.0.0",
            "skills": installed_skills,
            "mcp_servers": registered_servers,
        }
        _replace_installed_record(config, record)
        log.info(
            "Installed Agent Plugin '%s' (skills=%d, mcp_servers=%d, unverified)",
            info.name,
            len(installed_skills),
            len(registered_servers),
        )
        return _normalize_installed_record(record)


def cleanup_agent_plugin_extras(config: AppConfig, record: dict[str, Any]) -> None:
    """Undo what install added outside the plugin directory: skills copies
    (only when the provenance sidecar names this plugin) and MCP rows."""
    extras = record.get("agent_plugin") if isinstance(record, dict) else None
    if not isinstance(extras, dict):
        return
    plugin_id = _safe_text(record.get("plugin_id"))

    root = _user_skills_root()
    for skill_name in extras.get("skills", []) or []:
        target = root / _safe_text(skill_name)
        if target.is_dir() and _sidecar_owned_by(target, plugin_id):
            shutil.rmtree(target, ignore_errors=True)

    server_names = {_safe_text(n) for n in (extras.get("mcp_servers") or []) if _safe_text(n)}
    if server_names:
        path = registry_store_path(config)
        rows = _load_rows(path)
        kept = [
            r
            for r in rows
            if not (
                _safe_text(r.get("name")) in server_names
                and _safe_text(r.get("source_plugin")) == plugin_id
            )
        ]
        if len(kept) != len(rows):
            _save_rows(path, kept)

    data_dir = _plugin_data_dir(config, plugin_id)
    if data_dir.is_dir():
        shutil.rmtree(data_dir, ignore_errors=True)
