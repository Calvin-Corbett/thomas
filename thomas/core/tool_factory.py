"""
thomas/core/tool_factory.py
───────────────────────────
Reusable Tool Factory for explicitly supplied structured tool definitions.

Two layers:
  1. GeneratedTool — stores name, description, JSON schema, Python implementation.
  2. ToolFactory    — manages the on-disk JSON registry and registers
                      live Tool instances into the existing ToolRegistry.

Usage:
    from thomas.core.tool_factory import get_tool_factory
    factory = get_tool_factory()
    factory.register_tool(GeneratedTool(
        name="git.stash_and_pull",
        description="Stash current changes, pull latest, then unstash.",
        parameters={"type": "object", "properties": {}, "required": []},
        implementation="async def git_stash_and_pull(**kwargs): ...",
    ))
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REGISTRY_FILE = Path("thomas_tool_registry.json")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GeneratedTool:
    """An explicitly authored tool definition serialised for reuse."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    implementation: str  # Full Python source as string
    category: str = "generated"
    created_from: str = ""  # brief description of originating task
    usage_count: int = 0
    last_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GeneratedTool:
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            parameters=d.get("parameters", {"type": "object", "properties": {}}),
            implementation=d.get("implementation", ""),
            category=d.get("category", "generated"),
            created_from=d.get("created_from", ""),
            usage_count=d.get("usage_count", 0),
            last_used=d.get("last_used", ""),
        )

    def to_openai_spec(self) -> dict[str, Any]:
        """Return an OpenAI-compatible function spec for use in LLM calls."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class ToolFactory:
    """
    Stores and registers explicitly authored reusable tools.

    Flow:
      GeneratedTool  →  save_registry()
                        (JSON on disk)

    The JSON registry at thomas_tool_registry.json survives restarts.
    """

    def __init__(
        self,
        registry_file: Path | None = None,
        live_registry: Any = None,
    ) -> None:
        # Retained for call compatibility. Core no longer imports or adapts
        # runtime tools; a tools-layer caller owns executable registration.
        del live_registry
        self.registry_file = Path(registry_file or _REGISTRY_FILE)
        self._lock = threading.Lock()
        self._tools: dict[str, GeneratedTool] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> int:
        """Load persisted tools from disk. Returns count loaded."""
        if not self.registry_file.exists():
            return 0
        try:
            raw = json.loads(self.registry_file.read_text(encoding="utf-8"))
            with self._lock:
                self._tools = {name: GeneratedTool.from_dict(spec) for name, spec in raw.get("tools", {}).items()}
            log.info("ToolFactory: loaded %d tools from %s", len(self._tools), self.registry_file)
            return len(self._tools)
        except (OSError, TypeError, ValueError, KeyError) as e:
            log.warning("ToolFactory: failed to load registry: %s", e)
            return 0

    def save_registry(self) -> bool:
        """Flush the generated tool registry to disk."""
        try:
            with self._lock:
                payload = {
                    "version": 1,
                    "tools": {name: t.to_dict() for name, t in self._tools.items()},
                }
            self.registry_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except (OSError, TypeError, ValueError) as e:
            log.error("ToolFactory: save failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_tool(self, tool: GeneratedTool, overwrite: bool = False) -> bool:
        """Add an explicit GeneratedTool definition and persist the registry."""
        safe_name = _safe_tool_name(tool.name)
        with self._lock:
            if safe_name in self._tools and not overwrite:
                log.debug("ToolFactory: tool %r already registered (skip).", safe_name)
                return False
            tool.name = safe_name
            self._tools[safe_name] = tool
        self.save_registry()
        log.info("ToolFactory: registered tool %r (%s).", safe_name, tool.category)
        return True

    def get(self, name: str) -> GeneratedTool | None:
        with self._lock:
            return self._tools.get(_safe_tool_name(name))

    def list_tools(self, category: str | None = None) -> list[GeneratedTool]:
        with self._lock:
            tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return sorted(tools, key=lambda t: t.name)

    def increment_usage(self, name: str) -> None:
        """Call this whenever a generated tool is successfully used."""
        from datetime import datetime, timezone

        with self._lock:
            t = self._tools.get(_safe_tool_name(name))
            if t:
                t.usage_count += 1
                t.last_used = datetime.now(timezone.utc).isoformat()
        self.save_registry()

    def summary_text(self) -> str:
        with self._lock:
            tools = list(self._tools.values())
        if not tools:
            return "Tool factory: 0 generated tools."
        top = sorted(tools, key=lambda t: t.usage_count, reverse=True)[:5]
        lines = [f"Tool factory: {len(tools)} generated tools."]
        lines.append("Top by usage:")
        for t in top:
            lines.append(f"  - {t.name} (used {t.usage_count}x): {t.description[:60]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live Tool wrapper — wraps a GeneratedTool as a callable Tool instance
# ---------------------------------------------------------------------------


def _safe_tool_name(name: str) -> str:
    """Normalize an explicitly supplied structured tool name."""
    normalized = re.sub(r"[^a-z0-9.]+", "_", str(name or "").strip().lower())
    return normalized.strip("_.")[:64]


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_factory: ToolFactory | None = None
_factory_lock = threading.Lock()


def get_tool_factory(live_registry: Any = None) -> ToolFactory:
    """Return the process-level ToolFactory, loading from disk on first call."""
    global _factory
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                _factory = ToolFactory(live_registry=live_registry)
                _factory.load()
    elif live_registry is not None:
        log.debug("ToolFactory ignores live_registry; executable registration belongs to thomas.tools.")
    return _factory
