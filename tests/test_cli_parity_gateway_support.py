from __future__ import annotations

import sys
from pathlib import Path

import thomas.cli.parity_gateway_support as mod


def test_gateway_spawn_uses_supported_serve_flags(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyProc:
        pid = 43210

    def _fake_popen(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = list(cmd)
        captured["kwargs"] = dict(kwargs)
        return _DummyProc()

    monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)

    log_path = tmp_path / "gateway.log"
    proc = mod.gateway_spawn(config_path="", host="127.0.0.1", port=8899, log_path=log_path)

    assert int(proc.pid) == 43210
    assert log_path.exists()
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:4] == [sys.executable, "-m", "thomas.cli.main", "serve"]
    assert "--host" in cmd
    assert "--port" in cmd
    assert "--strict-port" not in cmd
