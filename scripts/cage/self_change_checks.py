"""What the promoter checks before it asks you anything, and how it moves ``dev``.

Everything here reads a self-fix as data. Nothing in it executes submitted code:
the new tree is built in a temporary git index and never checked out, and
changed Python is compiled, never imported. The promoter runs as you, so code
from a self-fix that ran here would run under your account before you had
approved anything -- exactly what the cage exists to stop.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

SUBMISSION_KIND = "self_change"
# The promoter runs as you under pythonw.exe, which has no console, so any console
# program it starts without this gets a window of its own on your screen. The first
# live promotion (2026-09-23) flashed dozens of them.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MANIFEST_PATH = "scripts/forge/gates/enforcement_manifest.json"
_SID_RE = re.compile(r"^self-[A-Za-z0-9_-]{1,80}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEADER_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)$")
# Parts of Thomas a self-fix may never change: his memory and state, and git itself.
_NEVER = ("runtime/", ".git/")
_NO_HOOKS = str(Path(tempfile.gettempdir()) / "thomas-promoter-no-hooks")
# A path that may land: printable ASCII with no space, quote or backslash (git prints those quoted), at most 200 long,
# and no "~": C: gives folders 8.3 short names (thomas/server/TOOL_M~1 is thomas/server/tool_manifests), so a "~" path
# can write into a guarded folder under a name its guarded card never matches. No tracked path has one.
_PLAIN_PATH = re.compile(r"[!#-\[\]-}]{1,200}")
# What a landed file may be: absent, or a plain or executable file. Never a symlink (120000) or submodule (160000).
_FILE_MODES = frozenset({"000000", "100644", "100755"})
# Its wording changes only through your own commit and a re-pin (scripts/cage/pin_catalogue.ps1).
_CARDS = "scripts/cage/card_catalogue.py"
# Files that change how git reads every other file: one landed with "*.py -diff" showed each later Python change as
# "binary" on its card, with no added line for the guarded-file check to read. They change only through your own commit.
_GIT_RULES = frozenset({".gitattributes", ".gitmodules"})
# The empty tree, as the attribute source of every diff a card is made from: no .gitattributes anywhere -- the running
# copy's included, where the caged account can write one under tests/, docs/, plans/ and changelog.d/ -- decides how a
# change is shown. Git then calls a file binary from its own bytes.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_CARD_DIFF = (f"--attr-source={_EMPTY_TREE}", "diff", "--no-textconv", "--no-ext-diff", "--no-color")
# git reads each --exclude as a wildmatch pattern: "thomas/[f]ix.py" left out thomas/fix.py and kept itself.
_WILDMATCH = re.compile(r"([\\\[\]*?])")


class Refused(Exception):  # noqa: N818 - reads as the verdict it is
    """The self-fix cannot be promoted, for the reason given."""


class Moved(Exception):  # noqa: N818
    """``dev`` moved between re-deriving the change and landing it."""


def run_git(
    repo: Path, *args: str, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    clean.update(env or {})
    # Bytes in: text mode on Windows turns every "\n" written to stdin into "\r\n",
    # so each commit message this made (e3921806) reached git with CRs.
    proc = subprocess.run(
        ["git", "-c", f"core.hooksPath={_NO_HOOKS}", "-c", "core.fsmonitor=false", *args],
        cwd=str(repo),
        env=clean,
        input=None if stdin is None else stdin.encode("utf-8"),
        capture_output=True,
        check=False,
        creationflags=NO_WINDOW,
    )
    out, err = (raw.decode("utf-8", "replace").replace("\r\n", "\n") for raw in (proc.stdout, proc.stderr))
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


# Windows starts a program with a command line of at most 32,767 characters. The junk sweep's 3,283 paths on one
# `git diff` line (2026-09-27) failed with WinError 206 after you had approved it, and nothing landed.
_PATHS_PER_LINE = 8000


def run_git_paths(repo: Path, *args: str, paths: list[str]) -> subprocess.CompletedProcess[str]:
    """``run_git(repo, *args, "--", *paths)``, in as many runs as the command-line limit needs, outputs joined.

    Stops at the first run that fails and returns its exit code. No paths runs nothing: a bare ``--`` would ask git
    about every file in the repo.
    """
    out: list[str] = []
    err: list[str] = []
    batch: list[str] = []
    size = 0
    for path in [*paths, None]:
        if batch and (path is None or size + len(path) > _PATHS_PER_LINE):
            done = run_git(repo, *args, "--", *batch)
            out.append(done.stdout)
            err.append(done.stderr)
            if done.returncode:
                return subprocess.CompletedProcess(done.args, done.returncode, "".join(out), "".join(err))
            batch, size = [], 0
        if path is not None:
            batch.append(path)
            size += len(path) + 3  # the space and quotes around it
    return subprocess.CompletedProcess(["git", *args], 0, "".join(out), "".join(err))


def read_submission(sub_dir: Path) -> tuple[dict[str, str], bytes]:
    """The manifest, and the exact patch bytes it hashed. Everything after this uses those bytes, never the file
    again: the hand-in folder stays writable by the caged account (scripts/cage/prepare_caged_server.ps1)."""
    try:
        manifest = json.loads((sub_dir / "submission.json").read_text(encoding="utf-8"))
        patch = (sub_dir / "change.patch").read_bytes()
    except (OSError, ValueError, RecursionError) as exc:  # RecursionError: a manifest nested deeper than json reads
        raise Refused(f"the submission could not be read: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != SUBMISSION_KIND:
        raise Refused("not a self-fix submission")
    if manifest.get("id") != sub_dir.name or not _SID_RE.match(sub_dir.name):
        raise Refused("the submission's id does not match its folder")
    if not _SHA_RE.match(str(manifest.get("base") or "")):
        raise Refused("the submission has no valid base commit")
    if hashlib.sha256(patch).hexdigest() != manifest.get("patch_sha256"):
        raise Refused("the patch does not match the hash recorded when it was submitted")
    return {k: str(v) for k, v in manifest.items() if not isinstance(v, (list, dict))}, patch


def load_submission(sub_dir: Path) -> dict[str, str]:
    return read_submission(sub_dir)[0]


def _bad_path(path: str) -> str | None:
    parts = path.split("/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path) or "\\" in path or ".." in parts or "" in parts:
        return f"an unsafe path ({path})"
    lowered = path.lower()
    if any(lowered.startswith(p) for p in _NEVER) or ".git" in [p.lower() for p in parts]:
        return f"a path a self-fix may not change ({path})"
    return None


def write_safety_refusal(patch: str, blue: Path) -> str | None:
    """Why this patch may not be applied at all, or None."""
    headers = 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            headers += 1
            match = _HEADER_RE.match(line)
            if not match or match.group(1) != match.group(2):
                return f"a file header the promoter cannot read safely ({line[:120]})"
            bad = _bad_path(match.group(1))
            if bad:
                return f"the patch touches {bad}"
            reparse = _reparse_on_the_way(blue, match.group(1))
            if reparse:
                return f"a folder on the way to {match.group(1)} is a link ({reparse})"
        elif re.match(r"^(new|deleted) file mode 1[26]0000", line) or re.match(r"^index \S+ 1[26]0000$", line):
            return "the patch adds or changes a symlink or submodule"
        elif line.startswith(("old mode ", "new mode ")):
            return "the patch changes a file mode"
        elif line.startswith(("rename from ", "copy from ", "similarity index ")):
            return "the patch renames or copies a file"
    return None if headers else "the patch changes nothing"


def _reparse_on_the_way(blue: Path, rel: str) -> str | None:
    here = blue
    for part in rel.split("/")[:-1]:
        here = here / part
        if here.is_symlink() or os.path.isjunction(here):
            return str(here)
    return None


def derive_tree(repo: Path, parent: str, patch: Path | bytes, exclude: list[str] | tuple[str, ...] = ()) -> str:
    """The tree *parent* becomes with the patch applied, built without a checkout.

    *patch* is the promoter's own copy (bytes, written into a folder only you can write) or a patch file."""
    with tempfile.TemporaryDirectory() as tmp:
        patch_path = patch_file(patch, tmp)
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        read = run_git(repo, "read-tree", parent, env=env)
        if read.returncode:
            raise Refused(f"could not read {parent[:12]}: {read.stderr.strip()[:200]}")
        skip = exclude_args(exclude)
        apply = apply_apart(repo, tmp)
        applied = run_git(repo, *apply, "--cached", "--whitespace=nowarn", *skip, str(patch_path), env=env)
        if applied.returncode:
            three_way = (*apply, "--cached", "--3way", "--whitespace=nowarn", *skip, str(patch_path))
            applied = run_git(repo, *three_way, env=env)
        written = run_git(repo, "write-tree", env=env) if applied.returncode == 0 else applied
        if written.returncode:
            raise Refused(f"the change no longer applies to dev: {written.stderr.strip()[:300]}")
        return written.stdout.strip()


