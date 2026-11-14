import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import pytest

from tests.between_tests import (  # noqa: F401
    _no_engine_thread_outlives_its_test,
    _no_saved_anthropic_key_outlives_its_test,
    _no_test_reads_another_tests_board,
    _no_test_starts_inside_a_closing_server,
    _nobody_is_waiting_on_the_owner,
    forget_other_tests_work,
)
from tests.collect_only_named import pytest_ignore_collect  # noqa: F401 -- a hook pytest finds here by its name
from tests.real_data_child_audit import SNAPSHOTTING as _LOCAL_SNAPSHOTTING_REAL_DATA
from tests.real_data_child_audit import (
    Remembering,
    filesystem_path_text,
    names_above,
    own_git_folder,
    part_of_checkout,
    read_child_log,
    remember_access,
)
from tests.slim_copy_audit import install as _watch_slim_copy_misses

# Child sitecustomize loads the audit by path without importing this checkout's
# tests package. Reuse its marker when this checkout is itself the child project.
_SNAPSHOTTING_REAL_DATA = getattr(
    sys.modules.get("_thomas_real_data_child_audit"), "SNAPSHOTTING", _LOCAL_SNAPSHOTTING_REAL_DATA
)

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
# Tests legitimately point the server at local test HTTP servers (loopback), which
# the SSRF guard (thomas/server/net_safety.py) blocks by default. Opt out here so
# integration tests run; the guard's blocking behavior is covered by test_net_safety.py.
os.environ.setdefault("THOMAS_ALLOW_PRIVATE_OUTBOUND", "1")
# evolve's headless build fallback spawns a real `claude -p` subprocess when the
# in-process agent no-ops; that subprocess blocks forever under pytest and hangs the
# suite (e.g. test_cli_evolve_commands.py). Disable the live fallback for tests --
# genuine evolve runs leave it enabled. See _evolve_cli_fallback_enabled().
os.environ.setdefault("THOMAS_EVOLVE_DISABLE_CLI_FALLBACK", "1")
# evolve's doppelganger builds a fresh "green" venv and, when its dep probe
# (import aiohttp, click, httpx) fails in that empty venv, runs a real networked
# `pip install -e .[repl,server]` that blocks forever offline -- hanging
# test_cli_evolve_commands.py. Build the green venv with --system-site-packages
# under test so it inherits those deps from this interpreter; the probe passes
# and the networked install is skipped. See doppelganger.ensure_green_venv().
os.environ.setdefault("THOMAS_EVOLVE_HERMETIC_VENV", "1")
# The model list refreshes itself at server start (thomas/models/catalog_refresh.py);
# tests build whole apps and must not ask real providers.
os.environ.setdefault("THOMAS_MODEL_CATALOG_AUTOREFRESH", "0")
# The ratchet (thomas/server/ratchet/service.py) proves and lands backlog work once a day;
# tests build whole apps and must never start it. Set, not setdefault: autorun_enabled()
# is on unless the environment says otherwise, so a run started from a Thomas server's
# shell -- which is where THOMAS_RATCHET_AUTORUN=1 would be exported -- is exactly the run
# a default would not have stopped, and the ratchet would prove real backlog candidates in
# real greens during the test run. A test that means to exercise autorun sets it itself;
# _a_test_leaves_the_thomas_env_as_it_found_it puts this back after it.
os.environ["THOMAS_RATCHET_AUTORUN"] = "0"
# The second look at every hand-in (thomas/server/precard/review.py) runs the real Claude CLI on your Claude
# plan. Set, not setdefault, for the same reason: no test settles a change through it unless it says so itself.
os.environ["THOMAS_SECOND_CHECK"] = "off"
# The check before the card (thomas/server/precard/check.py) copies dev twice and runs its tests, and one that
# cannot run now holds the change instead of handing it in. Set, not setdefault: a test that runs it turns it on.
os.environ["THOMAS_PRECARD_CHECK"] = "off"
# The code issue engine runs scripts/heartbeat.py from a timer thread in any app a test builds, and that reads your real data.
os.environ["THOMAS_CODE_ISSUE_ENGINE_ENABLED"] = "0"
# The self-upgrade engine's cycle thread scans the repo for minutes and no stop() ends it; it outlived its test (2026-11-08).
os.environ["THOMAS_SELF_UPGRADE_ENGINE_ENABLED"] = "0"

