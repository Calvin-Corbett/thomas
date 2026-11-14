"""Audit real-data opens in Python children launched by a pytest run.

Loaded by a temporary sitecustomize.py for child interpreters only. The log is
append-only and lives in the run's isolated test folder, never in real data.
"""

import json
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import unquote

SNAPSHOTTING: ContextVar[bool] = ContextVar("snapshotting_real_data", default=False)


def filesystem_path_text(text: str) -> str | None:
    """Unwrap Windows filesystem paths; reject the device namespace only."""
    if os.name != "nt":
        return text
    if text.startswith("\\\\.\\"):
        return None
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:] if len(text) > 5 and text[5] == ":" else None
    return text


def remember_access(by: dict[str, str], path: str, how: str) -> None:
    """Keep in *by* the first event and test that touched *path*, so a failing run names the test, not only the folder.

    On 2026-10-28 d79480's checks failed in the cage on "...\\Thomas\\green was opened by this test run", and the same
    files passed everywhere else, so the folder alone could not say which test to look at.
    """
    if path not in by:
        test = str(os.environ.get("PYTEST_CURRENT_TEST") or "outside any test").split(" (", 1)[0]
        by[path] = f"{how}{_where()}, {test}"


def _where() -> str:
    """Where the touch came from: the innermost frame outside the audit, then the innermost one in the checkout when
    that is a different frame, and the thread when it is not the main one. The test named is only the one running at
    that moment, and a background thread an earlier test left running touches real data under whichever test runs next
    (2026-10-29: tests/test_evolve_supervisor.py was named for os.listdir of ...\\Thomas, and nothing it calls reads
    that folder). The next hold named only "<frozen importlib._bootstrap>:488": the code that listed the folder was
    outside the checkout (the standard library or an installed package, run by an import), so it was skipped, and
    the import machinery's own frame, which is no file, resolved to a path inside the checkout."""
    import threading
    import traceback

    checkout = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + os.sep
    first = mine = ""
    for frame in traceback.StackSummary.extract(traceback.walk_stack(None), lookup_lines=False):
        if frame.filename.startswith("<"):
            continue
        name = os.path.abspath(frame.filename)
        if name.endswith(("conftest.py", "real_data_child_audit.py")):
            continue
        inside = os.path.normcase(name).startswith(checkout)
        shown = name[len(checkout) :] if inside else os.sep.join(name.split(os.sep)[-3:])
        spot = f"{shown.replace(os.sep, '/')}:{frame.lineno} {frame.name}"
        first = first or spot
        if inside:
            mine = spot
            break
    where = (f" at {first}" if first else "") + (f" via {mine}" if mine and mine != first else "")
    thread = threading.current_thread().name
    return where + ("" if thread == "MainThread" else f" in thread {thread}")


class Remembering(set):
    """A set of real-data paths that keeps, in *by*, the first test that added each one, as *how*."""

    def __init__(self, by: dict[str, str], how: str) -> None:
        super().__init__()
        self.by, self.how = by, how

    def add(self, path: str) -> None:
        remember_access(self.by, str(path), self.how)
        super().add(path)


def read_child_log(log: Path, by: dict[str, str]) -> set[str]:
    """The paths Python children recorded in *log*; each child's [path, how] is kept in *by* (bare paths still count)."""
    if not log.is_file():
        return set()
    found: set[str] = set()
    for line in log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        path, how = (record, "a Python child") if isinstance(record, str) else (str(record[0]), str(record[1]))
        found.add(path)
        by.setdefault(path, how)
    return found


def names_above(event: str, path: Path, checkout: Path) -> bool:
    """A listing of a folder above *checkout*: when the checkout lives inside the real data folder (the cage keeps its
    check copies in LOCALAPPDATA/Thomas/green/work), importing ``coverage`` lists each folder on the way to it to learn
    its letter case. That reads only the names on the way to the checkout; every other touch still counts."""
    return event in ("os.listdir", "os.scandir") and path in checkout.parents


