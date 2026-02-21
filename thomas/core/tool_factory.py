"""
thomas/core/tool_factory.py
───────────────────────────
Reusable Tool Factory — after every completed task, Thomas can extract a
reusable tool from what it just did and register it for future one-call reuse.

Two layers:
  1. GeneratedTool — stores name, description, JSON schema, Python implementation.
  2. ToolFactory    — manages extraction, the on-disk JSON registry, and registers
                      live Tool instances into the existing ToolRegistry.

Usage (from loop.py, post-task):
    from thomas.core.tool_factory import get_tool_factory
    factory = get_tool_factory()
    factory.extract_from_turn(task_description, tool_calls, result_summary)

Or register manually:
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
import textwrap
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_REGISTRY_FILE = Path("thomas_tool_registry.json")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GeneratedTool:
    """A tool extracted from a completed task and serialised for reuse."""

    name: str
    description: str
    parameters: Dict[str, Any]          # JSON Schema object
    implementation: str                  # Full Python source as string
    category: str = "generated"
    created_from: str = ""               # brief description of originating task
    usage_count: int = 0
    last_used: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GeneratedTool":
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

    def to_openai_spec(self) -> Dict[str, Any]:
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
    Extracts, stores, and registers reusable tools.

    Flow:
      extract_from_turn()  →  GeneratedTool  →  save_registry()  →  register_live()
                                                 (JSON on disk)       (ToolRegistry)

    The JSON registry at thomas_tool_registry.json survives restarts.
    Live registration into ToolRegistry makes the tool callable this session.
    """

    def __init__(
        self,
        registry_file: Optional[Path] = None,
        live_registry: Any = None,   # thomas.tools.registry.ToolRegistry | None
    ) -> None:
        self.registry_file = Path(registry_file or _REGISTRY_FILE)
        self._live_registry = live_registry
        self._lock = threading.Lock()
        self._tools: Dict[str, "GeneratedTool"] = {}

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
                self._tools = {
                    name: GeneratedTool.from_dict(spec)
                    for name, spec in raw.get("tools", {}).items()
                }
            log.info("ToolFactory: loaded %d tools from %s", len(self._tools), self.registry_file)
            return len(self._tools)
        except Exception as e:
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
        except Exception as e:
            log.error("ToolFactory: save failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_tool(self, tool: "GeneratedTool", overwrite: bool = False) -> bool:
        """
        Add a GeneratedTool to the factory registry, save to disk, and
        optionally register it live in the attached ToolRegistry.
        """
        safe_name = _safe_tool_name(tool.name)
        with self._lock:
            if safe_name in self._tools and not overwrite:
                log.debug("ToolFactory: tool %r already registered (skip).", safe_name)
                return False
            tool.name = safe_name
            self._tools[safe_name] = tool
        self.save_registry()
        self._maybe_register_live(tool)
        log.info("ToolFactory: registered tool %r (%s).", safe_name, tool.category)
        return True

    def get(self, name: str) -> Optional["GeneratedTool"]:
        with self._lock:
            return self._tools.get(_safe_tool_name(name))

    def list_tools(self, category: Optional[str] = None) -> List["GeneratedTool"]:
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

    # ------------------------------------------------------------------
    # Extraction — derive a GeneratedTool from a completed task turn
    # ------------------------------------------------------------------

    def extract_from_turn(
        self,
        task_description: str,
        tool_calls: List[Dict[str, Any]],
        result_summary: str,
        category: str = "generated",
    ) -> Optional["GeneratedTool"]:
        """
        Attempt to auto-extract a reusable tool from a completed conversation turn.

        Heuristic: worth capturing if ≥2 tool calls were made OR the task
        description contains actionable keywords (install, create, deploy, etc.).
        Returns the GeneratedTool if one was created, else None.
        """
        if not tool_calls or not task_description.strip():
            return None
        if len(tool_calls) < 2 and not _looks_reusable(task_description):
            return None

        name = _derive_tool_name(task_description)
        params = _infer_parameters(task_description, tool_calls)
        impl = _build_implementation(name, task_description, tool_calls, result_summary)
        description = _derive_description(task_description, result_summary)

        tool = GeneratedTool(
            name=name,
            description=description,
            parameters=params,
            implementation=impl,
            category=category,
            created_from=task_description[:200],
        )
        self.register_tool(tool, overwrite=False)
        return tool

    # ------------------------------------------------------------------
    # Live ToolRegistry integration
    # ------------------------------------------------------------------

    def attach_live_registry(self, registry: Any) -> None:
        """Attach a ToolRegistry so generated tools are callable this session."""
        self._live_registry = registry
        with self._lock:
            tools = list(self._tools.values())
        for t in tools:
            self._maybe_register_live(t)

    def _maybe_register_live(self, tool: "GeneratedTool") -> None:
        if self._live_registry is None:
            return
        try:
            live_tool = _make_live_tool(tool)
            self._live_registry.register(live_tool)
        except Exception as e:
            log.warning("ToolFactory: failed to register live tool %r: %s", tool.name, e)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

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
# Heuristics for auto-extraction
# ---------------------------------------------------------------------------

_REUSABLE_KEYWORDS = re.compile(
    r"\b(install|create|deploy|build|migrate|setup|configure|update|generate|"
    r"fetch|scrape|parse|process|export|import|sync|backup|restore|test|lint|"
    r"format|compile|bundle|run|execute|check|validate|convert|transform)\b",
    re.IGNORECASE,
)


def _looks_reusable(description: str) -> bool:
    return bool(_REUSABLE_KEYWORDS.search(description))


def _safe_tool_name(name: str) -> str:
    """Normalise to snake_case dot-separated tool name."""
    name = re.sub(r"[^a-z0-9.]+", "_", name.strip().lower())
    return name.strip("_.")[:64]


def _derive_tool_name(task: str) -> str:
    """Produce a tool name from a task description."""
    words = re.findall(r"[a-z]+", task.lower())
    stopwords = {"the", "a", "an", "and", "or", "to", "of", "in", "for",
                 "with", "on", "at", "by", "that", "this", "it", "is"}
    keywords = [w for w in words if w not in stopwords][:4]
    return "generated." + "_".join(keywords) if keywords else "generated.tool"


def _derive_description(task: str, result: str) -> str:
    base = task.strip()[:120]
    if result.strip():
        base += f" (result: {result.strip()[:60]})"
    return base


def _infer_parameters(task: str, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a minimal JSON-Schema parameters block from the tool calls that were made.
    Collects unique arg names seen and infers their type from the values.
    """
    props: Dict[str, Any] = {}
    for call in tool_calls:
        args = call.get("args", call.get("arguments", call.get("input", {})))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if isinstance(args, dict):
            for k, v in args.items():
                if k not in props:
                    typ = ("boolean" if isinstance(v, bool) else
                           "integer" if isinstance(v, int) else
                           "number" if isinstance(v, float) else
                           "array" if isinstance(v, list) else
                           "object" if isinstance(v, dict) else "string")
                    props[k] = {"type": typ, "description": f"Argument '{k}'"}
    return {"type": "object", "properties": props, "required": []}


def _build_implementation(
    name: str, task: str, tool_calls: List[Dict[str, Any]], result: str
) -> str:
    """Build a Python implementation stub including original tool call sequence as comments."""
    fn_name = name.replace(".", "_").replace("-", "_")
    calls_summary = "\n".join(
        f"    # {i+1}. {c.get('name', c.get('function', {}).get('name', 'tool'))}({c.get('args', {})})"
        for i, c in enumerate(tool_calls[:10])
    )
    return textwrap.dedent(f"""
        async def {fn_name}(**kwargs):
            \"\"\"
            Auto-generated reusable tool.
            Original task: {task.strip()[:150]}
            Result: {result.strip()[:100]}
            \"\"\"
            # Tool calls made during the original task:
{calls_summary}
            # TODO: Replace the above with actual shell.exec / fs.* / git.* calls.
            raise NotImplementedError(
                "{name} is an auto-generated stub. Implement body or invoke via Thomas."
            )
    """).strip()


# ---------------------------------------------------------------------------
# Live Tool wrapper — wraps a GeneratedTool as a callable Tool instance
# ---------------------------------------------------------------------------

def _make_live_tool(gt: "GeneratedTool") -> Any:
    """Return a Tool subclass instance wrapping a GeneratedTool."""
    from thomas.tools.base import Tool, ToolResult

    _gt = gt  # capture for closure

    class _DynamicTool(Tool):
        name = _gt.name
        category = _gt.category
        description = _gt.description
        parameters = _gt.parameters

        async def execute(self, args: Dict[str, Any]) -> ToolResult:
            return ToolResult(
                ok=True,
                data={
                    "tool": _gt.name,
                    "description": _gt.description,
                    "implementation": _gt.implementation,
                    "args_received": args,
                    "note": "Generated stub — Thomas will execute using standard tools.",
                },
            )

    return _DynamicTool()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_factory: Optional[ToolFactory] = None
_factory_lock = threading.Lock()


def get_tool_factory(live_registry: Any = None) -> ToolFactory:
    """Return the process-level ToolFactory, loading from disk on first call."""
    global _factory
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                _factory = ToolFactory(live_registry=live_registry)
                _factory.load()
    elif live_registry is not None and _factory._live_registry is None:
        _factory.attach_live_registry(live_registry)
    return _factory