# ---------------------------------------------------------------------------
# No test run touches your real Thomas data.
#
# load_config() copies THOMAS_DATA_DIR, THOMAS_DB_PATH and about twenty other data
# paths into os.environ whenever they are unset (apply_runtime_data_env_defaults in
# thomas/core/config.py). That is right for a server. In a pytest process the paths
# outlived the test that called load_config(), and monkeypatch never undid them.
# Measured 2026-09-24: after test_a_worker_cannot_truncate_a_file and
# test_a_self_fix_can_patch_a_green called it, test_build_role_models wrote a Build
# builder model into your real preferences database. So, before anything here
# imports Thomas:
#   1. the whole run gets a data folder of its own (this block);
#   2. every test gets the THOMAS_* environment back exactly as it found it
#      (_a_test_leaves_the_thomas_env_as_it_found_it);
#   3. the run fails for direct test-process access to real data and for
#      guarded real data changes (the tripwire, pytest_sessionfinish).
# ---------------------------------------------------------------------------
THOMAS_MODULES_BEFORE_GUARD = sorted(name for name in sys.modules if name == "thomas" or name.startswith("thomas."))
_ENV_THE_RUN_STARTED_WITH = dict(os.environ)
TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="thomas-test-data-")).resolve()
_RUN_FOLDERS = {
    "THOMAS_DATA_DIR": TEST_DATA_ROOT,
    "THOMAS_HOME": TEST_DATA_ROOT,
    "THOMAS_STATE_DIR": TEST_DATA_ROOT,
    # The shared secret store is found from LOCALAPPDATA, not THOMAS_DATA_DIR
    # (thomas/integrations/discord_bridge_runtime_support.py), and every app a test builds loads it: with only the
    # three keys above, 13 tests in a 54-file sample still opened your real shared/secrets.json.
    "THOMAS_SHARED_SECRET_STORE_DIR": TEST_DATA_ROOT / "shared",
    # Build projects, chat workspaces and code scratch live in your ~/.thomas, found
    # by thomas_owned_root() (thomas/forge/anvil/forge_code_projects.py), not by
    # THOMAS_DATA_DIR. Measured 2026-09-24: test_chat_delegation_worker_contract had
    # made 23 "Use browseropen and browserextract then" projects in your Build list.
    "THOMAS_OWNED_ROOT": TEST_DATA_ROOT / "owned",
    # A shell that runs Thomas carries THOMAS_MEMORY_ROOT=<checkout>\runtime, which is neither of the folders the
    # guard below watches. Measured 2026-09-25: a server booted from such a shell wrote into your real runtime\.thomas.
    "THOMAS_MEMORY_ROOT": TEST_DATA_ROOT / "runtime",
    # On dev 144b1954, 56 passing self-edit tests left a pytest source copy, its
    # baseline and 15 locks in a fake home's .thomas: these paths need run isolation.
    "THOMAS_SELF_EDIT_HOME": TEST_DATA_ROOT / "self-edit-home",
    # A test's hand-in can finish after its own cage folder is undone; on 2026-10-25 one reached the live inbox.
    "THOMAS_CAGE_ROOT": TEST_DATA_ROOT / "cage",
}
for _key, _folder in _RUN_FOLDERS.items():
    os.environ[_key] = str(_folder)

# Your ~/.thomas as it was before this run: where THOMAS_OWNED_ROOT pointed, and
# the folder in your home that Thomas falls back to.
_home_thomas = [Path.home() / ".thomas"]
if str(_ENV_THE_RUN_STARTED_WITH.get("THOMAS_OWNED_ROOT") or "").strip():
    _home_thomas.insert(0, Path(_ENV_THE_RUN_STARTED_WITH["THOMAS_OWNED_ROOT"].strip()).expanduser())
REAL_HOME_THOMAS_DIRS = tuple(dict.fromkeys(folder.resolve() for folder in _home_thomas))

from thomas.core.config import resolve_thomas_data_dir  # noqa: E402 -- only once the run has its own folder

