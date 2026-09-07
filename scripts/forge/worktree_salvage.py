"""Archive a worktree completely -- unique commits AND dirty state -- as
git refs before anything removes it, with a working restore command.

WHY THIS EXISTS: `worktree_triage.py` only reports; `tidy_refs.py` only
reaps what is *provably* safe (clean, merged). A worktree with a unique
commit or uncommitted edits has always meant "leave it alone forever."
This tool makes removal of those safe too: HEAD and the full dirty
working-tree state are captured as refs first, so `git worktree remove`
never destroys anything not also sitting in `refs/archive/worktree/`.

HOW THE DIRTY SNAPSHOT IS TAKEN: the worktree's real index is never
touched (another agent may be using it) -- all plumbing runs against a
*copy* pointed to via GIT_INDEX_FILE.
  0. capture `git status --porcelain=v1 -uall` FIRST, before any staging
     -- the independent, ground-truth record of what SHOULD end up in
     the snapshot (both this and the diff in step 3 run with
     `-c core.quotepath=false` so a non-ASCII filename is spelled the
     same raw way on both sides -- item 2 under HARDENING).
  1. copy the index to a temp file
  2. `add -A` with GIT_INDEX_FILE=<temp> and `-c core.autocrlf=false
     -c core.safecrlf=false` (byte-exact capture; a routine CRLF/LF
     notice must not masquerade as the data-loss warning item 1 watches
     for) -> stages the TEMP index only; `.gitignore` is respected on
     purpose (ignored junk is not work).
  3. `write-tree` -> a "content tree". `diff --name-only` against HEAD's
     tree gives actual_files, cross-checked against step 0's expected
     set (after dropping AD-shaped phantoms -- item 3) and against
     `_batch_tree_paths_exist`.
  4. if dirty: the (verified) expected-files list is written as a blob,
     added to the SAME temp index at the reserved path
     _EXPECTED_FILES_TREE_PATH, and `write-tree` runs once more -> the
     final snapshot tree. `commit-tree` (HEAD as parent, author/committer
     praxis-salvage, message via stdin) -> the dirty snapshot commit.
     verify() later reads the reserved tree entry as the independent
     record, not a re-run of the diff that built it (item 6).

Verified empirically against a real *linked* worktree (.git is a file):
GIT_INDEX_FILE alone is sufficient; no manual GIT_WORK_TREE/GIT_DIR
override needed. The real index on disk is unchanged after a run.

HARDENING (each item below traces to a specific review or live-batch
failure; see git blame / task-1-report.md for the incident behind each):
1. `add -A` exit 0 is not trusted alone: a stderr `warning:`/`error:`
   line fails the salvage (a Windows long-path warning can drop a whole
   subtree while git still exits 0). A NOTE is printed when
   core.longpaths is not true (the usual cause).
2. Non-ASCII filenames: status and diff both force
   `-c core.quotepath=false` so a name is spelled identically on the
   status side and the diff side -- otherwise one non-ASCII dirty
   filename is a permanent missing+extra false SKIP.
3. AD entries: `git status` reports "AD path" for a file `git add`-ed
   then deleted from disk before salvage runs. That path is in NEITHER
   the HEAD tree nor the content tree (add -A follows the working tree
   and drops it from the temp index too) and can never appear in a tree
   diff -- counting it as expected is a permanent false SKIP (live: a
   130-file batch). Dropped via `_batch_tree_paths_exist` before the
   cross-check, one batch call per tree, not one subprocess per path.
4. Naming is idempotent per worktree path; dry-run writes NO refs.
   Re-running salvage (dry-run then --apply, or --apply twice) at the
   same HEAD reuses the same name; suffixing (-2, -3, ...) only happens
   on a genuine collision with a DIFFERENT HEAD.
5. restore refuses (nonzero exit) when its archive fails verify(),
   unless --force -- which still prints the reason and marks the result
   RESTORE FORCED. A new-format restore also strips the reserved
   bookkeeping entry from the checkout (it was never real dirty content).
6. The expected-files list lives as a blob INSIDE the snapshot tree
   (reserved path _EXPECTED_FILES_TREE_PATH), not the commit message: a
   10,614-file worktree crashed `commit-tree -m <message>` with WinError
   206 (command line too long), and a blob referenced only from a
   message is unreachable by git's GC and prunable. The message itself
   (short, fixed-size) is passed via stdin, never -m. verify()/restore()
   still support the OLD inline-message format for pre-fix archives.
7. `.venv` junction removal wraps os.rmdir (a locked handle/AV scanner
   can raise plain OSError -> SalvageError, not an uncaught crash). A
   failed `git worktree remove --force` that still DEregistered the
   worktree (admin dir gone, directory left -- a locked-file case) is
   reported SALVAGE PARTIAL, not SKIP, since SKIP means untouched.

SAFETY: refuse-over-guess (any git failure mid-salvage -> SALVAGE SKIP,
nothing half-done); removal requires --apply AND a passing in-process
verify(); a `.venv` junction's target survival is asserted after
unlinking the link; a snapshot is refused below 5 GB free on the
worktree's git-dir drive; the main checkout is never salvaged/removed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB
_IDENTITY_NAME = "praxis-salvage"
_IDENTITY_EMAIL = "praxis-salvage@localhost"
_EXPECTED_FILES_MARKER = "expected-files:"  # OLD format only (inline in commit message body)
_EXPECTED_FILES_TREE_PATH = ".praxis-salvage-expected-files"  # NEW format: reserved tree entry
_EXPECTED_FILES_BLOB_HEADER = "Expected-Files-Blob: "  # informational only; the tree entry is authoritative


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Thin wrapper around subprocess.run so tests can monkeypatch one seam."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(cwd), *args], env=env)


_RAW_CONFIG = [
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.safecrlf=false",
    "-c",
    "core.quotepath=false",
]


def _git_raw(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Like _git, but forces core.autocrlf/core.safecrlf/core.quotepath off
    for this one invocation, so the command sees exact on-disk bytes and
    raw (unescaped, unquoted) filenames rather than a normalized view.

    Used for the pre-snapshot `status` capture, the `add -A` staging, and
    the `diff --name-only` calls that derive the actual-changed-file set
    (both in snapshot_worktree and in verify) -- all of them must agree
    with each other on what "changed" means and what a given path is
    actually spelled as, or two independent quirks produce a false
    mismatch:
      - CRLF/LF: a file that differs only by line ending under the
        ambient (possibly core.autocrlf=true) config looks dirty to one
        call and clean to the other.
      - quotepath: with the default core.quotepath=true, `git status`
        and `git diff` C-quote/octal-escape non-ASCII filenames for
        display; the surrounding-quote stripping in _files_from_status
        does not decode those octal escapes, so a single non-ASCII dirty
        filename can come out spelled two different ways on the status
        side vs the diff side -- a permanent missing+extra false SKIP no
        amount of retrying fixes. Forcing quotepath off makes every one
        of these calls emit the same raw UTF-8 bytes.
    Using the same override everywhere keeps all of them consistent
    regardless of the worktree's own config, while still capturing
    byte-exact content rather than a normalized copy.
    """
    return _run(["git", *_RAW_CONFIG, "-C", str(cwd), *args], env=env)


