import json

import pytest
from typer.testing import CliRunner

from thomas.browser.p002_browser_action_navigate_and_open import (
    BrowserOperationFailed,
    InvalidNavigateAndOpenInput,
    NavigateAndOpenRequest,
    format_error_as_json,
    format_result_as_json,
    run_p002_navigate_and_open,
)


class FakeBrowser:
    def __init__(self):
        self.calls = []

    def navigate(self, url: str, **kwargs):
        self.calls.append(("navigate", url, kwargs))
        return {"tab_id": "t1", "url": url}

    def open(self, url: str, **kwargs):
        self.calls.append(("open", url, kwargs))
        return {"tab_id": "t2", "url": url}


class FakeAsyncBrowser:
    def __init__(self):
        self.calls = []

    async def open(self, url: str, **kwargs):
        self.calls.append(("open", url, kwargs))
        return {"tab_id": "t_async", "url": url}


def test_from_mapping_infers_open_from_flag():
    req = NavigateAndOpenRequest.from_mapping({"url": "https://example.com", "open": True})
    assert req.action == "open"


def test_invalid_url_rejected():
    with pytest.raises(InvalidNavigateAndOpenInput):
        run_p002_navigate_and_open(
            NavigateAndOpenRequest(url="example.com", action="navigate"),
            browser=FakeBrowser(),
        )


def test_navigate_calls_browser_method():
    browser = FakeBrowser()
    result = run_p002_navigate_and_open(
        NavigateAndOpenRequest(url="https://example.com", action="navigate"),
        browser=browser,
    )
    assert result.ok is True
    assert result.action == "navigate"
    assert browser.calls[0][0] == "navigate"
    assert result.tab_id == "t1"


def test_open_calls_browser_method():
    browser = FakeBrowser()
    result = run_p002_navigate_and_open(
        NavigateAndOpenRequest(url="https://example.com", action="open"),
        browser=browser,
    )
    assert result.ok is True
    assert result.action == "open"
    assert browser.calls[0][0] == "open"
    assert result.tab_id == "t2"


def test_async_browser_supported_in_sync_entrypoint():
    browser = FakeAsyncBrowser()
    result = run_p002_navigate_and_open(
        NavigateAndOpenRequest(url="https://example.com", action="open"),
        browser=browser,
    )
    assert result.ok is True
    assert result.tab_id == "t_async"


def test_json_output_does_not_crash_on_non_serializable_raw():
    class WeirdRaw:
        pass

    class WeirdBrowser:
        def navigate(self, url: str):
            return WeirdRaw()

    result = run_p002_navigate_and_open(
        NavigateAndOpenRequest(url="https://example.com", action="navigate"),
        browser=WeirdBrowser(),
    )

    payload = json.loads(format_result_as_json(result))
    assert payload["ok"] is True
    assert payload["raw"]["type"] == "WeirdRaw"


def test_external_failure_wrapped_deterministically():
    class BoomBrowser:
        def navigate(self, url: str):
            raise RuntimeError("boom")

    with pytest.raises(BrowserOperationFailed) as excinfo:
        run_p002_navigate_and_open(
            NavigateAndOpenRequest(url="https://example.com", action="navigate"),
            browser=BoomBrowser(),
        )

    err_json = format_error_as_json(excinfo.value)
    payload = json.loads(err_json)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "browser.navigate_open.external_failure"


def test_cli_navigate_json_success(monkeypatch):
    # Patch browser resolution so CLI does not depend on external config.
    import thomas.browser.p002_browser_action_navigate_and_open as core

    monkeypatch.setattr(core, "_resolve_browser_tool", lambda: FakeBrowser())

    from thomas.cli.commands.browser import p002_browser_action_navigate_and_open as cli_mod

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["navigate", "https://example.com", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["action"] == "navigate"
    assert payload["url"] == "https://example.com"


def test_cli_invalid_url_json_error_exit_code(monkeypatch):
    # Even though URL validation fails before browser resolution, patch anyway
    # to keep the test robust to refactors.
    import thomas.browser.p002_browser_action_navigate_and_open as core

    monkeypatch.setattr(core, "_resolve_browser_tool", lambda: FakeBrowser())

    from thomas.cli.commands.browser import p002_browser_action_navigate_and_open as cli_mod

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["navigate", "example.com", "--json"])
    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "browser.navigate_open.invalid_input"
