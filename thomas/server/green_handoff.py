"""When a self-fix run ends: hand green's change to the commit-master, then clear green.

A self-fix is made in green (``green_checkout``), never in the running Thomas.
This is the only way the change heads for the running copy: a ``self_change``
submission in the commit-master's inbox, which re-derives it in a clean room,
runs the gates and asks you on a pinned card before anything lands.

What each ending does:

* **Finished** (``promote=True``): green's patch goes to the inbox, then green
  is deleted. An unchanged green submits nothing.
* **Failed** (``promote=False``): nothing is submitted. The worker's blocker
  report, if it wrote one, is copied to the running copy's ``runtime/`` (which
  is where the instructions tell it the report lives) before green goes.
* **The submission could not be written:** green is kept. Deleting it would
  lose a finished fix without a word; ``green_checkout.sweep`` clears it later.

The submission is written to a hidden temporary folder and renamed into place,
so the commit-master never reads half of one.

Task 3b (2026-09-24): a Thomas project's green is kept until the promoter's
verdict. Five projects started from one base; two passed their done checks and
were refused because dev had moved ("the change no longer applies to dev"), and
this module had already deleted their greens: only the patches in the promoter's
``processed`` folder survived, which the cage account cannot read. A project asks
for its green to be kept (:func:`await_verdict`); it is then marked "awaiting your
verdict" at settle, and :func:`verdict_reached` ends it: landed removes it,
anything else keeps it for 7 days from the verdict (:func:`held`, which the sweep
spares), so the team can repair it in place. The single chat worker's green still
goes at settle. :func:`size_problems` is the size rule the promoter does not
check, and :func:`sibling_changes` lists what the other projects are changing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import zlib
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from thomas.core import atomic_json
from thomas.server import green_checkout, green_size_rule

log = logging.getLogger(__name__)

SUBMISSION_KIND = "self_change"
_REPORT_MAX_BYTES = 1024 * 1024
# In green's own git folder, which the cage account may only read: what this green handed in, and what it heard back.
HANDOFF_NAME = "handoff.json"
HELD_S = green_checkout.KEPT_MAX_AGE_S  # a green kept for, or after, its verdict: 7 days from that verdict
_READ_TIMEOUT_S = 60.0
# The repo's size rule lives in green_size_rule, which reads BOTH registers it is written in. Re-exported
# because the note every Thomas project is given names this path (thomas_project._TEAM_NOTES).
BASELINE = green_size_rule.BASELINE
# The check before your card's scratch copies of dev (thomas.server.precard.scratch): no team's work, so no sibling's.
SCRATCH_PREFIX = "precard-"
# Worktree edits can leave HEAD and the index unchanged; recheck even quiet copies within 60 seconds.
_SIBLING_FRESH_S = 60.0
_SIBLING_WORKERS = 8
_sibling_clock = time.monotonic
_sibling_lock = threading.RLock()
# A copy changes only while a run works in it, and a run writes the copy's conversation record when it begins and when
# it ends. A copy whose records were last written longer ago than _RUN_RECENT_S, with no run of this server in it, is
# quiet: it is not walked, and git is asked about it again only after _QUIET_FRESH_S (up to twice that, so the quiet
# copies do not all come due in one listing). On 2026-11-13 there were 228 copies, 211 of them untouched for three days,
# and every one was walked for every listing and every project start: a whole processor all day, and 6 to 10 minutes
# before a new project's team began.
_RUN_RECENT_S = 6 * 3600.0
_QUIET_FRESH_S = 1800.0
_RECORDS = Path(".thomas") / "evolve" / "agent" / "conversations"
_wall_clock = time.time
_at_work: frozenset[str] = frozenset()  # the copies the last listing saw a run of this server in (runs_are_in)
# git's stamp, when git was last asked, the changed files, the walk's stamp (None for a quiet copy), the quiet stamp.
_sibling_cache: dict[Path, tuple[Any, ...]] = {}


def inbox_dir() -> Path:
    from thomas.tools.cage_shell import cage_root

    return cage_root() / "inbox"


def _write_submission(
    green: green_checkout.Green, patch: str, files: list[str], summary: str, chat: str, sid: str, checked: str = ""
) -> Path:
    inbox = inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    final = inbox / sid
    if final.exists():
        raise FileExistsError(f"submission already exists: {final}")
    staging = inbox / f".tmp-{sid}-{os.getpid()}"
    staging.mkdir()
    placed = False
    try:
        # Bytes, not text: write_text on Windows turns every LF into CRLF, and a
        # patch rewritten that way no longer applies to the commit it came from.
        patch_bytes = patch.encode("utf-8", errors="surrogateescape")  # exactly what git wrote
        (staging / "change.patch").write_bytes(patch_bytes)
        manifest = {
            "id": sid,
            "kind": SUBMISSION_KIND,
            "agent": "thomas",
            "base": green.base,
            "message": summary.strip().splitlines()[0][:200] if summary.strip() else "Thomas self-fix",
            "patch": "change.patch",
            "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
            "execution_id": green.execution_id,
            # What the check before the card found (thomas.server.precard), so the record kept in
            # `processed/` still says whether this change was checked long after its card is gone.
            "checked": checked,
            "chat": chat,
            "summary": summary,
            "files": files,
            "blue": str(green.blue),
            "submitted_at": time.time(),
        }
        (staging / "submission.json").write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        staging.rename(final)
        placed = True
    finally:
        # Whatever stopped it, a half-written submission never stays behind.
        if not placed:
            shutil.rmtree(staging, ignore_errors=True)
    return final


def _keep_report(green: green_checkout.Green) -> None:
    """Copy the worker's blocker report into the running copy's runtime/.

    Only plain files directly inside the report folder, and only if that folder
    really is inside green: anything in green could be a link pointing elsewhere.
    """
    source = green.work / "runtime" / "self_development" / green.execution_id
    if not source.is_dir() or source.is_symlink() or os.path.isjunction(source):
        return
    try:
        source.resolve().relative_to(green.work.resolve())
    except ValueError:
        return
    target = green.blue / "runtime" / "self_development" / green.execution_id
    for item in source.iterdir():
        if item.is_symlink() or not item.is_file() or item.stat().st_size > _REPORT_MAX_BYTES:
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target / item.name)


def _files_in(patch: str) -> list[str]:
    """The paths a ``--no-renames`` patch changes, read from its ``diff --git a/P b/P`` headers; [] when one is
    quoted or cannot be read that way (the caller then asks git)."""
    files: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        rest = line[len("diff --git a/") :]
        half = (len(rest) - len(" b/")) // 2
        if rest[half : half + 3] != " b/" or rest[:half] != rest[half + 3 :]:
            return []
        files.append(rest[:half])
    return files


def settle(
    execution_id: str,
    *,
    promote: bool,
    summary: str = "",
    chat: str = "",
    checked: str = "",
    patch: str | None = None,
) -> Path | None:
    """End green for this run. Returns the submission folder, if one was written.

    ``patch``, when given, is the patch the check before the card read (``precard.check_for_hand_in``), and
    it is what is handed in: never a fresh read of the green, which could differ from what was checked.

    A green kept for its verdict (:func:`await_verdict`) is marked awaiting it
    instead of being removed. Never raises: this runs as a run's reply is
    delivered, and a hand-off problem must be logged, not turned into a second
    failure of the run.
    """
    green = green_checkout.find_green(execution_id)
    if green is None:
        return None
    state = _state(green)
    submission: Path | None = None
    try:
        if promote:
            patch = green_checkout.green_patch(green) if patch is None else patch
            if patch.strip():
                sid = _next_id(green, state) if state.get("keep") else f"self-{green.execution_id}"
                files = _files_in(patch) or green_checkout.changed_paths(green)
                submission = _write_submission(green, patch, files, summary, chat, sid, checked)
                log.info("self-fix %s submitted for your approval: %s", execution_id, submission)
        else:
            _keep_report(green)
    except (green_checkout.GreenUnavailable, OSError, ValueError) as exc:
        log.warning("self-fix %s: green kept, hand-off failed: %s", execution_id, exc, exc_info=True)
        return None
    if submission is not None and state.get("keep"):
        _hold(green, state, submission.name)
        _end_processes(green)
        return submission
    green_checkout.mark_settled(green)
    _end_processes(green)
    try:
        green_checkout.remove_green(green)
    except OSError:
        log.warning("self-fix %s: green is still held; the next sweep removes it", execution_id, exc_info=True)
    return submission


def end_green_processes(execution_id: str) -> None:
    """End what the caged shell left running in this green, before its change is read for the last time."""
    green = _found(execution_id)
    if green is not None:
        _end_processes(green)


def _end_processes(green: green_checkout.Green) -> None:
    """End anything the caged shell left running in green before removing it.

    Measured 2026-09-22: a process a self-fix had started kept running as the
    cage account after its run ended, holding green as its folder. The cage
    runner keeps each green's processes in one Windows job; this ends it.
    """
    from thomas.tools import cage_shell

    try:
        if cage_shell.runner_alive():
            cage_shell.end_green(green.execution_id)
    except (OSError, ValueError, RuntimeError):
        log.warning("could not end green %s's processes", green.execution_id, exc_info=True)


# -- a green kept until its verdict (Task 3b) -------------------------------------------------------------------------


def _found(execution_id: object) -> green_checkout.Green | None:
    green = green_checkout.find_green(str(execution_id or ""))
    return green if isinstance(green, green_checkout.Green) else None


def _read_state(git_dir: Path) -> dict[str, Any]:
    try:
        state = json.loads(atomic_json.read_text_with_retry(git_dir / HANDOFF_NAME))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _state(green: green_checkout.Green) -> dict[str, Any]:
    return _read_state(green.git_dir) if isinstance(green, green_checkout.Green) else {}


def _save(green: green_checkout.Green, state: dict[str, Any]) -> None:
    atomic_json.write_json_atomic(green.git_dir / HANDOFF_NAME, state)  # two threads read one verdict


def _next_id(green: green_checkout.Green, state: dict[str, Any]) -> str:
    """A new id for each hand-in from this green: the verdict on an earlier one is still in the outbox."""
    earlier = [str(sid) for sid in state.get("sids") or []]
    return f"self-{green.execution_id}" + (f"-{len(earlier) + 1}" if earlier else "")


def _hold(green: green_checkout.Green, state: dict[str, Any], sid: str) -> None:
    now = time.time()
    record = {**state, "status": "awaiting", "sid": sid, "since": now, "sids": [*(state.get("sids") or []), sid]}
    try:
        _save(green, record)
    except OSError:
        log.warning("could not mark green %s awaiting its verdict", green.execution_id, exc_info=True)
    green_checkout.mark_kept(green, f"awaiting your verdict on {sid}")


def await_verdict(execution_id: str) -> None:
    """Keep this green past its hand-off, until the promoter's verdict: a Thomas project's team repairs a refused
    change in it. Nothing happens for a green that is not there."""
    green = _found(execution_id)
    if green is None:
        return
    try:
        _save(green, {**_state(green), "keep": True})
    except OSError:
        log.warning("could not ask to keep green %s until its verdict", execution_id, exc_info=True)


def awaiting_verdict(execution_id: str) -> bool:
    green = _found(execution_id)
    return green is not None and _state(green).get("status") == "awaiting"


def verdict_reached(verdict: dict[str, Any], *, execution_id: str = "", sid: str = "") -> str:
    """Act on the green a promoter's verdict is about. Returns what its cards say about the green, or "".

    Landed: the green is removed, as before. Declined, refused or an error: it is kept for 7 days from now, and the
    returned sentence says where. Only a green kept for its verdict is touched, only by the verdict on its latest
    hand-in, and a second call changes nothing (the chat's card and the card mirror both read the verdict). A caller
    that knows which green and hand-in it asked about says so; the verdict's own fields are the fallback.
    """
    verdict = verdict or {}
    green = _found(execution_id or verdict.get("execution_id"))
    if green is None:
        return ""
    state = _state(green)
    sid = sid or str(verdict.get("submission_id") or verdict.get("id") or "")
    if not state.get("keep") or (sid and sid != state.get("sid")):
        return ""
    status = str(verdict.get("status") or "error")
    if status == "landed":
        green_checkout.mark_settled(green)
        _end_processes(green)
        try:
            green_checkout.remove_green(green)
        except OSError:
            log.warning("green %s landed but is still held; the next sweep removes it", green.execution_id)
        return ""
    if state.get("status") != status:
        try:
            _save(green, {**state, "status": status, "since": time.time()})
        except OSError:
            log.warning("could not record the verdict on green %s", green.execution_id, exc_info=True)
        green_checkout.mark_kept(green, f"{status}: {str(verdict.get('detail') or '')[:300]}")
    return f"Its copy is kept for 7 days at {green.work}."


def held(*, now: float | None = None) -> set[str]:
    """Greens kept for their verdict, or after one, less than 7 days ago: the sweep spares these.

    ``green_checkout.sweep`` counts a kept green's 7 days from when it was made; an Autopilot project can take days
    before its hand-in, so this counts them from the hand-in and from your verdict instead.
    """
    moment = time.time() if now is None else now
    root = green_checkout.green_root() / "git"
    kept: set[str] = set()
    for git_dir in root.glob("*") if root.is_dir() else ():
        state = _read_state(git_dir)
        try:
            since = float(state.get("since") or 0)
        except (TypeError, ValueError):
            continue
        if state.get("keep") and since and moment - since <= HELD_S:
            kept.add(git_dir.name)
    return kept


def dev_tip(execution_id: str, branch: str = "dev") -> str:
    """The commit the promoter applies changes to now: the running copy's ``dev``, else its HEAD; "" if unread."""
    green = _found(execution_id)
    if green is None or not str(green.blue).strip():
        return ""
    for ref in (f"refs/heads/{branch}", "HEAD"):
        found = _read_git(["git", "-C", str(green.blue), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        if found:
            return found.strip()
    return ""


def uncommitted_in_running_copy(execution_id: str, files: list[str], branch: str = "dev") -> list[str] | None:
    """Which of *files* the running copy holds uncommitted work in, by the promoter's own test (Task 3g).

    ``self_change_checks.blue_dirty``: the worktree or the index differs from ``dev``'s tip, or a file that tip does
    not have is there (the change adds it). Its ``git diff`` refreshes and rewrites the index, taking the lock other
    agents and the promoter use, with or without ``--no-optional-locks``; this reads the same answer through ``git
    status``, which honours it and never writes, plus the files where ``HEAD`` itself is not ``dev``. None when it
    cannot be read.
    """
    green = _found(execution_id)
    tip = dev_tip(execution_id, branch)
    paths = list(dict.fromkeys(str(name) for name in files or [] if str(name).strip()))
    if green is None or not tip or not paths:
        return None
    git = ["git", "-C", str(green.blue), "--no-optional-locks", *("-c", "core.quotepath=off")]
    git += ["-c", "core.fsmonitor=false"]
    status = _read_git([*git, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--", *paths])
    moved = _read_git([*git, "diff", "--name-only", "-z", "--no-renames", tip, "HEAD", "--", *paths])
    if status is None or moved is None:
        return None
    dirty = {entry[3:] for entry in status.split("\0") if len(entry) > 3}
    dirty.update(name for name in moved.split("\0") if name)
    for path in paths:  # a file dev does not have: the change adds it, so the running copy must not have it either
        missing = _read_git([*git, "cat-file", "-e", f"{tip}:{path}"]) is None
        if path not in dirty and missing and os.path.lexists(Path(green.blue) / path):
            dirty.add(path)
    return sorted(dirty)


def _closing() -> bool:
    """Whether this server is closing. Imported here: ``precard`` imports this module while it is being imported."""
    from thomas.server.precard import workers

    return workers.closing()


def _read_git(command: list[str]) -> str | None:
    """A git read. Never ``git add``: another team's run may be using the index this would write."""
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    try:
        done = subprocess.run(
            command, env=clean, capture_output=True, text=True, encoding="utf-8", timeout=_READ_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _green_git(green: green_checkout.Green, *args: str) -> str | None:
    return _read_git(_green_git_command(green, *args))


def _green_git_command(green: green_checkout.Green, *args: str) -> list[str]:
    return ["git", f"--git-dir={green.git_dir}", f"--work-tree={green.work}", "--no-optional-locks"] + [
        "-c", "core.quotepath=off", "-c", "core.fsmonitor=false", *args,
    ]  # fmt: skip


def _blobs_at(green: green_checkout.Green, rev: str, rels: list[str]) -> dict[str, str] | None:
    """Each of *rels* as it was at *rev*, read by ONE ``git cat-file --batch``; a path *rev* lacks is left out.

    What ``git show <rev>:<rel>`` gave once per file: the stored blob, no filters (so not the trap the 2026-10-28
    research found in ``--batch --filters``, whose header gives the unfiltered size). Measured 2026-11-06: the
    server started ~100 git processes a minute, and the size rule ran one per measured file, twice per hand-in.
    None when git could not be asked, so the caller can ask one file at a time instead.
    """
    if not rels:
        return {}
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    asked = "".join(f"{rev}:{rel}\n" for rel in rels).encode("utf-8")
    try:
        done = subprocess.run(
            _green_git_command(green, "cat-file", "--batch"), input=asked, env=clean, capture_output=True,
            timeout=_READ_TIMEOUT_S, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    out, at, found = done.stdout, 0, {}
    for rel in rels:
        end = out.find(b"\n", at)
        if end < 0:
            return None
        header = out[at:end].split()
        at = end + 1
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            found[rel] = out[at : at + size].decode("utf-8", errors="replace")
            at += size + 1  # the blob and the newline after it
        elif len(header) == 3:  # a tree or other object: no file at this path to measure
            at += int(header[2]) + 1
    return found


def _worktree_stamp(work: Path) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    root = os.fspath(work)
    pending = [root]
    prefix_length = len(root) if root.endswith(os.sep) else len(root) + 1
    while pending:
        if _closing():  # a walk of a whole copy must not hold a closing server open
            raise OSError("Thomas is closing")
        folder = pending.pop()
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            if entry.name == ".git" and folder == root:
                continue
            stat = entry.stat(follow_symlinks=False)
            digest.update(entry.path[prefix_length:].encode("utf-8", errors="surrogateescape"))
            digest.update(f":{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}\0".encode("ascii"))
            if entry.is_dir(follow_symlinks=False):
                pending.append(entry.path)
    return digest.digest()


def runs_are_in(names: Iterable[str]) -> None:
    """Say which copies a run of this server is working in now: they are walked however old their records are."""
    global _at_work
    _at_work = frozenset(names)


def _quiet_stamp(work: Path, name: str) -> tuple[object, ...] | None:
    """The stamps of a quiet copy's conversation records, or None for a copy a run may be working in.

    None too for a copy with no record: nothing says when it was last worked in, so it is walked as before."""
    if name in _at_work:
        return None
    records = []
    try:
        for entry in os.scandir(work / _RECORDS):
            if entry.name.endswith(".json"):
                stat = entry.stat()
                records.append((entry.name, stat.st_mtime_ns, stat.st_size))
    except OSError:
        return None
    if not records or _wall_clock() - max(mtime for _, mtime, _ in records) / 1e9 < _RUN_RECENT_S:
        return None
    return tuple(sorted(records))


def _sibling_stamp(git_dir: Path) -> tuple[object, ...] | None:
    """Read HEAD's target commit and file stamps without starting git."""
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            if not ref.startswith("refs/") or any(part in (".", "..", "") for part in ref.split("/")):
                return None
            loose = git_dir / ref
            if loose.is_file():
                head = loose.read_text(encoding="ascii").strip()
            else:
                lines = (git_dir / "packed-refs").read_text(encoding="ascii").splitlines()
                head = next((parts[0] for line in lines if len(parts := line.split()) == 2 and parts[1] == ref), "")
        if not head:
            return None
        index = git_dir / "index"
        index_stat = index.stat() if index.exists() else None
        metadata = git_dir / green_checkout.METADATA_NAME
        meta_stat = metadata.stat() if metadata.exists() else None
        return (
            head,
            (index_stat.st_size, index_stat.st_mtime_ns) if index_stat else None,
            (meta_stat.st_size, meta_stat.st_mtime_ns) if meta_stat else None,
        )
    except (OSError, UnicodeError):
        return None


def _sibling_files(green: green_checkout.Green) -> tuple[tuple[str, ...], bool]:
    if _closing():
        return (), False  # not answered: nothing is remembered for this copy, and no git is started
    tracked = _green_git(green, "diff", "--no-renames", "--name-only", "-z", green.base, "--")
    added = _green_git(green, "ls-files", "--others", "--exclude-standard", "-z")
    names = tuple(dict.fromkeys(name for name in f"{tracked or ''}\0{added or ''}".split("\0") if name))
    return names, tracked is not None and added is not None


def sibling_changes(execution_id: str) -> dict[str, list[str]]:
    """Read in-play siblings without writing indexes; recheck unchanged copies within one minute.

    A quiet copy (:func:`_quiet_stamp`) is not walked: its conversation records say when a run was last in it."""
    root = green_checkout.green_root() / "git"
    found: dict[str, list[str]] = {}
    late: dict[str, list[str]] = {}  # quiet copies: reported after the ones a team is working in
    with _sibling_lock:
        pending: list[tuple[Path, tuple[object, ...] | None, green_checkout.Green, bytes | None, Any]] = []
        now = _sibling_clock()
        for git_dir in sorted(root.glob("*")) if root.is_dir() else ():
            if _closing():  # the survey reads every copy with git; a closing server waits for none of it
                return found
            try:
                if git_dir.name == execution_id or (git_dir / green_checkout.SETTLED_NAME).exists():
                    continue
                if git_dir.name.startswith(SCRATCH_PREFIX) or _read_state(git_dir).get("status") == "declined":
                    continue
            except OSError:
                continue
            stamp = _sibling_stamp(git_dir)
            work = root.parent / "work" / git_dir.name
            cached = _sibling_cache.get(git_dir)
            quiet = _quiet_stamp(work, git_dir.name)
            if quiet is not None:  # no run has been in it since its records were written: its files are as they were
                work_stamp = None
                fresh_s = _QUIET_FRESH_S * (1 + zlib.crc32(git_dir.name.encode("utf-8")) % 100 / 100)
                unchanged = cached and cached[0] == stamp and cached[4:] == (quiet,) and 0 <= now - cached[1] < fresh_s
            else:
                try:
                    work_stamp = _worktree_stamp(work) if work.is_dir() else None
                except OSError:
                    work_stamp = None
                unchanged = (
                    work_stamp is not None
                    and cached
                    and cached[0] == stamp
                    and cached[3] == work_stamp
                    and 0 <= now - cached[1] < _SIBLING_FRESH_S
                )
            if stamp is not None and unchanged:
                if cached[2]:
                    (late if quiet is not None else found)[git_dir.name] = list(cached[2])
                continue
            green = _found(git_dir.name)
            if green is not None:
                pending.append((git_dir, stamp, green, work_stamp, quiet))
        if pending:
            with ThreadPoolExecutor(max_workers=_SIBLING_WORKERS) as pool:
                answers = pool.map(_sibling_files, (green for _, _, green, _, _ in pending))
                for (git_dir, stamp, _, work_stamp, quiet), (names, answered) in zip(pending, answers):
                    try:
                        if (
                            answered
                            and stamp is not None
                            and (work_stamp is not None or quiet is not None)
                            and _sibling_stamp(git_dir) == stamp
                        ):
                            _sibling_cache[git_dir] = (stamp, _sibling_clock(), names, work_stamp, quiet)
                        else:
                            _sibling_cache.pop(git_dir, None)
                    except OSError:
                        _sibling_cache.pop(git_dir, None)
                    if names:
                        (late if quiet is not None else found)[git_dir.name] = list(names)
    found.update(late)  # a note to a new team names the first eight: the copies being worked in come first
    return found


def size_problems(execution_id: str) -> list[str]:
    """Where this green's change breaks the repo's size rule, in words for its team; [] when it keeps to it.

    The promoter lands a self-change without running the size gate (monolith_guard), so a change it lands
    could leave a file the next commit cannot touch. The rule is checked here instead -- and it is ONE rule,
    read by :mod:`thomas.server.green_size_rule` from both registers the repo writes it in: the waiver list
    in ``docs/monolith_guard_baseline.json`` and the debt notes in ``thomas/_architecture.py``. Checking only
    the first is what let a change land on 2026-09-25 that then failed every later commit's architecture
    check; that module's docstring has the measurement. The debt notes are read BOTH ways -- a file over the
    limit that no note records, and a note that no longer describes its file (the file gone, or brought back
    under the limit) -- because ``test_architecture.py`` fails for either, and for everyone after.

    Both registers are read out of the GREEN's own checkout, so a project that edits one is judged by what
    it wrote, not by the running copy.
    """
    green = _found(execution_id)
    if green is None:
        return []
    try:
        files = green_checkout.changed_paths(green)
    except green_checkout.GreenUnavailable:
        return []  # the settle itself says what is wrong with this green
    rule = green_size_rule.read_rule(green.work)  # the change's own registers, as the docstring says
    measured = [rel for rel in files if (green.work / rel).is_file() and green_size_rule.measured(rule, rel)]
    earlier = _blobs_at(green, green.base, measured)
    problems: list[str] = []
    for rel in files:
        path = green.work / rel
        if not path.is_file():
            # A path this change leaves no file at is still judged, because a debt note that names a deleted
            # file fails test_health_annotations exactly as a stale size claim does.
            problems.extend(green_size_rule.stale_debt_problems(rule, rel, None))
            continue
        if not green_size_rule.measured(rule, rel):
            continue  # also covers every debt-noted file: they are all .py, which both gates measure
        lines = green_size_rule.line_count(path.read_text(encoding="utf-8", errors="ignore"))
        text = earlier.get(rel, "") if earlier is not None else _green_git(green, "show", f"{green.base}:{rel}")
        before = green_size_rule.line_count(text or "")
        problems.extend(green_size_rule.file_problems(rule, rel, lines, before))
        problems.extend(green_size_rule.stale_debt_problems(rule, rel, lines))
    return problems


__all__ = [
    "BASELINE",
    "HANDOFF_NAME",
    "SCRATCH_PREFIX",
    "SUBMISSION_KIND",
    "await_verdict",
    "awaiting_verdict",
    "dev_tip",
    "end_green_processes",
    "held",
    "inbox_dir",
    "settle",
    "sibling_changes",
    "size_problems",
    "uncommitted_in_running_copy",
    "verdict_reached",
]
