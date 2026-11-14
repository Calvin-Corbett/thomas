"""What a Build run's files look like right now: its project's working tree against HEAD, plus its new files.

The Build screen shows the lines an agent is writing while it writes them. The transcript only says which file a
tool touched; the lines themselves are on disk, so this reads them from git, the same ground truth the CHANGED FILES
list uses, and is cheap enough to poll every few seconds: one ``git status``, one ``git ls-tree`` and one ``git diff``
for at most 30 files, newest first. A file over 256 KB, on disk or at HEAD, is listed without its lines and never
diffed, so the work per poll is bounded, not only the answer; each diff keeps its last 64 KB, where the writing is;
a new file is read directly. It runs off the event loop.

Thomas's own bookkeeping in the project (``.thomas/evolve/agent/``, ``.thomas/scratch/``) is left out, as it is from
every list of a run's changes, and so is anything git lists through a junction or a linked folder that leads out of
the project: nothing outside the project root is ever read.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.event_loop_offload import off_loop
from thomas.forge.anvil import forge_code_git, forge_code_projects

from .evolve_agent_run_state import APP_EVOLVE_AGENT_SESSION, runs, slot_active, slot_for_run_id

MAX_FILES = 30
MAX_DIFF_CHARS = 64 * 1024
# A file larger than this, on disk or at HEAD, is listed as too large: its diff would cost a full read every poll.
MAX_FILE_BYTES = 256 * 1024
MAX_UNTRACKED_BYTES = MAX_FILE_BYTES  # the name the new-file limit had first
# git's well-known empty tree: what a repository with no commit yet is compared against.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# The diff's shape, pinned against the settings that change it: the a/ b/ prefixes the parser reads (diff.noprefix
# and diff.mnemonicPrefix would drop or rename them), no external diff or textconv filter (the lines are the file's
# own), top-level paths, no colour, no renames.
_DIFF_ARGS = (
    *("-c", "core.quotepath=false", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false"),
    *("-c", "diff.relative=false", "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames"),
    *("--src-prefix=a/", "--dst-prefix=b/"),
)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_TOO_LARGE = {"added": 0, "removed": 0, "diff": "", "too_large": True}


def _lines(text: str) -> list[str]:
    """``text`` split on newlines only, each line keeping its own: str.splitlines would also split on a form feed or
    a Unicode line separator inside a line, and a diff line has exactly one newline."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _cap(diff: str) -> tuple[str, bool]:
    """At most MAX_DIFF_CHARS of one file's diff, keeping its END: the screen shows the last hunk, where the agent
    is writing, so the head of a long diff is what goes.

    The file header stays. Whole hunks are kept from the last one back while they fit; a last hunk longer than the
    room left keeps its final lines under a header renumbered to where they start, so line numbers stay true."""
    if len(diff) <= MAX_DIFF_CHARS:
        return diff, False
    lines = _lines(diff)
    first = next((i for i, line in enumerate(lines) if line.startswith("@@")), len(lines))
    head = "".join(lines[:first])
    room = MAX_DIFF_CHARS - len(head)
    if first == len(lines) or room <= 0:  # no hunk at all, or a header alone over the cap: its start is all there is
        cut = diff.rfind("\n", 0, MAX_DIFF_CHARS)
        return diff[: cut + 1 if cut > 0 else MAX_DIFF_CHARS], True
    hunks: list[list[str]] = []
    for line in lines[first:]:
        if line.startswith("@@"):
            hunks.append([line])
        else:
            hunks[-1].append(line)
    kept: list[str] = []
    for hunk in reversed(hunks):
        text = "".join(hunk)
        if len(text) <= room:
            kept.append(text)
            room -= len(text)
            continue
        if not kept:
            kept.append(_hunk_tail(hunk, room))
        break
    return head + "".join(reversed(kept)), True