# These modules fix a folder under Path.home() / ".thomas" when they are imported,
# and nothing can point them elsewhere (an override belongs in thomas/). Their
# tests, and every app a test builds, appended to your ~/.thomas/*_engine.jsonl, and
# test_distribution wrote {"test_key": ...} over your updater's state.json. Until
# they have an override, the run moves the module attribute each one reads.
HOME_STATE_FOLDERS = {
    ("thomas.core.code_issue_engine", "STATE_DIR"): TEST_DATA_ROOT / "home-state",
    ("thomas.core.local_agent_engine", "STATE_DIR"): TEST_DATA_ROOT / "home-state",
    ("thomas.core.self_upgrade_engine", "STATE_DIR"): TEST_DATA_ROOT / "home-state",
    ("thomas.core.ui_workflow_engine", "STATE_DIR"): TEST_DATA_ROOT / "home-state",
    ("thomas.core.workspace_sync_engine", "STATE_DIR"): TEST_DATA_ROOT / "home-state",
    ("thomas.cli.commands.updater", "_STATE_DIR"): TEST_DATA_ROOT / "home-state" / "updater",
}
for (_name, _attribute), _folder in HOME_STATE_FOLDERS.items():
    _module = importlib.import_module(_name)
    if hasattr(_module, _attribute):  # if one is renamed, test_no_test_touches_your_real_data fails
        setattr(_module, _attribute, _folder)


def _real_data_dirs() -> tuple[Path, ...]:
    """Your real data folder: where Thomas writes with the environment this run
    started in, and the platform default (LOCALAPPDATA\\Thomas on Windows)."""
    folders = [resolve_thomas_data_dir(env={})]
    try:
        folders.insert(0, resolve_thomas_data_dir(env=_ENV_THE_RUN_STARTED_WITH))
    except ValueError:  # an unusable THOMAS_PROFILE; the default folder is still watched
        pass
    return tuple(dict.fromkeys(folders))


REAL_DATA_DIRS = _real_data_dirs()

# Audit opens in this pytest process, including read-only opens that a before/after
# mtime comparison cannot see. The hook is installed after setup and only
# records paths; it cannot be removed.
_DIRECT_REAL_DATA_ACCESS: set[str] = set()
_REAL_DATA_ACCESS_BY: dict[str, str] = {}  # each path's first event and test
_OWN_GIT_FOLDER = own_git_folder(ROOT)  # a check copy keeps its git folder beside it, inside the real data folder


def _audit_real_data_access(event: str, args: tuple) -> None:
    if event == "os.system" and args:
        cwd = Path.cwd().resolve()
        if not part_of_checkout(cwd, ROOT, _OWN_GIT_FOLDER) and any(
            cwd == root or root in cwd.parents for root in REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS
        ):
            _CHILD_REAL_DATA_TARGETS.add(str(cwd))
        command = os.fsdecode(args[0]).lower().replace("\\", "/")
        # os.system inherits the environment without going through Popen, but
        # merely carrying an unused data path must not fail a harmless command.
        for key, value in os.environ.items():
            reference = rf"(?<![\w])(?:\${re.escape(key)}\b|\$\{{{re.escape(key)}\}}|%{re.escape(key)}%)"
            if not re.search(reference, command, flags=re.IGNORECASE if os.name == "nt" else 0):
                continue
            try:
                candidate = Path(value).expanduser()
                if not candidate.is_absolute():
                    continue
                candidate = candidate.resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if not part_of_checkout(candidate, ROOT, _OWN_GIT_FOLDER) and any(
                candidate == root or root in candidate.parents for root in REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS
            ):
                _CHILD_REAL_DATA_TARGETS.add(str(candidate))
        for root in REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS:
            if root == ROOT or ROOT in root.parents:
                continue
            name = os.path.normcase(str(root)).lower().replace("\\", "/")
            if any(
                command.startswith(name, index)
                and (index + len(name) == len(command) or command[index + len(name)] in '/\\" ')
                for index in range(len(command))
            ):
                _CHILD_REAL_DATA_TARGETS.add(str(root))
        return
    if (
        event
        not in (
            "open",
            "os.open",
            "os.listdir",
            "os.scandir",
            "os.chdir",
            "os.mkdir",
            "os.rmdir",
            "sqlite3.connect",
            "os.remove",
            "os.rename",
            "os.truncate",
            "os.utime",
        )
        or not args
        or (event in ("os.listdir", "os.scandir") and _SNAPSHOTTING_REAL_DATA.get())
    ):
        return
    paths = args[:2] if event == "os.rename" else args[:1]
    for raw in paths:
        if not isinstance(raw, (str, bytes, os.PathLike)):
            continue
        try:
            text = os.fsdecode(raw)
            if event == "sqlite3.connect" and text.startswith("file:"):
                text = unquote(text[5:].split("?", 1)[0])
            text = filesystem_path_text(text)
            if text is None:
                continue
            candidate = Path(text).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if part_of_checkout(candidate, ROOT, _OWN_GIT_FOLDER) or names_above(event, candidate, ROOT):
            continue  # the checkout, and the git folder it keeps beside it, may live beneath LOCALAPPDATA/Thomas
        if any(candidate == root or root in candidate.parents for root in REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS):
            remember_access(_REAL_DATA_ACCESS_BY, str(candidate), event)
            _DIRECT_REAL_DATA_ACCESS.add(str(candidate))


