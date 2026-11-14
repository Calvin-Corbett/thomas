"""Which paths agent tools may never write: Thomas's own runtime, and what the gates trust.

Moved out of ``thomas/tools/filesystem.py`` (which re-exports every name) to keep that
file under the 800-line limit. Behaviour is unchanged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath

from thomas.tools.runtime_protection_auth import _maybe_apply_native_auth_override  # noqa: F401 - re-exported
from thomas.tools.runtime_protection_flag import (
    _GREEN_EVOLVE_RUNTIME_WRITES_ENV,
    _RUNTIME_FLAG_REL,
    _RUNTIME_KEY_REL,
    _green_evolve_runtime_writes_enabled,
    _is_runtime_protection_disabled,
)

log = logging.getLogger("thomas.tools.filesystem")

__all__ = [
    "anchor_runtime_protection",
    "_HARDCODED_PROTECTED_DIRS",
    "_HARDCODED_PROTECTED_FILES",
    "_FILESYSTEM_ONLY_PROTECTED_PREFIXES",
    "_is_protected_runtime_path",
    "_maybe_apply_native_auth_override",
    "_runtime_protection_roots",
]


# The tree that holds the Thomas actually running this process, when the process
# is not Thomas's own server: the Build runner works inside a project folder, and
# without an anchor, runtime protection was checked against that folder, so a
# copy of Thomas could not be improved and any project's own scripts/ or
# pyproject.toml could not be edited. None keeps the original behaviour.
_RUNTIME_ANCHOR: Path | None = None


def anchor_runtime_protection(root: Path) -> None:
    """Make runtime protection guard ``root`` (the running Thomas) for this process."""
    global _RUNTIME_ANCHOR
    _RUNTIME_ANCHOR = Path(root).resolve()


# ---------------------------------------------------------------------------
# Hardcoded protected directories — the last line of defence.
# Even if agent_safety.toml is corrupted or unreadable, these stay active.
# Every directory listed here (relative to sandbox root) is read-only for
# agent-spawned tools.  The list is deliberately minimal: only Thomas's own
# runtime, enforcement scripts, and top-level policy files.
# ---------------------------------------------------------------------------
_HARDCODED_PROTECTED_DIRS: tuple[str, ...] = (
    "thomas/tools",
    "thomas/agent",
    "thomas/core",
    "thomas/server",
    "scripts",
    "evolve_supervisor",
    "evolve_corpus",
)

# Guarded by this layer alone, like the bypass control files below: git's own
# directory holds the pre-commit hooks that run every gate, the config that can
# redirect them, and the verification records two gates read. It is not in the
# documented directory registry (agent_safety.toml), which is owner-protected and
# whose list is checked against the tuple above; protecting more than the registry
# documents is safe, protecting less is not. Real git operations run git itself and
# are untouched: only the agent's file tools are refused.
_FILESYSTEM_ONLY_PROTECTED_PREFIXES: tuple[str, ...] = (".git",)

# Protected file paths (relative to sandbox root, forward-slash).
# Two categories:
#  - Top-level policy files an agent must not modify.
#  - The runtime-protection toggle flag + its signing key.  These live
#    inside the otherwise-writable runtime/ tree, but they are the
#    *bypass mechanism* — if an agent could write them via fs.write_file
#    they could disable all runtime protection.  See PR runtime-protection-
#    fix-2026-05-27 for the historical bug this closes.
_HARDCODED_PROTECTED_FILES: tuple[str, ...] = (
    "agent_safety.toml",
    "AGENTS.md",
    "GUARDRAILS.md",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "thomas.toml",
    "thomas.prod.toml",
    # The file-size guard's waivers. Protected when committing since the gate was
    # written, but not against the write itself: on 2026-09-19 a Build agent, pushed
    # by a check it could not pass, rewrote this file to waive every violation and
    # renewed an expired waiver to 2027. A live gate reads it, so the write is the
    # moment that matters.
    "docs/monolith_guard_baseline.json",
    # The rest of what the gates trust while Thomas runs: the other waiver list, the
    # board whose claims and acks the coordination gates judge, the markers that say
    # a check already passed, the rule files gates quote, and the ignore file that
    # decides what a gate can see. Each was protected when committing but writable
    # live, which is the moment a running gate reads it.
    "docs/ops/landed_history_waivers.json",
    "plans/thomas/WORKBOARD.md",
    "runtime/push_gate_cache.json",
    "runtime/coordination/workboard_takeover_transaction.json",
    "WORKTREE_RULES.md",
    "AGENT_SAFETY_GATES.md",
    "AGENT_RULES_QUICK_REFERENCE.md",
    "PROJECT_MANAGEMENT_RULES.md",
    "docs/AGENT_FILE_EDITING_RULES.md",
    "docs/REPO_STRUCTURE_PROTOCOL.md",
    ".gitignore",
    "runtime/.runtime_protection_disabled",
    "runtime/.runtime_protection_key",
    "runtime/.breakglass_window",
    "runtime/.breakglass_window_key",
)

from thomas.tools.runtime_protection_auth import _maybe_apply_native_auth_override  # noqa: F401 - re-exported
from thomas.tools.runtime_protection_flag import (  # noqa: F401 - re-exported, tests and gates import these from here
    _GREEN_EVOLVE_RUNTIME_WRITES_ENV,
    _MAX_DISABLE_HOURS,
    _RUNTIME_FLAG_REL,
    _RUNTIME_FLAG_VERSION,
    _RUNTIME_KEY_REL,
    _green_evolve_runtime_writes_enabled,
    _is_runtime_protection_disabled,
    _load_runtime_protection_key,
    _runtime_signing_payload,
    _within_disable_window,
)


def _is_protected_runtime_path(
    sandbox_root: Path,
    target: Path,
    *,
    allow_native_auth_override: bool = False,
    action_description: str = "",
    card: object | None = None,
) -> str | None:
    """Check if *target* falls inside a protected runtime directory or matches
    a protected file.

    Returns a human-readable reason string if the path is protected, or
    ``None`` if the write is allowed.

    The check is intentionally independent of any config file so that an agent
    cannot neutralise it by editing ``agent_safety.toml`` — that file is
    itself inside the protected set.

    Two bypass mechanisms (both require physical human presence at the OS):

    1. *Persistent* — a human runs ``python scripts/runtime_protection_toggle.py off``
       which requires Windows credential authentication and creates a flag
       file that disables runtime protection until toggled back on.

    2. *Per-operation* — set ``allow_native_auth_override=True`` to make this
       call attempt a one-shot native OS auth prompt (Win Hello / Touch ID /
       polkit) when the path would otherwise be refused. If the prompt is
       approved, this single call returns ``None`` (the operation is allowed).
       If denied/cancelled/unavailable, the refusal reason is returned as
       before.  This is the architecture extension landed in
       gate-architecture-2026-05-26 (see docs/SAFETY_ARCHITECTURE.md).
       Existing callers that don't pass the kwarg get unchanged behavior.

    The two *runtime-protection control files* (the disable flag and the HMAC
    key) are **absolutely protected**: the persistent-disable bypass does NOT
    apply to them.  Otherwise an active disable state could be used to
    overwrite the key with attacker-controlled bytes and persist a bypass
    across the next toggle cycle (security hardening review).
    The product owner can still write them via the per-operation native-auth override.

    When a process has anchored protection (``anchor_runtime_protection``), the
    check is made against the anchored tree instead of the tool's own root: files
    inside the running Thomas are protected whatever root the tool is confined to,
    and a folder that merely looks like Thomas (a copy, or a user project with its
    own ``scripts/`` or ``pyproject.toml``) is not.
    """
    anchor = _RUNTIME_ANCHOR
    if anchor is not None:
        try:
            target.resolve().relative_to(anchor)
        except ValueError:
            return None
        sandbox_root = anchor
    try:
        rel = target.resolve().relative_to(sandbox_root.resolve())
    except ValueError:
        # Outside sandbox entirely — _safe_path already handles this.
        return None

    # Normalise to forward-slash for consistent matching on all platforms.
    rel_posix = PurePosixPath(rel)
    rel_posix_str = str(rel_posix)

    # ── Always-protected: runtime-protection control files ────────────────
    # These must never be bypassed by the disable flag itself.  The product owner can
    # still reach them through the per-operation native-auth override below.
    if rel_posix_str in {_RUNTIME_FLAG_REL, _RUNTIME_KEY_REL}:
        reason = (
            f"BLOCKED: '{rel_posix_str}' is a runtime-protection control file. "
            "Only scripts/runtime_protection_toggle.py (Windows-auth required) "
            "may write here, regardless of the persistent disable flag."
        )
        return _maybe_apply_native_auth_override(
            reason=reason,
            rel_posix=rel_posix,
            allow_native_auth_override=allow_native_auth_override,
            action_description=action_description,
            card=card,
        )

    # Allow bypass when a human has explicitly disabled protection
    # (control files above are exempt from this bypass).
    if _is_runtime_protection_disabled(sandbox_root):
        return None

    reason: str | None = None
    green_evolve_writes = _green_evolve_runtime_writes_enabled(sandbox_root)
    # A block is PERMANENT for this caller: the identical write fails every time.
    # Saying only what is forbidden invites a retry loop, so every reason below also
    # names the two paths that do work and tells the model to stop.
    #
    # Measured 2026-09-19 by driving the UI: a chat task card asked to split
    # loop_execution.py, the agent correctly decided to create
    # thomas/agent/loop_provider_limits.py, and the write was blocked. The agent had
    # the block text, had fs.write_protected_file registered, and surfaced neither -
    # the run continued ten more minutes behind an "On it - working on this" spinner
    # and wrote nothing. What the model did in those minutes is not in the logs; what
    # is certain is that the person was never told. That silence is the Rule 0
    # failure: Thomas may not stop at a wall it will not name.
    way_forward = (
        " Retrying this exact write will fail the same way. Two routes do work:"
        " call `fs.write_protected_file`, which asks the person for OS authorization,"
        " or tell the person this needs Redesign, the thread type meant for editing"
        " Thomas itself. Stop now and report which one you need."
    )

    for prefix in _FILESYSTEM_ONLY_PROTECTED_PREFIXES:
        if rel_posix_str == prefix or rel_posix_str.startswith(prefix + "/"):
            return _maybe_apply_native_auth_override(
                reason=(
                    f"BLOCKED: '{rel_posix}' is inside '{prefix}/', which holds the hooks and "
                    "settings every gate depends on. Agent-spawned tools cannot modify it." + way_forward
                ),
                rel_posix=rel_posix,
                allow_native_auth_override=allow_native_auth_override,
                action_description=action_description,
                card=card,
            )

    # Check protected directories (any file *inside* these).
    for pdir in _HARDCODED_PROTECTED_DIRS:
        protected = PurePosixPath(pdir)
        try:
            rel_posix.relative_to(protected)
            if green_evolve_writes and str(protected).startswith("thomas/"):
                return None
            reason = (
                f"BLOCKED: '{rel_posix}' is inside protected runtime "
                f"directory '{pdir}/'. Agent-spawned tools cannot modify "
                f"Thomas's own runtime code." + way_forward
            )
            break
        except ValueError:
            continue

    if reason is None:
        # Check individual protected files at the repo root.
        for pfile in _HARDCODED_PROTECTED_FILES:
            if rel_posix == PurePosixPath(pfile):
                reason = (
                    f"BLOCKED: '{rel_posix}' is a protected policy file. "
                    "Agent-spawned tools cannot modify it." + way_forward
                )
                break

    if reason is None:
        return None

    return _maybe_apply_native_auth_override(
        reason=reason,
        rel_posix=rel_posix,
        allow_native_auth_override=allow_native_auth_override,
        action_description=action_description,
        card=card,
    )


def _runtime_protection_roots(sandbox_root: Path, project_root: Path) -> list[Path]:
    """Roots whose contents are Thomas's OWN protected runtime code.

    Protection guards Thomas's runtime (``thomas/``, ``scripts/``,
    ``evolve_supervisor/``, ``evolve_corpus/``, policy files),
    which live under the real *project root* — so that is always a protection root.
    A standalone deliverable workspace (e.g. ``~/.thomas/workspaces/<id>/``) is NOT:
    a background worker building a deliverable must stay free to create its own
    ``scripts/`` or ``thomas/`` subfolder there. Checking the workspace sandbox root
    against the hardcoded dir *names* falsely blocked such a write and hung the task.
    The sandbox root is included only when it IS, or sits inside, the project tree
    (a worker actually operating in the repo)."""
    roots = [project_root.resolve()]
    try:
        sr = sandbox_root.resolve()
    except OSError:
        return roots
    if sr != roots[0] and roots[0] in sr.parents:
        roots.append(sr)
    return roots