def _hunk_tail(hunk: list[str], room: int) -> str:
    """The last lines of one hunk that fit in ``room``, under its header renumbered to the first line kept."""
    match = _HUNK.match(hunk[0])
    body = hunk[1:]
    budget = max(1, room - 64)  # the renumbered header's own length
    start, used = len(body), 0
    while start > 0 and used + len(body[start - 1]) <= budget:
        start -= 1
        used += len(body[start])
    if start == len(body) and body:  # one line longer than the room: its beginning
        start = len(body) - 1
        body = body[:start] + [body[start][: budget - 1].rstrip("\n") + "\n"]
    if match is None:
        return "".join(body[start:])
    old_start, new_start = int(match.group(1)), int(match.group(3))
    old_len = int(match.group(2)) if match.group(2) is not None else 1
    new_len = int(match.group(4)) if match.group(4) is not None else 1
    old_skip = sum(1 for line in body[:start] if line[:1] in " -")
    new_skip = sum(1 for line in body[:start] if line[:1] in " +")
    old = f"-{old_start + old_skip},{max(0, old_len - old_skip)}"
    new = f"+{new_start + new_skip},{max(0, new_len - new_skip)}"
    return f"@@ {old} {new} @@\n" + "".join(body[start:])


def _counts(chunk: str) -> tuple[int, int]:
    added = removed = 0
    in_hunk = False
    for line in chunk.splitlines():
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added += 1
        elif in_hunk and line.startswith("-"):
            removed += 1
    return added, removed


def _chunk_path(chunk: str) -> str:
    old = ""
    for line in chunk.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            side = line[4:].strip().strip('"')
            if side.startswith(("a/", "b/")):
                if line.startswith("+++ "):
                    return side[2:]
                old = side[2:]
        elif line.startswith("@@"):
            break
    if old:
        return old
    header = chunk.splitlines()[0] if chunk else ""
    return header.split(" b/", 1)[1].strip('"') if " b/" in header else ""


def _git_failed(what: str, rc: int, out: str, err: str) -> forge_code_git.ForgeCodeGitError:
    return forge_code_git.ForgeCodeGitError(f"{what}: {(err or out).strip() or f'git exited {rc}'}")


def _head_exists(root: Path) -> bool:
    """Whether HEAD names a commit. ``False`` only when git says plainly it does not (a repository with no commit
    yet); a timeout, a busy git or any other failure is raised, never read as an empty history."""
    rc, out, err = forge_code_git._run_git(root, ["rev-parse", "--verify", "--quiet", "HEAD"])
    if rc == 0:
        return True
    if rc == 1 and not out.strip():  # --verify --quiet: exit 1, nothing printed, for a name that names nothing
        return False
    raise _git_failed("git could not read HEAD", rc, out, err)


def _head_sizes(root: Path, specs: list[str]) -> dict[str, int] | None:
    """Each named file's size at HEAD, or ``None`` when the repository has no commit yet."""
    rc, out, err = forge_code_git._run_git(root, ["ls-tree", "-l", "-z", "--full-name", "HEAD", "--", *specs])
    if rc != 0:
        if not _head_exists(root):
            return None
        raise _git_failed("git could not list HEAD", rc, out, err)
    sizes: dict[str, int] = {}
    for record in out.split("\0"):
        meta, _tab, path = record.partition("\t")
        fields = meta.split()
        if path and len(fields) == 4 and fields[3].isdigit():
            sizes[path] = int(fields[3])
    return sizes


def _disk_size(root: Path, rel: str) -> int:
    try:
        return os.lstat(root / rel).st_size  # a link is its own few bytes: git diffs its target text, never through it
    except OSError:
        return 0  # deleted: what is left to diff is its HEAD copy