def apply_apart(repo: Path, tmp: str) -> tuple[str, ...]:
    """``git apply`` in an empty work tree of its own inside *tmp*, never the running copy's.

    With --3way, for a file the patch adds that the index already has, git reads the work tree whatever --cached
    says, and checks the index's version out wherever the file is missing (apply.c load_current). Run in the running
    copy, checking one change on top of the one ahead of it on a shared card wrote that one's file into the running
    Thomas before you had approved anything (2026-10-09)."""
    work = Path(tmp) / "work"
    work.mkdir(exist_ok=True)
    found = run_git(repo, "rev-parse", "--absolute-git-dir")
    git_dir = found.stdout.strip()
    if found.returncode or not git_dir:
        raise Refused(f"could not find the git folder of the running copy: {found.stderr.strip()[:200]}")
    return ("-C", str(work), f"--git-dir={git_dir}", f"--work-tree={work}", "apply")


def exclude_args(paths: list[str] | tuple[str, ...]) -> list[str]:
    """``git apply --exclude`` for exactly each of *paths*: every wildmatch character escaped, so a file you left out
    is the only file left out."""
    return ["--exclude=" + _WILDMATCH.sub(r"\\\1", path) for path in paths]


def patch_file(patch: Path | bytes, tmp: str) -> Path:
    """*patch* as a file git can apply: the bytes written into *tmp* (a folder of the promoter's own), or the file."""
    if not isinstance(patch, bytes):
        return Path(patch).resolve()  # whole: git apply runs from a work tree of its own (apply_apart)
    path = Path(tmp) / "change.patch"
    path.write_bytes(patch)
    return path


