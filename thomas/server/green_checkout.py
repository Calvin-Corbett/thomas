"""Green: the private copy a self-fix is made in, so the running Thomas is never edited.

Your direction, 2026-09-22: "I thought I made a blue-green system just for this,
so he would edit the other version that's not running". Chat self-development
edited the running checkout ("blue") directly from 2026-06-28. A self-fix now
gets its own green: a ``git clone --shared`` of what blue has *committed*,
outside blue, deleted when the run ends. Its diff goes to the commit-master
inbox (``green_handoff``); nothing in green reaches blue until you approve it.

Two layout choices carry the safety, and both are about who can write what:

* **Green lives outside blue**, in ``<Thomas data dir>/green``
  (``THOMAS_GREEN_ROOT`` overrides). The cage's account, ``thomas-agent``, is
  granted write on green's work folders only -- the caged shell runs tests
  there -- and nothing else in your profile.
* **Green's git folder is separate** (``--separate-git-dir``) and the cage's
  account may only read it. The ``.git`` in the work folder is then a one-line
  pointer that anything in green can rewrite, so the server never reads it:
  every git call here names the git folder and the work tree itself.

Green's *contents* are untrusted by design. The commit-master re-derives the
change in a clean room and you approve the exact result.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

# Where greens live is shared with the tools that run in them (check.run), which may not import the server.
from thomas.core.git_launcher import real_git_first
from thomas.core.green_place import GREEN_ROOT_ENV, METADATA_NAME, green_root
from thomas.server import green_git_lock

log = logging.getLogger(__name__)

CAGE_ACCOUNT = "thomas-agent"
SETTLED_NAME = "settled"
KEPT_NAME = "kept"
# A green whose run stopped unfinished with real changes in it is kept this
# long, so a follow-up can resume it; an ordinary unsettled green gets 24h.
KEPT_MAX_AGE_S = 7 * 24 * 60 * 60.0

# An execution id becomes a folder name. Letters, digits, dash and underscore
# only: nothing that can climb out of the root or name a drive.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_GIT_TIMEOUT_S = 600.0


class GreenUnavailable(Exception):  # noqa: N818 - reads as the refusal it is
    """Green could not be made or used.

    Deliberately not a ``RuntimeError``, ``OSError``, ``ValueError`` or
    ``TypeError``: dispatch catches those four and hands the task to the Task
    Manager, which would edit blue. A self-fix with no green must fail.
    """


@dataclass(frozen=True)
class Green:
    execution_id: str
    work: Path
    git_dir: Path
    base: str
    blue: Path


def file_access_for(requested: int, work_dir: Path | str) -> int:
    """The file-access level a run in *work_dir* gets.

    In green, green is the whole project. At "This project" the ladder's project
    is the running checkout, reachable by absolute path -- measured live
    2026-09-22, a worker in green aimed a write there -- so a run in green is
    capped at its own space. Starting a self-fix still takes "This project".
    """
    from thomas.core.file_access import WORKSPACE

    try:
        in_green = Path(work_dir).resolve().is_relative_to((green_root() / "work").resolve())
    except OSError:
        in_green = False
    return min(int(requested), WORKSPACE) if in_green else int(requested)


def _paths(execution_id: str) -> tuple[Path, Path]:
    if not _ID_RE.match(str(execution_id or "")):
        raise GreenUnavailable(f"not a usable execution id for a green folder: {execution_id!r}")
    root = green_root()
    return root / "work" / execution_id, root / "git" / execution_id


def _clean_env() -> dict[str, str]:
    # A GIT_DIR or GIT_INDEX_FILE inherited from whatever started the server
    # would silently point these calls at another repository.
    return real_git_first({k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")})


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """A command on green. A timeout is a green that cannot be used, never a bare ``TimeoutExpired``:
    the ratchet's daily loop survives ``GreenUnavailable`` and would have ended on that one."""
    try:
        env = _clean_env()
        if args and args[0] == "git":
            args = [shutil.which("git", path=env.get("PATH")) or "git", *args[1:]]
        return subprocess.run(
            args,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GreenUnavailable(f"{' '.join(args[:2])} did not finish in {_GIT_TIMEOUT_S:g}s in {cwd}") from exc


def _git_command(green: Green, *args: str) -> list[str]:
    """Git on green, never through green's own ``.git`` pointer."""
    return [
        "git",
        f"--git-dir={green.git_dir}",
        f"--work-tree={green.work}",
        "-c",
        f"core.hooksPath={green.git_dir / 'no-hooks'}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.quotepath=off",
        *args,
    ]


def _git(green: Green, *args: str) -> subprocess.CompletedProcess[str]:
    """A git call on green. A lock left by a killed git is removed when abandoned and the call tried once more."""
    done = _run(_git_command(green, *args), cwd=green.work)
    if done.returncode == 0 or green_git_lock.LOCK_EXISTS not in (done.stderr or ""):
        return done
    kept = green_git_lock.clear_if_stale(green.git_dir, green.work)
    if not kept:
        return _run(_git_command(green, *args), cwd=green.work)
    done.stderr = f"{kept}. git said: {done.stderr.strip()}"
    return done


def git(green: Green, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git on *green* the safe way: naming its git folder and work tree, never its own ``.git`` pointer.

    For callers that need the exit code and the message as well as the output -- the card check applies a
    patch with ``git apply --3way``, where the failure and its wording are the finding.
    """
    return _git(green, *args)


def _secure_root(root: Path) -> None:
    """Only you, SYSTEM and Administrators may write the root; the cage's
    account may read it and write only ``work``. Windows only; best effort
    for the cage grants, because a machine without the cage has no account."""
    if os.name != "nt":
        return
    user = os.environ.get("USERNAME") or ""
    owner_grant = [f"{user}:(OI)(CI)F"] if user else []
    only_owners = ["/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", *owner_grant]
    base = _run(["icacls", str(root), *only_owners], cwd=root)
    if base.returncode != 0:
        raise GreenUnavailable(f"could not secure {root}: {(base.stdout + base.stderr).strip()[:300]}")
    (root / "work").mkdir(exist_ok=True)
    (root / "git").mkdir(exist_ok=True)
    reader = _run(["icacls", str(root), "/grant", f"{CAGE_ACCOUNT}:(OI)(CI)RX"], cwd=root)
    writer = _run(["icacls", str(root / "work"), "/grant", f"{CAGE_ACCOUNT}:(OI)(CI)M"], cwd=root)
    if reader.returncode or writer.returncode:
        log.warning("green root: the cage account could not be granted access; the caged shell cannot use green")


def _ensure_root() -> Path:
    root = green_root()
    if not root.exists():
        try:
            root.mkdir(parents=True)
        except OSError as exc:
            raise GreenUnavailable(f"could not create {root}: {exc}") from exc
        _secure_root(root)
    (root / "work").mkdir(exist_ok=True)
    (root / "git").mkdir(exist_ok=True)
    return root


def create_green(blue: Path, execution_id: str, *, checkout_tip: str | None = None) -> Green:
    """Clone blue's shared objects into a fresh green, checking out the requested tip once."""
    work, git_dir = _paths(execution_id)
    blue = Path(blue).resolve()
    head = _run(["git", "-C", str(blue), "rev-parse", "--verify", "HEAD^{commit}"], cwd=blue)
    base = head.stdout.strip()
    if head.returncode != 0 or not base:
        raise GreenUnavailable(f"{blue} is not a git checkout with a commit, so there is nothing to copy")
    _ensure_root()
    if work.exists() or git_dir.exists():
        raise GreenUnavailable(f"a green for {execution_id} already exists")
    green = Green(execution_id=execution_id, work=work, git_dir=git_dir, base=base, blue=blue)
    began = time.perf_counter()
    try:
        clone = ["git", "clone", "--quiet", "--shared", "--no-checkout", f"--separate-git-dir={git_dir}"]
        cloned = _run([*clone, str(blue), str(work)], cwd=work.parent)
        if cloned.returncode != 0:
            raise GreenUnavailable(f"git clone failed: {cloned.stderr.strip()[:300]}")
        # Writing 7,000 files is the slow part (measured 2026-11-05: 5.3-8.2s one at a time, 2.6-3.1s with 8
        # workers; a clean `git status` after either). A small tree falls back to one worker on its own.
        checkout = _git(
            green,
            *("-c", "checkout.workers=8", "-c", "checkout.thresholdForParallelism=100"),
            *("checkout", "--quiet", "--detach", checkout_tip or base),
        )
        if checkout.returncode != 0:
            raise GreenUnavailable(f"git checkout failed: {checkout.stderr.strip()[:300]}")
        meta = {
            "execution_id": execution_id,
            "base": checkout_tip or base,
            "blue": str(blue),
            "created_at": time.time(),
        }
        (git_dir / METADATA_NAME).write_text(json.dumps(meta), encoding="utf-8")
        log.info("green %s: shared objects, checkout ready in %.3fs", execution_id, time.perf_counter() - began)
    except GreenUnavailable:
        remove_green(green)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        remove_green(green)
        raise GreenUnavailable(f"could not make green: {exc}") from exc
    return replace(green, base=checkout_tip or base)


def record_request_start(green: Green, requested_at: float) -> None:
    """Keep the request clock with green's private git metadata, outside the worker's writable tree."""
    meta = _metadata(green.git_dir)
    if meta is None:
        return  # Tests and older copies without metadata have no clock to record.
    meta["requested_at"] = requested_at
    (green.git_dir / METADATA_NAME).write_text(json.dumps(meta), encoding="utf-8")


def first_edit_latency(green: Green) -> float | None:
    """Seconds from the request to the first observed edit of a non-coordination file."""
    meta = _metadata(green.git_dir)
    if not meta or not isinstance(meta.get("requested_at"), (int, float)):
        return None
    requested_at = float(meta["requested_at"])
    first = meta.get("first_edit_at")
    if not isinstance(first, (int, float)):
        if not green.work.is_dir() or not green.git_dir.is_dir():
            return None
        # Use working-tree status: staging here would modify the team's index and
        # the board's startup writes must not count as a code edit.
        status = _git(green, "status", "--porcelain", "--untracked-files=all")
        if status.returncode != 0:
            return None
        names = [
            line[3:]
            for line in status.stdout.splitlines()
            if len(line) > 3
            and line[3:].replace("\\", "/").split("/", 1)[0] not in {"plans", ".thomas", "PROBLEM.md", "PLAN.md"}
        ]
        if not names:
            return None
        first = time.time()  # First observation; Git alone cannot tell when a deletion occurred.
        meta["first_edit_at"] = first
        (green.git_dir / METADATA_NAME).write_text(json.dumps(meta), encoding="utf-8")
        log.info("green %s: request to first edit %.3fs", green.execution_id, first - requested_at)
    return max(0.0, float(first) - requested_at)


_EDIT_WATCHES: dict[str, asyncio.Task[float | None]] = {}


async def watch_first_edit(green: Green, *, interval: float = 0.2, timeout: float = 3600) -> float | None:
    """Poll outside the event loop until the first edit, removal or timeout."""
    until = time.monotonic() + timeout
    while time.monotonic() < until and green.work.is_dir():
        measured = await asyncio.to_thread(first_edit_latency, green)
        if measured is not None:
            return measured
        await asyncio.sleep(interval)
    return None


def begin_first_edit_watch(green: Green) -> None:
    """Keep the timing observation alive after the start response returns."""
    task = asyncio.create_task(watch_first_edit(green))
    _EDIT_WATCHES[green.execution_id] = task
    task.add_done_callback(lambda done: _first_edit_watch_done(green.execution_id, done))


def _first_edit_watch_done(execution_id: str, task: asyncio.Task[float | None]) -> None:
    if _EDIT_WATCHES.get(execution_id) is task:
        _EDIT_WATCHES.pop(execution_id)
    if not task.cancelled():
        try:
            task.result()
        except (OSError, GreenUnavailable):
            log.warning("Could not observe green's first edit", exc_info=True)


def _metadata(git_dir: Path) -> dict[str, object] | None:
    try:
        data = json.loads((git_dir / METADATA_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_green(execution_id: str) -> Green | None:
    try:
        work, git_dir = _paths(execution_id)
    except GreenUnavailable:
        return None
    meta = _metadata(git_dir)
    if meta is None or not work.is_dir():
        return None
    green = Green(
        execution_id=execution_id,
        work=work,
        git_dir=git_dir,
        base=str(meta.get("base") or ""),
        blue=Path(str(meta.get("blue") or "")),
    )
    taken_in = _dev_taken_in(green)
    if not taken_in:
        return green
    try:
        return set_base(green, taken_in)
    except (GreenUnavailable, OSError):
        return replace(green, base=taken_in)


def _dev_taken_in(green: Green) -> str:
    """The newest commit of the running copy's that green's HEAD already holds, when that is newer than its base.

    A repair round whose merge failed tells the team to run ``git merge <dev>`` itself. That moves HEAD onto dev but
    not the recorded base, so every later hand-in carried all of dev's commits since the copy was made and could never
    apply (2026-09-27: the ChatGPT sign-in project handed in 93 files and ran out of rounds). "" when nothing moved.
    """
    head = _git(green, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    if not head or head == green.base or not green.base or not Path(green.blue).is_dir():
        return ""
    blue = _run(["git", "-C", str(green.blue), "rev-parse", "--verify", "HEAD^{commit}"], cwd=Path(green.blue))
    tip = blue.stdout.strip() if blue.returncode == 0 else ""
    shared = _git(green, "merge-base", head, tip).stdout.strip() if tip else ""
    if not shared or shared == green.base:
        return ""
    newer = _git(green, "merge-base", "--is-ancestor", green.base, shared).returncode == 0
    return shared if newer else ""


def set_base(green: Green, base: str) -> Green:
    """Record that green now stands on *base* (``green_rebase`` moved it onto dev), so its next patch is against it.

    Written whole and renamed into place: a green whose record is half written would lose its base altogether.
    """
    meta = _metadata(green.git_dir)
    if meta is None:
        raise GreenUnavailable(f"green {green.execution_id} has no record to write its new base in")
    path = green.git_dir / METADATA_NAME
    temporary = path.with_name(f".{METADATA_NAME}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({**meta, "base": base}), encoding="utf-8")
    os.replace(temporary, path)
    return replace(green, base=base)


# Thomas's coordination state, which the tooling in every copy writes: the board the startup router keeps and the
# failures the automatic checks log. Never a team's change; a copy's version handed in would land over the live board
# (2026-09-27: a web-size change carried a board timestamp and two logged gate failures).
COORDINATION_PATHS = ("plans/thomas/WORKBOARD.md", "plans/thomas/problems")


def _new_files_the_running_copy_ignores(green: Green) -> list[str]:
    """New files in green's index that the running copy ignores: the repo's ``.gitignore`` and blue's own
    ``.git/info/exclude``, which green's separate git folder does not carry (2026-09-27: the search index's
    ``thomas_search.db-wal``/``-shm`` reached a card). Files base already tracks are never listed, so an edit to a
    tracked file that happens to match a pattern is kept. An answer git cannot give lists nothing."""
    added = _git(green, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=A", "-z", green.base)
    new = [name for name in added.stdout.split("\0") if name] if added.returncode == 0 else []
    exclude = Path(green.blue) / ".git" / "info" / "exclude"
    extra = ["-c", f"core.excludesFile={exclude}"] if exclude.is_file() else []
    ignored: list[str] = []
    for start in range(0, len(new), 200):
        found = _git(green, *extra, "check-ignore", "--no-index", "--", *new[start : start + 200])
        ignored += [line for line in found.stdout.splitlines() if line]
    return ignored


def _refuse_links(green: Green, *listing: str) -> None:
    from thomas.server import keeper_guard_capture as capture

    try:
        if capture.linked(green.work, ""):
            raise GreenUnavailable(f"green's work folder is a link: {green.work}")
        found = _git(green, *listing)
        if found.returncode != 0:
            raise GreenUnavailable(f"could not list green's changes: {found.stderr.strip()[:300]}")
        links = {
            link
            for path in found.stdout.split("\0")
            if path
            for link in (capture.first_link(green.work, path),)
            if link is not None
        }
    except OSError as exc:
        raise GreenUnavailable("could not look for links in green") from exc
    if links:
        names = sorted(links)
        shown = ", ".join(names[:10])
        more = f" and {len(names) - 10} more" if len(names) > 10 else ""
        raise GreenUnavailable(f"green's change is not handed in: {shown}{more} {capture.LINKS}")


def _stage_everything(green: Green) -> None:
    """Stage every change the copy made, except Thomas's coordination state, which stays on disk and out of the
    hand-in (it goes back to the copy's starting commit in the index only)."""
    _refuse_links(green, "ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard")
    staged = _git(green, "add", "--all")
    if staged.returncode != 0:
        raise GreenUnavailable(f"could not read green's changes: {staged.stderr.strip()[:300]}")
    try:
        _refuse_links(green, "diff", "--cached", "--no-renames", "--name-only", "-z", green.base)
    except GreenUnavailable:
        _git(green, "read-tree", green.base)
        raise
    kept_out = _git(green, "reset", "-q", green.base, "--", *COORDINATION_PATHS)
    ignored = _new_files_the_running_copy_ignores(green)
    for start in range(0, len(ignored), 200):  # in batches: a Windows command line has a length limit
        _git(green, "reset", "-q", green.base, "--", *ignored[start : start + 200])
    if kept_out.returncode != 0:
        raise GreenUnavailable(
            f"could not leave Thomas's board out of green's changes: {kept_out.stderr.strip()[:300]}"
        )


# What each copy held when it was last staged whole, by its git folder: a read of a copy that has not changed since is
# not staged again. Measured 2026-10-28, one hand-in test staged the same unchanged copy 14 times, about six git
# processes each, and git processes were 43-44% of the most-selected test files' CPU.
_STAGED: dict[str, tuple[str, bytes, bytes]] = {}


def worktree_stamp(work: Path) -> bytes:
    """A digest of every name, mode, size and write time under *work*, green's own ``.git`` pointer left out."""
    digest = hashlib.blake2b(digest_size=16)
    root = os.fspath(work)
    pending = [root]
    prefix = len(root) if root.endswith(os.sep) else len(root) + 1
    while pending:
        folder = pending.pop()
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            if entry.name == ".git" and folder == root:
                continue
            # Each file's own stat, not the folder listing's copy: NTFS updates a listing's size and write time
            # lazily, so a file written just before read differently a moment later (2026-10-28).
            info = os.stat(entry.path, follow_symlinks=False)
            digest.update(entry.path[prefix:].encode("utf-8", errors="surrogateescape"))
            digest.update(f":{info.st_mode}:{info.st_size}:{info.st_mtime_ns}\0".encode("ascii"))
            if entry.is_dir(follow_symlinks=False):
                pending.append(entry.path)
    return digest.digest()


def _stamp(green: Green) -> tuple[str, bytes, bytes] | None:
    """Green's base, what its index stages (one ``ls-files``: git's own reads rewrite the index file without changing
    what it stages) and its files; None when they cannot be read."""
    try:
        listed = _git(green, "ls-files", "-s", "-z")
        if listed.returncode != 0:
            return None
        staged = hashlib.blake2b(listed.stdout.encode("utf-8", errors="surrogateescape"), digest_size=16).digest()
        return (green.base, staged, worktree_stamp(green.work))
    except (OSError, GreenUnavailable):
        return None


def _stage_unless_unchanged(green: Green) -> None:
    """Stage green's whole change unless its files, its index and its base are as they were when it was last staged.

    The files are read before git stages and the mark is kept only when they read the same after: a write that lands
    while git stages is never taken as staged. A copy whose state cannot be read is staged, as before. A read that
    finds nothing moved costs one git process instead of about six."""
    key = str(green.git_dir)
    before = _stamp(green)
    if before is not None and _STAGED.get(key) == before:
        return
    _STAGED.pop(key, None)
    _stage_everything(green)
    after = _stamp(green)
    if before is not None and after is not None and (after[0], after[2]) == (before[0], before[2]):
        _STAGED[key] = after


def discard_coordination_edits(green: Green) -> None:
    """Make Thomas's board and problem logs on disk what green's index holds, which is never handed in anyway.

    ``_stage_everything`` keeps them out of the index only, so on disk they differ from it, and git will not move a
    file whose disk copy differs: merging dev in failed with "Entry 'plans/thomas/WORKBOARD.md' not uptodate"
    (2026-09-27), and dev changes the board with nearly every landing.
    """
    edited = _git(green, "diff", "--name-only", "-z", "--", *COORDINATION_PATHS)
    names = [name for name in edited.stdout.split("\0") if name] if edited.returncode == 0 else []
    for start in range(0, len(names), 200):  # in batches: a Windows command line has a length limit
        _git(green, "checkout", "-q", "--", *names[start : start + 200])
    _git(green, "clean", "-f", "-q", "--", *COORDINATION_PATHS)  # logs the copy made itself


def changed_paths(green: Green, *, _staged: bool = False) -> list[str]:
    """Every path green changed against its base; _staged reuses an unchanged, already-staged index."""
    return [path for _status, path in changed_status(green, _staged=_staged)]


def changed_status(green: Green, *, _staged: bool = False) -> list[tuple[str, str]]:
    """(status, path) for every path green changed against its base: A added, M changed, D deleted.

    The ratchet checks the statuses, not only the names: a deletion of a file the
    candidate never touched is what scratch run 9c submitted (``ratchet/attempt.py``).
    Only pass _staged when the caller just staged this green and no process or write
    has touched it since; normal callers stage afresh.
    """
    if not _staged:
        _stage_unless_unchanged(green)
    names = _git(green, "diff", "--cached", "--no-renames", "--name-status", "-z", green.base)
    if names.returncode != 0:
        raise GreenUnavailable(f"could not list green's changes: {names.stderr.strip()[:300]}")
    # -z writes status and path as separate NUL-terminated fields, in that order.
    fields = [field for field in names.stdout.split("\0") if field]
    return [(fields[i][:1], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]


def green_patch(green: Green, *, _staged: bool = False) -> str:
    """Green's whole change as one patch that applies to its base commit.

    Read as bytes and decoded with ``surrogateescape``, so encoding it the same
    way gives back exactly what git wrote. Read in text mode, the carriage return
    of every CRLF line in a changed file was dropped and the patch no longer
    applied to the file it came from (found by the promoter's tests, 2026-09-22).
    """
    if not _staged:
        _stage_unless_unchanged(green)
    command = _git_command(green, "diff", "--cached", "--no-renames", "--binary", "--full-index", green.base)
    try:
        diff = subprocess.run(
            command, cwd=str(green.work), env=_clean_env(), capture_output=True, timeout=_GIT_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise GreenUnavailable(f"reading green's patch did not finish in {_GIT_TIMEOUT_S:g}s") from exc
    if diff.returncode != 0:
        raise GreenUnavailable(f"could not diff green: {diff.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return diff.stdout.decode("utf-8", errors="surrogateescape")


# The ratchet merges without committing, and git still wants a name for the merge it prepares
# (measured 2026-09-24: "Committer identity unknown", exit 128, with no identity configured).
_RATCHET_IDENTITY = ("-c", "user.name=Thomas ratchet", "-c", "user.email=ratchet@thomas.invalid")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _unmerged(green: Green) -> list[str]:
    listed = _git(green, "diff", "--name-only", "--diff-filter=U", "-z")
    return sorted({name for name in listed.stdout.split("\0") if name})


def apply_candidate(green: Green, sha: str, *, pick: bool = False) -> list[str]:
    """Bring commit *sha* into green without committing; return the paths left in conflict.

    A merge (``--no-ff --no-commit``), or with ``pick`` a cherry-pick of that one
    commit: the ratchet picks a candidate stacked on work that already landed
    under another commit, so only its own change comes along.
    """
    if not _FULL_SHA_RE.match(str(sha or "")):
        raise GreenUnavailable(f"not a full commit id: {sha!r}")
    verb = ("cherry-pick", "--no-commit") if pick else ("merge", "--no-ff", "--no-commit", "--no-edit")
    done = _git(green, *_RATCHET_IDENTITY, *verb, sha)
    conflicted = _unmerged(green)
    if done.returncode != 0 and not conflicted:
        raise GreenUnavailable(f"could not bring {sha[:12]} into green: {(done.stderr or done.stdout).strip()[:300]}")
    return conflicted


def restore_paths(green: Green, paths: Iterable[str]) -> None:
    """Put *paths* back as they are at green's base; a file the base lacks is removed.

    A path a merge left in conflict is resolved the same way: ``git checkout <base> -- <path>`` replaces its
    unmerged entries (measured on a scratch repository, 2026-09-24).
    """
    for path in paths:
        if _git(green, "cat-file", "-e", f"{green.base}:{path}").returncode == 0:
            restored = _git(green, "checkout", green.base, "--", path)
        else:
            restored = _git(green, "rm", "-q", "-f", "--ignore-unmatch", "--", path)
        if restored.returncode != 0:
            raise GreenUnavailable(f"could not put {path} back: {restored.stderr.strip()[:300]}")


def green_tree(green: Green, *, _staged: bool = False) -> str:
    """The tree green holds now, everything staged, as a git object: for reading, never for committing."""
    if not _staged:
        _stage_unless_unchanged(green)
    written = _git(green, "write-tree")
    if written.returncode != 0:
        raise GreenUnavailable(f"could not read green's tree: {written.stderr.strip()[:300]}")
    return written.stdout.strip()


def checkout_detached(green: Green, rev: str) -> None:
    """Point green's files at another commit: the ratchet proves a commit already on dev this way."""
    done = _git(green, "checkout", "--quiet", "--force", "--detach", rev)
    if done.returncode != 0:
        raise GreenUnavailable(f"could not check out {rev[:12]}: {done.stderr.strip()[:300]}")


def apply_patch(green: Green, patch: str) -> list[str]:
    """Apply a patch made in another green (``green_patch``) here, three-way; return the paths left in conflict."""
    command = _git_command(green, "apply", "--3way", "--index", "--whitespace=nowarn", "-")
    try:
        done = subprocess.run(
            command,
            cwd=str(green.work),
            env=_clean_env(),
            input=patch.encode("utf-8", errors="surrogateescape"),
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GreenUnavailable(f"applying a patch did not finish in {_GIT_TIMEOUT_S:g}s") from exc
    conflicted = _unmerged(green)
    if done.returncode != 0 and not conflicted:
        raise GreenUnavailable(f"the patch does not apply: {done.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return conflicted


def _force_writable(func: object, path: str, _exc: object) -> None:
    # Git writes its objects read-only; Windows will not delete a read-only file.
    os.chmod(path, stat.S_IWRITE)
    func(path)  # type: ignore[operator]


def mark_settled(green: Green) -> None:
    """Record that this green's run is over, so the sweep takes it at any age."""
    try:
        (green.git_dir / SETTLED_NAME).write_text(str(time.time()), encoding="utf-8")
    except OSError:
        log.warning("could not mark green %s settled", green.execution_id, exc_info=True)


def mark_kept(green: Green, reason: str) -> None:
    """Record that this green holds unfinished work, so the sweep keeps it for
    ``KEPT_MAX_AGE_S`` instead of 24h. Live 2026-09-24: five self-fixes ended
    failed with real changes in their greens, and the sweep was going to take
    all of it. A settled marker still wins: the sweep then takes it at once."""
    try:
        payload = {"reason": str(reason or ""), "kept_at": time.time()}
        (green.git_dir / KEPT_NAME).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.warning("could not mark green %s kept", green.execution_id, exc_info=True)


def remove_green(green: Green, *, attempts: int = 3) -> None:
    """Capture before deletion; retry Windows folders briefly held by ended processes."""
    from thomas.server import keeper_guard

    watcher = _EDIT_WATCHES.pop(green.execution_id, None)
    if watcher is not None:
        try:
            watcher.get_loop().call_soon_threadsafe(watcher.cancel)
        except RuntimeError:
            # The start request's loop may already have closed during shutdown.
            pass
    with keeper_guard.removing(green):
        for attempt in range(attempts):
            try:
                for folder in (green.work, green.git_dir):
                    if folder.exists():
                        shutil.rmtree(folder, onexc=_force_writable)
                return
            except OSError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.5)


def sweep(*, max_age_s: float = 24 * 60 * 60.0, now: float | None = None, skip: Iterable[str] = ()) -> list[str]:
    """Remove greens older than ``max_age_s`` (``KEPT_MAX_AGE_S`` for a kept one): runs that ended without settling.

    ``skip`` names greens a live run is using, whatever their age: an Autopilot project can outlive 24h.
    """
    root = green_root()
    moment = time.time() if now is None else now
    removed: list[str] = []
    spared = {str(name) for name in skip}
    for git_dir in sorted((root / "git").glob("*")) if (root / "git").is_dir() else []:
        if git_dir.name in spared:
            continue
        meta = _metadata(git_dir) or {}
        try:
            created = float(meta.get("created_at") or git_dir.stat().st_mtime)  # type: ignore[arg-type]
        except (OSError, TypeError, ValueError):
            continue
        # A settled green is finished with, whatever its age: its run already
        # tried to remove it and something was still holding it.
        limit = KEPT_MAX_AGE_S if (git_dir / KEPT_NAME).exists() else max_age_s
        if moment - created <= limit and not (git_dir / SETTLED_NAME).exists():
            continue
        stray = Green(git_dir.name, root / "work" / git_dir.name, git_dir, str(meta.get("base") or ""), Path())
        try:
            remove_green(stray)
        except OSError:
            log.warning("could not remove stray green %s", git_dir.name, exc_info=True)
            continue
        removed.append(git_dir.name)
    return removed


__all__ = [
    "CAGE_ACCOUNT",
    "GREEN_ROOT_ENV",
    "Green",
    "GreenUnavailable",
    "apply_candidate",
    "apply_patch",
    "changed_paths",
    "changed_status",
    "checkout_detached",
    "create_green",
    "find_green",
    "first_edit_latency",
    "git",
    "green_patch",
    "green_root",
    "green_tree",
    "mark_kept",
    "record_request_start",
    "remove_green",
    "set_base",
    "restore_paths",
    "sweep",
]
