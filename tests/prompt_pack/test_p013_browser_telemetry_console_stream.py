import argparse
import json
from contextlib import contextmanager

import pytest


def test_p013_stream_console_invalid_input():
    from thomas.browser.p013_browser_telemetry_console_stream import (
        BrowserConsoleStreamInput,
        BrowserTelemetryInputError,
        stream_console,
    )

    with pytest.raises(BrowserTelemetryInputError) as excinfo:
        stream_console(BrowserConsoleStreamInput(duration_seconds=0))

    assert excinfo.value.code == "invalid_input"


def test_p013_stream_console_collects_events(monkeypatch):
    import thomas.browser.p013_browser_telemetry_console_stream as mod

    class FakeConsoleMessage:
        def __init__(self):
            self.type = "error"
            self.text = "Boom"
            self.location = {"url": "https://example.test/app.js", "lineNumber": 12, "columnNumber": 3}
            self.args = ["x", 123]

    class FakePage:
        def __init__(self, clock):
            self._handlers = {}
            self._clock = clock
            self._fired = False

        def on(self, event, cb):
            self._handlers.setdefault(event, []).append(cb)

        def wait_for_timeout(self, ms):
            # Advance fake clock and fire exactly one console event.
            self._clock["t"] += ms / 1000.0
            if not self._fired:
                self._fired = True
                for cb in self._handlers.get("console", []):
                    cb(FakeConsoleMessage())

    class FakeContext:
        def __init__(self, page):
            self.pages = [page]
            self._handlers = {}

        def on(self, event, cb):
            # Keep the handler; tests don't need to trigger new pages.
            self._handlers.setdefault(event, []).append(cb)

    class FakeBrowser:
        def __init__(self, ctx):
            self.contexts = [ctx]

    clock = {"t": 0.0}
    fake_page = FakePage(clock)
    fake_ctx = FakeContext(fake_page)
    fake_browser = FakeBrowser(fake_ctx)

    @contextmanager
    def fake_connect(_cdp_url):
        yield fake_browser

    monkeypatch.setattr(mod, "_connect_over_cdp", fake_connect)

    # Deterministic time.
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mod.time, "time", lambda: 123456.789)

    out = mod.stream_console(
        mod.BrowserConsoleStreamInput(
            cdp_url="ws://fake",
            duration_seconds=0.2,
            poll_interval_seconds=0.1,
            max_events=10,
            include_location=True,
            include_args=True,
        )
    )

    assert out.cdp_url == "ws://fake"
    assert out.truncated is False
    assert len(out.events) == 1
    ev = out.events[0]
    assert ev.level.lower() == "error"
    assert ev.text == "Boom"
    assert ev.location is not None
    assert ev.location.url == "https://example.test/app.js"
    assert ev.location.line == 12
    assert ev.location.column == 3
    assert ev.args == ["x", 123]


def test_p013_cli_json_success(monkeypatch, capsys):
    import thomas.browser.p013_browser_telemetry_console_stream as core
    import thomas.cli.commands.browser.p013_browser_telemetry_console_stream as cli

    def fake_stream_console(_req, *, on_event=None):
        return core.BrowserConsoleStreamOutput(
            events=[core.BrowserConsoleEvent(timestamp_ms=1, level="log", text="hi")],
            truncated=False,
            duration_seconds=0.01,
            cdp_url="ws://fake",
        )

    monkeypatch.setattr(core, "stream_console", fake_stream_console)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p013-browser-telemetry-console-stream", "--json", "--cdp-url", "ws://fake"])
    rc = args.func(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["events"][0]["text"] == "hi"


def test_p013_cli_json_failure(monkeypatch, capsys):
    import thomas.browser.p013_browser_telemetry_console_stream as core
    import thomas.cli.commands.browser.p013_browser_telemetry_console_stream as cli

    def fake_stream_console(_req, *, on_event=None):
        raise core.BrowserTelemetryConfigError(code="browser_endpoint_missing", message="no endpoint")

    monkeypatch.setattr(core, "stream_console", fake_stream_console)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p013-browser-telemetry-console-stream", "--json"])
    rc = args.func(args)

    assert rc != 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["error"]["code"] == "browser_endpoint_missing"


def test_p013_cli_json_schema(monkeypatch, capsys):
    import thomas.cli.commands.browser.p013_browser_telemetry_console_stream as cli

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli.register(sub)

    args = parser.parse_args(["p013-browser-telemetry-console-stream", "--json-schema"])
    rc = args.func(args)

    assert rc == 0
    schema = json.loads(capsys.readouterr().out.strip())
    assert schema["title"] == "BrowserConsoleStreamOutput"
