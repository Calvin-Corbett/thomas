"""Built-in tool groups described by a manifest.

First step of moving tool registration off hard-coded code lists
(``app_helpers._build_tools``). A group is a ``tool_manifests/<name>.toml``
record: which function registers it, what the host must hand that function, and
the exact tool names it provides.

``register_tool_group`` is what ``_build_tools`` calls. It reads the manifest,
registers the group into a scratch registry, checks the tool set against the
manifest, and only then copies the tools into the real registry in the order the
group registered them. If anything about that fails (no manifest, unreadable,
disallowed function, wrong tool set) it logs and runs ``fallback`` -- the
original hard-coded call -- so the registry is the same either way.
"""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from thomas.tools.base import Tool
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

_MANIFEST_DIR = Path(__file__).resolve().parent / "tool_manifests"
_GROUP_NAME = re.compile(r"[a-z0-9-]+")

#: How a manifest that cannot be used fails without it being a bug in Thomas.
GROUP_ERRORS = (OSError, ValueError, KeyError, ImportError, AttributeError, TypeError, RuntimeError)


@dataclass(frozen=True)
class ToolGroupManifest:
    id: str
    register: str
    needs: tuple[str, ...]
    tools: frozenset[str]


@dataclass(frozen=True)
class PinnedGroup:
    """What a group must be, written in code so a manifest can only select it, never redefine it."""

    register: str
    needs: tuple[str, ...]
    tools: frozenset[str]


#: The only groups a manifest may enable, each with the exact register function, host values and tool names the
#: code expects. A manifest that names another function, other host values or another tool set is refused and the
#: built-in registration runs instead. thomas/server/tool_manifests/ and this file are on the protected list
#: (agent_safety.toml [protected].enforcement_files): changing a pin here, editing a manifest or adding one needs the
#: owner's sign-in.
PINNED_GROUPS: dict[str, PinnedGroup] = {
    "code-search": PinnedGroup(
        register="thomas.tools.code_search:register_code_search_tools",
        needs=("sandbox",),
        tools=frozenset(
            {
                "code.search",
                "code.find_definition",
                "code.find_references",
                "code.project_structure",
                "code.semantic_search",
            }
        ),
    ),
}


class _ScratchRegistry(ToolRegistry):
    """A registry that also remembers every ``register`` call, in call order."""

    def __init__(self) -> None:
        super().__init__()
        self.in_order: list[Tool] = []

    def register(self, tool: Tool) -> None:
        super().register(tool)
        self.in_order.append(tool)


def _toml() -> ModuleType:
    # Imported here, not at module top: python 3.10 has no tomllib and ships tomli instead,
    # and a failure here must reach the fallback rather than break importing the server.
    try:
        import tomllib
    except ImportError:  # pragma: no cover - python 3.10 ships tomli as a dependency
        import tomli as tomllib
    return tomllib


def _split_register(name: str, register: str) -> tuple[str, str]:
    """``'thomas.tools.<module>:register_<what>'`` -> (module, function), else ValueError."""
    module_name, _, func_name = register.partition(":")
    if not module_name.startswith("thomas.tools.") or not func_name.startswith("register_"):
        raise ValueError(
            f"tool group {name!r}: register must be 'thomas.tools.<module>:register_<what>', got {register!r}",
        )
    return module_name, func_name


def _check_pin(name: str, manifest: ToolGroupManifest) -> None:
    """Refuse a manifest that is not exactly the pinned group it names. Raises ValueError."""
    pin = PINNED_GROUPS.get(name)
    if pin is None:
        raise ValueError(f"tool group {name!r} is not pinned in code; a manifest cannot add a group")
    if manifest.id != f"tools.{name}":
        raise ValueError(f"tool group {name!r}: manifest id {manifest.id!r} is not 'tools.{name}'")
    if (manifest.register, manifest.needs, manifest.tools) != (pin.register, pin.needs, pin.tools):
        raise ValueError(
            f"tool group {name!r}: manifest differs from the code's pin "
            f"(register {manifest.register!r}, needs {list(manifest.needs)}, tools {sorted(manifest.tools)})",
        )


def load_manifest(name: str) -> ToolGroupManifest:
    """Read ``tool_manifests/<name>.toml``. Raises one of ``GROUP_ERRORS``."""
    if not _GROUP_NAME.fullmatch(name):
        raise ValueError(f"tool group name must match [a-z0-9-]+, got {name!r}")
    with (_MANIFEST_DIR / f"{name}.toml").open("rb") as handle:
        raw = _toml().load(handle)
    register = str(raw["group"]["register"])
    _split_register(name, register)
    tools = frozenset(str(tool) for tool in raw["provides"]["tools"])
    if not tools:
        raise ValueError(f"tool group {name!r} provides no tools")
    manifest = ToolGroupManifest(
        id=str(raw["id"]),
        register=register,
        needs=tuple(str(need) for need in raw["group"].get("needs", ())),
        tools=tools,
    )
    _check_pin(name, manifest)
    return manifest


def build_group(manifest: ToolGroupManifest, host: Mapping[str, Any]) -> list[Tool]:
    """Register the group into a scratch registry; return its tools in registration order."""
    module_name, func_name = _split_register(manifest.id, manifest.register)
    _check_pin(manifest.id.removeprefix("tools."), manifest)
    register = getattr(importlib.import_module(module_name), func_name)
    scratch = _ScratchRegistry()
    register(scratch, *(host[need] for need in manifest.needs))
    provided = {tool.name for tool in scratch.list_tools()}
    if provided != manifest.tools:
        raise ValueError(
            f"{manifest.id} registered {sorted(provided)}, manifest says {sorted(manifest.tools)}",
        )
    return scratch.in_order


def _fall_back(name: str, exc: Exception, fallback: Callable[[], Any]) -> bool:
    log.warning("tool group %r: manifest path unavailable (%s); using the built-in registration", name, exc)
    fallback()
    return False


def register_tool_group(
    registry: ToolRegistry,
    name: str,
    host: Mapping[str, Any],
    fallback: Callable[[], Any],
) -> bool:
    """Register group ``name`` from its manifest; run ``fallback`` if that cannot be done.

    Returns True when the manifest path registered the group.
    """
    try:
        manifest = load_manifest(name)
    except FileNotFoundError as exc:
        # Normal for an install that does not ship the manifest files; not worth a warning per run.
        log.debug("tool group %r: no manifest (%s); using the built-in registration", name, exc)
        fallback()
        return False
    except GROUP_ERRORS as exc:
        return _fall_back(name, exc, fallback)
    try:
        tools = build_group(manifest, host)
    except GROUP_ERRORS as exc:
        return _fall_back(name, exc, fallback)
    for tool in tools:
        registry.register(tool)
    return True
