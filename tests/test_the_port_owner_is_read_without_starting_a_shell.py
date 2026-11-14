"""Who is listening on the server's port is read from the OS socket table, not by starting a shell.

Every start and every restart asks this before it does anything else. Asking PowerShell (``Get-NetTCPConnection``)
started a whole interpreter and took 2.2 s of a 9 s start on 2026-11-08; the socket table answers in milliseconds. The
shell stays as the fallback for a machine whose socket table cannot be read.
"""

from __future__ import annotations

import os
import socket
import subprocess
from types import SimpleNamespace

import psutil
import pytest

from thomas.server import app_lifecycle


@pytest.fixture
def listening_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def _no_shell(*_args, **_kwargs):
    raise AssertionError("a shell was started to ask who owns a port")


def test_the_owner_of_a_listening_port_is_found_without_a_shell(listening_port, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _no_shell)
    assert app_lifecycle._pids_listening_on_port(listening_port) == {os.getpid()}


def test_a_port_nobody_listens_on_has_no_owner_and_still_no_shell(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]  # closed again on leaving the block: nothing listens there
    monkeypatch.setattr(subprocess, "run", _no_shell)
    assert app_lifecycle._pids_listening_on_port(free) == set()


def test_an_unreadable_socket_table_falls_back_to_asking_the_shell(monkeypatch):
    def refused(*_args, **_kwargs):
        raise psutil.AccessDenied()

    asked = []

    def shell(command, **_kwargs):
        asked.append(command)
        return SimpleNamespace(returncode=0, stdout="4242\n")

    monkeypatch.setattr(psutil, "net_connections", refused)
    monkeypatch.setattr(subprocess, "run", shell)
    assert app_lifecycle._pids_listening_on_port(8899) == {4242}
    assert len(asked) == 1
