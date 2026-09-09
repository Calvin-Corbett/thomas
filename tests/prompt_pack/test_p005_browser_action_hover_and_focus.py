import json

import pytest

from thomas.browser.p005_browser_action_hover_and_focus import (
    HoverFocusError,
    HoverFocusRequest,
    hover_or_focus_sync,
)
from thomas.cli.commands.browser.p005_browser_action_hover_and_focus import (
    run_hover_or_focus,
)


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def hover(self, selector):
        self.calls.append(("hover", selector))

    def focus(self, selector):
        self.calls.append(("focus", selector))


class FakeBrowserNodeKw:
    def __init__(self):
        self.calls = []

    def hover(self, *, node_id):
        self.calls.append(("hover", node_id))


class ExplodingBrowser:
    def hover(self, selector):
        raise RuntimeError("boom")


def test_hover_success_calls_backend():
    browser = FakeBrowser()
    req = HoverFocusRequest(action="hover", selector="#btn")
    res = hover_or_focus_sync(browser, req)
    assert res.action == "hover"
    assert res.target == {"selector": "#btn"}
    assert browser.calls == [("hover", "#btn")]


def test_focus_success_calls_backend():
    browser = FakeBrowser()
    req = HoverFocusRequest(action="focus", selector="input[name=q]")
    res = hover_or_focus_sync(browser, req)
    assert res.action == "focus"
    assert res.target == {"selector": "input[name=q]"}
    assert browser.calls == [("focus", "input[name=q]")]


def test_node_id_keyword_variant_is_supported():
    browser = FakeBrowserNodeKw()
    req = HoverFocusRequest(action="hover", node_id=123)
    res = hover_or_focus_sync(browser, req)
    assert res.action == "hover"
    assert res.target == {"node_id": 123}
    assert browser.calls == [("hover", 123)]


def test_invalid_input_missing_target_is_deterministic():
    browser = FakeBrowser()
    req = HoverFocusRequest(action="hover")
    with pytest.raises(HoverFocusError) as excinfo:
        hover_or_focus_sync(browser, req)

    err = excinfo.value
    assert err.code == "invalid_input"
    assert err.message == "exactly one of selector or node_id must be provided"


def test_invalid_input_timeout_validation_is_deterministic():
    browser = FakeBrowser()
    req = HoverFocusRequest(action="hover", selector="#btn", timeout_ms=0)
    with pytest.raises(HoverFocusError) as excinfo:
        hover_or_focus_sync(browser, req)

    err = excinfo.value
    assert err.code == "invalid_input"
    assert err.message == "timeout_ms must be a positive integer"


def test_missing_config_is_deterministic():
    req = HoverFocusRequest(action="hover", selector="#btn")
    with pytest.raises(HoverFocusError) as excinfo:
        hover_or_focus_sync(None, req)

    err = excinfo.value
    assert err.code == "missing_config"
    assert err.message == "no active browser session/controller was provided"


def test_external_failure_is_deterministic():
    browser = ExplodingBrowser()
    req = HoverFocusRequest(action="hover", selector="#btn")
    with pytest.raises(HoverFocusError) as excinfo:
        hover_or_focus_sync(browser, req)

    err = excinfo.value
    assert err.code == "external_failure"
    # We include the exception *class name* only.
    assert err.message == "browser hover failed (RuntimeError)"


def test_cli_helper_json_payload_success_and_failure():
    browser = FakeBrowser()

    exit_code, payload = run_hover_or_focus(
        action="hover",
        selector="#btn",
        node_id=None,
        timeout_ms=None,
        json_out=True,
        browser=browser,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "hover"

    # JSON serialization must work for automation.
    json.dumps(payload, sort_keys=True)

    # Failure path: missing target.
    exit_code2, payload2 = run_hover_or_focus(
        action="hover",
        selector=None,
        node_id=None,
        timeout_ms=None,
        json_out=True,
        browser=browser,
    )
    assert exit_code2 == 2
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "invalid_input"

    json.dumps(payload2, sort_keys=True)


def test_cli_helper_node_id_is_coerced_to_int_when_numeric_string():
    browser = FakeBrowserNodeKw()

    exit_code, payload = run_hover_or_focus(
        action="hover",
        selector=None,
        node_id="42",
        timeout_ms=None,
        json_out=True,
        browser=browser,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["target"] == {"node_id": 42}