def tree_safety_refusal(repo: Path, parent: str, tree: str, blue: Path) -> str | None:
    """write_safety_refusal's rules on the tree that would land, not on the patch text: what git applied is what is
    judged, whatever the patch said. Line counts cannot show a mode (`git diff --numstat` prints a symlink as 1 0)."""
    listed = run_git(repo, "diff-tree", "-r", "--no-renames", "--raw", "-z", parent, tree)
    fields = listed.stdout.split("\0")
    if listed.returncode or fields[-1] != "" or len(fields) % 2 != 1:
        return f"the tree that would land could not be read plainly ({listed.stderr.strip()[:120]})"
    for meta, path in zip(fields[0:-1:2], fields[1::2]):  # ":old new oldsha newsha S", then the path
        modes = meta[1:].split()[:2] if meta.startswith(":") else []
        if len(modes) != 2:
            return "the tree that would land could not be read plainly"
        if not _PLAIN_PATH.fullmatch(path):
            shown = path.encode("ascii", "backslashreplace").decode("ascii")[:80]
            return (
                "the change has a path that is not plain printable ASCII (no space, quote, backslash or ~) of at most "
                f"200 characters ({shown})"
            )
        bad = _bad_path(path)
        if bad:
            return f"the change touches {bad}"
        old, new = modes
        if old not in _FILE_MODES or new not in _FILE_MODES:
            return f"the change adds, changes or removes a symlink or submodule ({path})"
        if "000000" not in modes and old != new:
            return f"the change changes a file mode ({path})"
        if path.lower() == _CARDS:  # lowered: on Windows another spelling is the same file
            return (
                f"the change edits the approval cards ({_CARDS}); their wording changes only through your own "
                "commit and a re-pin"
            )
        if path.rsplit("/", 1)[-1].lower() in _GIT_RULES:
            return (
                f"the change adds, edits or removes {path}, which changes how git shows every other file; that "
                "changes only through your own commit"
            )
        reparse = _reparse_on_the_way(blue, path)
        if reparse:
            return f"a folder on the way to {path} is a link ({reparse})"
    return None


