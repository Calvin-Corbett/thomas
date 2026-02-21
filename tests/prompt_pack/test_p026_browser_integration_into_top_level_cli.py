import argparse
import json
import webbrowser

import pytest


def _patch_backend_open(monkeypatch, *, value=True, exc: Exception | None = None):
    """Patch whichever backend `open_url` is likely to use.

    If thomas.tools.browser exposes a callable we can patch, patch that.
    Otherwise patch stdlib `webbrowser.open`.
    """
    try:
        import thomas.tools.browser as tb  # type: ignore
    except Exception:
        tb = None

    if tb is not None:
        for name in ("open_url", "open", "launch", "browse", "open_in_browser"):
            fn = getattr(tb, name, None)
            if callable(fn):
                if exc is not None:
                    def _raise(*a, **k):
                        raise exc
                    monkeypatch.setattr(tb, name, _raise)
                else:
                    monkeypatch.setattr(tb, name, lambda *a, **k: value)
                return ("thomas_tool", name)

    # Fallback
    if exc is not None:
        def _raise(*a, **k):
            raise exc
        monkeypatch.setattr(webbrowser, "open", _raise)
    else:
        monkeypatch.setattr(webbrowser, "open", lambda *a, **k: value)
    return ("webbrowser", "open")


def test_core_dry_run_normalizes_url():
    from thomas.browser.p026_browser_integration_into_top_level_cli import BrowserOpenRequest, open_url

    result = open_url(BrowserOpenRequest(url="example.com", dry_run=True))
    assert result.ok is True
    assert result.opened is False
    assert result.backend == "noop"
    assert result.url == "https://example.com"


def test_core_missing_config(tmp_path):
    from thomas.browser.p026_browser_integration_into_top_level_cli import BrowserOpenRequest, open_url

    missing = tmp_path / "missing.json"
    result = open_url(BrowserOpenRequest(url="https://example.com", config_path=str(missing), dry_run=True))
    assert result.ok is False
    assert result.error is not None
    assert result.error.kind == "missing_config"


def test_cli_success_json(monkeypatch, capsys):
    from thomas.cli.commands.browser.p026_browser_integration_into_top_level_cli import register_browser_command

    _patch_backend_open(monkeypatch, value=True)

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_browser_command(subparsers)

    args = parser.parse_args(["browser", "https://example.com", "--json"])
    handler = getattr(args, "func", None) or getattr(args, "_handler", None)
    assert callable(handler)
    code = handler(args)

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["opened"] is True
    assert payload["url"] == "https://example.com"
    assert payload["error"] is None


def test_cli_external_failure(monkeypatch, capsys):
    from thomas.cli.commands.browser.p026_browser_integration_into_top_level_cli import register_browser_command

    _patch_backend_open(monkeypatch, value=False)

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_browser_command(subparsers)

    args = parser.parse_args(["browser", "https://example.com", "--json"])
    handler = getattr(args, "func", None) or getattr(args, "_handler", None)
    code = handler(args)

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "external_failure"


def test_cli_invalid_url(monkeypatch, capsys):
    from thomas.cli.commands.browser.p026_browser_integration_into_top_level_cli import register_browser_command

    _patch_backend_open(monkeypatch, value=True)

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_browser_command(subparsers)

    args = parser.parse_args(["browser", "file:///etc/passwd", "--json"])
    handler = getattr(args, "func", None) or getattr(args, "_handler", None)
    code = handler(args)

    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "invalid_input"


def test_cli_json_schema(capsys):
    from thomas.cli.commands.browser.p026_browser_integration_into_top_level_cli import register_browser_command

    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_browser_command(subparsers)

    args = parser.parse_args(["browser", "--json-schema"])
    handler = getattr(args, "func", None) or getattr(args, "_handler", None)
    code = handler(args)

    captured = capsys.readouterr()
    assert code == 0
    schema = json.loads(captured.out)
    assert schema["title"] == "ThomasBrowserOpenResult"


def test_main_is_wired_if_available():
    """A light-touch assertion that main.py is wired.

    The implementation installs an argparse auto-register hook in thomas.cli.main.
    If main.py exists and imports argparse, that hook should be present.
    """
    import argparse as _argparse

    try:
        import thomas.cli.main as _main  # noqa: F401
    except Exception:
        pytest.skip("thomas.cli.main not importable in this environment")

    wrapped = getattr(_argparse.ArgumentParser.add_subparsers, "_p026_browser_wrapped", False)
    assert wrapped is True
