from __future__ import annotations

import argparse
import json

import pytest

from thomas.browser.p003_browser_action_click import (
    ClickConfigError,
    ClickExternalError,
    ClickInputError,
    ClickRequest,
    ClickTarget,
    click,
    click_json,
    parse_click_request,
    run,
)


class DummyBrowser:
    def __init__(self):
        self.clicked = []

    def click_node(self, node_id: int) -> None:
        self.clicked.append(("node_id", node_id))

    def click(self, selector: str) -> None:
        self.clicked.append(("selector", selector))


def test_click_by_node_id_success():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(node_id=7), timeout_ms=1000)

    res = click(req, browser=browser)

    assert res.ok is True
    assert res.clicked is True
    assert res.used == "node_id"
    assert browser.clicked == [("node_id", 7)]


def test_click_by_selector_success():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(selector="button.submit"), timeout_ms=1000)

    res = click(req, browser=browser)

    assert res.ok is True
    assert res.clicked is True
    assert res.used == "selector"
    assert browser.clicked == [("selector", "button.submit")]


def test_click_invalid_input_neither_target_provided():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(), timeout_ms=1000)

    with pytest.raises(ClickInputError) as ei:
        click(req, browser=browser)

    assert "Exactly one" in str(ei.value)


def test_click_invalid_input_both_targets_provided():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(node_id=1, selector="#x"), timeout_ms=1000)

    with pytest.raises(ClickInputError):
        click(req, browser=browser)


def test_click_missing_config_when_no_browser_can_be_resolved(monkeypatch):
    # Force the resolver to fail deterministically.
    from thomas.browser import p003_browser_action_click as mod

    monkeypatch.setattr(mod, "_resolve_browser_client", lambda: (_ for _ in ()).throw(ClickConfigError("nope")))

    req = ClickRequest(target=ClickTarget(node_id=1), timeout_ms=1000)
    with pytest.raises(ClickConfigError) as ei:
        click(req, browser=None)

    assert str(ei.value) == "nope"


def test_click_external_failure_is_wrapped():
    class ExplodingBrowser:
        def click_node(self, node_id: int) -> None:
            raise RuntimeError("boom")

    req = ClickRequest(target=ClickTarget(node_id=2), timeout_ms=1000)

    with pytest.raises(ClickExternalError) as ei:
        click(req, browser=ExplodingBrowser())

    msg = str(ei.value)
    assert "RuntimeError" in msg


def test_click_json_success_payload_is_machine_readable():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(node_id=3), timeout_ms=1000)

    payload = json.loads(click_json(req, browser=browser))

    assert payload["ok"] is True
    assert payload["clicked"] is True
    assert payload["used"] == "node_id"


def test_click_json_failure_payload_is_machine_readable():
    browser = DummyBrowser()
    req = ClickRequest(target=ClickTarget(), timeout_ms=1000)

    payload = json.loads(click_json(req, browser=browser))

    assert payload["ok"] is False
    assert payload["clicked"] is False
    assert payload["error"]["kind"] == "invalid_input"


def test_parse_click_request_from_dict():
    req = parse_click_request({"target": {"node_id": 9}, "timeout_ms": 1})
    assert isinstance(req, ClickRequest)
    assert req.target.node_id == 9
    assert req.timeout_ms == 1


def test_run_returns_error_dict_on_bad_payload():
    payload = run({"timeout_ms": 1})  # missing target
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "invalid_input"


def test_cli_runner_json_success(monkeypatch, capsys):
    # Import CLI module and monkeypatch browser resolver used by click().
    from thomas.browser import p003_browser_action_click as action
    from thomas.cli.commands.browser import p003_browser_action_click as cli

    browser = DummyBrowser()
    monkeypatch.setattr(action, "_resolve_browser_client", lambda: browser)

    args = argparse.Namespace(target=None, node_id=5, selector=None, timeout_ms=1000, json_output=True)
    code = cli._run_from_args(args)

    out = capsys.readouterr().out.strip()
    data = json.loads(out)

    assert code == cli.EXIT_OK
    assert data["ok"] is True
    assert data["used"] == "node_id"
    assert browser.clicked == [("node_id", 5)]


def test_cli_runner_exit_code_invalid_input(capsys):
    from thomas.cli.commands.browser import p003_browser_action_click as cli

    args = argparse.Namespace(target=None, node_id=None, selector=None, timeout_ms=1000, json_output=True)
    code = cli._run_from_args(args)

    out = capsys.readouterr().out.strip()
    data = json.loads(out)

    assert code == cli.EXIT_INPUT
    assert data["ok"] is False
    assert data["error"]["kind"] == "invalid_input"
