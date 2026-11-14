"""The steps every capture shares: readiness, the private workspace, the archive, verdicts, and writing the keep.

``capture_tree``, ``capture_folder`` and ``capture_green`` are built from these; ``capture.py`` is the command line
(see its notes). A name is looked up in the module whose code uses it, so a test that replaces one used here
(``ArchiveWriter``, ``new_capture_id``, the after-state's ``place_state``) patches this module.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path

from scripts.cage.referee.gitenv import GitFailed, GitRunner
from scripts.cage.referee.nofollow import UnsafeEntry

from .capture_settings import SUBSTANTIAL, Budget, CaptureRefused, Settings
from .gitplace import (
    Unreadable,
    _plain_folder,
    blobs_in_order,
    check_alternates,
    ls_tree,
    make_view,
    present,
    read_refs,
)
from .keep import FORMAT, ArchiveWriter, blob_id, is_text, new_capture_id, normalise, store_capture
from .places import compare_states, keeper_fs, place_state
from .private import why_not_private


def _ready(settings: Settings, place: Path | None, main_git: Path | None) -> None:
    """The keep must exist; it, the work folder and the state folder must be private (R3); the work drive has room.

    Private means ``private.why_not_private``: reached through no link, not inside the place or a folder the cage
    reads, and readable by nobody but you. The main repository's objects are read through alternates, so its folders
    get the same checks as a place's.
    """
    if not Path(settings.keep).is_dir():
        raise CaptureRefused(f"the keep {settings.keep} does not exist (enable_keep.ps1 makes it); nothing written")
    for path in (settings.keep, settings.work, settings.state_dir):
        if path is not None:
            reason = why_not_private(path, [place] if place else [])
            if reason:
                raise CaptureRefused(f"{reason}; nothing written")
    Budget(settings).check(0)
    if main_git is not None:
        fs = settings.fs or keeper_fs()
        for folder in (Path(main_git), Path(main_git) / "objects"):
            _plain_folder(fs, folder)
        check_alternates(fs, Path(main_git) / "objects")


@contextmanager
def _workspace(settings: Settings, place_key: str):
    at = settings.now()
    cap_id = new_capture_id(place_key, at)
    tmp = Path(settings.work) / f"tmp-{cap_id}"
    tmp.mkdir(parents=True)
    try:
        with ExitStack() as stack:  # an archive still open when the capture stops is closed before the folder goes
            yield cap_id, at, tmp, stack
    finally:
        shutil.rmtree(tmp, onexc=lambda f, p, _e: (os.chmod(p, stat.S_IWRITE), f(p)))


def _archive(stack: ExitStack, tmp: Path, budget: Budget) -> ArchiveWriter:
    return stack.enter_context(ArchiveWriter(tmp / "capture.zip", guard=budget.check))


def _problem(what: str, exc: Exception) -> dict:
    return {"path": f"git:{what}", "code": "unreadable", "detail": str(exc)[:300]}


def _attempt(problems: list[dict], what: str, default, func, *args):
    """``func(*args)``, or ``default`` with the failure listed in ``problems``: one git fact never loses the rest."""
    try:
        return func(*args)
    except (Unreadable, GitFailed, UnsafeEntry) as exc:
        problems.append(_problem(what, exc))
        return default


def _substantial(data: bytes) -> bool:
    return len(re.sub(rb"\s", b"", data)) >= SUBSTANTIAL


def _verdicts(settings: Settings, tmp: Path, main_git: Path | None, holdings: list[dict], by_path: bool) -> str | None:
    """Fill each holding's verdict against the main repository (design 5.2, without HUNKS_ON_DEV in v1)."""
    if main_git is None:
        for h in holdings:
            h["verdict"] = "UNJUDGED"
        return None
    fs = settings.fs or keeper_fs()
    dev = read_refs(fs, Path(main_git)).get("refs/heads/dev")
    view = make_view(settings.git_path, tmp / "main", [Path(main_git) / "objects"])
    tree = ls_tree(view, dev) if dev else {}
    dev_blobs = {oid for _, oid in tree.values()}
    live = [h for h in holdings if h.get("raw")]
    have = present(view, [h["raw"] for h in live] + [h["lf"] for h in live])
    need = sorted({tree[h["path"]][1] for h in live if by_path and h["path"] in tree})
    dev_lf = {
        oid: blob_id(normalise(data))
        for oid, data, _ in blobs_in_order(view, need, settings.file_limit)
        if data is not None and is_text(data)
    }
    for h in holdings:
        on_dev = tree.get(h["path"], ("", None))[1] if by_path else None
        if not h.get("raw"):
            h["verdict"] = "ON_DEV" if by_path and on_dev is None else "DELETE_PENDING"
        elif on_dev and (on_dev in (h["raw"], h["lf"]) or dev_lf.get(on_dev) == h["lf"]):
            h["verdict"] = "ON_DEV"
        elif (h["raw"] in dev_blobs or h["lf"] in dev_blobs) and h.get("substantial"):
            h["verdict"] = "ELSEWHERE_DEV"
        elif h["raw"] in have or h["lf"] in have:
            h["verdict"] = "IN_GIT"
        else:
            h["verdict"] = "ONLY_COPY"
    return dev


