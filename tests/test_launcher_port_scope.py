from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _launcher_source() -> str:
    return (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")


def test_launcher_only_discovers_listeners_on_requested_port() -> None:
    source = _launcher_source()

    assert "Get-NetTCPConnection -LocalPort $P -State Listen" in source
    assert "Get-NetTCPConnection -State Listen" not in source
    assert "function Get-ThomasListeners" not in source
    assert "function Test-ThomasProcessCommand" not in source


def test_launcher_restarts_target_without_stopping_other_ports() -> None:
    source = _launcher_source()

    restart = source.index("Stop-ThomasServerOnPort $Port | Out-Null")
    choose_port = source.index("$FreePort = Find-FreePort $Port")
    assert restart < choose_port
    assert "$allListeners = @(Get-ThomasListeners)" not in source
    assert "foreach ($existingPort in $allPorts)" not in source
    assert "without\n# enumerating or stopping unrelated listeners on other ports" in source
