"""The port-owner lookup gives up when Windows does not answer, and reads netstat in any language.

Boot Doctor asks netstat who holds the port before it does anything else, so a stuck netstat or PowerShell call used
to stop the rescue before it wrote a report. No answer now means "owner unknown", which names no Thomas process and so
stops nothing. netstat also translates the state column (ABHOEREN, ECOUTE, ...), so the listener is told by its
remote end, and a console that cannot decode a byte must not raise.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

import thomas.core.boot_process as boot_process

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="the owner lookup and its fallback are Windows-only")
PORT = 22121
# 0x99 is not ASCII: the decoding below stands in for a code page that cannot read a translated state name.
NETSTAT = (
    b"  Proto  Lokale Adresse    Remoteadresse      Status       PID\r\n"
    b"  TCP    0.0.0.0:22121     0.0.0.0:0          ABH\x99REN     111\r\n"
    b"  TCP    127.0.0.1:22121   127.0.0.1:50000    HERGESTELLT  222\r\n"
    b"  TCP    [::]:22121        [::]:0             ABH\x99REN     333\r\n"
    b"  TCP    0.0.0.0:221210    0.0.0.0:0          ABH\x99REN     444\r\n"
    b"  TCP    0.0.0.0:22122     0.0.0.0:0          ABH\x99REN     555\r\n"
)
ENGLISH = (
    b"  Proto  Local Address      Foreign Address    State        PID\r\n"
    b"  TCP    127.0.0.1:22121    0.0.0.0:0          LISTENING    111\r\n"
    b"  TCP    127.0.0.1:22121    127.0.0.1:50000    ESTABLISHED  222\r\n"
)


class _Console:
    """Stands in for subprocess.run: it needs a timeout to be allowed to answer, and decodes like a strict console."""

    def __init__(self, raw: bytes = b"", error: BaseException | None = None) -> None:
        self.raw, self.error, self.calls = raw, error, 0

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        if kwargs.get("timeout") is None:
            raise AssertionError(f"{cmd[0]} was started with no timeout, so a stuck machine would wait for it forever")
        if self.error is not None:
            raise self.error
        text = self.raw.decode("ascii", errors=kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")


def _fake(monkeypatch: pytest.MonkeyPatch, console: _Console) -> _Console:
    monkeypatch.setattr(boot_process.subprocess, "run", console)
    monkeypatch.setitem(sys.modules, "psutil", None)  # _pid_cmdline then asks PowerShell
    return console


def test_a_translated_netstat_still_names_every_listener_of_the_port(monkeypatch) -> None:
    _fake(monkeypatch, _Console(NETSTAT))

    # 111 and 333 listen on the port; 222 is a connection to it, 444 and 555 are other ports.
    assert boot_process._listening_pids_windows(PORT) == [111, 333]


def test_an_english_netstat_still_reads_the_same_way(monkeypatch) -> None:
    _fake(monkeypatch, _Console(ENGLISH))

    assert boot_process._listening_pids_windows(PORT) == [111]


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("netstat", 10), FileNotFoundError("netstat")])
def test_a_netstat_that_does_not_answer_names_no_owner(monkeypatch, error) -> None:
    console = _fake(monkeypatch, _Console(error=error))

    assert boot_process._listening_pids_windows(PORT) == []
    assert console.calls == 1


@WINDOWS_ONLY
@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("powershell", 10), FileNotFoundError("powershell")])
def test_a_command_line_lookup_that_does_not_answer_is_empty(monkeypatch, error) -> None:
    console = _fake(monkeypatch, _Console(error=error))

    assert boot_process._pid_cmdline(4242) == ""
    assert console.calls == 1


@WINDOWS_ONLY
def test_a_command_line_lookup_that_answers_is_returned(monkeypatch) -> None:
    _fake(monkeypatch, _Console(b"C:\\x\\python.exe -m thomas.server\r\n"))

    assert boot_process._pid_cmdline(4242) == r"C:\x\python.exe -m thomas.server"


@WINDOWS_ONLY
def test_with_no_answer_from_windows_nobody_is_called_thomas_and_nothing_is_stopped(monkeypatch) -> None:
    _fake(monkeypatch, _Console(error=subprocess.TimeoutExpired("netstat", 10)))

    assert boot_process.thomas_owns_port(PORT) is False
    assert boot_process.port_owner_note(PORT) == "the owning program could not be identified"