sys.addaudithook(_audit_real_data_access)
_watch_slim_copy_misses()  # only in a slim proof copy, which names the files it left out (spec 2026-10-29)

# Python children need their own audit hook: sys.addaudithook is process-local.
# A temporary startup module avoids changing any installed Python environment.
_CHILD_AUDIT_LOG = TEST_DATA_ROOT / "child-real-data-access.jsonl"
_CHILD_AUDIT_BOOT = TEST_DATA_ROOT / "child-audit-boot"
_CHILD_AUDIT_BOOT.mkdir()
(_CHILD_AUDIT_BOOT / "sitecustomize.py").write_text(
    "import importlib.util\n"
    f"spec = importlib.util.spec_from_file_location('_thomas_real_data_child_audit', {str(ROOT / 'tests' / 'real_data_child_audit.py')!r})\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "import sys\n"
    "sys.modules[spec.name] = module\n"
    "spec.loader.exec_module(module)\n"
    f"module.install({str(ROOT)!r})\n",
    encoding="utf-8",
)
_ORIGINAL_PYTHONPATH = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = _ORIGINAL_PYTHONPATH
os.environ["THOMAS_TEST_REAL_DATA_AUDIT_LOG"] = str(_CHILD_AUDIT_LOG)
os.environ["THOMAS_TEST_REAL_DATA_AUDIT_BOOT"] = str(_CHILD_AUDIT_BOOT)
os.environ["THOMAS_TEST_REAL_DATA_AUDIT_ROOTS"] = json.dumps(
    [str(root) for root in REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS]
)

_ORIGINAL_POPEN = subprocess.Popen
_CHILD_REAL_DATA_TARGETS: set[str] = Remembering(_REAL_DATA_ACCESS_BY, "a child command")


def _audit_popen(self, *args, **kwargs):
    """Carry Python auditing and flag real paths used by child commands."""
    command = args[0] if args else kwargs.get("args", ())
    arguments = (command,) if isinstance(command, (str, bytes, os.PathLike)) else command
    cwd = Path(kwargs.get("cwd") or os.getcwd()).resolve()
    roots = REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS
    # Native children do not load our Python audit hook; attribute a real-data
    # working directory or a path explicitly used by their command here.
    if not part_of_checkout(cwd, ROOT, _OWN_GIT_FOLDER) and any(cwd == root or root in cwd.parents for root in roots):
        _CHILD_REAL_DATA_TARGETS.add(str(cwd))
    for argument in arguments:
        if not isinstance(argument, (str, bytes, os.PathLike)):
            continue
        text = os.fsdecode(argument)
        # A shell command is one string, not a sequence of path arguments.
        # Its quoted absolute paths still point at real data even though the
        # whole command string cannot be resolved as a filesystem path.
        if kwargs.get("shell") and isinstance(command, (str, bytes)):
            normalized = os.path.normcase(text).replace("\\", "/")
            for root in roots:
                name = os.path.normcase(str(root)).replace("\\", "/")
                if (
                    root != ROOT
                    and ROOT not in root.parents
                    and any(
                        normalized.startswith(name, index)
                        and (index + len(name) == len(normalized) or normalized[index + len(name)] in '/\\" ')
                        for index in range(len(normalized))
                    )
                ):
                    _CHILD_REAL_DATA_TARGETS.add(str(root))
        try:
            candidate = (cwd / Path(text).expanduser()).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if part_of_checkout(candidate, ROOT, _OWN_GIT_FOLDER):  # the checkout, or the git folder it keeps beside it
            continue
        if any(candidate == root or root in candidate.parents for root in roots):
            _CHILD_REAL_DATA_TARGETS.add(str(candidate))
    env = kwargs.get("env")
    child_env = os.environ if env is None else dict(env)
    for key, value in child_env.items():
        if not isinstance(value, (str, bytes, os.PathLike)):
            continue
        command_text = " ".join(os.fsdecode(part) for part in arguments if isinstance(part, (str, bytes, os.PathLike)))
        reference = rf"%{re.escape(key)}%" if os.name == "nt" else rf"\$(?:{re.escape(key)}\b|\{{{re.escape(key)}\}})"
        if not re.search(reference, command_text, flags=re.IGNORECASE if os.name == "nt" else 0):
            continue
        try:
            candidate = Path(os.fsdecode(value)).expanduser()
            if not candidate.is_absolute():
                continue
            candidate = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if not part_of_checkout(candidate, ROOT, _OWN_GIT_FOLDER) and any(
            candidate == root or root in candidate.parents for root in roots
        ):
            _CHILD_REAL_DATA_TARGETS.add(str(candidate))
    if env is None:
        env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    # A new Windows console may inherit our sitecustomize path; remove it.
    new_console = os.name == "nt" and bool(kwargs.get("creationflags", 0) & subprocess.CREATE_NEW_CONSOLE)
    if new_console:
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in pythonpath.split(os.pathsep) if entry and Path(entry) != _CHILD_AUDIT_BOOT
        )
    else:
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(_CHILD_AUDIT_BOOT), pythonpath)))
    for key in ("LOG", "ROOTS", "BOOT"):
        name = f"THOMAS_TEST_REAL_DATA_AUDIT_{key}"
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    kwargs["env"] = env
    return _ORIGINAL_POPEN.__init__(self, *args, **kwargs)


