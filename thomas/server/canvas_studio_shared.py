"""What the Canvas routes and Thomas's own workspace helpers both use.

The saved Canvas layouts live under ``<root>/.thomas/canvas/<id>.json``. The Canvas routes in
``thomas.server.routes.canvas_studio_routes`` and the workspace helpers that save or read a layout for an agent
(``workspace_specialist_actions``, ``workspace_specialist_readback``, ``workspace_specialist_validation``) all go
through these functions. They sit here, with no web code, so the Canvas routes can be turned off without taking the
helpers' way to the same folder with them.

Layouts are written to a temporary file in the same folder and then moved into place, so a reader never sees half
of one.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

_REPO_MARKERS = ("pyproject.toml", "thomas", ".git")
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def _default_repo_root() -> Path:
    here = Path.cwd()
    for base in (here, *here.parents):
        if any((base / marker).exists() for marker in _REPO_MARKERS):
            return base
    return here


def _canvas_dir(root: Path) -> Path:
    return Path(root) / ".thomas" / "canvas"


def _resolve_default_profile(root: Path) -> str:
    """Resolve the user's persisted default model profile (evolve idiom).

    A UI-Studio AI action should think with the model the user picked in the
    chat UI. Resolved once at the API boundary; fully guarded so a config/import
    failure never hard-fails the route (it degrades to an empty profile, and the
    LLM routes then return a clear error instead of crashing).
    """
    try:
        from thomas.core.config import load_config
        from thomas.preferences.model_resolution import resolve_effective_model

        cfg = load_config(Path(root) / "thomas.toml")
        profile, _ = resolve_effective_model(cfg, user_id="default")
        return str(profile or "").strip()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return ""


def _safe_spec_id(spec: dict[str, Any]) -> str:
    raw = str(spec.get("id") or "").strip()
    if raw and _ID_RE.match(raw):
        return raw
    return "spec_" + uuid.uuid4().hex


def _write_spec(root: Path, spec: dict[str, Any]) -> str:
    directory = _canvas_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    spec_id = _safe_spec_id(spec)
    spec["id"] = spec_id
    target = directory / f"{spec_id}.json"
    tmp = directory / f".{spec_id}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return spec_id


def _read_spec(root: Path, spec_id: str) -> dict[str, Any] | None:
    if not _ID_RE.match(spec_id or ""):
        return None
    path = _canvas_dir(root) / f"{spec_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
