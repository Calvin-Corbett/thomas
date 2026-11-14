"""Two scratch copies of the dev a change will land on, one of them with the change applied.

You described the hand check: "take the submission's patch and the dev it will land on; apply it with
git apply --3way to a scratch copy of dev (a conflict is a finding); run the same tests on that copy and
on an unpatched copy of dev". This makes those two copies.

Both are ordinary greens (:func:`thomas.server.green_checkout.create_green`), so they get what a green
already gives: a ``git clone --shared`` outside the running checkout, a git folder of their own, and a
removal that copes with Windows holding a folder open. Two differences matter. They are checked out at
the dev tip the promoter will re-derive against, not at the running copy's HEAD, because that is the dev
the change has to work on. And their names start with ``green_handoff.SCRATCH_PREFIX``, which keeps them
out of ``green_handoff.sibling_changes`` -- the note that tells the other Thomas project teams what their
siblings are changing.

They are not marked settled while the check uses them. The sweep takes a settled green at any age, and it
runs whenever another self-fix starts: a copy swept out from under a running pytest reads as tests that
went missing, and would send a good change back. Only a copy :func:`discard` could not remove is marked
settled, so the next sweep finishes the job; one left by a process that died goes after the usual 24h.

Nothing here writes the running copy's index. The clone reads blue's objects and every later git call
names the scratch copy's own git folder and work tree.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from thomas.server import green_checkout, green_handoff

log = logging.getLogger(__name__)

# The scratch copies' execution ids: <PREFIX><execution id>-base and -change, inside green_checkout's
# 80-character folder-name limit for the ids Thomas project greens actually use.
PREFIX = green_handoff.SCRATCH_PREFIX
BASE, WITH_CHANGE = "base", "change"
_ID_MAX = 80


def scratch_id(execution_id: str, part: str) -> str:
    """The folder name one scratch copy gets, short enough for :func:`green_checkout.create_green`."""
    room = _ID_MAX - len(PREFIX) - len(part) - 1
    return f"{PREFIX}{str(execution_id)[:room]}-{part}"


def copy_of_dev(blue: Path, tip: str, execution_id: str, part: str) -> green_checkout.Green:
    """A scratch copy of *blue* checked out at *tip*. Raises ``GreenUnavailable`` when it cannot be made."""
    name = scratch_id(execution_id, part)
    leftover = green_checkout.find_green(name) or _half(name)
    if leftover is not None:  # a copy, or half of one, an earlier try left: the tip may have moved since
        # What that try left running there (a test run cut off by a restart) is what holds the folder open.
        green_handoff.end_green_processes(name)
        try:
            green_checkout.remove_green(leftover)
        except OSError:
            # Still held. On 2026-11-04 this raise stopped two checks before your card, one of them four times:
            # leave that copy for the sweep and check in a fresh one beside it.
            log.warning("an earlier check copy %s is still held open; checking in a fresh copy", name, exc_info=True)
            green_checkout.mark_settled(leftover)  # kept in the git folder; a half without one just goes unmarked
            name = _free_name(execution_id, part)
    return green_checkout.create_green(blue=Path(blue), execution_id=name, checkout_tip=tip)


def _half(name: str) -> green_checkout.Green | None:
    """What is left of a copy called *name* that is no longer one: only its files, only its git folder, or a git
    folder with no record of what it is. ``find_green`` does not find such a half, so nothing removed it, and
    ``create_green`` refuses a name either folder still has. On 2026-11-10 that stopped one change before your card
    three times on a half almost four days old."""
    root = green_checkout.green_root()
    work, git_dir = root / "work" / name, root / "git" / name
    if not (work.exists() or git_dir.exists()):
        return None
    return green_checkout.Green(execution_id=name, work=work, git_dir=git_dir, base="", blue=Path(""))


def _free_name(execution_id: str, part: str) -> str:
    """The first ``<part>2``, ``<part>3``... copy name no green, and no half of one, holds yet."""
    for number in range(2, 100):
        name = scratch_id(execution_id, f"{part}{number}")
        if green_checkout.find_green(name) is None and _half(name) is None:
            return name
    raise green_checkout.GreenUnavailable(f"every spare check copy name for {execution_id} is still held open")


def copies_of_dev(blue: Path, tip: str, execution_id: str) -> tuple[green_checkout.Green, green_checkout.Green]:
    """Make both scratch copies concurrently; remove any completed copy if either fails."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        base_job = pool.submit(copy_of_dev, blue, tip, execution_id, BASE)
        change_job = pool.submit(copy_of_dev, blue, tip, execution_id, WITH_CHANGE)
    base_error, change_error = base_job.exception(), change_job.exception()
    if base_error or change_error:
        discard_all(
            base_job.result() if base_error is None else None, change_job.result() if change_error is None else None
        )
        raise base_error or change_error
    return base_job.result(), change_job.result()