def _holding(rel: str, data: bytes, **facts) -> dict:
    lf = blob_id(normalise(data)) if is_text(data) else blob_id(data)
    return {"path": rel, "raw": blob_id(data), "lf": lf, "size": len(data), "substantial": _substantial(data), **facts}


def _captured_differs(manifest: dict, before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """A stored file whose bytes are not what the place held before and after the capture: it changed while read.

    The before and after states hash each file on their own, so a file swapped while it was read and put back before
    the after-state (same size and write time) would leave both states equal; the bytes the capture stored are the
    witness. Files bigger than the state's hash limit carry no hash there and are not compared.
    """
    root = manifest.get("abs_path")
    if root not in before:
        return []
    lines = []
    for h in manifest["holdings"]:
        if not h.get("sha256") or not str(h.get("stored", "")).startswith("files/"):
            continue
        for label, state in (("before", before[root]), ("after", after[root])):
            entry = state["entries"].get(h["path"])
            seen = entry[3] if entry and entry[0] == "file" else None
            if isinstance(seen, str) and len(seen) == 64 and seen != h["sha256"]:
                lines.append(f"{root}: captured: {h['path']} is not what the place held {label} the capture")
                break
    return lines


def _finish(
    settings: Settings,
    manifest: dict,
    tmp: Path,
    archive: ArchiveWriter,
    bundle: Path | None,
    before: dict[str, dict] | None,
) -> dict:
    """Check size and space, take the after-state of every place read, and write the capture into the keep."""
    archive.close()
    parts = {"zip": archive.path} if archive.entries else {}
    if bundle is not None:
        parts["bundle"] = bundle
    total = sum(p.stat().st_size for p in parts.values())
    if total > settings.cap_bytes:
        raise CaptureRefused(f"this capture is {total} bytes, over the {settings.cap_bytes}-byte cap; nothing written")
    free = shutil.disk_usage(settings.keep).free
    if free - total < settings.min_free_bytes:
        raise CaptureRefused(f"writing {total} bytes would leave {free - total} free, under the floor; nothing written")
    manifest["entries"] = archive.entries
    if before:
        after = {where: place_state(Path(where), fs=settings.fs or keeper_fs()) for where in before}
        changes = [f"{where}: {line}" for where in before for line in compare_states(before[where], after[where])]
        changes += _captured_differs(manifest, before, after)
        digests = {where: {"before": before[where]["digest"], "after": after[where]["digest"]} for where in before}
        manifest["state"] = {"same": not changes, "changes": changes[:200], "places": digests}
        if settings.state_dir:
            Path(settings.state_dir).mkdir(parents=True, exist_ok=True)
            for number, where in enumerate(before):
                for name, state in (("before", before[where]), ("after", after[where])):
                    out = Path(settings.state_dir) / f"{manifest['id']}.{number}.{name}.json"
                    out.write_text(json.dumps(state), "utf-8")
    for _ in range(3):
        try:
            written = store_capture(Path(settings.keep), manifest, parts)
            break
        except FileExistsError:
            manifest["id"] = new_capture_id(manifest["place"], settings.now())
    else:
        raise CaptureRefused("three capture ids in a row were already taken in the keep")
    only = sum(1 for h in manifest["holdings"] if h.get("verdict") == "ONLY_COPY" and not h.get("churn"))
    return {
        "id": manifest["id"],
        "kind": manifest["kind"],
        "manifest": str(written),
        "holdings": len(manifest["holdings"]),
        "churn_flagged": sum(1 for h in manifest["holdings"] if h.get("churn")),
        "only_copy": only,
        "refused": len(manifest["refused"]),
        "commits": sum(r["commits"] for r in (manifest.get("bundle") or {}).get("refs", [])),
        "bytes": total,
        "state_same": (manifest.get("state") or {}).get("same"),
    }


def _base_manifest(settings: Settings, cap_id: str, at: datetime, kind: str, key: str, where: str) -> dict:
    version = ""
    try:
        version = GitRunner(settings.git_path, Path(os.devnull), Path(os.devnull), Path(settings.work)).text(
            "--version", repo=False
        )
    except (GitFailed, OSError, ValueError):
        pass
    return {
        "format": FORMAT,
        "id": cap_id,
        "kind": kind,
        "place": key,
        "label": settings.label,
        "provenance": settings.provenance,
        "abs_path": where,
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous": None,
        "full": True,
        "base": None,
        "dev": None,
        "holdings": [],
        "churn": [],
        "refused": [],
        "bundle": None,
        "commits": [],
        "state": None,
        "tool": {"name": "scripts/keeper/capture.py", "version": 1, "git": version},
    }
