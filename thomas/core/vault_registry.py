"""The Vault — safety-critical paths that agent tools may NEVER modify, regardless
of any guardrail preset or user toggle.

Enumerated from ``agent_safety.toml`` (``[runtime_protection]`` + top-level
``protected_files``) and loaded at import so the set is code-local and cannot be
weakened at runtime. This is the single, testable source of truth that mirrors the
hard enforcement already in ``thomas/tools/filesystem.py`` — the rest of the system
consults ``is_vault_protected`` instead of re-deriving the list.

The Vault is orthogonal to the toggleable guardrail policy (see
``thomas.server.guardrails_state``): guardrails can be relaxed; the Vault cannot.
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
