"""Live-source policy and exact scope checks for native self-edit candidates."""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from thomas.forge.anvil import forge_code_projects
from thomas.forge.anvil.forge_code_self_edit import SelfEditSnapshotError

# The worker cannot promote edits to the mechanisms that decide what it may
# promote. These are supervisor authority, even when no workboard claim exists.
_AUTHORITY_PREFIXES = (
    "thomas/server/routes/evolve_agent_self_edit",
    "thomas/tools/runtime_protection",
    "thomas/tools/filesystem",
    "thomas/tools/diff",
    "thomas/forge/anvil/forge_code_self_edit",
    "thomas/forge/anvil/forge_code_redesign_undo",
    "thomas/forge/anvil/forge_code_candidate_check",
    "thomas/forge/anvil/resumable_candidate_verifier",
)
_AUTHORITY_FILES = {
    "thomas/forge/anvil/forge_code_runner.py",
    "thomas/tools/registry.py",
    "thomas/agent/loop_tool_paths.py",
    "thomas/server/routes/evolve_agent_runtime.py",
    "thomas/server/routes/evolve_agent_routes.py",
    "thomas/server/routes/evolve_agent_conversation_routes.py",
}


def resolve_source(identity: object) -> Path:
    if identity != "thomas-source":
        raise SelfEditSnapshotError("Select Edit Thomas to create a self-edit task")
    source = forge_code_projects.thomas_source_repo_root()
    if source is None:
        raise SelfEditSnapshotError("Thomas source is unavailable")
    return source.resolve()


def validate_scope(source: Path, paths: object) -> list[str]:
    """Authorize only explicit product files; worker output cannot expand scope."""
    from thomas.core.board_fence import board_fenced_paths

    if not isinstance(paths, list) or not 1 <= len(paths) <= 30:
        raise SelfEditSnapshotError("Choose between 1 and 30 exact files for this change")
    policy = tomllib.loads((source / "agent_safety.toml").read_text(encoding="utf-8"))
    protected = policy.get("protected")
    if not isinstance(protected, dict) or not protected.get("policy_files"):
        raise SelfEditSnapshotError("The live source policy is unavailable")
    blocked = [
        str(p).replace("\\", "/").casefold() for rows in protected.values() if isinstance(rows, list) for p in rows
    ]
    board = (source / "plans" / "thomas" / "WORKBOARD.md").read_text(encoding="utf-8")
    blocked += [p.casefold() for p in board_fenced_paths(board, exempt_agents=set())]
    result = []
    for raw in paths:
        if not isinstance(raw, str):
            raise SelfEditSnapshotError("Each self-edit file must be an exact relative path")
        name = raw.strip().replace("\\", "/")
        path = PurePosixPath(name)
        if (
            not name.startswith("thomas/")
            or path.is_absolute()
            or ".." in path.parts
            or any(c in name for c in "*?[:")
            or name != str(path)
        ):
            raise SelfEditSnapshotError(f"Invalid product file: {name}")
        lower = name.casefold()
        if (
            path.name.casefold() in {"agents.md", "guardrails.md"}
            or lower in _AUTHORITY_FILES
            or lower.startswith(_AUTHORITY_PREFIXES)
            or any(
                lower == p.rstrip("/") or lower.startswith(p.rstrip("/") + "/") or fnmatch.fnmatchcase(lower, p)
                for p in blocked
            )
        ):
            raise SelfEditSnapshotError(f"Protected or currently claimed file: {name}")
        target = source / name
        if not target.resolve().is_relative_to(source.resolve()):
            raise SelfEditSnapshotError("The selected file leaves Thomas source")
        result.append(name)
    if len(set(result)) != len(result):
        raise SelfEditSnapshotError("Choose each self-edit file only once")
    return sorted(result)


def validate_delta(candidate, scope: list[str], changed: list[str]) -> None:
    validate_scope(candidate.source_root, scope)
    outside = sorted(set(changed) - set(scope))
    if outside:
        raise SelfEditSnapshotError("Candidate changed files outside the selected scope: " + ", ".join(outside))
