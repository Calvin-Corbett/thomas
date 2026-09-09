"""Repository-defined agent/role definitions for Thomas (CAP-025).

Agents are markdown files discovered at runtime from the working repo, mirroring
the discovery/precedence conventions of repository-defined slash commands
(:mod:`thomas.cli.repo_commands`):

- ``.thomas/agents/<name>.md`` (primary source)
- ``.claude/agents/<name>.md`` (compatible fallback, mirroring the Claude Code
  convention so existing muscle memory transfers)

On a name collision ``.thomas`` wins over ``.claude``.

File format: YAML-style frontmatter declaring the agent's contract followed by a
body that is the agent's system instructions::

    ---
    name: reviewer
    description: Careful code reviewer
    tools: read_file, grep, shell
    model: reasoning
    ---
    You are a meticulous code reviewer. ...

Recognized frontmatter keys:

- ``name`` (optional; defaults to the file stem) — the agent id.
- ``description`` (optional) — one-line summary.
- ``tools`` (required for a *valid* agent) — an explicit allowlist of tool
  names, comma- or whitespace-separated (``[a, b]`` list syntax is tolerated).
- ``model`` (required for a *valid* agent) — a model profile id string.

The body (everything after the frontmatter) is the agent's system instructions.

Two layers of robustness:

1. **Discovery** live-reads and *structurally* parses definitions, tolerating
   malformed files with a clear per-file warning — it never raises.
2. **Validation** (:func:`validate_agent_definition`) checks the *semantic*
   contract: required fields present, every declared tool resolves to a real
   registered tool name (against an injected known-tool set, so callers/tests
   stay hermetic), and the model profile is a non-empty string.

This module deliberately does NOT wire itself into live dispatch. It exposes the
loader plus validated :class:`RepoAgent` objects as the integration seam a
runner consumes — mirroring how ``repo_commands`` exposes rendered prompts.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Precedence order: earlier directories win name collisions.
AGENT_DIR_SOURCES: tuple[tuple[str, str], ...] = (
    (".thomas", ".thomas/agents"),
    (".claude", ".claude/agents"),
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MAX_AGENT_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class RepoAgent:
    """A repository-defined agent, ready for a runner to consume.

    ``tools`` is the explicit allowlist of tool names, ``model`` the resolved
    model-profile id, and ``instructions`` the system prompt body.
    """

    name: str
    description: str = ""
    tools: tuple[str, ...] = ()
    model: str = ""
    instructions: str = ""
    source: str = ""
    origin: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Structured outcome of :func:`validate_agent_definition`."""

    ok: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepoAgentScan:
    """Result of scanning the repo for agent definition files."""

    agents: tuple[RepoAgent, ...] = ()
    warnings: tuple[str, ...] = ()


# Cache keyed by resolved root -> (directory signature, scan result).
_SCAN_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], RepoAgentScan]] = {}


def _agent_files(root: Path) -> list[tuple[str, Path]]:
    """Return (origin, path) pairs for every candidate definition file."""
    found: list[tuple[str, Path]] = []
    for origin, rel_dir in AGENT_DIR_SOURCES:
        directory = root / rel_dir
        try:
            if not directory.is_dir():
                continue
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            log.debug("Cannot list repo agent dir %s: %s", directory, exc)
            continue
        for path in entries:
            try:
                if path.suffix.lower() == ".md" and path.is_file():
                    found.append((origin, path))
            except OSError as exc:
                log.debug("Cannot stat repo agent file %s: %s", path, exc)
    return found


