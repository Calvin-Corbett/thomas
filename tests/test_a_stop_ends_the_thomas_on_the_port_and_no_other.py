"""``-Stop`` (and so the shortcut's ``/stop``) has to end the server that has no window, and only that one.

With the console window gone, the launcher's own stop function is the only off switch
the shortcut has. Its decisions are tested next door against stand-ins; this runs the
function itself against two real processes that look like a Thomas server to it (a
command line of ``-m thomas.server --port N``, a socket listening on N), one on the
port it is given and one on another port. The processes are started here, on ports the
operating system hands out, and the test ends both.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_UI, closed_port, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

_SERVER = """\
import socket, sys
port = int(sys.argv[sys.argv.index("--port") + 1])
listener = socket.socket()
listener.bind(("127.0.0.1", port))
listener.listen(5)
# Gives up after two minutes, so a test that dies early leaves nothing listening.
listener.settimeout(120)
while True:
    # Accept and hang up: a listener that never accepts fills its queue, and then a
    # connection times out as it would to a server that is gone.
    listener.accept()[0].close()
"""

# A stand-in tray agent: ``-m thomas.tray_agent --port N``, optionally running the server it manages.
_TRAY = """\
import subprocess, sys, time
args = sys.argv[1:]
if "--child" in args:
    subprocess.Popen([sys.executable, "-m", "thomas.server", "--host", "127.0.0.1", "--port", args[args.index("--child") + 1]])
time.sleep(120)
"""
# A parent that is not a tray agent, running a server.
_PARENT = """\
import subprocess, sys, time
subprocess.Popen([sys.executable, "-m", "thomas.server", "--host", "127.0.0.1", "--port", sys.argv[1]])
time.sleep(120)
"""


def _fake_thomas(root: Path) -> None:
    """A ``thomas.server`` that only listens, so nothing of the real Thomas is started."""
    package = root / "thomas" / "server"
    package.mkdir(parents=True)
    (root / "thomas" / "__init__.py").write_text("", encoding="ascii")
    (package / "__init__.py").write_text("", encoding="ascii")
    (package / "__main__.py").write_text(_SERVER, encoding="ascii")
    (root / "thomas" / "tray_agent.py").write_text(_TRAY, encoding="ascii")
    (root / "parent.py").write_text(_PARENT, encoding="ascii")


def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _wait(port: int, *, listening: bool, seconds: float = 30.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _accepts(port) is listening:
            return True
        time.sleep(0.3)
    return False


def _start(root: Path, port: int) -> subprocess.Popen[bytes]:
    env = {**os.environ, "PYTHONPATH": str(root)}
    return subprocess.Popen(
        [sys.executable, "-m", "thomas.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=root,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_stop_ends_the_thomas_listening_on_the_port_and_leaves_another_one_running(tmp_path: Path) -> None:
    _fake_thomas(tmp_path)
    target, bystander = closed_port(), closed_port()
    started: list[subprocess.Popen[bytes]] = []
    try:
        for port in (target, bystander):
            started.append(_start(tmp_path, port))
        assert _wait(target, listening=True) and _wait(bystander, listening=True), "the stand-in servers did not start"

        out = run_functions(
            RUN_UI,
            ["Test-PortListening", "Stop-ThomasServerOnPort"],
            f"$Root = {ps_path(tmp_path)}\n'stopped: ' + (Stop-ThomasServerOnPort {target})\n",
            tmp_path,
        )

        assert "stopped: True" in out and f"Port {target} is in use by an existing Thomas server" in out, out
        assert _wait(target, listening=False), "the server on the port was not stopped"
        assert _accepts(bystander), "a Thomas on another port was stopped too"
    finally:
        for proc in started:
            proc.terminate()
        for proc in started:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_stop_with_nothing_on_the_port_stops_nothing(tmp_path: Path) -> None:
    out = run_functions(
        RUN_UI,
        ["Test-PortListening", "Stop-ThomasServerOnPort"],
        f"'stopped: ' + (Stop-ThomasServerOnPort {closed_port()})\n",
        tmp_path,
    )

    assert "stopped: False" in out, out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")
def test_a_listener_that_is_not_a_thomas_server_is_left_alone(tmp_path: Path) -> None:
    """Something else on the port is not ours to end, whatever it is doing."""
    other = tmp_path / "other.py"
    other.write_text(_SERVER, encoding="ascii")
    port = closed_port()
    proc = subprocess.Popen(
        [sys.executable, str(other), "--port", str(port)],
        cwd=tmp_path,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert _wait(port, listening=True), "the stand-in server did not start"
        out = run_functions(
            RUN_UI,
            ["Test-PortListening", "Stop-ThomasServerOnPort"],
            f"'stopped: ' + (Stop-ThomasServerOnPort {port})\n",
            tmp_path,
        )

        assert "stopped: False" in out, out
        assert _accepts(port), "a listener that is not Thomas was stopped"
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def _spawn(root: Path, *argv: str) -> subprocess.Popen[bytes]:
    """A process under the base interpreter: no virtualenv launcher between a parent and its child."""
    env = {**os.environ, "PYTHONPATH": str(root)}
    return subprocess.Popen(
        [getattr(sys, "_base_executable", sys.executable), *argv],
        cwd=root,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _end_all(procs: list[subprocess.Popen[bytes]]) -> None:
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def _stop(tmp_path: Path, port: int) -> str:
    return run_functions(
        RUN_UI,
        ["Test-PortListening", "Stop-ThomasServerOnPort"],
        f"'stopped: ' + (Stop-ThomasServerOnPort {port})\n",
        tmp_path,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")
def test_a_tray_agent_on_the_port_is_stopped_and_one_on_another_port_is_not(tmp_path: Path) -> None:
    """A tray agent respawns the server it manages, so the one for this port goes first; another port's is not ours."""
    _fake_thomas(tmp_path)
    target, other = closed_port(), closed_port()
    mine = _spawn(tmp_path, "-m", "thomas.tray_agent", "--port", str(target))
    bystander = _spawn(tmp_path, "-m", "thomas.tray_agent", "--port", str(other))
    try:
        out = _stop(tmp_path, target)

        assert "stopped: True" in out and f"Found Thomas tray agent on port {target}" in out, out
        assert mine.wait(timeout=20) is not None, "the tray agent for the port was not stopped"
        assert bystander.poll() is None, "a tray agent on another port was stopped too"
    finally:
        _end_all([mine, bystander])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")
