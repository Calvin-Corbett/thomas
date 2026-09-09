"""Parse and validate Agent Plugins (agent-plugins.org 1.0.0) bundles.

The open standard packages exactly two component types: Agent Skills
(``skills/<name>/SKILL.md`` — the same format Thomas's resolver already
speaks) and MCP servers (``mcp.json`` at the plugin root). This module owns
detection and validation; ``agent_plugins_adapter`` owns installation.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLUGIN_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
UNVERIFIED_SIGNATURE = "unverified-community"

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_MCP_TRANSPORTS = {"stdio", "streamable-http", "sse"}


def _safe_text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


@dataclass
class AgentPluginInfo:
    name: str
    version: str
    description: str
    author_name: str
    homepage: str
    skills: list[str] = field(default_factory=list)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)


def validate_agent_plugin_name(name: str) -> str:
    if not (1 <= len(name) <= 64):
        raise ValueError("Agent Plugin name must be 1-64 characters")
    if not _NAME_RE.match(name) or "--" in name or ".." in name:
        raise ValueError(
            "Agent Plugin name must be lowercase alphanumeric with single '-' or '.' separators"
        )
    return name


def detect_agent_plugin_root(extract_root: Path) -> Path | None:
    """A bundle is an Agent Plugin when plugin.json sits at the root or inside
    exactly one top-level directory (the GitHub archive shape). A bundle that
    also carries a Thomas manifest.json is NOT claimed by this adapter — the
    signed desktop-plugin path always wins."""
    for candidate in _candidate_roots(extract_root):
        if (candidate / "manifest.json").exists():
            return None
        if (candidate / "plugin.json").exists():
            return candidate
    return None


def _candidate_roots(extract_root: Path) -> list[Path]:
    roots = [extract_root]
    children = [child for child in extract_root.iterdir() if child.is_dir()]
    if len(children) == 1 and not any(item.is_file() for item in extract_root.iterdir()):
        roots.append(children[0])
    return roots


def bundle_is_agent_plugin(bundle_bytes: bytes) -> bool:
    """Cheap detection from the zip listing only — no extraction."""
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
    except (zipfile.BadZipFile, OSError):
        return False
    roots = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
    # Top-level FILES only: GitHub archives carry an explicit "repo-main/"
    # directory entry, which must not defeat the single-nested-root branch.
    tops = {n for n in names if not n.endswith("/") and "/" not in n}
    if "manifest.json" in tops:
        return False
    if "plugin.json" in tops:
        return True
    if len(roots) == 1 and not tops:
        prefix = next(iter(roots))
        if f"{prefix}/manifest.json" in names:
            return False
        return f"{prefix}/plugin.json" in names
    return False


def parse_agent_plugin(plugin_root: Path) -> AgentPluginInfo:
    manifest_path = plugin_root / "plugin.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"plugin.json is unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("plugin.json must be a JSON object")
    schema = _safe_text(data.get("$schema"))
    if schema != PLUGIN_SCHEMA_URL:
        raise ValueError(
            f"plugin.json $schema must be {PLUGIN_SCHEMA_URL} (got {schema or 'nothing'})"
        )
    name = validate_agent_plugin_name(_safe_text(data.get("name")))

    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    info = AgentPluginInfo(
        name=name,
        version=_safe_text(data.get("version")) or "0.0.0",
        description=_safe_text(data.get("description")),
        author_name=_safe_text(author.get("name")),
        homepage=_safe_text(data.get("homepage")),
    )

    skills_dir = plugin_root / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                info.skills.append(child.name)

    mcp_path = plugin_root / "mcp.json"
    if mcp_path.is_file():
        info.mcp_servers = _parse_mcp_config(mcp_path)

    if not info.skills and not info.mcp_servers:
        raise ValueError(
            "Agent Plugin has no installable components (no skills/ and no mcp.json)"
        )
    return info


def _parse_mcp_config(mcp_path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"mcp.json is unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("mcp.json must be a JSON object")
    if _safe_text(data.get("$schema")) != MCP_SCHEMA_URL:
        raise ValueError(f"mcp.json $schema must be {MCP_SCHEMA_URL}")
    servers_raw = data.get("mcpServers")
    if not isinstance(servers_raw, dict) or not servers_raw:
        raise ValueError("mcp.json must declare a non-empty mcpServers object")
    servers: dict[str, dict[str, Any]] = {}
    for raw_name, raw_cfg in servers_raw.items():
        server_name = _safe_text(raw_name)
        if not server_name or not isinstance(raw_cfg, dict):
            raise ValueError("mcp.json server entries must be named objects")
        transport = _safe_text(raw_cfg.get("type")) or "stdio"
        if transport not in _MCP_TRANSPORTS:
            raise ValueError(f"mcp.json server '{server_name}' has unknown type '{transport}'")
        if transport == "stdio":
            if not _safe_text(raw_cfg.get("command")):
                raise ValueError(f"mcp.json stdio server '{server_name}' needs a command")
        elif not _safe_text(raw_cfg.get("url")):
            raise ValueError(f"mcp.json {transport} server '{server_name}' needs a url")
        servers[server_name] = dict(raw_cfg)
    return servers
