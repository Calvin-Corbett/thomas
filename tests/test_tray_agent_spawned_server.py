"""The server the tray agent spawns gets the idle model engines switched off.

Popen is always faked; nothing here starts a real server.
"""

from __future__ import annotations

import pytest

from thomas.tray_agent import agent as tray


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point every tray state/log path at tmp_path so no test touches ~/.thomas."""
    monkeypatch.setattr(tray, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(tray, "_TRAY_STATE_FILE", tmp_path / "tray_state.json")
    monkeypatch.setattr(tray, "_LOG_FILE", tmp_path / "tray_agent.log")
    monkeypatch.setattr(tray, "_SERVER_LOG_FILE", tmp_path / "server.log")
    return tmp_path


class _FakeProcess:
    pid = 4242

    def poll(self):
        return None


def _spawn_env(monkeypatch, port: int) -> dict[str, str]:
    """Start a ServerProcess with Popen faked and return the env the child got."""
    seen: dict[str, str] = {}

    def fake_popen(cmd, **kwargs):
        seen.update(kwargs["env"])
        return _FakeProcess()

    monkeypatch.setattr(tray.subprocess, "Popen", fake_popen)
    server = tray.ServerProcess(port=port)
    answers = iter([False, True])  # free before the spawn, listening after it
    monkeypatch.setattr(server, "_port_is_live", lambda timeout=0.35: next(answers))
    assert server.start() is True
    return seen


def test_the_server_the_tray_starts_has_the_idle_engines_off(state_dir, monkeypatch) -> None:
    for name in tray._QUIET_ENGINE_ENV:
        monkeypatch.delenv(name, raising=False)

    env = _spawn_env(monkeypatch, 22044)

    assert len(tray._QUIET_ENGINE_ENV) == 6
    for name in tray._QUIET_ENGINE_ENV:
        assert env[name] == "0", name


def test_tray_child_is_marked_for_landed_code_reload_even_if_parent_is_not(state_dir, monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_TRAY_SERVER_PORT", raising=False)
    env = _spawn_env(monkeypatch, 22046)
    assert env["THOMAS_TRAY_SERVER_PORT"] == "22046"


def test_an_engine_you_exported_stays_on(state_dir, monkeypatch) -> None:
    for name in tray._QUIET_ENGINE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("THOMAS_CODE_ISSUE_ENGINE_ENABLED", "1")

    env = _spawn_env(monkeypatch, 22045)

    assert env["THOMAS_CODE_ISSUE_ENGINE_ENABLED"] == "1"
    assert env["THOMAS_SELF_UPGRADE_ENGINE_ENABLED"] == "0"


def test_the_tray_list_matches_the_direct_launchers_list() -> None:
    """run-ui.ps1 names the same six variables; the two lists must not drift."""
    launcher = (tray._get_repo_root() / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")
    start = launcher.index("foreach ($quietVar in @(")
    block = launcher[start : launcher.index("{ Set-Item", start)]

    assert all(f"'{name}'" in block for name in tray._QUIET_ENGINE_ENV)
    assert block.count("'THOMAS_") == len(tray._QUIET_ENGINE_ENV)