class _AuditedPopen(_ORIGINAL_POPEN):
    __init__ = _audit_popen


subprocess.Popen = _AuditedPopen


def _child_real_data_access() -> set[str]:
    return read_child_log(_CHILD_AUDIT_LOG, _REAL_DATA_ACCESS_BY)


def _points_into(value: str, roots: tuple[Path, ...]) -> bool:
    text = str(value or "").strip()
    if not text or not Path(text).expanduser().is_absolute():  # "1", "off": not a path
        return False
    try:
        candidate = Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return any(candidate == root or root in candidate.parents for root in roots)


# A run started from a Thomas server's shell inherits its data paths
# (THOMAS_DB_PATH, THOMAS_RUNS_DB_PATH, ...). None of them may lead a test home.
DROPPED_REAL_DATA_KEYS = tuple(
    sorted(
        key
        for key, value in os.environ.items()
        if key.startswith("THOMAS_")
        and key not in _RUN_FOLDERS
        and _points_into(value, REAL_DATA_DIRS + REAL_HOME_THOMAS_DIRS)
    )
)
for _key in DROPPED_REAL_DATA_KEYS:
    os.environ.pop(_key, None)

# The files the tripwire watches. SQLite files also change when the running
# Thomas checkpoints or opens its database; their passive mtimes are not proof
# that a test touched them. Direct access is audited below.
_WATCHED_REAL_DATA = (
    "thomas.db",
    "thomas.db-wal",
    "thomas.db-shm",
    "thomas.db-journal",
    ".thomas/*.sqlite3",
    ".thomas/*.sqlite3-wal",
    ".thomas/*.sqlite3-shm",
    ".thomas/*.sqlite3-journal",
    "json/*",
)


def snapshot_real_data(roots) -> dict[str, int]:
    """Each watched file's mtime in ns. Only stats the files; never opens one."""
    token = _SNAPSHOTTING_REAL_DATA.set(True)
    try:
        found: dict[str, int] = {}
        for root in roots:
            for pattern in _WATCHED_REAL_DATA:
                for path in Path(root).glob(pattern):
                    try:
                        found[str(path)] = path.stat().st_mtime_ns
                    except OSError:
                        continue
        return found
    finally:
        _SNAPSHOTTING_REAL_DATA.reset(token)


HOME_THOMAS_ENTRY_FOLDERS = ("self-edit-candidates", "source-application-locks")


def snapshot_home_thomas(roots) -> dict[str, int]:
    """Stat mtimes of ~/.thomas top-level files, projects/* folders and self-edit entries.

    Record every direct file or folder in self-edit-candidates and
    source-application-locks too. A folder's mtime moves when something is
    created or removed directly in it, so the tripwire sees it. Only stats.
    """
    token = _SNAPSHOTTING_REAL_DATA.set(True)
    try:
        found: dict[str, int] = {}
        for root in roots:
            folders = (
                (Path(root), Path.is_file),
                (Path(root) / "projects", Path.is_dir),
                *((Path(root) / name, lambda _path: True) for name in HOME_THOMAS_ENTRY_FOLDERS),
            )
            for folder, wanted in folders:
                try:
                    entries = list(folder.iterdir())
                except OSError:
                    continue
                for path in entries:
                    try:
                        if wanted(path):
                            found[str(path)] = path.stat().st_mtime_ns
                    except OSError:
                        continue
        return found
    finally:
        _SNAPSHOTTING_REAL_DATA.reset(token)


