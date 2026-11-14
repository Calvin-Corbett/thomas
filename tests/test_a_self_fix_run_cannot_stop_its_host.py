"""A self-fix run can never stop the Thomas it runs inside.

On 2026-09-24 the caged server (port 8898) ended with exit code 15, which is what
``os.kill(pid, signal.SIGTERM)`` leaves on Windows, while five self-fix runs were
working in greens. ``_check_single_instance`` stopped whatever PID its memory
folder's serve.lock named, and any Thomas server holding its port, without asking
whose they were.

These drive the real ``_check_single_instance`` against temporary memory folders.
Only the operating system's answers are faked: the process listing and the port
probe (the ``subprocess`` app_lifecycle calls), and ``os.kill``, which records
every call. "The other Thomas" is a real sleeping child process, so whether it is
still running is the operating system's own answer.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from thomas.server import app_lifecycle, green_checkout
from thomas.server import serve_instance_guard as guard

ROOT = Path(app_lifecycle.__file__).resolve().parents[2]
PORT = 8898
_REAL_KILL = os.kill
SHELL_RUNNER = f'"{ROOT / ".venv" / "Scripts" / "pythonw.exe"}" "{ROOT / "scripts" / "cage" / "shell_runner.py"}"'
CAGED_SERVER = (
    f'"C:\\Python312\\python.exe" "{ROOT / "scripts" / "cage" / "caged_server.py"}" '
    '--port 8898 --codex-home "C:\\Users\\you\\.codex"'
)


class FakeOS:
    """The process table, the port table and ``os.kill``, for one test."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.listeners: dict[int, set[int]] = {}
        self.kills: list[tuple[int, int]] = []
        self.children: dict[int, subprocess.Popen[bytes]] = {}
        self.listing_times_out = False

    def spawn(self) -> int:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.children[proc.pid] = proc
        return proc.pid

    def gone(self) -> int:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(30)
        self.children[proc.pid] = proc  # the handle held here keeps the pid from being reused
        return proc.pid

    def running(self, pid: int) -> bool:
        return self.children[pid].poll() is None

    def server(
        self, pid: int, cmdline: str, *, ppid: int = 1, listening_on: int | None = None, name: str = "python.exe"
    ) -> None:
        self.rows.append({"ProcessId": pid, "ParentProcessId": ppid, "Name": name, "CommandLine": cmdline})
        if listening_on is not None:
            self.listeners.setdefault(listening_on, set()).add(pid)

    def stopped(self) -> list[int]:
        return [pid for pid, sig in self.kills if sig != 0]

    def kill(self, pid: int, sig: int) -> None:
        self.kills.append((pid, sig))
        proc = self.children.get(pid)
        if proc is None or proc.poll() is not None:
            raise ProcessLookupError(pid)
        if sig != 0:
            _REAL_KILL(pid, signal.SIGTERM)  # our own child, nothing else
            proc.wait(30)

    def run(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = " ".join(str(arg) for arg in args)
        if self.listing_times_out and ("Win32_Process" in command or args[0] == "ps"):
            raise subprocess.TimeoutExpired(args, 5.0)
        if "Win32_Process" in command:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.rows), "")
        if args[0] == "ps":
            lines = [f"{row['ProcessId']} {row['ParentProcessId']} {row['CommandLine']}" for row in self.rows]
            return subprocess.CompletedProcess(args, 0, "\n".join(lines), "")
        asked = re.search(r"-LocalPort (\d+)|-iTCP:(\d+)", command)
        if asked:
            port = int(asked.group(1) or asked.group(2))
            found = "\n".join(str(pid) for pid in sorted(self.listeners.get(port, set())))
            return subprocess.CompletedProcess(args, 0 if found or os.name == "nt" else 1, found, "")
        raise AssertionError(f"unexpected command: {command}")