def _signature(files: list[tuple[str, Path]]) -> tuple[tuple[str, int, int], ...]:
    """A cheap change signature: (path, mtime_ns, size) per definition file."""
    rows: list[tuple[str, int, int]] = []
    for _origin, path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(rows)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
    """Split required ``---`` frontmatter from *text*.

    Returns ``(meta, body, error)``; *error* is non-empty when the frontmatter
    block is missing or malformed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "", "missing frontmatter block (expected leading '---')"
    end_index = 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index == 0:
        return {}, "", "unterminated frontmatter block (missing closing '---')"
    meta: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            return {}, "", f"invalid frontmatter line (expected 'key: value'): {stripped!r}"
        key, _, value = stripped.partition(":")
        normalized_key = key.strip().lower().replace("_", "-")
        meta[normalized_key] = value.strip()
    body = "\n".join(lines[end_index + 1 :])
    return meta, body, ""


def _parse_tools(value: str) -> tuple[str, ...]:
    """Parse a ``tools`` frontmatter value into an ordered, de-duplicated tuple.

    Accepts comma- and/or whitespace-separated names, tolerating inline-list
    syntax (``[a, b]``) and surrounding quotes on individual names.
    """
    raw = str(value or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    parts = [part.strip().strip("'\"") for part in re.split(r"[,\s]+", raw)]
    ordered: list[str] = []
    for part in parts:
        if part and part not in ordered:
            ordered.append(part)
    return tuple(ordered)


def _load_agent_file(origin: str, path: Path) -> tuple[RepoAgent | None, str]:
    """Structurally parse one definition file into ``(agent, warning)``."""
    label = f"{origin}/agents/{path.name}"
    stem_name = path.stem.strip().lower()
    try:
        if path.stat().st_size > _MAX_AGENT_FILE_BYTES:
            return None, f"{label}: file too large (max {_MAX_AGENT_FILE_BYTES // 1024} KiB)"
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{label}: unreadable ({type(exc).__name__}: {exc})"
    meta, body, error = _parse_frontmatter(text)
    if error:
        return None, f"{label}: {error}"
    name = str(meta.get("name", "") or stem_name).strip().lower()
    if not _NAME_RE.match(name):
        return None, f"{label}: invalid agent name {name!r} (use letters, digits, '.', '_', '-')"
    instructions = body.strip()
    if not instructions:
        return None, f"{label}: empty agent instructions"
    return (
        RepoAgent(
            name=name,
            description=str(meta.get("description", "")).strip().strip("'\""),
            tools=_parse_tools(meta.get("tools", "")),
            model=str(meta.get("model", "")).strip().strip("'\""),
            instructions=instructions,
            source=str(path),
            origin=origin,
        ),
        "",
    )


def discover_repo_agents(root: Path | None = None) -> RepoAgentScan:
    """Scan the working repo for agent definitions.

    Live-reads with a cheap mtime/size cache, so newly added files are
    discoverable without a restart. Never raises: malformed or unreadable files
    are reported via ``RepoAgentScan.warnings``. Structural parsing only —
    callers apply :func:`validate_agent_definition` against a live tool set.
    """
    try:
        base = (root or Path.cwd()).resolve()
    except OSError as exc:
        log.debug("Cannot resolve repo agent root: %s", exc)
        return RepoAgentScan()
    files = _agent_files(base)
    signature = _signature(files)
    cache_key = str(base)
    cached = _SCAN_CACHE.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    agents: dict[str, RepoAgent] = {}
    warnings: list[str] = []
    for origin, path in files:
        agent, warning = _load_agent_file(origin, path)
        if agent is None:
            warnings.append(warning)
            continue
        existing = agents.get(agent.name)
        if existing is not None:
            # Earlier sources win (.thomas over .claude); same-source dupes
            # cannot happen because names come from unique file stems.
            log.debug(
                "Repo agent %s from %s shadowed by %s",
                agent.name,
                agent.source,
                existing.source,
            )
            continue
        agents[agent.name] = agent

    scan = RepoAgentScan(
        agents=tuple(sorted(agents.values(), key=lambda a: a.name)),
        warnings=tuple(warnings),
    )
    _SCAN_CACHE[cache_key] = (signature, scan)
    return scan


def find_repo_agent(name: str, root: Path | None = None) -> RepoAgent | None:
    """Return the repo agent exactly matching *name*, or ``None``."""
    wanted = str(name or "").strip().lower()
    if not wanted:
        return None
    for agent in discover_repo_agents(root).agents:
        if agent.name == wanted:
            return agent
    return None


def known_tool_names(registry: object) -> frozenset[str]:
    """Best-effort extraction of registered tool names from a registry object.

    Duck-typed against :class:`thomas.tools.registry.ToolRegistry` (anything
    exposing ``list_tools()`` whose items have a ``.name``). Returns an empty
    set if the object does not look like a registry, so callers can pass one
    without a hard import.
    """
    lister = getattr(registry, "list_tools", None)
    if not callable(lister):
        return frozenset()
    try:
        tools = lister()
    except TypeError:
        return frozenset()
    names: set[str] = set()
    for tool in tools or ():
        tool_name = getattr(tool, "name", None)
        if isinstance(tool_name, str) and tool_name:
            names.add(tool_name)
    return frozenset(names)


def validate_agent_definition(
    agent: RepoAgent,
    known_tools: Iterable[str] | None = None,
) -> ValidationResult:
    """Validate a :class:`RepoAgent`'s semantic contract.

    Checks required fields (``name``, ``tools``, ``model``, ``instructions``),
    that the model profile is a non-empty string, and — when *known_tools* is
    supplied — that every declared tool resolves to a real registered tool
    name. Returns a structured :class:`ValidationResult`; ``ok`` is ``True``
    only when ``errors`` is empty.
    """
    errors: list[str] = []

    name = str(agent.name or "").strip()
    if not name:
        errors.append("missing required field 'name'")
    elif not _NAME_RE.match(name):
        errors.append(f"invalid agent name {name!r} (use letters, digits, '.', '_', '-')")

    model = str(agent.model or "").strip()
    if not model:
        errors.append("model profile must be a non-empty string")

    instructions = str(agent.instructions or "").strip()
    if not instructions:
        errors.append("missing required field 'instructions' (agent body is empty)")

    if not agent.tools:
        errors.append("missing required field 'tools' (declare at least one tool)")
    elif known_tools is not None:
        available = {str(item) for item in known_tools}
        for tool_name in agent.tools:
            if tool_name not in available:
                errors.append(f"unknown tool {tool_name!r} (not a registered tool name)")

    return ValidationResult(ok=not errors, errors=tuple(errors))


@dataclass(frozen=True)
class RepoAgentValidationScan:
    """Discovery result partitioned into valid agents and their issues."""

    agents: tuple[RepoAgent, ...] = ()
    warnings: tuple[str, ...] = ()
    invalid: tuple[tuple[str, ValidationResult], ...] = field(default=())


def discover_valid_repo_agents(
    root: Path | None = None,
    known_tools: Iterable[str] | None = None,
) -> RepoAgentValidationScan:
    """Discover agents and split them into valid vs. invalid by validation.

    Convenience wrapper over :func:`discover_repo_agents` +
    :func:`validate_agent_definition` for runners that want only agents ready
    to consume. Structural-parse warnings are carried through; validation
    failures are surfaced in ``invalid`` as ``(name, ValidationResult)`` pairs.
    """
    scan = discover_repo_agents(root)
    available = None if known_tools is None else {str(item) for item in known_tools}
    valid: list[RepoAgent] = []
    invalid: list[tuple[str, ValidationResult]] = []
    for agent in scan.agents:
        result = validate_agent_definition(agent, available)
        if result.ok:
            valid.append(agent)
        else:
            invalid.append((agent.name, result))
    return RepoAgentValidationScan(
        agents=tuple(valid),
        warnings=scan.warnings,
        invalid=tuple(invalid),
    )
