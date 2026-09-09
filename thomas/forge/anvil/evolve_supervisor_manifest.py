"""Signed blue-supervisor manifests and protected-path restoration."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
from pathlib import Path
from typing import Any

import tomllib

from . import evolve as _evolve
from .doppelganger import (
    _GREEN_SUPPORT_DIRS,
    _GREEN_SUPPORT_FILES,
    _IGNORE_NAMES,
    _INCLUDE_DIRS,
    _INCLUDE_FILES,
    SUPERVISOR_OWNED_PATHS,
)

BLUE_SUPERVISOR_MANIFEST_KEY = _evolve.BLUE_SUPERVISOR_MANIFEST_KEY
BLUE_SUPERVISOR_MANIFEST_SCOPES = _evolve.BLUE_SUPERVISOR_MANIFEST_SCOPES
BLUE_SUPERVISOR_MANIFEST_VERSION = _evolve.BLUE_SUPERVISOR_MANIFEST_VERSION


def _iter_scope_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for name in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        candidate = root / name
        if candidate.is_file():
            files[candidate.relative_to(root).as_posix()] = candidate
    for dirname in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        base = root / dirname
        if not base.exists():
            continue
        for candidate in base.rglob("*"):
            if candidate.is_dir():
                continue
            if candidate.name.endswith(".pyc"):
                continue
            if any(part in _IGNORE_NAMES for part in candidate.parts):
                continue
            files[candidate.relative_to(root).as_posix()] = candidate
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _blue_supervisor_manifest_key_path(repo_root: Path) -> Path:
    return Path(repo_root) / BLUE_SUPERVISOR_MANIFEST_KEY


def _load_or_create_blue_supervisor_manifest_key(repo_root: Path) -> bytes:
    key_path = _blue_supervisor_manifest_key_path(repo_root)
    if key_path.exists():
        raw = key_path.read_text(encoding="utf-8").strip()
        if raw:
            return bytes.fromhex(raw)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_hex(32)
    key_path.write_text(raw + "\n", encoding="utf-8")
    return bytes.fromhex(raw)


def _load_blue_supervisor_manifest_key(repo_root: Path) -> bytes:
    key_path = _blue_supervisor_manifest_key_path(repo_root)
    if not key_path.exists():
        raise RuntimeError("evolve session is missing blue supervisor manifest key; refusing promotion")
    raw = key_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise RuntimeError("evolve session has an empty blue supervisor manifest key; refusing promotion")
    return bytes.fromhex(raw)


def _blue_supervisor_manifest_payload(repo_root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    root = Path(repo_root)
    for scope in BLUE_SUPERVISOR_MANIFEST_SCOPES:
        base = root / scope
        if not base.exists():
            continue
        for candidate in sorted(base.rglob("*.py")):
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(root)
            if any(part in _IGNORE_NAMES for part in rel.parts):
                continue
            files[rel.as_posix()] = _sha256(candidate)
    payload = {
        "version": BLUE_SUPERVISOR_MANIFEST_VERSION,
        "scopes": list(BLUE_SUPERVISOR_MANIFEST_SCOPES),
        "files": files,
    }
    payload["manifest_sha256"] = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return payload


def _signed_blue_supervisor_manifest(repo_root: Path) -> dict[str, Any]:
    payload = _blue_supervisor_manifest_payload(repo_root)
    key = _load_or_create_blue_supervisor_manifest_key(repo_root)
    payload["signature"] = {
        "alg": "hmac-sha256",
        "value": hmac.new(key, _canonical_json_bytes(payload), hashlib.sha256).hexdigest(),
    }
    return payload


def _validate_blue_supervisor_manifest_for_promotion(repo_root: Path, session: dict[str, Any]) -> None:
    manifest = dict(session.get("blue_supervisor_manifest") or {})
    if not manifest:
        raise RuntimeError("evolve session is missing blue supervisor/anvil manifest; refusing promotion")
    signature = dict(manifest.get("signature") or {})
    if signature.get("alg") != "hmac-sha256" or not str(signature.get("value") or "").strip():
        raise RuntimeError("evolve session has an invalid blue supervisor/anvil manifest signature; refusing promotion")
    signed_value = str(signature["value"])
    unsigned_manifest = dict(manifest)
    unsigned_manifest.pop("signature", None)
    expected_manifest = _blue_supervisor_manifest_payload(repo_root)
    if unsigned_manifest != expected_manifest:
        raise RuntimeError("blue supervisor/anvil files changed since evolve session baseline; refusing promotion")
    key = _load_blue_supervisor_manifest_key(repo_root)
    actual_signature = hmac.new(key, _canonical_json_bytes(unsigned_manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signed_value, actual_signature):
        raise RuntimeError("blue supervisor/anvil manifest signature mismatch; refusing promotion")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def _normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _load_evolve_protected_paths(repo_root: Path) -> set[str]:
    relpaths = set(SUPERVISOR_OWNED_PATHS)
    config_path = repo_root / "agent_safety.toml"
    if not config_path.exists():
        return relpaths
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return relpaths
    protected = payload.get("protected")
    if not isinstance(protected, dict):
        return relpaths
    for key in ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts"):
        rows = protected.get(key) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            rel = _normalize_relpath(str(item or "")).strip()
            if rel:
                relpaths.add(rel)
    return relpaths


def _is_evolve_protected_path(rel: str, protected_paths: set[str]) -> bool:
    norm = _normalize_relpath(rel)
    if norm in protected_paths:
        return True
    return any(item.endswith("/") and norm.startswith(item.rstrip("/") + "/") for item in protected_paths if item)


def _restore_green_path_from_blue(paths, rel: str) -> None:
    rel_path = Path(_normalize_relpath(rel))
    blue_path = paths.blue_root / rel_path
    green_path = paths.green_root / rel_path
    if blue_path.exists():
        green_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blue_path, green_path)
        return
    if green_path.exists():
        green_path.unlink()
