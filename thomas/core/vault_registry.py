"""The Vault — a readable inventory of the safety-critical paths that agent tools
may never modify, regardless of any guardrail preset or user toggle.

This module *describes* the policy; it does not enforce it. The set is parsed
from ``agent_safety.toml`` (``[runtime_protection]``) on first use, not at import,
and it is therefore config-derived rather than code-local: point ``_REPO_ROOT`` at
a tree with a weakened config and the set shrinks to match.

Enforcement lives in ``thomas/tools/filesystem.py::_is_protected_runtime_path``,
which keeps its own hardcoded copy of the list **on purpose** — see the comment at
``_HARDCODED_PROTECTED_DIRS`` and the ``[runtime_protection]`` preamble in
``agent_safety.toml``. That guard must hold even when the config is missing or
corrupt, and this module cannot offer that: ``_load`` swallows a parse failure and
returns empty sets, so a corrupt ``agent_safety.toml`` makes every
``is_vault_protected`` answer ``False``. It fails open; the filesystem guard fails
closed. Do not "unify" the two by pointing the filesystem guard at this module.

The two sets are deliberately **not** identical. They list the same seven protected
directories, but the filesystem guard protects four files this registry does not:
``runtime/.runtime_protection_disabled``, ``runtime/.runtime_protection_key``,
``runtime/.breakglass_window`` and ``runtime/.breakglass_window_key``. Those are the
bypass mechanism itself (see PR runtime-protection-fix-2026-05-27), so widening this
registry is not a documentation change — it is a security change.
``tests/test_guardrails_vault.py`` pins the difference in both directions.

Consumers, as of 2026-07-31: none in production. Nothing under ``thomas/`` imports
this module; the only caller of ``is_vault_protected`` is
``tests/test_guardrails_vault.py``. It exists as an audit/reporting surface for
guardrail UI that has not landed yet.

The Vault is orthogonal to the toggleable guardrail policy (see
``thomas.server.guardrails_state``): guardrails can be relaxed; the paths listed
here are ones the filesystem guard refuses regardless.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import tomllib

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The protected-operation families the Vault covers (documentation/audit).
VAULT_CATEGORIES: tuple[str, ...] = (
    "secrets",  # secret stores / API keys
    "protected_files",  # top-level policy files (agent_safety.toml, gates config, ...)
    "protected_dirs",  # the engine dirs (thomas/core, thomas/agent, thomas/tools, ...)
    "enforcement",  # gate scripts / enforcement integrity
    "breakglass",  # breakglass auth flags
    "signed_flags",  # signed runtime flags (QuickBuilder, etc.)
    "key_read",  # runtime-protection key material
)


def _norm(path: object) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./").strip("/")


@lru_cache(maxsize=1)
def _load() -> tuple[frozenset[str], tuple[str, ...]]:
    """Return (protected_files, protected_dirs) parsed from agent_safety.toml."""
    files: set[str] = set()
    dirs: list[str] = []
    try:
        data = tomllib.loads((_REPO_ROOT / "agent_safety.toml").read_text(encoding="utf-8"))
        files.update(_norm(f) for f in (data.get("protected_files") or []))
        rp = data.get("runtime_protection") or {}
        files.update(_norm(f) for f in (rp.get("protected_files") or []))
        dirs.extend(_norm(d) for d in (rp.get("protected_dirs") or []))
    except Exception:  # pragma: no cover - missing/malformed config -> empty Vault, fs layer still guards
        pass
    return frozenset(f for f in files if f), tuple(d for d in dirs if d)


def vault_protected_files() -> frozenset[str]:
    return _load()[0]


def vault_protected_dirs() -> tuple[str, ...]:
    return _load()[1]


def is_vault_protected(rel_path: str) -> bool:
    """True if a repo-relative path is a Vault-protected file or under a protected dir."""
    p = _norm(rel_path)
    if not p:
        return False
    files, dirs = _load()
    if p in files:
        return True
    return any(p == d or p.startswith(f"{d}/") for d in dirs)
