"""Capture a plain folder: every file as found, caches left out, and no git run on it.

Part of the capture tool; ``capture.py`` is its command line (see its notes).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from scripts.cage.referee.nofollow import UnsafeEntry

from .capture_settings import CACHE_FOLDERS, Budget, Settings
from .capture_steps import _archive, _base_manifest, _finish, _holding, _ready, _verdicts, _workspace
from .gitplace import Unreadable, _norm, _plain_folder
from .keep import UnsafePath, safe_rel
from .places import keeper_fs, place_state, read_in_place, walk


def capture_folder(
    place: Path, settings: Settings, main_git: Path | None = None, exclude: Iterable[str] = CACHE_FOLDERS
) -> dict:
    """Save every file of a plain folder as found (no git is run on it; a ``.git`` inside is saved as files)."""
    fs = settings.fs or keeper_fs()
    place = Path(os.path.abspath(place))
    _ready(settings, place, main_git)
    _plain_folder(fs, place)
    before = {str(place): place_state(place, fs=fs)}
    key = f"folder:{_norm(place)}"
    with _workspace(settings, key) as (cap_id, at, tmp, stack):
        manifest = _base_manifest(settings, cap_id, at, "folder", key, str(place))
        found = walk(fs, place, exclude_names=exclude)
        if "." in found.refused:
            raise Unreadable(f"{place} could not be listed ({found.refused['.']})")
        refused = [{"path": p, "code": c} for p, c in sorted(found.refused.items())]
        archive = _archive(stack, tmp, Budget(settings))
        holdings = []
        for rel in sorted(found.files):
            try:
                data, _ = read_in_place(fs, place, safe_rel(rel), settings.file_limit)
            except (UnsafeEntry, UnsafePath) as exc:
                refused.append({"path": rel, "code": getattr(exc, "code", "unsafe_path")})
                continue
            h = _holding(rel, data, status="file", stored=f"files/{rel}")
            h["sha256"] = archive.add(h["stored"], data, kind="file", path=rel)["sha256"]
            holdings.append(h)
        manifest["dev"] = _verdicts(settings, tmp, main_git, holdings, by_path=False)
        manifest.update(holdings=holdings, refused=refused, excluded=found.excluded)
        return _finish(settings, manifest, tmp, archive, None, before)
