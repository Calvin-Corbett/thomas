import asyncio

import pytest

from thomas.browser.p006_browser_action_scroll_and_scroll_into_view import (
    BrowserActionError,
    ScrollIntoViewRequest,
    ViewportScrollRequest,
    perform_scroll_into_view,
    perform_viewport_scroll,
)


class FakeMouse:
    def __init__(self):
        self.calls = []

    def wheel(self, dx, dy):
        self.calls.append((dx, dy))


class FakeLocator:
    def __init__(self, selector):
        self.selector = selector
        self.calls = []

    def scroll_into_view_if_needed(self, **kwargs):
        self.calls.append(kwargs)


class FakePage:
    def __init__(self, *, with_mouse=True, with_locator=True):
        self.mouse = FakeMouse() if with_mouse else None
        self._with_locator = with_locator
        self.locator_calls = []
        self.evaluate_calls = []
        self.last_locator = None

    def locator(self, selector):
        if not self._with_locator:
            raise AttributeError("locator disabled")
        self.locator_calls.append(selector)
        self.last_locator = FakeLocator(selector)
        return self.last_locator

    def evaluate(self, js, arg=None):
        self.evaluate_calls.append((js, arg))

        # Simulate JS fallback behavior based on selector.
        if isinstance(arg, str):
            if arg == ".missing":
                return {"ok": False, "found": False}
            if arg == "bad[":
                return {"ok": False, "found": False, "error": "SyntaxError: Invalid selector"}
            return {"ok": True, "found": True}

        return {"ok": True}


def test_scroll_request_validation_rejects_zero_delta():
    with pytest.raises(BrowserActionError) as exc:
        ViewportScrollRequest.from_dict({"delta_x": 0, "delta_y": 0})
    assert exc.value.code == "INVALID_INPUT"


def test_scroll_into_view_request_validation_rejects_empty_selector():
    with pytest.raises(BrowserActionError) as exc:
        ScrollIntoViewRequest.from_dict({"selector": "   "})
    assert exc.value.code == "INVALID_INPUT"


def test_perform_viewport_scroll_uses_mouse_wheel_when_available():
    page = FakePage(with_mouse=True)
    req = ViewportScrollRequest.from_dict({"delta_x": 0, "delta_y": 123})

    result = asyncio.run(perform_viewport_scroll(page, req))
    assert result.delta_y == 123
    assert page.mouse.calls == [(0, 123)]


def test_perform_viewport_scroll_falls_back_to_evaluate_when_no_mouse():
    page = FakePage(with_mouse=False)
    req = ViewportScrollRequest.from_dict({"delta_x": 10, "delta_y": -20})

    result = asyncio.run(perform_viewport_scroll(page, req))
    assert result.delta_x == 10
    assert len(page.evaluate_calls) == 1
    js, arg = page.evaluate_calls[0]
    assert "scrollBy" in js
    assert arg == [10, -20]


def test_perform_scroll_into_view_uses_locator_when_available():
    page = FakePage(with_locator=True)
    req = ScrollIntoViewRequest.from_dict({"selector": "#foo", "timeout_ms": 5000})

    result = asyncio.run(perform_scroll_into_view(page, req))
    assert result.selector == "#foo"
    assert result.found is True
    assert result.method == "locator"
    assert page.locator_calls == ["#foo"]
    assert page.last_locator is not None
    assert page.last_locator.calls == [{"timeout": 5000}]


def test_perform_scroll_into_view_falls_back_to_js_and_errors_on_not_found():
    page = FakePage(with_locator=False)
    req = ScrollIntoViewRequest.from_dict({"selector": ".missing"})

    with pytest.raises(BrowserActionError) as exc:
        asyncio.run(perform_scroll_into_view(page, req))

    assert exc.value.code == "ELEMENT_NOT_FOUND"
    assert len(page.evaluate_calls) == 1


def test_perform_scroll_into_view_falls_back_to_js_and_errors_on_invalid_css():
    page = FakePage(with_locator=False)
    req = ScrollIntoViewRequest.from_dict({"selector": "bad["})

    with pytest.raises(BrowserActionError) as exc:
        asyncio.run(perform_scroll_into_view(page, req))

    assert exc.value.code == "INVALID_INPUT"


def test_perform_scroll_into_view_rejects_non_css_selector_without_locator():
    page = FakePage(with_locator=False)
    req = ScrollIntoViewRequest.from_dict({"selector": "text=Hello"})

    with pytest.raises(BrowserActionError) as exc:
        asyncio.run(perform_scroll_into_view(page, req))

    assert exc.value.code == "UNSUPPORTED_SELECTOR"


def test_cli_json_success(monkeypatch):
    from typer.testing import CliRunner

    import thomas.cli.commands.browser.p006_browser_action_scroll_and_scroll_into_view as cli_mod

    def fake_executor(action_name, params):
        return {"action": action_name, "params": params}

    monkeypatch.setattr(cli_mod, "_resolve_browser_executor", lambda: fake_executor)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["scroll", "--y", "50", "--json"])
    assert result.exit_code == 0
    assert '"ok": true' in result.stdout
    assert '"action": "scroll"' in result.stdout


def test_cli_json_failure(monkeypatch):
    from typer.testing import CliRunner

    import thomas.cli.commands.browser.p006_browser_action_scroll_and_scroll_into_view as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "_resolve_browser_executor",
        lambda: (_ for _ in ()).throw(BrowserActionError("MISSING_CONFIG", "no browser")),
    )

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["scroll", "--y", "50", "--json"])
    assert result.exit_code == 2
    assert '"ok": false' in result.stdout
    assert '"code": "MISSING_CONFIG"' in result.stdout


def test_cli_json_validation_failure():
    from typer.testing import CliRunner

    import thomas.cli.commands.browser.p006_browser_action_scroll_and_scroll_into_view as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["scroll", "--json"])
    assert result.exit_code == 2
    assert '"ok": false' in result.stdout
    assert '"code": "INVALID_INPUT"' in result.stdout