def tree_changes(repo: Path, parent: str, tree: str) -> list[tuple[str, str]]:
    listed = run_git(repo, "diff-tree", "-r", "--no-renames", "--name-status", "-z", parent, tree)
    fields = [f for f in listed.stdout.split("\0") if f]
    return [(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]


def blob(repo: Path, rev: str, path: str) -> str:
    found = run_git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{path}")
    return found.stdout.strip() if found.returncode == 0 else ""


def text_at(repo: Path, rev: str, path: str) -> str:
    return run_git(repo, "show", f"{rev}:{path}").stdout if blob(repo, rev, path) else ""


def card_diff(repo: Path, parent: str, tree: str, *options: str, path: str = "") -> str:
    """``git diff`` as a card shows it: the blobs' own bytes, whatever any .gitattributes, textconv or external diff
    says. A diff git cannot make is an error, never an empty change: an empty one would read as nothing to guard."""
    shown = run_git(repo, *_CARD_DIFF, *options, parent, tree, *(("--", path) if path else ()))
    if shown.returncode:
        raise ValueError(f"git could not show the change for its card: {shown.stderr.strip()[:200]}")
    return shown.stdout


def file_diff(repo: Path, parent: str, tree: str, path: str) -> str:
    """One file's diff, every added line in it -- even in a file git would call binary -- for the guarded-file check."""
    return card_diff(repo, parent, tree, "--text", path=path)


def _object_ids(repo: Path, specs: list[str]) -> list[str] | None:
    """The object id each "rev:path" in *specs* names ("" where it names nothing), from one git process, or None when
    git does not answer every one plainly -- then the caller asks one at a time, as before.

    One process instead of two per path: the integrity check asked 136 times per card (9.95 s of the promoter's 12.7 s
    before a card, measured 2026-10-08) for the same answers."""
    if not specs:
        return []
    found = run_git(repo, "cat-file", "--batch-check=%(objectname)", stdin="".join(f"{spec}\n" for spec in specs))
    lines = found.stdout.split("\n")
    if found.returncode != 0 or len(lines) < len(specs):
        return None
    ids: list[str] = []
    for spec, line in zip(specs, lines):
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", line):
            ids.append(line)
        elif line == f"{spec} missing":
            ids.append("")
        else:  # ambiguous, or anything git did not answer as an id or "missing"
            return None
    return ids


def integrity_refusal(repo: Path, parent: str, tree: str) -> str | None:
    """Gate files are changed only through your own commit path, never a self-fix."""
    try:
        enforced = list(json.loads(text_at(repo, parent, MANIFEST_PATH) or "{}"))
    except ValueError:
        return "the enforcement manifest on dev cannot be read"
    paths = [MANIFEST_PATH, *enforced]
    ids = _object_ids(repo, [f"{rev}:{path}" for rev in (parent, tree) for path in paths])
    if ids is None:
        touched = [p for p in paths if blob(repo, parent, p) != blob(repo, tree, p)]
    else:
        touched = [p for p, old, new in zip(paths, ids[: len(paths)], ids[len(paths) :]) if old != new]
    if touched:
        return (
            "the change edits enforced gate file(s): "
            + ", ".join(touched[:6])
            + ". Gate changes go through your own commit path, not a self-fix."
        )
    return None


# What parsing a file can raise. RecursionError: `x = 1+1+...` with 5,000 terms is past what the parser nests, and it
# used to escape every check and fail each pass on the same hand-in.
_UNPARSABLE = (SyntaxError, ValueError, RecursionError, MemoryError)


def compile_refusal(repo: Path, tree: str, changes: list[tuple[str, str]]) -> str | None:
    """Every changed Python file must compile. compile() parses; it runs nothing."""
    for status, path in changes:
        if status == "D" or not path.endswith(".py"):
            continue
        shown = subprocess.run(
            ["git", "cat-file", "blob", f"{tree}:{path}"],
            cwd=str(repo),
            capture_output=True,
            check=False,
            creationflags=NO_WINDOW,
        )
        try:
            compile(shown.stdout, path, "exec", dont_inherit=True)
        except _UNPARSABLE as exc:
            return f"{path} does not compile: {exc}"
    return None


def _blob_bytes(repo: Path, rev: str, path: str) -> bytes:
    shown = subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{path}"],
        cwd=str(repo),
        capture_output=True,
        check=False,
        creationflags=NO_WINDOW,
    )
    return shown.stdout if shown.returncode == 0 else b""


