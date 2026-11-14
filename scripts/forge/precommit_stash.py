#!/usr/bin/env python3
"""Recover unstaged work that a failed commit left in pre-commit's own stash.

WHY THIS EXISTS. A commit that fails a gate does not simply stop. pre-commit
clears unstaged changes before it runs any hook and restores them afterwards --
but where a hook's auto-fixes conflict with what it stashed, its recovery path
re-checks-out the tree and re-applies. If that second apply also fails, the edit
survives ONLY inside the patch pre-commit wrote. `git status` then reports the
file UNMODIFIED, so the loss reads as "nothing changed" rather than as damage,
and retrying destroys the next attempt too. Seven edits went that way in one
session on 2026-09-09, and the cause was misdiagnosed twice as another agent
rewriting the tree.

WHY IT IS NOT A HOOK. An earlier attempt snapshotted the tree from inside the
hook chain. It could not work: pre-commit runs `git checkout -- .` BEFORE
yielding to the first hook (`pre_commit/staged_files_only.py`, `_CHECKOUT_CMD`),
so inside a hook the working tree already equals the index and `git diff HEAD`
sees only staged content -- exactly the part that gets restored rather than
lost. Worse, anything in the commit path can fail the commit, and a recovery
tool that adds a new way to lose work is not a recovery tool.

So this reads what pre-commit already saved, and runs only when asked. Nothing
here executes during a commit.

THE PATCHES. `~/.cache/pre-commit/patch<unix-ts>-<pid>`, written by
`git diff-index --ignore-submodules --binary --exit-code --no-color
--no-ext-diff <tree>`. pre-commit never deletes them, so most represent runs
that recovered fine; a stash is interesting only when its content is NOT in the
tree. Listing says which those are, and shows only those by default.

HOW IT PUTS WORK BACK. Applying the stash as a diff is tried first, because
when it works it is exact and touches nothing else. In the case this tool
exists for it does NOT work: the hook rewrote the same file and staged the
rewrite, so the diff no longer matches the tree or the index. That is not the
same as the work being gone. The patch names its own pre-image blob, so each
file is rebuilt from that blob in a scratch repository and copied back --
see `extract`. Whatever gets displaced is kept beside the file as
`<name>.pre-restore`, and `--restore --dry-run` reports the whole plan
without writing any of it.

WHAT IT CANNOT TELL YOU. The cache is per machine, not per worktree or per
agent -- 833 stashes on this one, from every commit anything has attempted.
A patch is named `patch<unix-ts>-<pid>` and carries no record of who wrote
it or which tree it came from, so a stash from another agent's commit looks
exactly like one of yours. Read the file list before restoring; that list
is the only ownership signal there is, and inventing a better-looking one
would just be a guess wearing a confident label.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PATCH_NAME = re.compile(r"^patch(\d+)-(\d+)$")

# Spelled with chr() rather than as escapes on purpose: this file has been
# written through shells that collapse a doubled backslash, which turns a
# two-character escape into the raw control byte and makes the module
# unparseable. Nothing here needs to be terse.
NUL = bytes((0,))
TAB = bytes((9,))
CR_TEXT = chr(13)


def cache_dir() -> Path:
    """Where pre-commit keeps its stashes, honouring its own env overrides."""
    explicit = os.environ.get("PRE_COMMIT_HOME")
    if explicit:
        return Path(explicit)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "pre-commit"
    return Path.home() / ".cache" / "pre-commit"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)


def patches(directory: Path) -> list[tuple[int, Path]]:
    """(unix seconds, path) for every stash pre-commit left, oldest first."""
    found: list[tuple[int, Path]] = []
    if not directory.is_dir():
        return found
    for entry in directory.iterdir():
        match = PATCH_NAME.match(entry.name)
        if match and entry.is_file() and entry.stat().st_size:
            found.append((int(match.group(1)), entry))
    return sorted(found)


def state(repo: Path, patch: Path) -> str:
    """Whether this stash holds work the tree is missing.

    `--check -R` succeeding means the change is ALREADY in the tree, so applying
    it would be a no-op at best. That is the common case and not worth showing.
    """
    if _git(repo, "apply", "--check", "-R", str(patch)).returncode == 0:
        return "already-in-tree"
    if _git(repo, "apply", "--check", str(patch)).returncode == 0:
        return "RECOVERABLE"
    return "conflicts"


def files_in(repo: Path, patch: Path) -> list[str]:
    out = _git(repo, "apply", "--numstat", str(patch)).stdout.decode("utf-8", "replace")
    return re.findall(r"^[\d-]+\t[\d-]+\t(.+)$", out, re.M)


def apply_patch(repo: Path, patch: Path) -> tuple[bool, str]:
    """Apply the way pre-commit does, including its autocrlf retry (its #570).

    Plain apply only, and deliberately so. `git apply` verifies every hunk
    before it writes anything, so a failure here leaves the tree exactly as it
    was -- which is the whole contract this function is allowed to make.
    `--3way` breaks that contract: it implies --index, and on a partial merge it
    writes conflict markers into the working tree and stages what it merged
    before returning non-zero. A run that reported "nothing was changed" had in
    fact replaced the file with `<<<<<<< ours` and buried the hook's version.
    Everything --3way could have salvaged, extract() salvages against a scratch
    tree that has no way to damage this one.
    """
    for base in (("apply", "--whitespace=nowarn"),):
        if _git(repo, *base, str(patch)).returncode == 0:
            return True, "applied"
        retry = _git(repo, "-c", "core.autocrlf=false", *base, str(patch))
        if retry.returncode == 0:
            return True, "applied with autocrlf=false"
        last = retry.stderr.decode("utf-8", "replace")
    return False, " ".join(last.split())



# --- extraction ---------------------------------------------------------
#
# When a stash will not apply as a diff, the work is still fully described by
# it, and the reason for the failure is knowable: `git apply` places a diff
# against the tree and index as they are NOW, and in the case this tool exists
# for they have moved. The hook auto-fixed the same file and staged the fix, so
# the index entry is a different blob and even a three-way merge gives up with
# "does not exist in index".
#
# The patch does not actually depend on any of that. Its `index <old>..<new>`
# line names the pre-image blob by hash, that blob is still in the object
# database, and applying the diff to THAT reproduces the post-image byte for
# byte. So rebuild each file in a scratch tree the patch does agree with, and
# copy the result out. Nothing here reads the live index, and nothing here can
# fail halfway and leave the working tree worse than it found it.


def _split_patch(raw: bytes) -> list[bytes]:
    """One standalone single-file patch per section.

    Splitting on a column-0 "diff --git " is safe: every body line of a diff is
    prefixed (space, +, -, @ or a backslash), and the base85 payload of a
    --binary diff contains no spaces, so that header cannot occur as content.
    """
    parts = re.split(rb"(?m)^(?=diff --git )", raw)
    return [part for part in parts if part.startswith(b"diff --git ")]


def _file_path(repo: Path, chunk_file: Path, chunk: bytes) -> str | None:
    """Ask git for the path, so quoting and odd bytes stay its problem."""
    out = _git(repo, "apply", "--numstat", "-z", str(chunk_file)).stdout
    fields = out.split(NUL)[0].split(TAB)
    if len(fields) == 3 and fields[2]:
        return fields[2].decode("utf-8", "replace")
    match = re.search(rb"(?m)^[+][+][+] b/(.+)$", chunk)
    if match:
        return match.group(1).decode("utf-8", "replace").rstrip(CR_TEXT)
    return None


def _extract_one(repo: Path, chunk: bytes, stage: Path, seq: int, dry_run: bool) -> tuple[str, str, str]:
    """Rebuild one file from its own pre-image. Returns (path, outcome, note)."""
    chunk_file = stage / f".chunk{seq}.patch"
    chunk_file.write_bytes(chunk)

    path = _file_path(repo, chunk_file, chunk)
    if path is None:
        return ("<unnamed>", "skipped", "this section of the patch names no file")

    pair = re.search(rb"(?m)^index ([0-9a-f]+)[.][.]([0-9a-f]+)", chunk)
    if pair is None:
        return (path, "skipped", "no index line, so the pre-image cannot be named")
    old = pair.group(1).decode("ascii")

    target = stage / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    if set(old) != {"0"}:   # all zeros means the patch creates the file
        blob = _git(repo, "cat-file", "blob", old)
        if blob.returncode != 0:
            return (path, "unrecoverable", f"pre-image blob {old} is not in the object database")
        target.write_bytes(blob.stdout)

    applied = _git(stage, "apply", "--whitespace=nowarn", str(chunk_file))
    if applied.returncode != 0:
        detail = " ".join(applied.stderr.decode("utf-8", "replace").split())
        return (path, "unrecoverable", detail or "the patch did not apply to its own pre-image")

    if not target.exists():
        return (path, "not-applied", "the stash DELETES this file; your copy was left alone")

    recovered = target.read_bytes()
    live = repo / path
    if live.exists() and live.read_bytes() == recovered:
        return (path, "already-in-tree", "identical, nothing written")

    if dry_run:
        was = f"{len(live.read_bytes())}B differs" if live.exists() else "absent"
        return (path, "would-restore", f"{len(recovered)}B, current: {was}")

    note = "the file was missing from your tree"
    if live.exists():
        backup = live.with_name(live.name + ".pre-restore")
        if backup.exists():
            note = f"{backup.name} already existed and was left untouched"
        else:
            backup.write_bytes(live.read_bytes())
            note = f"what was there is saved as {backup.name}"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(recovered)
    return (path, "RESTORED", note)


def extract(repo: Path, patch: Path, dry_run: bool = False) -> list[tuple[str, str, str]]:
    """Rebuild every file in a stash that the diff itself could not place."""
    chunks = _split_patch(patch.read_bytes())
    if not chunks:
        return []
    with tempfile.TemporaryDirectory(prefix="precommit-stash-") as tmp:
        stage = Path(tmp)
        # A real repository, so `git apply` cannot decide the scratch tree lives
        # inside some OTHER repo that happens to contain the temp directory and
        # refuse its paths as outside it.
        _git(stage, "init", "-q")
        return [_extract_one(repo, chunk, stage, seq, dry_run) for seq, chunk in enumerate(chunks)]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover work from pre-commit's stash.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--limit", type=int, default=10, help="How many stashes to consider (newest first).")
    parser.add_argument("--patch", default=None, help="Restore this stash by name instead of the newest recoverable one.")
    parser.add_argument("--restore", action="store_true", help="Apply a stash instead of listing.")
    parser.add_argument("--all", action="store_true", help="Show every stash, not only recoverable ones.")
    parser.add_argument("--dry-run", action="store_true", help="With --restore, report what would be written without writing it.")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    directory = cache_dir()
    found = patches(directory)
    if not found:
        print(f"pre-commit stash: none found in {directory}")
        return 0

    recent = found[-max(1, args.limit):]
    rows = [(when, path, state(repo, path)) for when, path in reversed(recent)]
    recoverable = [row for row in rows if row[2] == "RECOVERABLE"]
    conflicted = [row for row in rows if row[2] == "conflicts"]

    if not args.restore:
        print(f"pre-commit stash: {len(found)} saved in {directory}; examined {len(rows)} newest")
        for when, path, how in rows:
            if how == "already-in-tree" and not args.all:
                continue
            age = (time.time() - when) / 60
            names = files_in(repo, path)
            print(f"  {path.name}  {age:6.0f}m ago  {path.stat().st_size:>8}B  {how}")
            for name in names[:4]:
                print(f"      {name}")
            if len(names) > 4:
                print(f"      ... and {len(names) - 4} more")
        # Say which of the three states we are actually in. An earlier draft
        # printed "nothing to recover" whenever nothing applied cleanly, which
        # reads as reassurance in exactly the case that needs a person: a stash
        # holding work the tree lacks that will not apply on its own.
        if recoverable:
            print(f"\n{len(recoverable)} stash(es) hold work this tree does not have.")
            print("Restore the newest with: python scripts/forge/precommit_stash.py --restore")
        elif conflicted:
            print(f"\n{len(conflicted)} stash(es) are neither already applied nor cleanly applyable.")
            print("git cannot place them, but their content is still fully recorded,")
            print("and a whole stash conflicts even when only one of its files moved.")
            print("See what recovering the newest would change, without changing it:")
            print("  python scripts/forge/precommit_stash.py --restore --dry-run")
            print("Then drop --dry-run to write it.")
        else:
            print("\nNothing to recover: every stash examined is already in the working tree.")
        return 0

    if args.patch:
        chosen = next((p for _, p in found if p.name == args.patch), None)
        if chosen is None:
            print(f"pre-commit stash: no stash named {args.patch} in {directory}")
            return 1
    elif recoverable:
        chosen = recoverable[0][1]
    elif conflicted:
        chosen = conflicted[0][1]
    else:
        print("pre-commit stash: nothing to restore -- every recent stash is already in the tree.")
        return 0

    if args.dry_run:
        print(f"pre-commit stash: {chosen.name} -- dry run, nothing will be written")
        for path, outcome, note in extract(repo, chosen, dry_run=True):
            print(f"  {outcome:<14} {path}  ({note})")
        print("Re-run without --dry-run to apply. Overwritten content is kept as <file>.pre-restore.")
        return 0

    ok, detail = apply_patch(repo, chosen)
    if ok:
        print(f"pre-commit stash: restored {chosen.name} ({detail})")
        for name in files_in(repo, chosen):
            print(f"  {name}")
        return 0

    # The diff will not land on this tree -- which is not the same as the work
    # being gone, and is the expected outcome in the case this tool exists for.
    # Rebuild each file from the pre-image the patch names instead.
    print(f"pre-commit stash: {chosen.name} does not apply as a diff")
    print(f"  {detail}")
    print("Rebuilding its files from the blobs the patch records instead.")
    results = extract(repo, chosen)
    if not results:
        print("No file sections could be parsed out of it. The stash is intact at:")
        print(f"  {chosen}")
        return 1

    for path, outcome, note in results:
        print(f"  {outcome:<14} {path}  ({note})")
    restored = [row for row in results if row[1] == "RESTORED"]
    failed = [row for row in results if row[1] not in ("RESTORED", "already-in-tree")]
    if restored:
        print(f"{len(restored)} file(s) rebuilt from {chosen.name}. Nothing was staged --")
        print("review with `git diff` before you commit, and delete the .pre-restore copies.")
    if failed:
        print(f"{len(failed)} file(s) could NOT be rebuilt. The stash is intact at:")
        print(f"  {chosen}")
        return 1
    if not restored:
        print("Every file in this stash already matches your tree; nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
