"""A dev-moved repair round starts with dev already merged into the team's copy (Task 3h).

When the promoter refuses a Thomas project's hand-in because "the change no longer applies to dev", Autopilot sends
it back to its team for a repair round (``thomas_project.DEV_MOVED``). That round's message told the team to run
``git merge`` in its copy, and the team cannot: Build's Claude team has Read, Edit, Write, Glob, Grep and the Praxis
tools, and no shell. On 2026-09-25 the ratchet project (thomas-479adbe796ab) spent its rounds checking that its files
were intact without ever seeing what dev had changed, was refused again for ``tests/conftest.py``, and stopped.

:func:`rebase_onto_dev` does the merge on the server before the round starts (``thomas_project.prepare_repair``),
with git pointed at the green's own git folder and work tree, never the running copy's:

1. The team's whole change is taken the way a hand-in takes it (``green_checkout.green_patch``), and a copy is kept
   in the green's git folder (:data:`MERGES_DIR`), so nothing the team made can be lost whatever happens next.
2. That patch is applied to dev's tip in a scratch index with ``git apply --cached --3way``, the promoter's own
   operation (``scripts/cage/self_change_checks.derive_tree``): every hunk that still fits applies, and each file
   where dev and the team changed the same lines is written with conflict markers (``git merge-file``), labelled
   ``dev`` and ``your change``.
3. Only then is the green touched, once no file dev adds would land on one the green keeps untracked (the Build
   conversation under ``.thomas/``, the runtime folder): one step (``git read-tree -m -u``) rewrites only the files
   that differ, and its HEAD and recorded base (``green_checkout.set_base``) move to dev, so the next hand-in's patch
   is the team's work against today's dev, not dev's own changes too.

A failure before step 3 leaves the green as it was; one during or after it puts the green back from the saved patch
and the old base. Either way the answer says why, and the round's message keeps the old steps.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.server import green_checkout, green_handoff

# In the green's git folder. Never git's own rebase-merge or rebase-apply, which mean a rebase is in progress.
MERGES_DIR = "thomas-dev-merges"
# The two sides of a conflict, as the team reads them in the file: <<<<<<< dev ... >>>>>>> your change.
DEV_LABEL, BEFORE_LABEL, TEAM_LABEL = "dev", "before", "your change"
_OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")
_SAID_CHARS = 400


class _Failed(Exception):
    """A step that stopped the merge, in words the round's message can show."""


@dataclass(frozen=True)
class Rebased:
    """What moving a green onto dev did: ``failed`` is "" when the green now stands on ``dev``."""

    dev: str = ""
    conflicts: tuple[str, ...] = ()
    failed: str = ""
    saved: str = ""  # the team's change as it was, kept in the green's git folder

    @property
    def ok(self) -> bool:
        return not self.failed

    def stamp(self) -> dict[str, Any]:
        """What a repair round records about the merge; ``evolve_agent_autopilot.repair_message`` reads it."""
        return {"dev": self.dev, "merged": self.ok, "conflicts": list(self.conflicts), "merge_failed": self.failed}


def rebase_onto_dev(execution_id: str) -> Rebased:
    """Move this green onto the running copy's dev tip with its team's change re-applied on top. Never raises.

    Files where the change and dev meet are left with conflict markers and named in ``conflicts``. Nothing here
    commits: HEAD and the index move to dev, and the team's change stays in the work tree as the team left it.
    """
    green = green_checkout.find_green(execution_id)
    if green is None:
        return Rebased(failed="the team's copy is gone")
    dev = green_handoff.dev_tip(execution_id)
    if not dev:
        return Rebased(failed="dev could not be read in the running copy")
    if dev == green.base:
        return Rebased(dev)  # dev has not moved under this copy
    try:
        patch = green_checkout.green_patch(green)  # stages everything: the index is the team's whole change now
        saved = _keep(green, patch, dev)
        green_checkout.discard_coordination_edits(green)  # else git will not move the board dev changed
    except (green_checkout.GreenUnavailable, OSError) as exc:
        return Rebased(
            dev, failed=f"the team's change could not be read and kept ({exc}); nothing in this copy changed"
        )
    try:
        before = _must(green, "write-tree").strip()
        after, conflicts = _merged(green, dev, saved, bool(patch.strip()))
        _refuse_to_overwrite(green, before, after)
    except (_Failed, ValueError) as exc:  # worked out in a scratch index: the green itself is untouched
        return Rebased(dev, failed=f"{exc}; nothing in this copy changed", saved=str(saved))
    try:
        _must(green, "read-tree", "-m", "-u", before, after)  # only the files that differ between the two
        _must(green, "reset", "--quiet", dev)  # HEAD and the index on dev; the team's change is in the work tree
        green_checkout.set_base(green, dev)
    except (_Failed, green_checkout.GreenUnavailable, OSError, ValueError) as exc:
        return Rebased(dev, failed=_put_back(green, saved, bool(patch.strip()), str(exc)), saved=str(saved))
    return Rebased(dev, tuple(conflicts), saved=str(saved))