def _tracked_diffs(root: Path, paths: list[str]) -> dict[str, dict[str, Any]]:
    """One ``git diff`` against HEAD for every tracked file named, split back into one entry per file.

    A file over MAX_FILE_BYTES on disk or at HEAD is left out of the diff and listed as too large: git's output
    for it would be read whole, every poll, to send back its last 64 KB. Without a commit yet the files are
    compared with the empty tree; any other failure is an error, never a whole-file rewrite that did not happen."""
    spec = ":(top,literal){}".format
    head = _head_sizes(root, [spec(path) for path in paths])
    entries: dict[str, dict[str, Any]] = {}
    small: list[str] = []
    for path in paths:
        if max(_disk_size(root, path), (head or {}).get(path, 0)) > MAX_FILE_BYTES:
            entries[path] = dict(_TOO_LARGE)
        else:
            small.append(path)
    if not small:
        return entries
    base = "HEAD" if head is not None else _EMPTY_TREE
    rc, out, err = forge_code_git._run_git(root, [*_DIFF_ARGS, base, "--", *(spec(path) for path in small)])
    if rc != 0:
        raise _git_failed("git diff could not read the changes", rc, out, err)
    chunks = [part for part in ("\n" + out).split("\ndiff --git ")[1:] if part.strip()]
    for part in chunks:
        chunk = "diff --git " + part.rstrip("\n") + "\n"
        path = _chunk_path(chunk)
        if not path:
            continue
        added, removed = _counts(chunk)
        diff, truncated = _cap(chunk)
        entries[path] = {"added": added, "removed": removed, "diff": diff, **({"truncated": True} if truncated else {})}
    return entries


def _new_file(root: Path, rel: str) -> dict[str, Any]:
    """A file git does not track yet, shown as wholly added, read straight from disk -- never through a link."""
    path = root / rel
    try:
        if path.is_symlink():  # a linked folder above it is ruled out by live_diff's check; this is a file link
            return {"added": 0, "removed": 0, "diff": "", "link": True}
        if path.lstat().st_size > MAX_FILE_BYTES:
            return dict(_TOO_LARGE)
        data = path.read_bytes()
    except OSError:
        return {"added": 0, "removed": 0, "diff": ""}
    if b"\0" in data[:8192]:
        return {"added": 0, "removed": 0, "diff": f"Binary file {rel} added\n", "binary": True}
    lines = data.decode("utf-8", errors="replace").splitlines()
    head = f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
    body = (f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)) if lines else ""
    diff, truncated = _cap(head + body)
    return {"added": len(lines), "removed": 0, "diff": diff, **({"truncated": True} if truncated else {})}


def _is_repository(root: Path) -> bool | None:
    """``False`` when git says ``root`` is no work tree (or is gone), ``True`` when it is one, ``None`` when git gave
    no answer (a timeout, every git slot busy)."""
    rc, out, _err = forge_code_git._run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if rc == 0:
        return out.strip() == "true"
    return False if rc == 128 else None  # 128: git's own fatal "not a git repository" / "cannot change to"


def _inside_check(root: Path) -> Callable[[str], bool]:
    """A test that a path git listed really lies in the project: git lists the files under an untracked junction
    or linked folder as the project's own, and reading them would read wherever it leads. One resolve per folder."""
    try:
        real_root = root.resolve()
    except OSError:
        return lambda _rel: False
    folders: dict[str, bool] = {"": True}

    def inside(rel: str) -> bool:
        folder = rel.rpartition("/")[0]
        if folder not in folders:
            try:
                real = (real_root / folder).resolve()
                folders[folder] = real == real_root or real.is_relative_to(real_root)
            except OSError:
                folders[folder] = False
        return folders[folder]

    return inside