def own_git_folder(checkout: Path) -> Path | None:
    """Where *checkout* keeps its git folder when that is not inside it; None when it is inside, or cannot be read.

    The cage's check copies keep theirs beside the files, in LOCALAPPDATA/Thomas/green/git/<name>, and the copy's
    ``.git`` is a one-line file that says so. That folder is the copy's own, as its files are."""
    dot = Path(checkout) / ".git"
    try:
        if dot.is_dir():
            return None
        text = dot.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not text.startswith("gitdir:"):
        return None
    target = Path(text.split(":", 1)[1].strip())
    try:
        return (target if target.is_absolute() else Path(checkout) / target).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def part_of_checkout(path: Path, checkout: Path, git_folder: Path | None) -> bool:
    """*path* is the checkout, a file in it, or in the git folder it keeps elsewhere (:func:`own_git_folder`)."""
    if path == checkout or checkout in path.parents:
        return True
    return git_folder is not None and (path == git_folder or git_folder in path.parents)


def install(checkout: str) -> None:
    """Record accesses, including read-only opens, before child application code runs."""
    log = os.environ.get("THOMAS_TEST_REAL_DATA_AUDIT_LOG")
    roots_text = os.environ.get("THOMAS_TEST_REAL_DATA_AUDIT_ROOTS")
    if not log or not roots_text:
        return
    try:
        roots = tuple(Path(root).resolve() for root in json.loads(roots_text))
        source = Path(checkout).resolve()
    except (ValueError, TypeError, OSError):
        return
    git_folder = own_git_folder(source)
    events = {
        "open",
        "os.listdir",
        "os.scandir",
        "os.chdir",
        "os.mkdir",
        "os.rmdir",
        "os.remove",
        "os.rename",
        "os.truncate",
        "os.utime",
        "sqlite3.connect",
    }

    def audit(event: str, args: tuple) -> None:
        if event not in events or not args or (event in ("os.listdir", "os.scandir") and SNAPSHOTTING.get()):
            return
        for raw in args[:2] if event == "os.rename" else args[:1]:
            if not isinstance(raw, (str, bytes, os.PathLike)):
                continue
            try:
                text = os.fsdecode(raw)
                if event == "sqlite3.connect" and text.startswith("file:"):
                    text = unquote(text[5:].split("?", 1)[0])
                text = filesystem_path_text(text)
                if text is None:
                    continue
                path = Path(text).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if (
                part_of_checkout(path, source, git_folder)
                or names_above(event, path, source)
                or not any(path == root or root in path.parents for root in roots)
            ):
                continue
            # O_APPEND keeps independent children from overwriting each other's
            # records; a single os.write emits one complete, newline-delimited record.
            descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                test = str(os.environ.get("PYTEST_CURRENT_TEST") or "a test").split(" (", 1)[0]
                record = [str(path), f"{event} in a Python child, {test}{_where()}"]
                os.write(descriptor, (json.dumps(record) + "\n").encode("utf-8"))
            finally:
                os.close(descriptor)

    sys.addaudithook(audit)

    # A Python child inherits our PYTHONPATH. Without this exception, a child
    # launched into its own Windows console inherits sitecustomize even though
    # the pytest parent deliberately skips injection for new consoles. Keep the
    # hook in this process while leaving the new console's startup untouched.
    if os.name == "nt":
        import subprocess

        original_popen = subprocess.Popen
        boot = os.environ.get("THOMAS_TEST_REAL_DATA_AUDIT_BOOT")

        class AuditedPopen(original_popen):
            def __init__(self, *args, **kwargs):
                if boot and kwargs.get("creationflags", 0) & subprocess.CREATE_NEW_CONSOLE:
                    env = dict(kwargs.get("env") or os.environ)
                    env["PYTHONPATH"] = os.pathsep.join(
                        entry for entry in env.get("PYTHONPATH", "").split(os.pathsep) if entry != boot
                    )
                    kwargs["env"] = env
                super().__init__(*args, **kwargs)

        subprocess.Popen = AuditedPopen


def test_filesystem_path_text_keeps_normal_paths() -> None:
    """The startup helper is independently collectible by the Build verifier."""
    path = str(Path(__file__).resolve())
    assert filesystem_path_text(path) == path
