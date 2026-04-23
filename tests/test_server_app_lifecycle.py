from __future__ import annotations

import json
import signal
from types import SimpleNamespace

from thomas.server import app_lifecycle as mod


def _cfg(tmp_path):
    return SimpleNamespace(memory=SimpleNamespace(root_path=str(tmp_path)))


def test_check_single_instance_stops_matching_listener_on_requested_port(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    kill_calls: list[tuple[int, int]] = []
    terminated: set[int] = set()

    def fake_run(args, **kwargs):
        if args[:4] == ["netstat", "-ano", "-p", "tcp"]:
            return SimpleNamespace(
                returncode=0,
                stdout="  TCP    127.0.0.1:8899     0.0.0.0:0      LISTENING       4321\n",
            )
        if args[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"CommandLine": "python.exe -m thomas.server --host 127.0.0.1 --port 8899"}),
            )
        raise AssertionError(f"Unexpected subprocess call: {args}")

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0:
            if pid in terminated:
                raise OSError("already gone")
            return
        if sig == signal.SIGTERM:
            terminated.add(pid)
            return
        raise AssertionError(f"Unexpected signal: {sig}")

    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod.os, "getpid", lambda: 9999)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.os, "kill", fake_kill)
    monkeypatch.setattr(mod._time, "sleep", lambda _seconds: None)

    mod._check_single_instance(cfg, "127.0.0.1", 8899)

    assert (4321, signal.SIGTERM) in kill_calls
    lock_data = json.loads((tmp_path / ".thomas" / "serve.lock").read_text(encoding="utf-8"))
    assert lock_data["pid"] == 9999
    assert lock_data["port"] == 8899


def test_check_single_instance_ignores_non_thomas_listener(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    kill_calls: list[tuple[int, int]] = []

    def fake_run(args, **kwargs):
        if args[:4] == ["netstat", "-ano", "-p", "tcp"]:
            return SimpleNamespace(
                returncode=0,
                stdout="  TCP    127.0.0.1:8899     0.0.0.0:0      LISTENING       8765\n",
            )
        if args[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"CommandLine": "python.exe -m http.server 8899"}),
            )
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod.os, "getpid", lambda: 9999)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr(mod._time, "sleep", lambda _seconds: None)

    mod._check_single_instance(cfg, "127.0.0.1", 8899)

    assert kill_calls == []
    lock_data = json.loads((tmp_path / ".thomas" / "serve.lock").read_text(encoding="utf-8"))
    assert lock_data["pid"] == 9999