def apply_change(green: green_checkout.Green, patch: str) -> str:
    """Apply *patch* to the copy with ``git apply --3way``. "" when it went in; else why it did not.

    ``--3way`` is what the promoter's own re-derivation does, so a patch that will not apply here is a
    patch that will not land -- a conflict is a finding about the change, not a fault of the check.
    """
    # Bytes, not text: ``green_patch`` decoded exactly what git wrote with surrogateescape, and writing it
    # back any other way rewrites the line endings and the patch stops applying to the commit it came from.
    path = green.git_dir / "precard.patch"
    try:
        path.write_bytes(patch.encode("utf-8", errors="surrogateescape"))
    except OSError as exc:
        return f"the change's patch could not be written to the scratch copy: {exc}"
    applied = green_checkout.git(green, "apply", "--3way", "--whitespace=nowarn", str(path))
    if applied.returncode == 0:
        return ""
    # git says it lacks the blob for a 3-way merge, then "Falling back to direct application...", once for each file
    # whose preimage it does not have. On 2026-10-26 those lines filled the 2,000 characters a team is shown, and the
    # errors naming what did not apply never reached it: they are counted in one line, after the errors.
    lines = [line for line in (applied.stderr or applied.stdout or "").splitlines() if line.strip()]
    fallbacks = [line for line in lines if line.startswith("Falling back to direct application")]
    lines = [line for line in lines if line not in fallbacks and "lacks the necessary blob" not in line]
    # By git's own wording, not by a word a file name can hold (test_a_conflict_..., 2026-10-27).
    errors = [line for line in lines if line.startswith(("error:", "U ")) or line.endswith("with conflicts.")]
    lines = errors + [line for line in lines if line not in errors]
    if fallbacks:
        lines.append(f"(git had no 3-way base for {len(fallbacks)} file(s) and applied them directly)")
    return "\n".join(lines)[:2000] or f"git apply --3way exited {applied.returncode}"


def discard(green: green_checkout.Green | None) -> None:
    """Remove a scratch copy. A copy that will not go is left marked settled for the next sweep."""
    if green is None:
        return
    try:
        green_checkout.remove_green(green)
    except OSError:
        log.warning("the card check could not remove its scratch copy %s", green.execution_id, exc_info=True)
        green_checkout.mark_settled(green)  # nothing uses it now: the next sweep may take it at any age


def discard_all(*greens: green_checkout.Green | None) -> None:
    """Remove all copies together, waiting for every removal to finish."""
    with ThreadPoolExecutor(max_workers=max(1, len(greens))) as pool:
        removals = [pool.submit(discard, green) for green in greens if green is not None]
        for removal in removals:
            removal.result()


__all__ = [
    "BASE",
    "PREFIX",
    "WITH_CHANGE",
    "apply_change",
    "copies_of_dev",
    "copy_of_dev",
    "discard",
    "discard_all",
    "scratch_id",
]