def _defined_names(source: bytes) -> set[str]:
    """Names a module defines at top level, read by parsing -- nothing is run."""
    try:
        body = list(ast.parse(source).body)
    except _UNPARSABLE:
        return set()
    names: set[str] = set()
    while body:
        node = body.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.If, ast.Try, ast.With)):  # conditional definitions still define
            for field in ("body", "orelse", "finalbody", "handlers"):
                body.extend(getattr(node, field, []) or [])
        elif isinstance(node, ast.ExceptHandler):
            body.extend(node.body)
    return names


def import_break_refusal(repo: Path, parent: str, tree: str, changes: list[tuple[str, str]]) -> str | None:
    """A change may not remove a name another module in the tree imports by name.

    Measured live 2026-09-22: a worker that could not read the file it had to edit
    wrote a module holding only its new docstring, deleting every name the rest of
    Thomas imported from it. Both versions are parsed; nothing is imported.
    """
    for status, path in changes:
        if status == "A" or not path.endswith(".py"):
            continue
        module = path[:-3].replace("/", ".").removesuffix(".__init__")
        before = _defined_names(_blob_bytes(repo, parent, path))
        after = set() if status == "D" else _defined_names(_blob_bytes(repo, tree, path))
        removed = before - after
        if not removed:
            continue
        found = run_git(repo, "grep", "-l", "-F", f"from {module} import", tree, "--", "*.py")
        for line in found.stdout.splitlines():
            importer = line.split(":", 1)[-1]
            if importer == path:
                continue
            try:
                parsed = ast.parse(_blob_bytes(repo, tree, importer))
            except _UNPARSABLE:
                continue
            for node in ast.walk(parsed):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
                    lost = sorted({alias.name for alias in node.names} & removed)
                    if lost:
                        return f"the change removes {', '.join(lost)} from {path}, which {importer} imports"
    return None


def numstat(repo: Path, parent: str, tree: str) -> dict[str, str]:
    """Each changed path's size as "+added -deleted", or "binary" when its own bytes are (see card_diff)."""
    sizes: dict[str, str] = {}
    for line in card_diff(repo, parent, tree, "--numstat", "--no-renames").splitlines():
        added, deleted, path = (line.split("\t", 2) + ["", "", ""])[:3]
        sizes[path] = "binary" if added == "-" else f"+{added} -{deleted}"
    return sizes


def blue_dirty(repo: Path, parent: str, changes: list[tuple[str, str]]) -> list[str]:
    """Changed paths where the running copy holds work that is not in *parent*."""
    paths = [path for _, path in changes]
    dirty: set[str] = set()
    for extra in ((), ("--cached",)):
        listed = run_git_paths(repo, "diff", *extra, "--name-only", "-z", parent, paths=paths)
        dirty.update(p for p in listed.stdout.split("\0") if p)
    dirty.update(path for status, path in changes if status == "A" and os.path.lexists(repo / path))
    return sorted(dirty)


