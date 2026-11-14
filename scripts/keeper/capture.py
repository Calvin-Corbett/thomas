"""Capture v1: save what a place holds into the keep, restore a capture, and prove a place was left as it was.

    python scripts/keeper/capture.py tree   <place>  --main <main .git>  [--label ...]   a clone or linked worktree
    python scripts/keeper/capture.py folder <place>  [--main <main .git>] [--label ...]  a plain folder, as found
    python scripts/keeper/capture.py green  <conversation id> [--path P ...]             a green, through GET only
    python scripts/keeper/capture.py restore <capture id> <new folder> [--main-objects <main .git>/objects]
    python scripts/keeper/capture.py state <place> --out <file>   /   compare <before.json> <after.json>
    python scripts/keeper/capture.py size [--keep <keep>]          the keep's file count and bytes

A tree capture holds every file that differs from the place's HEAD (tracked changes, deletions and untracked files
that are not ignored), the HEAD content of each, any staged-only content, and a bundle of the commits that dev does
not have. Line-ending-only churn is listed, not stored. A folder capture holds every file (caches left out). A green
capture holds what the caged server's read-only file route returns. Each capture records the place's state before
and after; exit code 3 means it was saved but the place changed while it was read (someone was working there).

A git fact that cannot be read (the index, HEAD, packed-refs, the stash log, info/exclude) is listed under
``refused`` and the capture goes on: every readable file is still saved, compared with whatever could be read (with
no HEAD, every file is saved as new). Only a place that cannot be listed at all, or one whose git folder redirects
somewhere unregistered, is refused whole. The size cap and the free-space floor hold while the capture is written
into the work folder, not only once it is complete.

Design sections 3 and 6 (``nostrand/FINAL-DESIGN.md``). Exit codes: 0 saved, 1 restore problems, 2 refused, 3 saved
but the place changed during the capture.

This module is the command line. The captures are ``capture_tree``, ``capture_folder`` and ``capture_green``, built
from ``capture_steps`` and ``capture_settings``, and their names are re-exported here. A name is looked up in the
module whose code uses it, so a test that replaces one patches that module, not this one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make ``scripts.*`` importable from the repository root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cage.referee.gitenv import GitFailed  # noqa: E402
from scripts.cage.referee.nofollow import UnsafeEntry  # noqa: E402
from scripts.keeper.capture_folder import capture_folder  # noqa: E402
from scripts.keeper.capture_green import capture_green, listed_files  # noqa: E402
from scripts.keeper.capture_settings import (  # noqa: E402
    CACHE_FOLDERS,
    CID,
    DEFAULT_GIT,
    DEFAULT_KEEP,
    DEFAULT_SERVER,
    DEFAULT_WORK,
    GB,
    SUBSTANTIAL,
    Budget,
    CaptureRefused,
    Settings,
)
from scripts.keeper.capture_tree import capture_tree  # noqa: E402
from scripts.keeper.gitplace import Unreadable  # noqa: E402
from scripts.keeper.keep import RestoreFailed, restore  # noqa: E402
from scripts.keeper.places import compare_states, place_state  # noqa: E402
from scripts.keeper.private import why_not_private  # noqa: E402


def _settings(args) -> Settings:
    git = args.git or (DEFAULT_GIT if os.path.isfile(DEFAULT_GIT) else shutil.which("git") or "")
    if not os.path.isabs(git) or not os.path.isfile(git):
        raise CaptureRefused("git must be named by an absolute path (--git)")
    return Settings(
        keep=Path(args.keep),
        work=Path(args.work),
        git_path=git,
        label=args.label,
        provenance=args.provenance,
        cap_bytes=int(args.cap_gb * GB),
        min_free_bytes=int(args.min_free_gb * GB),
        state_dir=Path(args.state_dir) if args.state_dir else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capture.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("tree", "folder", "green", "restore"):
        p = sub.add_parser(name)
        p.add_argument("target")
        if name == "restore":
            p.add_argument("dest")
            p.add_argument("--main-objects")
            p.add_argument("--dry-run", action="store_true")
        p.add_argument("--keep", default=DEFAULT_KEEP)
        p.add_argument("--work", default=DEFAULT_WORK)
        p.add_argument("--git")
        p.add_argument("--main", help="the main repository's .git folder (dev is read from it)")
        p.add_argument("--label", default="")
        p.add_argument("--provenance", default="")
        p.add_argument("--cap-gb", type=float, default=5.0)
        p.add_argument("--min-free-gb", type=float, default=15.0)
        p.add_argument("--state-dir")
        if name == "folder":
            p.add_argument("--exclude", action="append", default=None, help="folder names to leave out")
        if name == "green":
            p.add_argument("--path", action="append", default=[])
            p.add_argument("--paths-from", help="a saved /api/self/projects listing to take changed_files from")
            p.add_argument("--server", default=DEFAULT_SERVER)
            p.add_argument("--base")
    st = sub.add_parser("state")
    st.add_argument("target")
    st.add_argument("--out", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("before")
    cmp_.add_argument("after")
    size = sub.add_parser("size")
    size.add_argument("--keep", default=DEFAULT_KEEP)
    args = parser.parse_args(argv)
    if args.cmd == "size":
        files = [p for p in Path(args.keep).rglob("*") if p.is_file()]
        print(json.dumps({"keep": args.keep, "files": len(files), "bytes": sum(p.stat().st_size for p in files)}))
        return 0
    try:
        if args.cmd == "state":  # a state names every file of the place and its hash: it goes only where captures go
            reason = why_not_private(Path(os.path.abspath(args.out)).parent, [Path(args.target)])
            if reason:
                raise CaptureRefused(f"{reason}; nothing written")
            Path(args.out).write_text(json.dumps(place_state(Path(args.target))), "utf-8")
            return 0
        if args.cmd == "compare":
            lines = compare_states(*(json.loads(Path(p).read_text("utf-8")) for p in (args.before, args.after)))
            print("\n".join(lines) if lines else "same")
            return 1 if lines else 0
        settings = _settings(args)
        main_git = Path(args.main) if args.main else None
        if args.cmd == "restore":
            objects = Path(args.main_objects) if args.main_objects else None
            report = restore(settings.keep, args.target, Path(args.dest), git_path=settings.git_path,
                             main_objects=objects, dry_run=args.dry_run)  # fmt: skip
            print(json.dumps(report, indent=1))
            return 0 if report["ok"] else 1
        if args.cmd == "tree":
            result = capture_tree(Path(args.target), settings, main_git)
        elif args.cmd == "folder":
            exclude = CACHE_FOLDERS if args.exclude is None else args.exclude
            result = capture_folder(Path(args.target), settings, main_git, exclude)
        else:
            paths = list(args.path)
            if args.paths_from:
                listing = json.loads(Path(args.paths_from).read_text("utf-8"))
                rows = listing if isinstance(listing, list) else listing.get("projects", [])
                paths += next(
                    (r.get("changed_files") or [] for r in rows if r.get("conversation_id") == args.target), []
                )
            paths = paths or listed_files(args.server, args.target)
            result = capture_green(args.target, paths, settings, args.server, main_git, args.base)
    except (CaptureRefused, Unreadable, RestoreFailed, GitFailed, UnsafeEntry, OSError, MemoryError) as exc:
        print(json.dumps({"refused": f"{type(exc).__name__}: {exc}"}))  # MemoryError: something too big to hold
        return 2
    print(json.dumps(result, indent=1))
    return 0 if result["state_same"] in (True, None) else 3


if __name__ == "__main__":
    sys.exit(main())
