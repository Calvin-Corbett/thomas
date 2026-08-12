"""Shared root-instruction contract enforcement across execution surfaces.

The main agent loop resolves and injects hierarchical project instructions
(``THOMAS.md`` / ``CLAUDE.md`` / ``AGENTS.md`` / ``.cursorrules``) into its
system prompt via :mod:`thomas.agent.instruction_resolution`. Delegated workers
and specialist dispatch build their *own* system prompts on a different code
path, so without a shared helper the same root instruction contract can silently
be dropped for delegated work.

This module is that shared seam. It does **not** duplicate the resolver — it
reuses :func:`discover_project_instructions` / :func:`format_project_instructions`
so every surface honors the exact same precedence and override rules — and it
adds a stable :func:`contract_signature` so two surfaces can *assert* they applied
the same instruction set.

Design notes
------------
- ``apply_root_instructions`` is idempotent-safe to call once per surface: it
  appends the resolved, budget-bounded instruction block to a system prompt and
  returns it unchanged when no instruction files apply (clean degrade).
- ``contract_signature`` is **budget-independent**: it hashes the resolved source
  files (path + full content), not the truncated merge, so the main surface and a
  delegated worker rooted at the same cwd produce an identical signature even when
  they pass different ``budget`` values. It changes only when the underlying
  instruction set changes.
- stdlib-only, so it stays importable on early startup paths like the resolver it
  wraps.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from thomas.agent.instruction_resolution import (
    DEFAULT_MERGE_MAX_CHARS,
    resolve_instruction_sources,
)
from thomas.agent.project_instructions import (
    discover_project_instructions,
    format_project_instructions,
)

log = logging.getLogger(__name__)

# Default prompt budget for the injected instruction block. Callers with a known
# model context window should pass a tighter, window-derived budget.
DEFAULT_INSTRUCTION_BUDGET = DEFAULT_MERGE_MAX_CHARS

# Signature returned when no instruction files apply at the given cwd.
EMPTY_SIGNATURE = "instr:none"

_SIGNATURE_PREFIX = "instr:"
_SIGNATURE_HEX_LEN = 16


def apply_root_instructions(
    system_prompt: str,
    *,
    cwd: str | Path | None,
    budget: int = DEFAULT_INSTRUCTION_BUDGET,
) -> str:
    """Return ``system_prompt`` with the root instruction contract applied.

    Resolves the hierarchical root/project instructions rooted at ``cwd`` (reusing
    the canonical resolver — never re-implementing it) and appends the formatted,
    ``budget``-bounded block to ``system_prompt``. When no instruction files apply
    (e.g. a fresh empty worker workspace), the prompt is returned unchanged so
    delegated workers degrade cleanly.
    """

    base = str(system_prompt or "")
    try:
        content = discover_project_instructions(cwd, max_chars=max(200, int(budget)))
    except (OSError, ValueError):
        # Narrow, non-fatal: instruction discovery is best-effort and must never
        # block a worker turn. Log and fall through to the unmodified prompt.
        log.debug("Root instruction discovery failed for cwd=%r; skipping.", cwd, exc_info=True)
        return base
    if not content:
        return base
    return base.rstrip() + "\n\n" + format_project_instructions(content)


def contract_signature(cwd: str | Path | None) -> str:
    """Return a stable identifier of the active instruction set rooted at ``cwd``.

    Two execution surfaces rooted at the same cwd yield the same signature; the
    signature differs when the resolved instruction set (any applicable file's
    path or content) differs. Budget-independent by construction, so a main
    surface and a delegated worker can assert they honored the same contract even
    with different prompt budgets. Returns :data:`EMPTY_SIGNATURE` when nothing
    applies.
    """

    try:
        sources = resolve_instruction_sources(cwd)
    except (OSError, ValueError):
        log.debug("Instruction signature resolution failed for cwd=%r.", cwd, exc_info=True)
        return EMPTY_SIGNATURE
    if not sources:
        return EMPTY_SIGNATURE

    digest = hashlib.sha256()
    # Sources are already returned in deterministic precedence order; hash each
    # file's absolute path and full (untruncated) content so the signature tracks
    # the real instruction set rather than the budget-clipped merge.
    for source in sources:
        digest.update(source.path.as_posix().encode("utf-8", "replace"))
        digest.update(b"\x00")
        digest.update(source.content.encode("utf-8", "replace"))
        digest.update(b"\x00")
    return _SIGNATURE_PREFIX + digest.hexdigest()[:_SIGNATURE_HEX_LEN]