def running_copy_refusal(
    repo: Path, parent: str, tree: str, changes: list[tuple[str, str]]
) -> tuple[str | None, frozenset[str]]:
    """Why the running copy cannot take *tree* over *parent* now, or None; and the paths that already hold it.

    Run before the card and again right after your answer: the prompt has no timeout, and the caged account can
    change files in the running copy while it is up. The words are the ones the server reads
    (self_change_status.RUNNING_COPY_DIRTY) to hand the change in again once the work is committed."""
    # Work already sitting in the running copy exactly as it would land is the change itself, not work at risk.
    already = already_in_running_copy(repo, parent, tree, changes)
    dirty = [path for path in blue_dirty(repo, parent, changes) if path not in already]
    if dirty:
        return "the running copy has uncommitted work in " + ", ".join(dirty[:6]), already
    for _status, path in changes:
        reparse = _reparse_on_the_way(repo, path)
        if reparse:
            return f"a folder on the way to {path} is a link ({reparse})", already
    return None, already


def already_in_running_copy(repo: Path, parent: str, tree: str, changes: list[tuple[str, str]]) -> frozenset[str]:
    """Changed paths whose running-copy file is already exactly what *tree* lands.

    Same bytes on disk as the tree's blob (or no file, for a path the tree deletes), and an index that holds that
    blob, *parent*'s blob (edited but not staged) or no entry at all -- so nobody staged anything else there.
    Landing such a path overwrites nothing, so it is not anyone's work at risk: it is the work being landed.
    Uncommitted work salvaged from the running copy (refs/salvage/uncommitted-*) lands this way; without it,
    ``blue_dirty`` refuses that work forever, because the work sits in the files it would land.
    """
    paths = [path for _, path in changes]
    if not paths:
        return frozenset()
    wanted = _blobs_at(repo, tree, paths)
    before = _blobs_at(repo, parent, paths)
    indexed: dict[str, str] = {}
    for row in filter(None, run_git_paths(repo, "ls-files", "-s", "-z", paths=paths).stdout.split("\0")):
        meta, _, path = row.partition("\t")
        indexed[path] = meta.split()[1]
    checkout = _checkout_bytes(repo, {path: blob for path, blob in wanted.items() if (repo / path).is_file()})
    same: set[str] = set()
    for path in paths:
        blob_id = wanted.get(path)
        file = repo / path
        if blob_id is None:  # the tree deletes it: nothing may be on disk
            on_disk = not os.path.lexists(file)
        else:  # the exact bytes a checkout would write, line endings included, against the bytes that are there
            expected = checkout.get(path)
            on_disk = expected is not None and file.is_file() and file.read_bytes() == expected
        if on_disk and (path not in indexed or indexed[path] in (blob_id, before.get(path))):
            same.add(path)
    return frozenset(same)


def _checkout_bytes(repo: Path, blobs: dict[str, str]) -> dict[str, bytes]:
    """Read exact checkout bytes in one batch; filtered output cannot be framed by Git's size header."""
    if not blobs:
        return {}
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    marker = os.urandom(32).hex().encode("ascii")
    proc = subprocess.run(
        ["git", "-c", f"core.hooksPath={_NO_HOOKS}", "-c", "core.fsmonitor=false"]
        + ["cat-file", f"--batch={marker.decode('ascii')} %(objectname) %(objecttype)", "--filters"],
        cwd=str(repo),
        env=clean,
        input="".join(f"{blob} {path}\n" for path, blob in blobs.items()).encode("utf-8"),
        capture_output=True,
        check=False,
        creationflags=NO_WINDOW,
    )
    if proc.returncode:
        return {}
    # Git reports the unfiltered object size even when checkout filters change its length.
    # Randomly marked headers delimit the filtered bytes; ambiguous framing fails closed.
    frames = proc.stdout.split(marker + b" ")
    if frames[0] or len(frames) != len(blobs) + 1:
        return {}
    found: dict[str, bytes] = {}
    for (path, blob), frame in zip(blobs.items(), frames[1:], strict=True):
        header, separator, body = frame.partition(b"\n")
        if header != blob.encode("ascii") + b" blob" or not separator or not body.endswith(b"\n"):
            return {}
        found[path] = body[:-1]
    return found