def test_the_tray_agent_that_runs_the_listener_is_stopped_with_it(tmp_path: Path) -> None:
    """Ending the server alone would have its tray agent start another one at once."""
    _fake_thomas(tmp_path)
    port = closed_port()
    # Not bound to the port by its own arguments ("--port 1"), so only the listener's parent link reaches it.
    tray = _spawn(tmp_path, "-m", "thomas.tray_agent", "--port", "1", "--child", str(port))
    try:
        assert _wait(port, listening=True), "the stand-in server did not start"
        out = _stop(tmp_path, port)

        assert "stopped: True" in out and "Found tray parent for duplicate server" in out, out
        assert _wait(port, listening=False), "the server was not stopped"
        assert tray.wait(timeout=20) is not None, "the tray agent that manages it was left to start another"
    finally:
        _end_all([tray])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")
def test_a_parent_that_is_not_a_tray_agent_is_left_running(tmp_path: Path) -> None:
    """The parent of the listener is stopped only when it is a tray agent; it may be anything else."""
    _fake_thomas(tmp_path)
    port = closed_port()
    parent = _spawn(tmp_path, "parent.py", str(port))
    try:
        assert _wait(port, listening=True), "the stand-in server did not start"
        out = _stop(tmp_path, port)

        assert "stopped: True" in out and "Found tray parent" not in out, out
        assert _wait(port, listening=False), "the server was not stopped"
        assert parent.poll() is None, "a parent that is not a tray agent was stopped"
    finally:
        _end_all([parent])