def live_diff(project_root: str | Path) -> dict[str, Any]:
    """``{"history": bool, "files": [{file, added, removed, untracked, diff, mtime, ...}]}``, newest change first."""
    root = Path(project_root)
    try:
        entries = forge_code_git._status_entries(root)
    except forge_code_git.ForgeCodeGitError as exc:
        # A folder worked on without history has no HEAD to compare with; the screen simply shows no live lines.
        # Any other failure (a timeout, git busy) is raised: an empty answer would reset the screen's baseline.
        if _is_repository(root) is False:
            return {"history": False, "files": [], "error": str(exc)}
        raise
    inside = _inside_check(root)
    rows: list[tuple[int, str, str]] = []
    for status, path in entries:
        rel = path.replace("\\", "/")
        if rel.lower().startswith(forge_code_git._RUNTIME_BOOKKEEPING_PREFIXES) or not inside(rel):
            continue
        try:
            mtime = int((root / rel).lstat().st_mtime * 1000)
        except OSError:
            mtime = 0  # deleted: no time of its own, so it sorts last
        rows.append((mtime, status, rel))
    rows.sort(key=lambda row: row[0], reverse=True)
    rows = rows[:MAX_FILES]
    tracked = [rel for _mtime, status, rel in rows if status != "??"]
    diffs = _tracked_diffs(root, tracked) if tracked else {}
    files = []
    for mtime, status, rel in rows:
        entry = _new_file(root, rel) if status == "??" else diffs.get(rel, {"added": 0, "removed": 0, "diff": ""})
        files.append({"file": rel, "untracked": status == "??", "mtime": mtime, **entry})
    return {"history": True, "files": files}


def _session_root(session: dict[str, Any]) -> Path | None:
    """Where the run edits: its project, or the private candidate of an Edit Thomas run."""
    self_edit = getattr(session.get("proc"), "thomas_self_edit", None)
    if isinstance(self_edit, dict) and self_edit.get("candidate_root"):
        return Path(str(self_edit["candidate_root"]))
    root = str(session.get("project_root") or "")
    return Path(root) if root else None


def build_live_diff_handlers(
    app: web.Application,
    require_api_access: Callable[[web.Request], None],
    catalog_root: Callable[[], Path],
    find_conversation: Callable[[Path, str], tuple[Path, dict[str, Any] | None]],
) -> dict[str, Any]:
    async def live_diff_handler(request: web.Request) -> web.Response:
        require_api_access(request)
        run_id = str(request.query.get("run_id") or "").strip()
        cid = str(request.query.get("conversation_id") or "").strip()
        root: Path | None = None
        if run_id:
            slot = slot_for_run_id(app, run_id)
            legacy = app.get(APP_EVOLVE_AGENT_SESSION)
            if slot is not None:
                root = _session_root(slot.get("session") or {})
            elif isinstance(legacy, dict) and str(legacy.get("run_id") or "") == run_id:
                root = _session_root(legacy)
            if root is None:
                return web.json_response({"ok": False, "code": "run_not_found", "run_id": run_id}, status=404)
        elif cid:
            slot = runs(app).get(cid)
            if slot is not None and slot_active(slot):
                root = _session_root(slot.get("session") or {})
            if root is None:
                try:
                    root, conv = await off_loop(
                        "code_live_diff.conversation", find_conversation, Path(catalog_root()), cid
                    )
                except forge_code_projects.ForgeCodeProjectError as exc:
                    return web.json_response(
                        {"ok": False, "error": str(exc), "code": "project_unavailable"}, status=409
                    )
                if conv is None:
                    return web.json_response({"ok": False, "error": "not found"}, status=404)
        else:
            return web.json_response(
                {"ok": False, "error": "run_id or conversation_id is required", "code": "run_id_required"},
                status=400,
            )
        try:
            result = await off_loop("code_live_diff.read", live_diff, root)
        except forge_code_git.ForgeCodeGitError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": "git_status_unavailable"}, status=503)
        return web.json_response(
            {"ok": True, "project_root": str(root), **({"run_id": run_id} if run_id else {}), **result}
        )

    return {"live_diff": live_diff_handler}


__all__ = [
    "MAX_DIFF_CHARS",
    "MAX_FILE_BYTES",
    "MAX_FILES",
    "MAX_UNTRACKED_BYTES",
    "build_live_diff_handlers",
    "live_diff",
]
