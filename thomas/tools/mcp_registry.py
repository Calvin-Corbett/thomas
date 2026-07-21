"""Searchable MCP catalog with one-step install and task-triggered suggestions.

This is the discovery layer that sits above CAP-067's executable MCP client
(``thomas/tools/mcp_client.py``) and the compat server-metadata store
(``thomas/cli/compat_mcp.py`` -> ``thomas/cli/parity_support.py``).

It provides:

- :data:`CATALOG` -- a bundled, curated set of well-known stdio MCP servers as
  static in-module data (no network). Each entry carries a runnable
  ``command``/``args`` template so an installed server is immediately usable.
- :func:`search` -- rank catalog entries by keyword / description overlap with
  a free-text query.
- :func:`suggest_for_task` -- given a task string, return catalog entries whose
  names / keywords / categories match the task (and nothing for an unrelated
  task).
- :func:`install` -- write a chosen catalog entry into the *same* server
  metadata store the CAP-067 client reads, using the identical row schema
  (``name/transport/command/args/url/env/enabled/created_at/updated_at``), so
  the installed server round-trips through ``mcp add``/``mcp list`` and can be
  launched by :func:`thomas.tools.mcp_client.client_from_server_row`. Install is
  idempotent and returns the stored row.

Layering: tools tier. Imports only stdlib + ``thomas.core.config`` (tools may
import core). The compat persistence helpers live in the cli tier, so the small
path/read/write logic is replicated locally rather than imported upward. The
store path is derived identically to ``thomas.cli.parity_support`` (config
``memory.root_path`` / ``.thomas`` / ``cli`` / ``mcp_servers.json``); the
``THOMAS_MCP_REGISTRY_PATH`` environment variable overrides it for tests and
explicit deployments.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig

REGISTRY_PATH_ENV = "THOMAS_MCP_REGISTRY_PATH"

# Tokens too generic to carry intent; ignored when matching queries/tasks.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "with",
        "in",
        "on",
        "my",
        "me",
        "please",
        "can",
        "you",
        "i",
        "want",
        "need",
        "help",
        "some",
        "this",
        "that",
        "it",
        "is",
        "are",
        "be",
        "do",
        "get",
        "use",
        "using",
        "from",
        "into",
        "about",
        "at",
        "as",
        "by",
        "so",
        "then",
        "over",
        "up",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class McpRegistryError(Exception):
    """Raised when the registry cannot resolve a store path or catalog entry."""


@dataclass(frozen=True)
class CatalogEntry:
    """A curated, well-known MCP server available for one-step install."""

    name: str
    description: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    homepage: str = ""
    transport: str = "stdio"

    def to_server_row(self, *, timestamp: str) -> dict[str, Any]:
        """Render this entry as a compat ``mcp add`` metadata row."""
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": [str(x) for x in self.args],
            "url": "",
            "env": {str(k): str(v) for k, v in self.env.items()},
            "enabled": True,
            "source": "catalog",
            "homepage": self.homepage,
            "created_at": timestamp,
            "updated_at": timestamp,
        }


# --- Bundled curated catalog (static, no network) -----------------------------
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        name="filesystem",
        description="Read, write, and list files and directories on local disk.",
        categories=("files", "storage"),
        keywords=("file", "files", "filesystem", "directory", "folder", "disk", "read", "write", "path"),
        command="npx",
        args=("-y", "@modelcontextprotocol/server-filesystem", "."),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogEntry(
        name="git",
        description="Inspect and operate a Git repository: status, diff, log, commit, branches.",
        categories=("git", "vcs"),
        keywords=("git", "repository", "repo", "commit", "diff", "branch", "merge", "version", "control", "log"),
        command="uvx",
        args=("mcp-server-git",),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogEntry(
        name="sqlite",
        description="Query and modify a local SQLite relational database with SQL.",
        categories=("database", "sql"),
        keywords=("sqlite", "database", "db", "sql", "query", "relational", "table", "rows", "schema"),
        command="uvx",
        args=("mcp-server-sqlite", "--db-path", "./data.db"),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogEntry(
        name="fetch",
        description="Fetch a URL over HTTP and return the page content as text or markdown.",
        categories=("web", "http"),
        keywords=("fetch", "http", "https", "web", "url", "download", "scrape", "page", "website", "internet"),
        command="uvx",
        args=("mcp-server-fetch",),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogEntry(
        name="memory",
        description="Persistent knowledge-graph memory: remember entities, relations, and notes.",
        categories=("memory", "knowledge"),
        keywords=("memory", "remember", "recall", "notes", "knowledge", "graph", "entities", "facts"),
        command="npx",
        args=("-y", "@modelcontextprotocol/server-memory"),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogEntry(
        name="time",
        description="Get the current time and convert between time zones.",
        categories=("time", "utility"),
        keywords=("time", "clock", "timezone", "date", "convert", "utc", "schedule"),
        command="uvx",
        args=("mcp-server-time",),
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
)

_CATALOG_BY_NAME: dict[str, CatalogEntry] = {entry.name: entry for entry in CATALOG}


def catalog() -> tuple[CatalogEntry, ...]:
    """Return the bundled catalog entries."""
    return CATALOG


def get_entry(name: str) -> CatalogEntry | None:
    """Return the catalog entry with ``name`` (case-insensitive), or ``None``."""
    return _CATALOG_BY_NAME.get(str(name or "").strip().lower())


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(str(text or "").lower()) if tok not in _STOPWORDS and len(tok) > 1]


def _label_tokens(entry: CatalogEntry) -> set[str]:
    """Tokens drawn from an entry's name, keywords, and categories (not description)."""
    tokens: set[str] = {entry.name}
    for label in (*entry.keywords, *entry.categories):
        tokens.update(_tokenize(label))
    return tokens