@pytest.fixture
def fake_os(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake = FakeOS()
    monkeypatch.setattr(os, "kill", fake.kill)
    monkeypatch.setattr(
        app_lifecycle,
        "subprocess",
        types.SimpleNamespace(
            run=fake.run, TimeoutExpired=subprocess.TimeoutExpired, CompletedProcess=subprocess.CompletedProcess
        ),
    )
    # The port table is read from the OS socket table first and from the shell only where that fails; this world's
    # table is the one the fake holds.
    monkeypatch.setattr(
        app_lifecycle, "_listeners_from_the_socket_table", lambda port: set(fake.listeners.get(int(port), set()))
    )
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    yield fake
    for proc in fake.children.values():
        if proc.poll() is None:
            proc.kill()
            proc.wait(30)


def _config(memory: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(memory=types.SimpleNamespace(root_path=memory))


def _lock(memory: Path, **fields: object) -> Path:
    lock = memory / ".thomas" / "serve.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(fields), encoding="utf-8")
    return lock


def _venv_python(checkout: Path) -> str:
    return f'"{checkout / ".venv" / "Scripts" / "python.exe"}" -m thomas serve --port {PORT}'


def _refused(memory: Path) -> pytest.ExceptionInfo[SystemExit]:
    with pytest.raises(SystemExit) as refused:
        app_lifecycle._check_single_instance(_config(memory), "127.0.0.1", PORT)
    assert refused.value.code not in (0, None)
    return refused


def test_a_lock_owner_from_another_checkout_is_left_running(fake_os: FakeOS, tmp_path: Path, capsys) -> None:
    other = fake_os.spawn()
    other_root = tmp_path / "another-thomas"
    lock = _lock(tmp_path / "memory", pid=other, port=PORT, root=str(other_root))

    _refused(tmp_path / "memory")

    assert fake_os.stopped() == []
    assert fake_os.running(other)
    assert str(other_root) in capsys.readouterr().err
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == other, "the other server's lock was taken"


def test_the_same_checkouts_lock_owner_is_stopped_so_a_restart_works(fake_os: FakeOS, tmp_path: Path) -> None:
    # The previous server's own lock: its start time is the OS's answer for its PID.
    previous = fake_os.spawn()
    started_at = guard.process_started_at(previous)
    assert started_at is not None
    lock = _lock(tmp_path / "memory", pid=previous, port=PORT, root=str(ROOT), started_at=started_at)

    port = app_lifecycle._check_single_instance(_config(tmp_path / "memory"), "127.0.0.1", PORT)

    assert fake_os.stopped() == [previous]
    assert not fake_os.running(previous)
    assert json.loads(lock.read_text(encoding="utf-8")) == {
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "port": PORT,
        "root": str(ROOT),
        "started_at": guard.process_started_at(os.getpid()),
        "caged": False,
    }
    assert port == PORT


def test_a_lock_from_before_locks_recorded_their_checkout_is_left_running(fake_os: FakeOS, tmp_path: Path) -> None:
    other = fake_os.spawn()
    _lock(tmp_path / "memory", pid=other, host="127.0.0.1", port=PORT)

    _refused(tmp_path / "memory")

    assert fake_os.stopped() == []
    assert fake_os.running(other)


def test_a_lock_left_by_a_server_that_is_gone_does_not_block_a_start(fake_os: FakeOS, tmp_path: Path) -> None:
    lock = _lock(tmp_path / "memory", pid=fake_os.gone(), host="127.0.0.1", port=PORT)

    port = app_lifecycle._check_single_instance(_config(tmp_path / "memory"), "127.0.0.1", PORT)

    assert fake_os.stopped() == []
    assert json.loads(lock.read_text(encoding="utf-8"))["root"] == str(ROOT)
    assert port == PORT


@pytest.mark.skipif(os.name != "nt", reason="the POSIX process listing carries no program name")
def test_a_lock_whose_pid_now_belongs_to_another_program_stops_nothing(fake_os: FakeOS, tmp_path: Path) -> None:
    reused = fake_os.spawn()
    fake_os.server(reused, "C:\\Program Files\\Browser\\browser.exe --type=renderer", name="browser.exe")
    lock = _lock(tmp_path / "memory", pid=reused, port=PORT, root=str(ROOT))

    port = app_lifecycle._check_single_instance(_config(tmp_path / "memory"), "127.0.0.1", PORT)

    assert fake_os.stopped() == []
    assert fake_os.running(reused)
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert port == PORT


# After a reboot or a crash the lock's PID can belong to any process, often
# another python one: the cage's shell runner and your owner desk are pythonw,
# as the same account. Each case is a stale lock, so the start goes ahead, stops
# nothing, and takes the lock over, without waiting on the process it names.
_REUSED = {
    "the cage shell runner": {"root": str(ROOT), "cmdline": SHELL_RUNNER, "name": "pythonw.exe"},
    "another account's process (command line unreadable)": {"root": str(ROOT), "cmdline": ""},
    "no process listing": {"root": str(ROOT), "listing": "empty"},
    "a process listing that timed out": {"root": str(ROOT), "listing": "timeout"},
    "another server of this checkout, started after the lock": {
        "root": str(ROOT),
        "cmdline": _venv_python(ROOT).replace(f"--port {PORT}", "--port 8899"),
        "started": "earlier",
    },
    "a lock with no checkout, PID now the cage shell runner": {"cmdline": SHELL_RUNNER, "name": "pythonw.exe"},
}


@pytest.mark.parametrize("case", list(_REUSED))
def test_a_stale_lock_whose_pid_was_reused_stops_nothing_and_does_not_stall(
    fake_os: FakeOS, tmp_path: Path, case: str
) -> None:
    shape = _REUSED[case]
    reused = fake_os.spawn()
    if "cmdline" in shape:
        fake_os.server(reused, str(shape["cmdline"]), name=str(shape.get("name") or "python.exe"))
    fake_os.listing_times_out = shape.get("listing") == "timeout"
    fields: dict[str, object] = {"pid": reused, "host": "127.0.0.1", "port": PORT}
    if "root" in shape:
        fields["root"] = shape["root"]
    if shape.get("started") == "earlier":
        fields["started_at"] = float(guard.process_started_at(reused) or 0.0) - 3600.0
    lock = _lock(tmp_path / "memory", **fields)

    began = time.perf_counter()
    port = app_lifecycle._check_single_instance(_config(tmp_path / "memory"), "127.0.0.1", PORT)
    took = time.perf_counter() - began

    assert fake_os.stopped() == [], f"{case}: a process that only reused the lock's PID was stopped"
    assert fake_os.running(reused)
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert port == PORT
    assert took < 2.0, f"{case}: the start took {took:.1f} s over a stale lock"


@pytest.mark.parametrize("lock_shape", ["a lock the caged server wrote", "a lock from before that was recorded"])
def test_the_caged_server_is_never_stopped_by_a_start(
    fake_os: FakeOS, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, lock_shape: str
) -> None:
    # A builder running this checkout's own scripts/cage/caged_server.py, with no
    # agent id: its code and (after caged_server.py's chdir) its folder are the
    # checkout's, and its memory folder is the caged server's.
    caged = fake_os.spawn()
    monkeypatch.chdir(ROOT)
    if lock_shape == "a lock the caged server wrote":
        started_at = guard.process_started_at(caged)
        lock = _lock(tmp_path / "memory", pid=caged, port=PORT, root=str(ROOT), started_at=started_at, caged=True)
    else:
        fake_os.server(caged, CAGED_SERVER, listening_on=PORT)
        lock = _lock(tmp_path / "memory", pid=caged, host="127.0.0.1", port=PORT, root=str(ROOT))

    _refused(tmp_path / "memory")

    assert fake_os.stopped() == []
    assert fake_os.running(caged)
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == caged
    said = capsys.readouterr().err
    assert "caged server" in said and "schtasks /End /TN ThomasCagedServer" in said


def test_a_port_holder_from_another_checkout_is_left_running(fake_os: FakeOS, tmp_path: Path, capsys) -> None:
    other = fake_os.spawn()
    other_root = tmp_path / "another-thomas"
    fake_os.server(other, _venv_python(other_root), listening_on=PORT)

    _refused(tmp_path / "memory")

    assert fake_os.stopped() == []
    assert fake_os.running(other)
    said = capsys.readouterr().err
    assert f"port {PORT} is used by another Thomas ({other_root}); start this one with --port " in said


def test_the_same_checkouts_duplicate_on_the_port_is_stopped(fake_os: FakeOS, tmp_path: Path) -> None:
    # The layout measured on Windows: the listening interpreter's command line
    # names the base Python; its venv launcher parent, same arguments, names the
    # checkout the server came from.
    duplicate, launcher = fake_os.spawn(), 4_000_000
    fake_os.server(launcher, _venv_python(ROOT).replace(f" --port {PORT}", ""))
    fake_os.server(duplicate, '"C:\\Python312\\python.exe" -m thomas serve', ppid=launcher, listening_on=PORT)

    port = app_lifecycle._check_single_instance(_config(tmp_path / "memory"), "127.0.0.1", PORT)

    assert fake_os.stopped() == [duplicate]
    lock = json.loads((tmp_path / "memory" / ".thomas" / "serve.lock").read_text(encoding="utf-8"))
    assert lock["root"] == str(ROOT)
    assert port == PORT


def _green(monkeypatch: pytest.MonkeyPatch, *, code_from_it: bool) -> Path:
    green = green_checkout.green_root() / "work" / "exec-green-1"
    green.mkdir(parents=True)
    if code_from_it:
        monkeypatch.setattr(guard, "checkout_root", lambda: green)
    else:
        monkeypatch.chdir(green)
    return green


@pytest.mark.parametrize("how", ["run inside a green", "a green's own copy of the code"])
def test_a_server_started_from_a_green_stops_nothing_and_takes_a_free_port(
    fake_os: FakeOS, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, how: str
) -> None:
    host_server = fake_os.spawn()
    fake_os.server(host_server, _venv_python(ROOT), listening_on=PORT)
    _green(monkeypatch, code_from_it=how != "run inside a green")

    port = app_lifecycle._check_single_instance(_config(tmp_path / "green-memory"), "127.0.0.1", PORT)

    assert fake_os.stopped() == []
    assert fake_os.running(host_server)
    assert port not in (PORT, 8899) and port > 0
    assert f"http://127.0.0.1:{port}/" in capsys.readouterr().out
    lock = json.loads((tmp_path / "green-memory" / ".thomas" / "serve.lock").read_text(encoding="utf-8"))
    assert lock["port"] == port


def test_a_green_sharing_the_hosts_memory_stops_nothing(
    fake_os: FakeOS, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The likeliest shape of 2026-09-24: a builder's server in a green, pointed at
    # the live server's memory folder, finds that server's lock.
    host_server = fake_os.spawn()
    lock = _lock(tmp_path / "memory", pid=host_server, host="127.0.0.1", port=PORT, root=str(ROOT))
    _green(monkeypatch, code_from_it=True)

    _refused(tmp_path / "memory")

    assert fake_os.stopped() == []
    assert fake_os.running(host_server)
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == host_server


def test_a_server_removes_only_its_own_lock_when_it_stops(tmp_path: Path) -> None:
    theirs = _lock(tmp_path / "memory", pid=os.getpid() + 1, port=PORT, root=str(ROOT))
    app_lifecycle._release_lock(_config(tmp_path / "memory"))
    assert theirs.exists(), "a stopping server deleted the lock of the server that replaced it"

    ours = _lock(tmp_path / "memory", pid=os.getpid(), port=PORT, root=str(ROOT))
    app_lifecycle._release_lock(_config(tmp_path / "memory"))
    assert not ours.exists()
