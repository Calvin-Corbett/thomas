"""Capture a git working copy: its uncommitted work, the bases of what changed, and the commits dev lacks.

Part of the capture tool; ``capture.py`` is its command line (see its notes). A name is looked up in the module whose
code uses it, so a test that replaces one the tree capture uses (``locate``, ``make_view``, ``blobs_in_order``,
``write_bundle``, ``INDEX_LIMIT``, the before-state's ``place_state``) patches this module.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from scripts.cage.referee.gitenv import GitFailed
from scripts.cage.referee.nofollow import UnsafeEntry

from .capture_settings import Budget, Settings
from .capture_steps import (
    _archive,
    _attempt,
    _base_manifest,
    _finish,
    _holding,
    _problem,
    _ready,
    _verdicts,
    _workspace,
)
from .gitplace import (
    INDEX_LIMIT,
    IgnoreShadow,
    Unreadable,
    _norm,
    _plain_folder,
    blobs_in_order,
    check_ignored,
    commit_log,
    locate,
    ls_index,
    ls_tree,
    make_view,
    objects_size,
    read_head,
    read_refs,
    small,
    stash_tips,
    unique_count,
    write_bundle,
)
from .keep import UnsafePath, blob_id, is_text, normalise, safe_rel
from .places import keeper_fs, place_state, read_in_place, walk


def _read_index(fs, view, git_dir: Path, tmp: Path, problems: list[dict]):
    """``(entries, private copy)`` of a place's index; ``({}, None)`` with the reason in ``problems`` if unreadable.

    Design 3.3: a byte copy through the no-follow seam, read in the view. Corrupt, split, locked, too large or
    rewritten while read: the files are still saved, compared with HEAD alone.
    """
    raw = _attempt(problems, "index", None, small, fs, git_dir / "index", INDEX_LIMIT)
    if not raw:
        return {}, None
    copy, empty = tmp / "index", tmp / "empty"
    copy.write_bytes(raw)
    empty.mkdir()
    try:
        return ls_index(view, copy, empty), copy
    except GitFailed as exc:
        problems.append(_problem("index", exc))
        return {}, None


def capture_tree(place: Path, settings: Settings, main_git: Path | None = None) -> dict:
    """Save a git working copy's uncommitted work, its bases, and the commits dev lacks."""
    fs = settings.fs or keeper_fs()
    place = Path(os.path.abspath(place))
    _ready(settings, place, main_git)
    _plain_folder(fs, place)  # a place that is itself a link is refused before its .git is read or git runs
    spot = locate(fs, place, main_git)
    main_git = Path(os.path.abspath(main_git)) if main_git else None
    read = [place, spot.git_dir] if spot.linked else [place]  # a linked worktree's own git folder is read too
    before = {str(where): place_state(where, fs=fs) for where in read}
    problems: list[dict] = []  # git facts that could not be read: listed, and every readable file is still saved
    refs = read_refs(fs, spot.common, problems)
    head = _attempt(problems, "HEAD", None, read_head, fs, spot.git_dir, refs)
    objects = [spot.common / "objects"]
    if main_git is not None and _norm(main_git) != _norm(spot.common):
        objects.append(main_git / "objects")
    key = f"tree:{_norm(place)}"
    with _workspace(settings, key) as (cap_id, at, tmp, stack):
        budget = Budget(settings)
        view = make_view(settings.git_path, tmp / "place", objects)
        manifest = _base_manifest(settings, cap_id, at, "tree", key, str(place))
        manifest.update(base=head, linked=spot.linked, git_dir=str(spot.git_dir))
        head_tree = _attempt(problems, "HEAD tree", {}, ls_tree, view, head) if head else {}
        index, index_copy = _read_index(fs, view, spot.git_dir, tmp, problems)
        manifest["index_read"] = index_copy is not None
        manifest["conflicts"] = sorted(p for p, (_, _, stage, _) in index.items() if stage)
        sparse = {p for p, (_, _, _, skip) in index.items() if skip}
        manifest["skip_worktree"] = len(sparse)
        tracked = {p.lower(): p for p in [*head_tree, *index]}
        tracked_dirs = {p.lower().rsplit("/", n)[0] for p in tracked for n in range(1, p.count("/") + 1)}
        exclude = _attempt(problems, "info/exclude", None, small, fs, spot.common / "info" / "exclude")
        exclude_copy = None
        if exclude:
            exclude_copy = tmp / "exclude"
            exclude_copy.write_bytes(exclude)
        shadow = IgnoreShadow(fs, place, tmp / "s")

        def keep_dirs(dirs: list[str]) -> Iterable[str]:
            shadow.prepare(dirs, folders=True)
            ignored = check_ignored(view, shadow.root, dirs, exclude_copy, index_copy)
            return [d for d in dirs if d not in ignored or d.lower() in tracked_dirs]

        found = walk(fs, place, keep_dirs=keep_dirs, skip_root=[".git"], stop_at_nested_git=True)
        if "." in found.refused:
            raise Unreadable(f"{place} could not be listed ({found.refused['.']})")
        untracked = [p for p in found.files if p.lower() not in tracked]
        shadow.prepare(untracked, folders=False)
        ignored = check_ignored(view, shadow.root, untracked, exclude_copy, index_copy)
        refused = problems + [{"path": p, "code": c} for p, c in sorted(found.refused.items())]
        refused += [{"path": p, "code": "nested_repository"} for p in found.nested]
        archive = _archive(stack, tmp, budget)
        holdings, churn, seen, raw_of = [], [], set(), {}
        for rel in sorted(found.files):
            tpath = tracked.get(rel.lower())
            if tpath is None and rel in ignored:
                continue
            if tpath:
                seen.add(tpath)
            try:
                data, _ = read_in_place(fs, place, safe_rel(rel), settings.file_limit)
            except (UnsafeEntry, UnsafePath) as exc:
                refused.append({"path": rel, "code": getattr(exc, "code", "unsafe_path")})
                continue
            raw = raw_of[tpath or rel] = blob_id(data)
            base = head_tree.get(tpath)[1] if tpath in head_tree else None
            if base == raw:
                continue
            if base and is_text(data) and blob_id(normalise(data)) == base:
                churn.append(rel)
                continue
            status = "modified" if base else ("added" if tpath in index else "new")
            mode = (index.get(tpath) or head_tree.get(tpath) or ("100644",))[0]
            h = _holding(rel, data, status=status, mode=mode, base=base or "none", stored=f"files/{rel}")
            holdings.append(h)
            h["sha256"] = archive.add(h["stored"], data, kind="file", path=rel)["sha256"]
        gone = [p for p in tracked.values() if p not in seen and p in head_tree and p not in sparse]
        blocked = [r["path"].lower() for r in refused]
        for path in sorted(gone):
            if not any(path.lower() == b or path.lower().startswith(b + "/") for b in blocked):
                holdings.append(
                    {"path": path, "status": "deleted", "raw": None, "lf": None, "base": head_tree[path][1]}
                )
        with_base = [h for h in holdings if h["base"] != "none"]
        bases = blobs_in_order(view, [h["base"] for h in with_base], settings.file_limit)
        for h, (_, content, why) in zip(with_base, bases):
            if content is None:
                refused.append({"path": h["path"], "code": f"base_{why}"})
                continue
            h["base_stored"] = f"base/{h['path']}"
            archive.add(h["base_stored"], content, kind="base", path=h["path"])
            if h["raw"] and is_text(content) and blob_id(normalise(content)) == h["lf"]:
                h["churn"] = True
        staged = {
            p: oid
            for p, (_, oid, stage, _) in index.items()
            if not stage and oid not in (head_tree.get(p, ("", None))[1], raw_of.get(p))
        }
        order = sorted(staged)
        staged_blobs = blobs_in_order(view, [staged[p] for p in order], settings.file_limit)
        for path, (_, content, why) in zip(order, staged_blobs):
            if content is None:
                refused.append({"path": path, "code": f"staged_blob_{why}"})
                continue
            archive.add(f"index/{path}", content, kind="index", path=path)
            manifest.setdefault("staged", []).append({"path": path, "oid": staged[path], "stored": f"index/{path}"})
        dev = _verdicts(settings, tmp, main_git, holdings, by_path=True)
        nots = [dev] if dev else []
        tips = [("HEAD", head)] if head else []
        if not spot.linked:
            tips += [(n, s) for n, s in sorted(refs.items()) if not n.startswith(("refs/remotes/", "refs/tags/"))]
            stash = _attempt(refused, "stash", [], stash_tips, fs, spot.common)
            tips += [(f"stash@{{{n}}}", s) for n, s in enumerate(stash)]
        manifest["refs"] = [{"name": n, "sha": s} for n, s in sorted(refs.items())]
        bundled: list[dict] = []
        for name, sha in tips:
            try:
                count = unique_count(view, sha, nots)
            except GitFailed:
                refused.append({"path": f"ref:{name}", "code": "objects_missing"})
                continue
            if count and sha not in {b["sha"] for b in bundled}:
                bundled.append({"name": name, "sha": sha, "commits": count})
        bundle = None
        if bundled:
            shas = [b["sha"] for b in bundled]
            try:  # git writes a bundle in one go: its size is judged before it starts
                estimate = objects_size(view, shas, nots)
            except (GitFailed, ValueError):
                estimate = 0  # this git cannot measure it; the written bundle is still checked below
            budget.check(archive.size, estimate, exact=True)
            bundle = tmp / "capture.bundle"
            names = write_bundle(view, shas, nots, bundle)
            budget.check(archive.size + bundle.stat().st_size)
            for row, ref in zip(bundled, names):
                row["view_ref"] = ref
            manifest["bundle"] = {"refs": bundled, "prerequisites": nots, "estimate": estimate}
            manifest["commits"] = commit_log(view, shas, nots)
        manifest.update(dev=dev, holdings=holdings, churn=churn, refused=refused, nested=found.nested)
        return _finish(settings, manifest, tmp, archive, bundle, before)