def _blobs_at(repo: Path, rev: str, paths: list[str]) -> dict[str, str]:
    """Each of *paths* that exists in *rev*, with its blob id."""
    found: dict[str, str] = {}
    for row in filter(None, run_git_paths(repo, "ls-tree", "-r", "-z", rev, paths=paths).stdout.split("\0")):
        meta, _, path = row.partition("\t")
        found[path] = meta.split()[2]
    return found


def make_commit(repo: Path, tree: str, parent: str, body: str, trailers: list[tuple[str, str]]) -> str:
    from scripts.crew.brief import commit_integrity

    message = commit_integrity.compose_message(body, trailers)
    author = {"GIT_AUTHOR_NAME": "Thomas-Agent", "GIT_AUTHOR_EMAIL": "352198248+Thomas-Agent@users.noreply.github.com"}
    made = run_git(repo, "commit-tree", tree, "-p", parent, env=author, stdin=message)
    if made.returncode:
        raise Refused(f"the commit could not be made: {made.stderr.strip()[:200]}")
    return made.stdout.strip()


# One landing at a time in this process: the card loop and the window's loop (scripts/cage/window_loop.py) both land.
# The compare-and-swap guards dev, not the running copy's checkout or its put-back after a failure.
_LANDING = threading.Lock()


def land(
    repo: Path,
    branch: str,
    commit: str,
    parent: str,
    changes: list[tuple[str, str]],
    already: frozenset[str] = frozenset(),
) -> str:
    """Move *branch* from *parent* to *commit*, then the running copy's changed files.

    The move is a compare-and-swap: other agents commit with the same plumbing,
    and a ``dev`` that moved means the approval no longer covers what would land.
    *already* is :func:`already_in_running_copy`: files that held this change before it landed. Putting things
    back after a failed update never touches them, since the old version there would erase that work.
    """
    with _LANDING:
        return _land(repo, branch, commit, parent, changes, already)


def _land(
    repo: Path, branch: str, commit: str, parent: str, changes: list[tuple[str, str]], already: frozenset[str]
) -> str:
    ref = f"refs/heads/{branch}"
    if run_git(repo, "update-ref", ref, commit, parent).returncode:
        raise Moved(branch)
    head = run_git(repo, "symbolic-ref", "-q", "HEAD").stdout.strip()
    if head != ref:
        return f"the running copy is on {head or 'a detached commit'}, so only {branch} moved"
    keep = [p for s, p in changes if s != "D"]
    gone = [p for s, p in changes if s == "D"]
    error = ""
    for _attempt in range(3):
        out = run_git_paths(repo, "checkout", commit, paths=keep)
        # -f: dev already moved, so HEAD no longer has these files and plain `git rm` calls each index entry a
        # staged change and refuses. blue_dirty found no work of anyone's in them before this ran.
        rm = run_git_paths(repo, "rm", "-f", "-q", "--ignore-unmatch", paths=gone)
        failed = [r for r in (out, rm) if r.returncode]
        if not failed:
            return ""
        error = failed[0].stderr.strip()[:200]
        time.sleep(1.0)
    # Put everything back: a dev that moved under a running copy that did not
    # would show the change reversed, ready for the next agent to commit.
    run_git(repo, "update-ref", ref, parent, commit)
    before = _blobs_at(repo, parent, [p for _, p in changes if p not in already])
    existed = [p for _, p in changes if p in before]
    added = [p for s, p in changes if s == "A" and p not in already]
    run_git_paths(repo, "checkout", parent, paths=existed)
    run_git_paths(repo, "rm", "-f", "-q", "--ignore-unmatch", paths=added)  # staged by the checkout above: -f
    raise Refused(f"the running copy could not be updated ({error}); {branch} was put back")