class SalvageError(Exception):
    """A git command failed mid-salvage; carries the reason for SALVAGE SKIP."""


def _require(proc: subprocess.CompletedProcess, what: str) -> str:
    if proc.returncode != 0:
        raise SalvageError(f"{what} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def _require_raw(proc: subprocess.CompletedProcess, what: str) -> str:
    """Like _require, but returns stdout WITHOUT stripping.

    `_require`'s `.strip()` is safe for single-value output (a sha, a tree
    id) but corrupts multi-line `git status --porcelain` output: porcelain
    v1's leading column is a literal space when a file is unmodified in
    the index (e.g. " M path"), and strip() eats exactly that leading
    space off the first line, shifting every downstream slice by one
    character for that line alone.
    """
    if proc.returncode != 0:
        raise SalvageError(f"{what} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def _require_clean(proc: subprocess.CompletedProcess, what: str) -> str:
    """Like _require, but ALSO fails if stderr carries a `warning:`/`error:`
    line even though git exited 0.

    git's exit code alone is not trustworthy for `add -A`: a long-path
    warning on Windows (or an embedded-repo warning, or similar) can leave
    an entire subtree silently absent from the resulting tree while the
    command still reports success. Refuse-over-guess applies here too.
    """
    out = _require(proc, what)
    for line in proc.stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("warning:") or stripped.startswith("error:"):
            raise SalvageError(f"{what} reported a problem despite exit 0: {stripped}")
    return out


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "worktree"


def _ref_exists(repo_root: Path, ref: str) -> bool:
    return _git(repo_root, "show-ref", "--verify", "--quiet", ref).returncode == 0


def _worktree_is_registered(repo_root: Path, worktree: Path) -> bool:
    """True if `worktree` still appears in `git worktree list --porcelain`.

    A failed `git worktree remove --force` does not necessarily mean the
    worktree was "left fully in place": git can deregister a worktree
    (delete its `.git/worktrees/<name>` admin dir) and still fail to
    delete the working directory itself -- e.g. a locked file blocking
    the final rmdir (observed live: "error: failed to delete ...:
    Directory not empty" after the worktree had already vanished from
    `git worktree list`). That state is neither "removed" nor "left
    alone"; salvage() must tell the two apart rather than call both of
    them SALVAGE SKIP.

    If the listing itself fails, conservatively assumes still-registered
    (the SKIP-shaped assumption) rather than claim PARTIAL on a guess.
    """
    proc = _git(repo_root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return True
    target = str(worktree.resolve()).replace("\\", "/").rstrip("/")
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :].strip().replace("\\", "/").rstrip("/")
            if path == target:
                return True
    return False


def _commit_tree_sha(repo_root: Path, commit_sha: str | None) -> str | None:
    """The tree a commit points at, or None if commit_sha is None/unresolvable.

    Used to compare archived dirty content by what it actually holds
    rather than by commit sha: two `commit-tree` calls with an identical
    tree/parent/author but different wall-clock timestamps produce
    different commit shas even though nothing about the content changed.
    """
    if commit_sha is None:
        return None
    proc = _git(repo_root, "rev-parse", f"{commit_sha}^{{tree}}")
    return proc.stdout.strip() if proc.returncode == 0 else None


def resolve_name(repo_root: Path, worktree: Path, head_sha: str) -> tuple[str, bool]:
    """Returns (name, is_reuse). Read-only -- never writes a ref, so it is
    safe to call from a dry run.

    Reuses an existing archived name if that name's head ref already
    equals this worktree's current HEAD (idempotent re-salvage of the same
    worktree state -- e.g. dry-run followed by --apply, or a retried
    --apply after a locked-worktree SKIP). Only suffixes (-2, -3, ...)
    when an existing name at that slug belongs to a DIFFERENT head sha --
    a genuine collision with some other worktree's archive.
    """
    base = slugify(worktree.name)
    candidate = base
    n = 2
    while True:
        ref = f"refs/archive/worktree/{candidate}"
        if not _ref_exists(repo_root, ref):
            return candidate, False
        existing = _git(repo_root, "rev-parse", "--verify", ref)
        if existing.returncode == 0 and existing.stdout.strip() == head_sha:
            return candidate, True
        candidate = f"{base}-{n}"
        n += 1


def _free_bytes(path: Path) -> int:
    probe = path if path.exists() else path.parent
    return shutil.disk_usage(str(probe)).free


def _has_venv_junction(venv: Path) -> bool:
    if hasattr(os.path, "isjunction") and os.path.isjunction(str(venv)):
        return True
    return venv.is_symlink()


def _unlink_venv_junction(worktree: Path) -> None:
    """Remove a `.venv` junction (the LINK only) and assert its target survives.

    os.rmdir on a Windows directory junction/reparse point deletes only the
    reparse point, never the target directory's contents -- this is the
    load-bearing venv-junction rule from the plan's Global Constraints.
    os.rmdir itself can still raise (locked handle, AV scanner holding the
    reparse point open); that must become a SALVAGE SKIP, not a crash.
    """
    venv = worktree / ".venv"
    if not _has_venv_junction(venv):
        return
    target = venv.resolve()
    try:
        os.rmdir(str(venv))
    except OSError as exc:
        raise SalvageError(f"could not unlink .venv junction: {exc}") from exc
    if not target.exists():
        raise SalvageError(f".venv junction target vanished after unlinking the link: {target}")


def _longpaths_note(repo_root: Path) -> str | None:
    """A NOTE line when core.longpaths is not enabled -- the single most
    common cause of a Windows `add -A` silently dropping a subtree while
    still exiting 0."""
    proc = _git(repo_root, "config", "--get", "core.longpaths")
    value = proc.stdout.strip().lower() if proc.returncode == 0 else ""
    if value == "true":
        return None
    return (
        "NOTE core.longpaths is not set to true in this repo's config -- "
        "git can silently omit files under long paths on Windows; run "
        "`git config core.longpaths true` to close that gap."
    )


def _files_from_status(status_out: str) -> set[str]:
    """Parse `git status --porcelain=v1 --untracked-files=all` output into
    a set of paths. --untracked-files=all is required (not the default
    `normal`) so an untracked directory is expanded to its individual
    files -- matching the per-file granularity `add -A` produces, instead
    of collapsing to one `?? dirname/` line that would falsely look like
    a mismatch against the tree diff.
    """
    files: set[str] = set()
    for line in status_out.splitlines():
        if len(line) <= 3:
            continue
        rest = line[3:]
        if " -> " in rest:  # renames: "XY OLD -> NEW"
            rest = rest.split(" -> ", 1)[1]
        rest = rest.strip()
        if len(rest) >= 2 and rest.startswith('"') and rest.endswith('"'):
            rest = rest[1:-1]
        if rest:
            files.add(rest)
    return files


def _batch_tree_paths_exist(cwd: Path, tree_sha: str, paths: set[str]) -> set[str]:
    """Which of `paths` exist as a blob at `tree_sha`.

    One `git cat-file --batch-check` call regardless of how many paths --
    scale-safe for thousands of paths (a subprocess per path would not
    be, at the scale this tool has to work at). `cat-file --batch-check`
    reads one "<tree>:<path>" per input line and prints results in the
    same order, so paths and output lines can be zipped positionally.
    """
    if not paths:
        return set()
    ordered = list(paths)
    stdin_text = "\n".join(f"{tree_sha}:{p}" for p in ordered) + "\n"
    proc = _run(["git", "-C", str(cwd), "cat-file", "--batch-check"], input=stdin_text)
    if proc.returncode != 0:
        raise SalvageError(f"cat-file --batch-check against {tree_sha} failed: {proc.stderr.strip()}")
    existing: set[str] = set()
    for path, line in zip(ordered, proc.stdout.splitlines()):
        if not line.endswith(" missing"):
            existing.add(path)
    return existing


def _parse_expected_files(body: str) -> set[str] | None:
    lines = body.splitlines()
    if _EXPECTED_FILES_MARKER not in lines:
        return None
    idx = lines.index(_EXPECTED_FILES_MARKER)
    return {line for line in lines[idx + 1 :] if line.strip()}


def snapshot_worktree(repo_root: Path, worktree: Path, head_sha: str) -> tuple[str | None, int]:
    """Build the dirty snapshot commit for `worktree`, if any.

    Returns (dirty_sha_or_None, file_count) -- file_count EXCLUDES the
    reserved expected-files bookkeeping entry described below. Never
    touches the worktree's real index -- all plumbing runs against a temp
    copy pointed to by GIT_INDEX_FILE. Cross-checks the resulting tree
    against an independent `git status` snapshot taken BEFORE any
    staging, so a silently-broken `add -A` cannot self-certify as
    correct.

    The expected-files list is recorded as a blob INSIDE the snapshot
    commit's own tree, at the reserved path _EXPECTED_FILES_TREE_PATH --
    not embedded in the commit message. Two reasons: (1) a live worktree
    with 10,614 dirty files crashed `commit-tree -m <message>` with
    WinError 206 (command line too long) when the list was inlined into
    the -m argument; (2) a blob written via a dangling `hash-object -w`
    and referenced only from a commit MESSAGE is not reachable by git's
    own GC rules and can be pruned out from under a later verify(). Living
    inside the tree makes it reachable via the ordinary commit -> tree ->
    blob chain, and the commit message itself is passed via stdin (never
    -m), so no command-line length limit applies to it either, however
    long the file list.
    """
    gitdir = _require(_git(worktree, "rev-parse", "--absolute-git-dir"), "rev-parse --absolute-git-dir")
    real_index = Path(gitdir) / "index"

    free = _free_bytes(Path(gitdir))
    if free < MIN_FREE_BYTES:
        raise SalvageError(f"insufficient disk space for snapshot: {free} bytes free (< 5 GB) on {gitdir}")

    status_out = _require_raw(
        _git_raw(worktree, "status", "--porcelain=v1", "--untracked-files=all"), "status --porcelain=v1"
    )
    expected_files = _files_from_status(status_out)

    fd, temp_index_path = tempfile.mkstemp(prefix="salvage-index-", dir=gitdir)
    os.close(fd)
    temp_index = Path(temp_index_path)
    try:
        if real_index.exists():
            shutil.copy2(real_index, temp_index)
        else:
            temp_index.unlink()  # let `add -A` create a fresh index (unborn HEAD)

        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(temp_index)

        _require_clean(_git_raw(worktree, "add", "-A", env=env), "add -A")
        content_tree = _require(_git(worktree, "write-tree", env=env), "write-tree")

        head_tree = _require(_git(worktree, "rev-parse", f"{head_sha}^{{tree}}"), "rev-parse HEAD^{tree}")

        # `git status` reports "AD" (and the analogous rename-then-delete
        # forms) for a path that was `git add`-ed -- staged in the index
        # as new/modified -- and then deleted from disk before this
        # salvage ran. `add -A` follows the working tree and removes that
        # path from the temp index too, so it ends up in NEITHER head_tree
        # NOR content_tree: it cannot appear in a tree diff either way. If
        # left in expected_files, the cross-check below can never match --
        # a permanent, unfixable "missing=[...]" false SKIP (reproduced
        # live: a 130-file batch refused this way). Drop any expected path
        # absent from both trees; checked via a single batch call per
        # tree, not one subprocess per path, so this stays scale-safe.
        phantom = expected_files - _batch_tree_paths_exist(worktree, head_tree, expected_files)
        phantom -= _batch_tree_paths_exist(worktree, content_tree, expected_files)
        if phantom:
            expected_files = expected_files - phantom

        if content_tree == head_tree:
            if expected_files:
                raise SalvageError(
                    f"status reported {len(expected_files)} dirty file(s) before snapshotting "
                    f"but the snapshot tree is identical to HEAD -- likely under-capture: "
                    f"{sorted(expected_files)}"
                )
            return None, 0

        changed = _require(_git_raw(worktree, "diff", "--name-only", head_tree, content_tree), "diff head vs snapshot")
        actual_files = {line for line in changed.splitlines() if line.strip()}

        if actual_files != expected_files:
            missing = sorted(expected_files - actual_files)
            extra = sorted(actual_files - expected_files)
            raise SalvageError(
                f"snapshot tree does not match the pre-snapshot `git status`: missing={missing} extra={extra}"
            )

        # Record the (already-verified) expected-files list as a blob
        # inside the tree itself -- reachable, not a dangling hash-object.
        blob_content = "\n".join(sorted(actual_files)) + "\n"
        blob_sha = _require(
            _run(["git", "-C", str(worktree), "hash-object", "-w", "--stdin"], input=blob_content),
            "hash-object expected-files blob",
        )
        _require(
            _git(
                worktree,
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob_sha},{_EXPECTED_FILES_TREE_PATH}",
                env=env,
            ),
            "update-index expected-files entry",
        )
        snapshot_tree = _require(_git(worktree, "write-tree", env=env), "write-tree (with expected-files entry)")

        commit_env = dict(os.environ)
        commit_env.update(
            GIT_AUTHOR_NAME=_IDENTITY_NAME,
            GIT_AUTHOR_EMAIL=_IDENTITY_EMAIL,
            GIT_COMMITTER_NAME=_IDENTITY_NAME,
            GIT_COMMITTER_EMAIL=_IDENTITY_EMAIL,
        )
        # Short, fixed-size message regardless of file count -- the file
        # list itself lives in the tree (above), not here. The blob line
        # is informational (fast lookup without a tree read); the tree
        # entry is authoritative. Passed via stdin, never -m, so no
        # command-line length limit applies even to this short header.
        message = "\n".join(
            [
                f"praxis-salvage snapshot of {worktree.name} ({len(actual_files)} files)",
                "",
                f"Expected-Files-Path: {_EXPECTED_FILES_TREE_PATH}",
                f"{_EXPECTED_FILES_BLOB_HEADER}{blob_sha}",
            ]
        )
        dirty_sha = _require(
            _run(
                ["git", "-C", str(worktree), "commit-tree", snapshot_tree, "-p", head_sha],
                input=message,
                env=commit_env,
            ),
            "commit-tree",
        )
        return dirty_sha, len(actual_files)
    finally:
        if temp_index.exists():
            temp_index.unlink()


def verify(repo_root: Path, name: str) -> tuple[bool, str, str | None, str | None, int]:
    """In-process check: both refs resolvable; the dirty snapshot's tree
    matches its recorded pre-snapshot expected-files list (an independent
    record, not a re-run of the diff that built the snapshot); dirty
    commit's parent is the archived head. Returns
    (ok, message, head_sha, dirty_sha, files) -- files EXCLUDES the
    reserved expected-files bookkeeping entry (new format only; see
    below).

    Supports two archive formats, since old archives must keep verifying
    without being re-salvaged:
      - NEW: the expected-files list is a blob at the reserved path
        _EXPECTED_FILES_TREE_PATH inside the dirty commit's own tree
        (reachable, GC-safe, no command-line length limit regardless of
        file count). This is authoritative when present.
      - OLD (pre-fix archives): the list was embedded inline in the
        commit message body under _EXPECTED_FILES_MARKER. Used only when
        the reserved tree entry is absent.
    """
    head_ref = f"refs/archive/worktree/{name}"
    dirty_ref = f"refs/archive/worktree/{name}-dirty"

    head_proc = _git(repo_root, "rev-parse", "--verify", head_ref)
    if head_proc.returncode != 0:
        return False, f"head ref {head_ref} does not resolve", None, None, 0
    head_sha = head_proc.stdout.strip()

    if not _ref_exists(repo_root, dirty_ref):
        return True, "clean (no dirty ref)", head_sha, None, 0

    dirty_proc = _git(repo_root, "rev-parse", "--verify", dirty_ref)
    if dirty_proc.returncode != 0:
        return False, f"dirty ref {dirty_ref} does not resolve", head_sha, None, 0
    dirty_sha = dirty_proc.stdout.strip()

    parent = _git(repo_root, "rev-parse", f"{dirty_ref}^")
    if parent.returncode != 0 or parent.stdout.strip() != head_sha:
        return False, "dirty snapshot's parent is not the archived head", head_sha, dirty_sha, 0

    diff = _git_raw(repo_root, "diff", "--name-only", head_sha, dirty_sha)
    if diff.returncode != 0:
        return False, "could not diff head against dirty snapshot", head_sha, dirty_sha, 0
    actual = {line for line in diff.stdout.splitlines() if line.strip()}

    reserved_blob = _git(repo_root, "rev-parse", "--verify", f"{dirty_sha}:{_EXPECTED_FILES_TREE_PATH}")
    if reserved_blob.returncode == 0:
        # NEW format: authoritative expected-files list lives in the tree.
        actual.discard(_EXPECTED_FILES_TREE_PATH)
        cat = _git(repo_root, "cat-file", "blob", reserved_blob.stdout.strip())
        if cat.returncode != 0:
            return False, "expected-files blob could not be read", head_sha, dirty_sha, len(actual)
        expected = {line for line in cat.stdout.splitlines() if line.strip()}
    else:
        # OLD format: pre-fix archives recorded the list inline in the
        # commit message instead of the tree. Must keep working.
        body_proc = _git(repo_root, "show", "-s", "--format=%B", dirty_ref)
        expected = _parse_expected_files(body_proc.stdout) if body_proc.returncode == 0 else None
        if expected is None:
            return (
                False,
                "dirty commit has no recorded expected-files list (neither tree entry nor message)",
                head_sha,
                dirty_sha,
                len(actual),
            )

    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        return (
            False,
            f"snapshot does not match its recorded pre-snapshot expected file set (missing={missing} extra={extra})",
            head_sha,
            dirty_sha,
            len(actual),
        )

    return True, "ok", head_sha, dirty_sha, len(actual)


def salvage(repo_root: Path, worktree: Path, *, apply: bool) -> str:
    """Runs one salvage; returns the exact line to print --
    `SALVAGE OK ...`, `SALVAGE SKIP ...`, or `SALVAGE PARTIAL ...`.

    Dry-run (apply=False) is ref-free: it computes and reports the
    would-be name, head/dirty shas, and file count, but writes no ref.
    Loose git objects (the snapshot tree/commit) may still be created --
    that is harmless and left for `git gc` -- but nothing is "archived"
    until --apply actually points a ref at them.

    SKIP vs PARTIAL on a failed `git worktree remove --force`: SKIP means
    the worktree is untouched and still registered (`git worktree list`
    still shows it) -- the ordinary "left fully in place" meaning every
    other SKIP reason has. PARTIAL means git deregistered the worktree
    (its `.git/worktrees/<name>` admin dir is gone) but still failed to
    delete the directory itself -- an orphaned directory with a dangling
    `.git` file, not "left in place". The archive refs are safe either
    way (written and verified before removal is even attempted); PARTIAL
    just means the directory needs manual cleanup once `verify` confirms
    the refs are intact.
    """
    worktree = worktree.resolve()
    if worktree == repo_root.resolve():
        return "SALVAGE SKIP main reason=refusing to salvage the main checkout"
    if not worktree.exists():
        return f"SALVAGE SKIP {slugify(worktree.name)} reason=worktree path does not exist: {worktree}"

    note = _longpaths_note(repo_root)
    if note:
        print(note)

    try:
        head_sha = _require(_git(worktree, "rev-parse", "HEAD"), "rev-parse HEAD")
        dirty_sha, file_count = snapshot_worktree(repo_root, worktree, head_sha)
        name, is_reuse = resolve_name(repo_root, worktree, head_sha)
    except SalvageError as exc:
        return f"SALVAGE SKIP {slugify(worktree.name)} reason={exc}"

    dirty_repr = dirty_sha if dirty_sha else "none"

    if not apply:
        return f"SALVAGE OK {name} head={head_sha} dirty={dirty_repr} changed={file_count} removed=no"

    prior_dirty_sha = None
    if is_reuse:
        prior = _git(repo_root, "rev-parse", "--verify", f"refs/archive/worktree/{name}-dirty")
        prior_dirty_sha = prior.stdout.strip() if prior.returncode == 0 else None

    try:
        _require(_git(repo_root, "update-ref", f"refs/archive/worktree/{name}", head_sha), "update-ref head")
        dirty_ref_name = f"refs/archive/worktree/{name}-dirty"
        if dirty_sha:
            _require(_git(repo_root, "update-ref", dirty_ref_name, dirty_sha), "update-ref dirty")
        elif prior_dirty_sha is not None:
            # The worktree is clean now, but a stale -dirty ref from a
            # prior archive of this same (reused) name still points at old
            # content. Left in place, verify()/restore() would keep
            # reporting that stale dirty snapshot even though the printed
            # SALVAGE OK line correctly says dirty=none -- a ref that lies
            # about what was actually removed. Delete it.
            _require(
                _git(repo_root, "update-ref", "-d", dirty_ref_name, prior_dirty_sha),
                "update-ref -d dirty (stale)",
            )

        ok, reason, *_ = verify(repo_root, name)
        if not ok:
            raise SalvageError(f"post-snapshot verify failed: {reason}")
    except SalvageError as exc:
        return f"SALVAGE SKIP {name} reason={exc}"

    # updated=yes only when the archived dirty CONTENT actually changed
    # this call (created, moved to different content, or deleted); compared
    # by tree, not commit sha -- see _commit_tree_sha.
    updated_suffix = ""
    if is_reuse:
        content_changed = _commit_tree_sha(repo_root, dirty_sha) != _commit_tree_sha(repo_root, prior_dirty_sha)
        updated_suffix = f" updated={'yes' if content_changed else 'no'}"

    try:
        _unlink_venv_junction(worktree)
    except SalvageError as exc:
        return f"SALVAGE SKIP {name} reason={exc}"

    remove_proc = _git(repo_root, "worktree", "remove", "--force", str(worktree))
    if remove_proc.returncode != 0:
        raw_reason = remove_proc.stderr.strip() or remove_proc.stdout.strip()
        reason = "; ".join(raw_reason.splitlines()) if raw_reason else "unknown"
        if _worktree_is_registered(repo_root, worktree):
            # Genuinely untouched: still registered, directory presumably
            # still there. This is the only case SALVAGE SKIP's usual
            # meaning ("left fully in place") actually holds.
            return f"SALVAGE SKIP {name} reason=worktree remove refused: {reason}"
        # git deregistered the worktree (removed its .git/worktrees/<name>
        # admin dir) but still failed to delete the directory -- an
        # orphaned directory with a dangling .git file, not "left in
        # place". The archive refs are already safe (written and verified
        # above); only the directory removal partially failed.
        return f"SALVAGE PARTIAL {name} head={head_sha} dirty={dirty_repr} reason=worktree remove refused: {reason} dir={worktree}"

    return f"SALVAGE OK {name} head={head_sha} dirty={dirty_repr} changed={file_count} removed=yes{updated_suffix}"


def restore(repo_root: Path, name: str, new_path: Path, *, apply: bool, force: bool = False) -> tuple[bool, str]:
    """Returns (ok, message). ok is False when the CLI should exit nonzero:
    either the restore itself failed, or verify() failed and --force was
    not given.
    """
    ok, reason, head_sha, dirty_sha, _files = verify(repo_root, name)
    if not ok:
        if head_sha is None:
            return False, f"RESTORE REFUSED {name} reason={reason} (nothing resolvable, --force cannot help)"
        if not force:
            return False, f"RESTORE REFUSED {name} reason={reason} (use --force to restore anyway)"

    target_sha = dirty_sha or head_sha
    forced = (not ok) and force

    if not apply:
        prefix = "RESTORE FORCED" if forced else "would restore"
        detail = f" verify_reason={reason}" if forced else ""
        return True, f"{prefix} {name}{detail} ({target_sha}) to {new_path}"

    proc = _git(repo_root, "worktree", "add", "--detach", str(new_path), target_sha)
    if proc.returncode != 0:
        return False, f"restore of {name} failed: {proc.stderr.strip() or proc.stdout.strip()}"

    # NEW-format dirty snapshots carry a reserved bookkeeping entry inside
    # their own tree (see snapshot_worktree) so it survives git gc.
    # restore() hands back the dirty state as it actually was -- that
    # bookkeeping file was never part of it, so strip it from the
    # checkout. Old-format archives and HEAD-only restores never have it;
    # the existence check makes this a no-op for them.
    if dirty_sha is not None and target_sha == dirty_sha:
        reserved = new_path / _EXPECTED_FILES_TREE_PATH
        if reserved.exists():
            reserved.unlink()

    if forced:
        return True, f"RESTORE FORCED {name} verify_reason={reason} path={new_path}"
    return True, str(new_path)


def _cmd_salvage(ns: argparse.Namespace) -> int:
    line = salvage(ns.repo_root, Path(ns.worktree), apply=ns.apply)
    print(line)
    return 0


def _cmd_restore(ns: argparse.Namespace) -> int:
    ok, message = restore(ns.repo_root, ns.name, Path(ns.new_path), apply=ns.apply, force=ns.force)
    print(message)
    return 0 if ok else 1


def _cmd_verify(ns: argparse.Namespace) -> int:
    ok, reason, head_sha, dirty_sha, files = verify(ns.repo_root, ns.name)
    dirty_repr = dirty_sha if dirty_sha else "none"
    if ok:
        print(f"VERIFY OK {ns.name} head={head_sha} dirty={dirty_repr} changed={files}")
        return 0
    print(f"VERIFY FAIL {ns.name} reason={reason}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    default_root = Path(__file__).resolve().parents[2]

    p_salvage = sub.add_parser("salvage", help="archive a worktree's HEAD and dirty state, optionally remove it")
    p_salvage.add_argument("worktree")
    p_salvage.add_argument("--repo-root", type=Path, default=default_root)
    p_salvage.add_argument(
        "--apply", action="store_true", help="actually remove after a passing verify (default is dry-run)"
    )
    p_salvage.set_defaults(func=_cmd_salvage)

    p_restore = sub.add_parser("restore", help="recreate a worktree from an archived name")
    p_restore.add_argument("name")
    p_restore.add_argument("new_path")
    p_restore.add_argument("--repo-root", type=Path, default=default_root)
    p_restore.add_argument("--apply", action="store_true", help="actually create the worktree (default is dry-run)")
    p_restore.add_argument(
        "--force", action="store_true", help="restore even if verify fails (still reports the failure)"
    )
    p_restore.set_defaults(func=_cmd_restore)

    p_verify = sub.add_parser("verify", help="check an archived name's refs are intact")
    p_verify.add_argument("name")
    p_verify.add_argument("--repo-root", type=Path, default=default_root)
    p_verify.set_defaults(func=_cmd_verify)

    ns = ap.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