def _when(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9).isoformat(timespec="microseconds")


def real_data_changes(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """One sentence per watched file that was written, created or deleted."""
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if old is None:
            changes.append(f"{path} was created during the run ({_when(new)})")
        elif new is None:
            changes.append(f"{path} was deleted during the run (last written {_when(old)})")
        else:
            changes.append(f"{path} was written during the run ({_when(old)} -> {_when(new)})")
    return changes


def _sqlite_file(path: str) -> bool:
    name = Path(path).name.lower()
    return name.endswith((".db-wal", ".db-shm", ".db-journal", ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal"))


def _running_in_a_green(env: dict[str, str]) -> bool:
    # scripts/cage/shell_runner.py child_env() gives every command it runs in a
    # green this agent id (GREEN_AGENT_ID in thomas/server/serve_instance_guard.py).
    return str(env.get("THOMAS_AGENT_ID") or "").strip() == "thomas-green"


def check_real_data(
    session, before: dict[str, int], roots, *, in_a_green: bool, snapshot=snapshot_real_data
) -> list[str]:
    """Fail on test-process access or guarded changes, not live SQLite sidecar churn.

    In a green, unrelated changes in the caged Thomas's own folder are
    reported without failing the run. Direct access by tests always fails.
    """
    after = snapshot(roots)
    passive_changes = real_data_changes(before, after)
    # The running application can create and remove SQLite sidecars without
    # any test touching them. Changes to the database file itself remain guarded.
    changes = [line for line in passive_changes if not _sqlite_file(line.split(" was ", 1)[0])]
    watched_roots = tuple(Path(root).resolve() for root in roots)
    changes.extend(
        f"{path} was opened by this test run ({_REAL_DATA_ACCESS_BY.get(path, 'unattributed')})"
        for path in sorted(_DIRECT_REAL_DATA_ACCESS | _child_real_data_access() | _CHILD_REAL_DATA_TARGETS)
        if any(Path(path) == root or root in Path(path).parents for root in watched_roots)
    )
    if changes and session.exitstatus in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
        if not in_a_green or any(" was opened by this test run" in line for line in changes):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    return changes


_REAL_DATA_AT_START = snapshot_real_data(REAL_DATA_DIRS)
_HOME_THOMAS_AT_START = snapshot_home_thomas(REAL_HOME_THOMAS_DIRS)
_REAL_DATA_CHANGED: list[str] = []
pytest_plugins = []
if (Path(__file__).with_name("conftest_factories.py")).exists():
    pytest_plugins.append("tests.conftest_factories")


# Optional pytest plugins. find_spec() can raise ImportError (a parent package
# is missing) or ValueError (the module has no __spec__), so guard narrowly
# rather than swallowing every exception.
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# pytest-asyncio's entry point loads its .plugin submodule; appending the
# package itself adds its fixtures without colliding with that registration.
if _has_module("pytest_asyncio"):
    pytest_plugins.append("pytest_asyncio")

# NOTE: pytest-timeout is intentionally NOT appended here. It ships a setuptools
# entry point, so pytest auto-loads it (as the "timeout" plugin) whenever the
# package is installed. Appending it re-registers the *same* module under a
# second name and raises "Plugin already registered under a different name" --
# the failure that silently took down the merge-readiness architecture gate on
# any interpreter that had the package installed. When pytest-timeout is absent,
# pytest_addoption below registers the ini keys as a warning-free fallback so
# pyproject's `timeout = 300` never errors.

if _has_module("aiohttp.pytest_plugin"):
    pytest_plugins.append("aiohttp.pytest_plugin")


@pytest.fixture(autouse=True)
def _a_test_leaves_the_thomas_env_as_it_found_it() -> Iterator[None]:
    """load_config() in one test cannot hand its data paths to the next, nor a session its identity.

    Keys a test added are removed, and keys it changed or removed are put back,
    whether it used monkeypatch or wrote os.environ itself. The name sorts first,
    so this is the first autouse fixture set up and the last torn down.
    """
    before = {key: value for key, value in os.environ.items() if key.startswith(("THOMAS_", "AGENT_"))}
    yield
    for key in [key for key in os.environ if key.startswith(("THOMAS_", "AGENT_")) and key not in before]:
        del os.environ[key]
    for key, value in before.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _runtime_protection_defaults_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate gate tests from this checkout's signed owner preference."""

    from scripts.forge.gates import _runtime_guard

    monkeypatch.setattr(_runtime_guard, "runtime_protection_disabled", lambda _root: False)


@pytest.fixture(autouse=True)
def _the_cage_does_not_decide_test_outcomes(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A test must not depend on whether an OS service is running right now.

    The cage posture is pinned on this machine at C:\\ProgramData\\ThomasCage,
    and the pin is a floor the environment cannot lower -- deliberately, so
    nothing Thomas runs can switch his own cage off. The side effect, measured
    2026-09-22: shell.exec routed every test command through the caged runner,
    so tests asserting on the LOCAL spooled path (hang evidence, the spool file,
    the selector-loop fallback) silently stopped exercising it, and when the
    runner died 12 tests failed for a reason that had nothing to do with them.

    The pin cannot be lowered, but the root it is read from can be redirected in
    THIS process, which is not a bypass: it changes nothing on disk and nothing
    outside the test run. Tests that mean to exercise the cage set it up
    themselves (tests/test_the_shell_runs_in_the_cage.py).

    The same goes for the account and the run: a suite run by a caged Build is
    the cage account (Guarded then gets a shell) and inherits that Build's run
    channel (the Claude argv then carries its MCP tools). Tests that mean either
    set it up themselves (tests/test_the_cage_gives_build_a_shell.py,
    tests/test_run_channel_mcp.py).

    A test marked ``real_cage_account`` keeps the real reader. Replacing it for
    every test made the one test of HOW the account is read unable to fail: it
    asserted the replacement's own answer, so a reader that trusted USERNAME
    passed.
    """
    from thomas.core import cage_account
    from thomas.tools import cage_shell

    if request.node.get_closest_marker("real_cage_account") is None:
        monkeypatch.setattr(cage_account, "running_as_cage_account", lambda: False)
    for key in ("THOMAS_RUN_CHANNEL_URL", "THOMAS_CODE_RUN_ID", "THOMAS_RUN_CHANNEL_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", tmp_path_factory.mktemp("no-cage"))
    monkeypatch.setattr(cage_shell, "DEFAULT_PIN_ROOT", tmp_path_factory.mktemp("no-pins"))
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path_factory.mktemp("no-cage-root")))
    monkeypatch.setenv(cage_shell.POSTURE_ENV, "off")
    getattr(cage_shell._configured_posture, "cache_clear", lambda: None)()


@pytest.fixture(autouse=True)
def _runtime_protection_starts_unanchored() -> None:
    """No test inherits another test's idea of where the running Thomas lives.

    ``anchor_runtime_protection`` sets a module global so a Build runner checks
    protection against the real Thomas rather than its project folder. A test that
    anchored to its own temp folder and never reset it left every later test in
    the process checking against that stale folder -- measured 2026-09-22, the
    runtime-protection KEY file then became writable through fs.write_file in
    test_filesystem_protection_control_files, which passed alone and failed in
    the suite. A protection suite that can quietly stop protecting is not a
    regression signal, so the anchor is cleared around every test.
    """
    from thomas.tools import runtime_protection_paths as protection

    protection._RUNTIME_ANCHOR = None
    yield
    protection._RUNTIME_ANCHOR = None


@pytest.fixture(autouse=True)
def _green_stays_in_the_test(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep test greens and their saved captures in temp folders, never the real
    keeper drop; tests also set aside none of the 256 MB disk reserve."""
    from thomas.core.green_place import GREEN_ROOT_ENV  # its own home: what this file imports selects every test
    from thomas.server import keeper_guard

    monkeypatch.setenv(GREEN_ROOT_ENV, str(tmp_path_factory.mktemp("green-root")))
    monkeypatch.setenv(keeper_guard.DROP_ENV, str(tmp_path_factory.mktemp("keeper-drop")))
    monkeypatch.setattr(keeper_guard, "RESERVE_BYTES", 0)


@pytest.fixture(autouse=True)
def _no_test_starts_the_real_claude_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat's Claude-plan transport may only be driven by a fake runner.

    ``stream_claude_cli`` takes an injectable ``spawn`` for exactly that
    (tests/_claude_plan_fakes.py drives the real stream-json protocol through it
    for both Claude-plan suites). Its default starts ``claude`` on this machine, which
    under pytest would sign in as you, spend your plan's allowance and block the
    run waiting for a real model. A test that reaches the default is a test that
    meant to fake it, so it fails here instead of launching anything.
    """
    from thomas.core import llm_streaming_claude_cli

    async def refuse(command: list[str], *, cwd: str) -> None:
        raise AssertionError(
            f"a test tried to start the real Claude CLI ({' '.join(str(part) for part in command[:3])}). "
            "Pass stream_claude_cli a fake spawn=, or assert on cli_command() instead."
        )

    monkeypatch.setattr(llm_streaming_claude_cli, "_spawn", refuse)


@pytest.fixture(autouse=True)
def _ratchet_records_stay_in_the_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The ratchet's ledger, census and lease live in a temp folder, never the data directory's ratchet
    folder, where the running Thomas records what it has landed."""
    monkeypatch.setenv("THOMAS_RATCHET_ROOT", str(tmp_path_factory.mktemp("ratchet-root")))


@pytest.fixture(autouse=True)
def _no_test_reads_another_tests_work() -> None:
    """Every test starts with an empty task ledger and no Build projects.

    A test that names no root of its own shares both with its whole worker, and both outlive it: an unfinished task
    counts as active for five minutes, and a project reached a later test's prompt through the Build project catalog.
    Each victim passed alone and failed after its writer, on 405383ba too (measured 2026-10-31).
    """
    forget_other_tests_work(TEST_DATA_ROOT / "owned")


def _add_ini_if_missing(parser, name: str, help_text: str) -> None:
    registered = getattr(parser, "_inidict", {})
    if name in registered:
        return
    try:
        parser.addini(name, help_text)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "real_cage_account: keep the real Windows account reader (_the_cage_does_not_decide_test_outcomes)"
    )


def pytest_addoption(parser) -> None:
    _add_ini_if_missing(parser, "timeout", "Fallback registration for pytest-timeout's timeout setting.")
    _add_ini_if_missing(
        parser,
        "timeout_method",
        "Fallback registration for pytest-timeout's timeout_method setting.",
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    in_a_green = _running_in_a_green(_ENV_THE_RUN_STARTED_WITH)
    _REAL_DATA_CHANGED[:] = check_real_data(
        session, _REAL_DATA_AT_START, REAL_DATA_DIRS, in_a_green=in_a_green
    ) + check_real_data(
        session, _HOME_THOMAS_AT_START, REAL_HOME_THOMAS_DIRS, in_a_green=in_a_green, snapshot=snapshot_home_thomas
    )


def pytest_terminal_summary(terminalreporter) -> None:
    if not _REAL_DATA_CHANGED:
        return
    in_a_green = _running_in_a_green(_ENV_THE_RUN_STARTED_WITH)
    terminalreporter.section(
        "REAL THOMAS DATA ACCESS OR UNATTRIBUTED CHANGE DURING THIS TEST RUN", sep="!", red=True, bold=True
    )
    for line in _REAL_DATA_CHANGED:
        terminalreporter.write_line(line, red=True, bold=True)
    terminalreporter.write_line(
        f"Tests ran with THOMAS_DATA_DIR, THOMAS_OWNED_ROOT and THOMAS_SELF_EDIT_HOME under {TEST_DATA_ROOT}. "
        "Opened paths were accessed by this test process; other listed paths changed externally."
    )
    terminalreporter.write_line(
        "In a green, external changes do not fail the run; direct test access does."
        if in_a_green
        else "Direct access and non-SQLite changes fail the run. SQLite changes without test access do not."
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(TEST_DATA_ROOT, ignore_errors=True)
    from tests.run_folder_sweep import sweep  # the folders earlier runs could not remove (2026-11-06: 1,992 of them)

    sweep(TEST_DATA_ROOT.parent, own=TEST_DATA_ROOT)


# Not every file under tests/ is a Python test module. The browser harnesses run the shipped modules under Node
# (``.mjs``) or drive them in Chromium (``.html``), and each one is asserted on from a ``tests/test_*.py`` module
# that starts it -- they live in tests/web_node/ and tests/web/, so this belongs to the whole tree rather than to one
# folder. A verification run hands pytest every changed path under tests/ (``_is_test_file`` in
# thomas/forge/anvil/build_verify.py), and pytest handed a path it has no collector for fails the ENTIRE run with
# "found no collectors" before a single test executes. Accepting the path and collecting nothing from it keeps such
# a run about the Python tests, which is where these harnesses are checked.
HARNESS_SUFFIXES = {".mjs", ".html"}


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> pytest.Collector | None:
    if file_path.suffix in HARNESS_SUFFIXES:
        return BrowserHarness.from_parent(parent, path=file_path)
    return None


class BrowserHarness(pytest.File):
    """A harness path, accepted and yielding no tests of its own."""

    def collect(self):
        return ()
