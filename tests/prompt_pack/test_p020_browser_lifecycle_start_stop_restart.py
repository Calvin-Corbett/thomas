import json

import pytest
from typer.testing import CliRunner

from thomas.browser.p020_browser_lifecycle_start_stop_restart import (
    BrowserLifecycleError,
    BrowserLifecycleRequest,
    BrowserLifecycleResult,
    get_default_browser_controller,
    run_browser_lifecycle,
)
from thomas.cli.commands.browser import p020_browser_lifecycle_start_stop_restart as cli_mod


class FakeController:
    def __init__(self):
        self.state = "stopped"
        self.calls = []

    def start(self, *, timeout_seconds=None):
        self.calls.append(("start", timeout_seconds))
        self.state = "running"
        return {"started": True}

    def stop(self, *, timeout_seconds=None):
        self.calls.append(("stop", timeout_seconds))
        self.state = "stopped"
        return {"stopped": True}

    def restart(self, *, timeout_seconds=None):
        self.calls.append(("restart", timeout_seconds))
        self.state = "running"
        return {"restarted": True}


def test_run_start_success():
    ctl = FakeController()
    result = run_browser_lifecycle(BrowserLifecycleRequest(action="start"), controller=ctl)
    assert result.ok is True
    assert result.state == "running"
    assert result.details == {"started": True}
    assert ctl.calls == [("start", None)]


def test_run_stop_success():
    ctl = FakeController()
    ctl.state = "running"
    result = run_browser_lifecycle(BrowserLifecycleRequest(action="stop"), controller=ctl)
    assert result.ok is True
    assert result.state == "stopped"
    assert result.details == {"stopped": True}
    assert ctl.calls == [("stop", None)]


def test_run_restart_success():
    ctl = FakeController()
    result = run_browser_lifecycle(BrowserLifecycleRequest(action="restart"), controller=ctl)
    assert result.ok is True
    assert result.state == "running"
    assert result.details == {"restarted": True}
    assert ctl.calls == [("restart", None)]


def test_restart_falls_back_to_stop_then_start_when_backend_has_no_restart():
    class NoRestart:
        def __init__(self):
            self.calls = []

        def start(self, *, timeout_seconds=None):
            self.calls.append(("start", timeout_seconds))
            return {"started": True}

        def stop(self, *, timeout_seconds=None):
            self.calls.append(("stop", timeout_seconds))
            return {"stopped": True}

    ctl = NoRestart()
    result = run_browser_lifecycle(BrowserLifecycleRequest(action="restart"), controller=ctl)
    assert result.ok is True
    assert result.state == "running"
    assert ctl.calls == [("stop", None), ("start", None)]


def test_invalid_action_is_deterministic_error():
    ctl = FakeController()
    with pytest.raises(BrowserLifecycleError) as excinfo:
        run_browser_lifecycle(BrowserLifecycleRequest(action="nope"), controller=ctl)

    err = excinfo.value
    assert err.code == "INVALID_INPUT"
    assert "start" in err.message and "stop" in err.message and "restart" in err.message


def test_invalid_timeout_is_deterministic_error():
    ctl = FakeController()
    with pytest.raises(BrowserLifecycleError) as excinfo:
        run_browser_lifecycle(BrowserLifecycleRequest(action="start", timeout_seconds=-1), controller=ctl)

    err = excinfo.value
    assert err.code == "INVALID_INPUT"
    assert "timeout" in err.message


def test_external_failure_is_wrapped_deterministically():
    class BoomController(FakeController):
        def start(self, *, timeout_seconds=None):
            raise RuntimeError("kaboom")

    ctl = BoomController()
    with pytest.raises(BrowserLifecycleError) as excinfo:
        run_browser_lifecycle(BrowserLifecycleRequest(action="start"), controller=ctl)

    err = excinfo.value
    assert err.code == "EXTERNAL_FAILURE"
    assert err.message == "Browser start failed."
    assert err.details.get("exception_type") == "RuntimeError"


def test_missing_config_is_deterministic(monkeypatch):
    import thomas.browser.p020_browser_lifecycle_start_stop_restart as mod

    monkeypatch.setattr(mod, "_try_import", lambda name: None)

    with pytest.raises(BrowserLifecycleError) as excinfo:
        get_default_browser_controller()

    err = excinfo.value
    assert err.code == "CONFIG_MISSING"


def test_cli_json_success(monkeypatch):
    runner = CliRunner()

    def fake_run(req, *, controller=None):
        assert req.action == "start"
        assert req.timeout_seconds is None
        return BrowserLifecycleResult(action="start", ok=True, state="running", details={"pid": 123})

    monkeypatch.setattr(cli_mod, "run_browser_lifecycle", fake_run)

    res = runner.invoke(cli_mod.app, ["start", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["details"]["pid"] == 123


def test_cli_json_timeout_is_passed(monkeypatch):
    runner = CliRunner()

    def fake_run(req, *, controller=None):
        assert req.action == "start"
        assert req.timeout_seconds == 2.5
        return BrowserLifecycleResult(action="start", ok=True, state="running", details={})

    monkeypatch.setattr(cli_mod, "run_browser_lifecycle", fake_run)

    res = runner.invoke(cli_mod.app, ["start", "--json", "--timeout", "2.5"])
    assert res.exit_code == 0


def test_cli_json_failure(monkeypatch):
    runner = CliRunner()

    def fake_run(req, *, controller=None):
        raise BrowserLifecycleError(code="CONFIG_MISSING", message="no config")

    monkeypatch.setattr(cli_mod, "run_browser_lifecycle", fake_run)

    res = runner.invoke(cli_mod.app, ["start", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "CONFIG_MISSING"
    assert data["error"]["message"] == "no config"
