"""The two questions the Thomas.vbs launcher asks the machine before it starts Thomas, run for real.

Is something serving Thomas's port? Only a refused connection means no: a server too busy to
answer, or answering something odd, is still there, and a second one started over it stops it.
Is a start already under way? Only a run-ui.ps1 of this checkout that began recently counts:
run-ui.ps1 normally exits once the server is up, so an old one is a console left open.

The health probe is driven against scratch ports on 127.0.0.1, and the process check against the
real process list with a stand-in run-ui.ps1 that only sleeps. No launcher is run.
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from scripts import thomas_app

from tests.launcher_script_host_support import CSCRIPT, cscript, write_vbs

pytestmark = pytest.mark.skipif(CSCRIPT is None, reason="needs Windows Script Host")


class _Health(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        self.send_response(self.status if self.path == "/api/health" else 404)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def _serve(status: int) -> HTTPServer:
    handler = type("Handler", (_Health,), {"status": status})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stalled_port() -> socket.socket:
    """Listening, never accepting: a Thomas whose event loop is too busy to answer."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    return sock


def _nonsense_server() -> socket.socket:
    """Accepts and answers something that is not HTTP, then hangs up."""
    sock = _stalled_port()

    def answer() -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            conn.sendall(b"this is not http\r\n\r\n")
            conn.close()

    threading.Thread(target=answer, daemon=True).start()
    return sock


def test_the_health_probe_says_down_only_when_nothing_accepts_the_connection(tmp_path: Path) -> None:
    probe = write_vbs(
        tmp_path / "probe.vbs", "WScript.Echo CStr(ServerIsUp(WScript.Arguments(0)))\n" + thomas_app._SERVER_PROBE
    )

    for status in (200, 503):  # a busy or degraded server still answers: it is not restarted
        server = _serve(status)
        try:
            done = cscript(probe, f"http://127.0.0.1:{server.server_port}/")
        finally:
            server.shutdown()
            server.server_close()
        assert done.stdout.strip() == "True", f"status {status}: {done.stdout}{done.stderr}"

    # Too busy to answer in time, and answering something odd: something is there, and a
    # second server started over it would stop it. Only a refused connection is down.
    for name, make in (("stalled", _stalled_port), ("not http", _nonsense_server)):
        sock = make()
        try:
            done = cscript(probe, f"http://127.0.0.1:{sock.getsockname()[1]}/")
        finally:
            sock.close()
        assert done.stdout.strip() == "True", f"{name}: {done.stdout}{done.stderr}"

    silent = cscript(probe, f"http://127.0.0.1:{_closed_port()}/")
    assert silent.stdout.strip() == "False", silent.stdout + silent.stderr


def _stand_in(*args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - powershell running a sleep on our own scratch file
        ["powershell", "-NoProfile", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(proc: subprocess.Popen[bytes]) -> None:
    proc.kill()
    proc.wait(timeout=30)


def test_only_a_young_run_ui_of_this_checkout_counts_as_a_start_under_way(tmp_path: Path) -> None:
    """The real process list, with stand-ins that only sleep."""
    mine = tmp_path / "mine" / "scripts" / "run-ui.ps1"
    mine.parent.mkdir(parents=True)
    mine.write_text("Start-Sleep -Seconds 120\n", encoding="ascii")
    other = tmp_path / "another checkout" / "scripts" / "run-ui.ps1"
    check = write_vbs(
        tmp_path / "running.vbs",
        "WScript.Echo CStr(StartIsRunning(WScript.Arguments(0), CLng(WScript.Arguments(1))))\n"
        + thomas_app._START_GUARD,
    )

    def running(path: Path | str, seconds: int = 1800) -> str:
        return cscript(check, str(path), str(seconds)).stdout.strip()

    # A shell that only mentions the script (a pager, an editor command) is not running it.
    mention = _stand_in("-Command", f"Start-Sleep -Seconds 120 # {mine}")
    try:
        assert running(mine) == "False"
    finally:
        _stop(mention)

    standin = _stand_in("-ExecutionPolicy", "Bypass", "-File", str(mine))
    try:
        assert running(mine) == "True"
        assert running(str(mine).upper()) == "True", "paths are not case sensitive"
        assert running(other) == "False", "another checkout's run-ui is not this one"
        time.sleep(2)
        assert running(mine, 1) == "False", "a run-ui older than the window is a console left open, not a start"
        assert running(mine, 1800) == "True"
    finally:
        _stop(standin)
    assert running(mine) == "False"


def test_a_process_list_that_cannot_be_read_is_not_a_start_under_way(tmp_path: Path) -> None:
    """Unreadable means 'start as usual', never 'locked out'; a matching process is alive throughout."""
    mine = tmp_path / "scripts" / "run-ui.ps1"
    mine.parent.mkdir()
    mine.write_text("Start-Sleep -Seconds 120\n", encoding="ascii")
    working = "WScript.Echo CStr(StartIsRunning(WScript.Arguments(0), 1800))\n" + thomas_app._START_GUARD
    unreadable = working.replace("winmgmts:root\\cimv2", "winmgmts:root\\no_such_namespace")
    assert unreadable != working

    standin = _stand_in("-ExecutionPolicy", "Bypass", "-File", str(mine))
    try:
        assert cscript(write_vbs(tmp_path / "works.vbs", working), str(mine)).stdout.strip() == "True"
        broken = cscript(write_vbs(tmp_path / "broken.vbs", unreadable), str(mine))
        assert broken.stdout.strip() == "False", broken.stdout + broken.stderr
    finally:
        _stop(standin)
