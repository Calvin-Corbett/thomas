"""Profile resolution and isolated candidate-root preparation for Evolve."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from thomas.core.config import load_config
from thomas.core.model_resolution import resolve_effective_model, resolve_model_profile_name

from .doppelganger import _GREEN_SUPPORT_DIRS, _GREEN_SUPPORT_FILES, _IGNORE_NAMES, _INCLUDE_DIRS, _INCLUDE_FILES
from .evolve_delta_analysis import _delta_fingerprint_for_root
from .evolve_supervisor_manifest import _validate_blue_supervisor_manifest_for_promotion


def _preferred_evolve_codex_profile(config: Any) -> str:
    if "openai_codex" in config.models:
        return "openai_codex"
    if "codex" in config.models:
        return "codex"
    return ""


def _normalize_evolve_profile_name(config: Any, profile_name: str | None) -> str:
    requested = str(profile_name or "").strip()
    if not requested:
        return ""
    resolved = resolve_model_profile_name(config, requested)
    if resolved:
        return resolved
    if requested.lower() == "codex":
        return _preferred_evolve_codex_profile(config) or requested
    return requested


def _resolve_evolve_profile(repo_root: Path, requested_profile: str = "") -> str:
    config = load_config(repo_root / "thomas.toml")
    requested = _normalize_evolve_profile_name(config, requested_profile)
    env_profile = _normalize_evolve_profile_name(config, os.environ.get("THOMAS_DEFAULT_MODEL", ""))
    resolved_profile, _ = resolve_effective_model(
        config,
        cli_profile=requested or None,
        env_profile=env_profile or None,
    )
    resolved = str(resolved_profile or "").strip()
    preferred_codex = _preferred_evolve_codex_profile(config)
    if not resolved and preferred_codex:
        return preferred_codex
    if not str(requested_profile or "").strip() and resolved.lower() == "local" and preferred_codex:
        return preferred_codex
    return resolved


def _evolve_secret_root(repo_root: Path) -> Path:
    override = str(os.environ.get("THOMAS_SECRET_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return load_config(repo_root / "thomas.toml").memory.root_path / ".thomas"


def _copy_tree_without_caches(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for candidate in src.rglob("*"):
        rel = candidate.relative_to(src)
        if any(part in _IGNORE_NAMES for part in rel.parts):
            continue
        target = dst / rel
        if candidate.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)


def _prepare_verification_root(paths, *, source_root: Path | None = None, dirname: str = "verify") -> Path:
    """Build a clean exam mirror from scoped green files only."""
    source = Path(source_root or paths.green_root)
    verify_root = paths.dg_root / dirname
    if verify_root.exists():
        shutil.rmtree(verify_root)
    verify_root.mkdir(parents=True, exist_ok=True)
    for support_dir in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        src = source / support_dir
        if src.exists():
            _copy_tree_without_caches(src, verify_root / support_dir)
    for filename in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        src = source / filename
        if src.exists():
            target = verify_root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    return verify_root


def _prepare_delta_candidate_root(paths, delta: dict[str, Any], *, dirname: str = "promote-candidate") -> Path:
    """Build current-blue plus the verified green delta for supervisor review."""
    candidate_root = paths.dg_root / dirname
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    candidate_root.mkdir(parents=True, exist_ok=True)
    for include_dir in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        src = paths.blue_root / include_dir
        if src.exists():
            _copy_tree_without_caches(src, candidate_root / include_dir)
    for include_file in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        src = paths.blue_root / include_file
        if src.exists():
            target = candidate_root / include_file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for rel in sorted(str(item) for item in (delta.get("changed_files") or [])):
        src = paths.green_root / rel
        target = candidate_root / rel
        if src.exists():
            if src.is_dir():
                raise RuntimeError(f"candidate delta path is a directory: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
    return candidate_root


def _validate_verified_delta_for_promotion(paths, session: dict[str, Any], expected_delta: dict[str, Any]) -> list[str]:
    changed_files = list(expected_delta.get("changed_files") or [])
    current_fingerprint = _delta_fingerprint_for_root(paths.green_root, expected_delta)
    expected_fingerprint = dict(session.get("verified_delta_fingerprint") or {})
    if not expected_fingerprint:
        raise RuntimeError("evolve session is missing verified delta fingerprint; refusing promotion")
    if expected_fingerprint != current_fingerprint:
        raise RuntimeError("green tree changed since evolve session verification; refusing promotion")
    expected_blue_base = dict(session.get("blue_delta_base_fingerprint") or {})
    if not expected_blue_base:
        raise RuntimeError("evolve session is missing blue delta base fingerprint; refusing promotion")
    current_blue_base = _delta_fingerprint_for_root(paths.blue_root, expected_delta)
    if expected_blue_base != current_blue_base:
        raise RuntimeError("blue target files changed since evolve session baseline; refusing promotion")
    _validate_blue_supervisor_manifest_for_promotion(paths.blue_root, session)
    return changed_files
