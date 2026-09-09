from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.browser.p023_browser_trace_start_stop_export import (
    DEFAULT_TRACE_REGISTRY,
    BrowserTraceError,
    BrowserTraceErrorCode,
    BrowserTraceExportInput,
    BrowserTraceStartInput,
)
from thomas.cli.commands.browser.p023_browser_trace_start_stop_export import app as trace_app


class FakeTracing:
    def __init__(self) -> None:
        self.started = False
        self.start_calls = []
        self.stop_calls = []

    def start(
        self,
        *,
        title=None,
        snapshots=None,
        screenshots=None,
        sources=None,
        **kwargs,
    ) -> None:
        # Accept **kwargs to simulate forward-compatible Playwright APIs.
        if self.started:
            raise RuntimeError("already started")
        self.started = True
        self.start_calls.append(
            {
                "title": title,
                "snapshots": snapshots,
                "screenshots": screenshots,
                "sources": sources,
                "extra": dict(kwargs),
            }
        )

    def stop(self, *args, **kwargs) -> None:
        if not self.started:
            raise RuntimeError("not started")
        self.started = False

        path = kwargs.get("path")
        if path is None and args:
            path = args[0]
        self.stop_calls.append({"path": path})

        # Simulate Playwright writing a trace zip.
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"FAKE_TRACE_ZIP_BYTES")


class FakeContext:
    def __init__(self) -> None:
        self.tracing = FakeTracing()


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch, tmp_path):
    # Keep trace artifacts inside the test temp directory for determinism.
    monkeypatch.setenv("THOMAS_BROWSER_TRACE_DIR", str(tmp_path))
    DEFAULT_TRACE_REGISTRY.reset_for_tests()
    yield
    DEFAULT_TRACE_REGISTRY.reset_for_tests()


def test_trace_start_stop_export_happy_path(tmp_path: Path) -> None:
    ctx = FakeContext()

    start_out = DEFAULT_TRACE_REGISTRY.start(ctx, BrowserTraceStartInput(title="hello"))
    assert start_out.status == "started"
    assert start_out.trace_id

    stop_out = DEFAULT_TRACE_REGISTRY.stop(ctx)
    assert stop_out.status == "stopped"
    assert stop_out.trace_id == start_out.trace_id
    temp_path = Path(stop_out.temp_path)
    assert temp_path.exists()
    assert temp_path.read_bytes() == b"FAKE_TRACE_ZIP_BYTES"

    export_dest = tmp_path / "exported_trace.zip"
    export_out = DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(export_dest)))
    assert export_out.status == "exported"
    assert export_out.trace_id == start_out.trace_id
    assert Path(export_out.exported_path).exists()
    assert export_out.bytes_written > 0
    assert export_dest.read_bytes() == b"FAKE_TRACE_ZIP_BYTES"


def test_export_path_without_suffix_gets_zip_appended(tmp_path: Path) -> None:
    ctx = FakeContext()
    DEFAULT_TRACE_REGISTRY.start(ctx, BrowserTraceStartInput())
    DEFAULT_TRACE_REGISTRY.stop(ctx)

    dest_without_suffix = tmp_path / "trace_no_suffix"
    out = DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(dest_without_suffix)))
    assert out.exported_path.endswith(".zip")
    assert Path(out.exported_path).exists()


def test_export_to_directory_auto_names(tmp_path: Path) -> None:
    ctx = FakeContext()
    DEFAULT_TRACE_REGISTRY.start(ctx, BrowserTraceStartInput())
    DEFAULT_TRACE_REGISTRY.stop(ctx)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    out = DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(out_dir)))
    exported = Path(out.exported_path)
    assert exported.parent == out_dir
    assert exported.name.startswith("browser_trace_")
    assert exported.suffix == ".zip"
    assert exported.exists()


def test_trace_stop_without_start_fails() -> None:
    ctx = FakeContext()
    with pytest.raises(BrowserTraceError) as ei:
        DEFAULT_TRACE_REGISTRY.stop(ctx)
    assert ei.value.code == BrowserTraceErrorCode.NOT_STARTED.value


def test_trace_export_without_stop_fails(tmp_path: Path) -> None:
    ctx = FakeContext()
    DEFAULT_TRACE_REGISTRY.start(ctx, BrowserTraceStartInput())
    with pytest.raises(BrowserTraceError) as ei:
        DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(tmp_path / "x.zip")))
    assert ei.value.code == BrowserTraceErrorCode.NOT_STOPPED.value


def test_export_existing_file_requires_overwrite(tmp_path: Path) -> None:
    ctx = FakeContext()
    DEFAULT_TRACE_REGISTRY.start(ctx, BrowserTraceStartInput())
    DEFAULT_TRACE_REGISTRY.stop(ctx)

    dest = tmp_path / "exists.zip"
    dest.write_bytes(b"OLD")

    with pytest.raises(BrowserTraceError) as ei:
        DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(dest), overwrite=False))
    assert ei.value.code == BrowserTraceErrorCode.INVALID_EXPORT_PATH.value

    out = DEFAULT_TRACE_REGISTRY.export(ctx, BrowserTraceExportInput(path=str(dest), overwrite=True))
    assert Path(out.exported_path).read_bytes() == b"FAKE_TRACE_ZIP_BYTES"


def test_cli_json_missing_session() -> None:
    runner = CliRunner()
    result = runner.invoke(trace_app, ["start", "--json"])
    assert result.exit_code != 0

    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == BrowserTraceErrorCode.MISSING_SESSION.value


def test_cli_end_to_end_json(tmp_path: Path) -> None:
    runner = CliRunner()
    ctx = FakeContext()

    r1 = runner.invoke(trace_app, ["start", "--json", "--title", "T"], obj=ctx)
    assert r1.exit_code == 0
    p1 = json.loads(r1.stdout.strip())
    assert p1["ok"] is True
    trace_id = p1["result"]["trace_id"]
    assert trace_id

    r2 = runner.invoke(trace_app, ["stop", "--json"], obj=ctx)
    assert r2.exit_code == 0
    p2 = json.loads(r2.stdout.strip())
    assert p2["ok"] is True
    assert p2["result"]["trace_id"] == trace_id
    assert Path(p2["result"]["temp_path"]).exists()

    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    r3 = runner.invoke(trace_app, ["export", "--json", str(dest_dir)], obj=ctx)
    assert r3.exit_code == 0
    p3 = json.loads(r3.stdout.strip())
    assert p3["ok"] is True
    exported = Path(p3["result"]["exported_path"])
    assert exported.exists()
    assert exported.parent == dest_dir