def merged_steps(dev: str, conflicts: list[str]) -> str:
    """What a dev-moved round tells its team once dev is merged in (``evolve_agent_autopilot.repair_message``)."""
    first = (
        f"These files still hold conflict markers (<<<<<<< / >>>>>>>) where dev and your change met: "
        f"{', '.join(str(name) for name in conflicts)}. In each one, resolve every conflict keeping both sides' "
        "intent: what dev changed, and what your change does. Leave no marker behind."
        if conflicts
        else "Every part of your change still fitted, and no file holds a conflict marker. Check that your change "
        "still does what it should on top of what dev changed."
    )
    return (
        "Your finished change no longer applied to dev, which had moved on since this copy was made. Thomas has "
        f"merged dev into this copy for you: it now stands on {dev}, with your change applied on top, and there is "
        f"no git step to run.\n1. {first}\n2. Move any release notes into a changelog.d/<short-name>.md fragment; "
        "never edit CHANGELOG.md.\n3. Re-run the checks, then finish as usual, and the change is handed "
        "in again."
    )


def _keep(green: green_checkout.Green, patch: str, dev: str) -> Path:
    """Keep the team's change, byte for byte, in the green's git folder (which the cage account may only read)."""
    folder = green.git_dir / MERGES_DIR / f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True)
    data = patch.encode("utf-8", errors="surrogateescape")  # exactly what git wrote (green_checkout.green_patch)
    (folder / "change.patch").write_bytes(data)
    record = {"from": green.base, "to": dev, "at": time.time(), "patch_sha256": hashlib.sha256(data).hexdigest()}
    (folder / "merge.json").write_text(json.dumps(record), encoding="utf-8")
    return folder / "change.patch"


def _merged(green: green_checkout.Green, dev: str, patch: Path, changed: bool) -> tuple[str, list[str]]:
    """The tree this green becomes -- dev with the team's change on top -- and the files left with markers."""
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / "index"
        _must(green, "read-tree", dev, index=index)
        stages: dict[str, dict[str, tuple[str, str]]] = {}
        if changed:
            applied = _git(green, "apply", "--cached", "--3way", "--whitespace=nowarn", str(patch), index=index)
            stages = _unmerged(green, index)
            # Git applies all of a patch or none of it: an error with nothing left unmerged means none applied.
            if applied.returncode and (not stages or _errors(applied)):
                raise _Failed(f"the team's change does not apply to dev even with a three-way merge: {_said(applied)}")
        for path, sides in stages.items():
            _mark(green, index, path, sides)
        return _must(green, "write-tree", index=index).strip(), sorted(stages)


def _unmerged(green: green_checkout.Green, index: Path) -> dict[str, dict[str, tuple[str, str]]]:
    stages: dict[str, dict[str, tuple[str, str]]] = {}
    for entry in filter(None, _must(green, "ls-files", "--unmerged", "-z", index=index).split("\0")):
        info, _, path = entry.partition("\t")
        mode, object_id, stage = info.split()
        stages.setdefault(path, {})[stage] = (mode, object_id)
    return stages


