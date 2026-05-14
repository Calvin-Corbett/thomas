import json

import pytest

from thomas.browser.p004_browser_action_type_and_press import (
    TypeAndPressError,
    TypeAndPressParams,
    format_json,
    parse_params,
    safe_run,
    type_and_press,
)


class _FakeLocator:
    def __init__(self):
        self.calls = []

    def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    def fill(self, text, **kwargs):
        self.calls.append(("fill", text, kwargs))

    def press(self, key, **kwargs):
        self.calls.append(("press", key, kwargs))


class _FakePage:
    def __init__(self, locator):
        self._locator = locator
        self.locators = []

    def locator(self, selector):
        self.locators.append(selector)
        return self._locator


def test_type_and_press_success_calls_in_order():
    locator = _FakeLocator()
    page = _FakePage(locator)
    params = TypeAndPressParams(selector="#q", text="hello", key="Enter", timeout_ms=123, click_first=True)

    result = type_and_press(page, params)
    assert result.ok is True
    assert result.selector == "#q"
    assert result.text == "hello"
    assert result.key == "Enter"

    assert page.locators == ["#q"]
    assert [c[0] for c in locator.calls] == ["click", "fill", "press"]


def test_safe_run_returns_failure_dict_instead_of_raising():
    out = safe_run(None, {"selector": "#q", "text": "hello"})
    assert out["ok"] is False
    assert out["code"] == "MISSING_BROWSER"


def test_parse_params_rejects_empty_selector():
    with pytest.raises(TypeAndPressError) as ei:
        parse_params({"selector": " ", "text": "x"})
    assert ei.value.code == "INVALID_INPUT"
    assert "selector" in ei.value.message


def test_typing_failure_is_wrapped_deterministically():
    class BoomLocator(_FakeLocator):
        def fill(self, text, **kwargs):
            raise RuntimeError("boom")

    locator = BoomLocator()
    page = _FakePage(locator)
    params = TypeAndPressParams(selector="#q", text="hello")

    with pytest.raises(TypeAndPressError) as ei:
        type_and_press(page, params)
    assert ei.value.code in ("EXTERNAL_FAILURE", "TIMEOUT")
    assert ei.value.step == "type"
    assert "boom" in ei.value.message


def test_format_json_is_machine_readable():
    locator = _FakeLocator()
    page = _FakePage(locator)
    result = type_and_press(page, TypeAndPressParams(selector="#q", text="hello"))
    payload = json.loads(format_json(result))
    assert payload["ok"] is True
    assert payload["selector"] == "#q"


def test_cli_emits_json(monkeypatch):
    from typer.testing import CliRunner

    from thomas.cli.commands.browser import p004_browser_action_type_and_press as cli_mod

    locator = _FakeLocator()
    page = _FakePage(locator)

    monkeypatch.setattr(cli_mod, "_resolve_page_with_cleanup", lambda url: cli_mod._ResolvedPage(page=page, cleanup=lambda: None, source="test"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.app,
        [
            "--selector",
            "#q",
            "--text",
            "hello",
            "--key",
            "Enter",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["selector"] == "#q"


def test_cli_schema_output(monkeypatch):
    from typer.testing import CliRunner

    from thomas.cli.commands.browser import p004_browser_action_type_and_press as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["--schema"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["action"] == "type_and_press"
    assert "input_schema" in payload
    assert "output_schema" in payload