def _score(entry: CatalogEntry, query_tokens: list[str], *, include_description: bool) -> int:
    """Weighted overlap score for ``entry`` against ``query_tokens``."""
    if not query_tokens:
        return 0
    label_tokens = _label_tokens(entry)
    desc_tokens = set(_tokenize(entry.description)) if include_description else set()
    score = 0
    for token in query_tokens:
        if token == entry.name:
            score += 6
        elif token in label_tokens:
            score += 3
        elif token in desc_tokens:
            score += 1
    return score


def search(query: str, *, limit: int = 0) -> list[CatalogEntry]:
    """Rank catalog entries by relevance to ``query`` (highest first).

    Matches name/keywords/categories strongly and description weakly. Entries
    with no overlap are excluded. Ties break alphabetically by name for
    determinism. ``limit`` (> 0) caps the number of results.
    """
    query_tokens = _tokenize(query)
    scored = [(entry, _score(entry, query_tokens, include_description=True)) for entry in CATALOG]
    ranked = sorted(
        (pair for pair in scored if pair[1] > 0),
        key=lambda pair: (-pair[1], pair[0].name),
    )
    entries = [entry for entry, _ in ranked]
    if limit and limit > 0:
        return entries[:limit]
    return entries


def suggest_for_task(task_text: str, *, limit: int = 3) -> list[CatalogEntry]:
    """Suggest catalog servers relevant to a free-text task description.

    Matches on names/keywords/categories only (not description) so that a task
    which merely happens to share a common word with a description does not
    trigger a spurious suggestion. Returns an empty list for an unrelated task.
    """
    task_tokens = _tokenize(task_text)
    scored = [(entry, _score(entry, task_tokens, include_description=False)) for entry in CATALOG]
    ranked = sorted(
        (pair for pair in scored if pair[1] > 0),
        key=lambda pair: (-pair[1], pair[0].name),
    )
    entries = [entry for entry, _ in ranked]
    if limit and limit > 0:
        return entries[:limit]
    return entries


# --- Persistence (mirrors thomas.cli.parity_support schema) -------------------
def registry_store_path(config: AppConfig | None = None) -> Path:
    """Resolve the MCP server-metadata store path.

    ``THOMAS_MCP_REGISTRY_PATH`` wins when set; otherwise the path is derived
    from ``config`` exactly as the compat CLI does. Raises when neither is
    available.
    """
    override = os.environ.get(REGISTRY_PATH_ENV)
    if override and override.strip():
        return Path(override.strip())
    if config is not None:
        return config.memory.root_path / ".thomas" / "cli" / "mcp_servers.json"
    raise McpRegistryError(f"no registry path: set {REGISTRY_PATH_ENV} or pass a config")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("servers")
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"servers": rows, "updated_at": _utc_iso()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _find_row(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = str(name or "").strip().lower()
    for row in rows:
        if str((row or {}).get("name") or "").strip().lower() == target:
            return row
    return None


def install(name: str, *, config: AppConfig | None = None) -> dict[str, Any]:
    """Install a catalog server into the compat metadata store (idempotent).

    Writes the chosen catalog entry as a compat ``mcp add`` row so the CAP-067
    client can launch it immediately. Re-installing the same server updates the
    existing row in place (preserving its original ``created_at``) rather than
    appending a duplicate. Returns the stored row.
    """
    entry = get_entry(name)
    if entry is None:
        available = ", ".join(sorted(_CATALOG_BY_NAME))
        raise McpRegistryError(f"unknown catalog server {name!r}; available: {available}")

    path = registry_store_path(config)
    rows = _load_rows(path)
    now = _utc_iso()
    new_row = entry.to_server_row(timestamp=now)

    existing = _find_row(rows, entry.name)
    if existing is None:
        rows.append(new_row)
        stored = new_row
    else:
        created_at = existing.get("created_at") or now
        existing.update(new_row)
        existing["created_at"] = created_at
        existing["updated_at"] = now
        stored = existing
    _save_rows(path, rows)
    return stored