def _mark(green: green_checkout.Green, index: Path, path: str, sides: dict[str, tuple[str, str]]) -> None:
    """Write *path* with conflict markers, as ``git apply --3way`` leaves one in a work tree, but named for the team."""
    if not {"1", "2", "3"} <= sides.keys():
        raise _Failed(f"{path} changed on both sides in a way conflict markers cannot show")
    labels = ("-L", DEV_LABEL, "-L", BEFORE_LABEL, "-L", TEAM_LABEL)
    merged = _git(green, "merge-file", "--object-id", *labels, sides["2"][1], sides["1"][1], sides["3"][1])
    object_id = merged.stdout.strip()
    if not _OBJECT_ID.match(object_id):  # a binary file, or git could not merge it at all
        raise _Failed(f"{path} changed on both sides and could not be marked: {_said(merged)}")
    _must(green, "update-index", "--cacheinfo", f"{sides['2'][0]},{object_id},{path}", index=index)


def _refuse_to_overwrite(green: green_checkout.Green, before: str, after: str) -> None:
    """Stop before the move when a file it adds would land on something this copy keeps untracked.

    Everything the team made is staged by now, so anything on disk where the move adds a file is the run's or the
    green's own and ignored: a Build conversation, a runtime file. ``git read-tree -u`` treats an ignored file as
    expendable and overwrites it (found by this module's tests).
    """
    added = _must(green, "diff-tree", "-r", "--no-renames", "--diff-filter=A", "--name-only", "-z", before, after)
    blocked = []
    for path in filter(None, added.split("\0")):
        parts = Path(path).parts
        in_the_way = [green.work.joinpath(*parts[:depth]) for depth in range(1, len(parts) + 1)]
        if any(_linked(p) or (p.exists() and (p == in_the_way[-1] or not p.is_dir())) for p in in_the_way):
            blocked.append(path)
    if blocked:
        raise _Failed(f"dev adds files where this copy keeps its own untracked ones: {', '.join(blocked[:10])}")


def _linked(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def _put_back(green: green_checkout.Green, patch: Path, changed: bool, why: str) -> str:
    """Put the green back exactly as it was: its old base, with the team's saved change on top. Says what happened.

    Everything is staged first, so the hard reset removes the team's new files as well as dev's; the saved patch
    then brings the team's back. Ignored files are never staged, so they are never touched.
    """
    steps: list[tuple[str, ...]] = [("add", "--all"), ("reset", "--quiet", "--hard", green.base)]
    if changed:
        steps.append(("apply", "--index", "--whitespace=nowarn", str(patch)))
    try:
        for step in steps:
            _must(green, *step)
    except _Failed as exc:
        return f"{why}; putting this copy back failed too ({exc}), and the team's change is kept at {patch}"
    return f"{why}; this copy was put back as it was"


def _git(green: green_checkout.Green, *args: str, index: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Git on the green alone (``green_checkout._git_command`` names its git folder and work tree, never the running
    copy's); *index* is a scratch index for working a result out before anything in the green changes."""
    env = green_checkout._clean_env()
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    try:
        return subprocess.run(
            green_checkout._git_command(green, *args),
            cwd=str(green.work),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=green_checkout._GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _Failed(f"git {args[0]} could not run: {exc}") from exc


def _must(green: green_checkout.Green, *args: str, index: Path | None = None) -> str:
    done = _git(green, *args, index=index)
    if done.returncode:
        raise _Failed(f"git {args[0]} failed: {_said(done)}")
    return done.stdout


def _errors(done: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in (done.stderr or "").splitlines() if line.startswith(("error:", "fatal:"))]


def _said(done: subprocess.CompletedProcess[str]) -> str:
    """Git's own reason, on one line: its error lines when it gave any, else all it said."""
    lines = _errors(done) or (done.stderr or done.stdout or "").splitlines()
    return " ".join(" ".join(lines).split())[:_SAID_CHARS] or f"exit status {done.returncode}"


__all__ = ["MERGES_DIR", "Rebased", "merged_steps", "rebase_onto_dev"]
