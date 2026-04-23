from __future__ import annotations

import importlib
import json
import os
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

import click
import pytest
import typer
from typer.testing import CliRunner

from thomas.browser.p021_browser_download_tracking import (
    DownloadTrackingError,
    DownloadTrackingInput,
    track_download,
)


def _write_file_later(dirpath: Path, name: str, data: bytes, delay_s: float) -> Path:
    path = dirpath / name

    def _worker() -> None:
        time.sleep(delay_s)
        path.write_bytes(data)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return path


def _overwrite_file_later(path: Path, data: bytes, delay_s: float) -> None:
    def _worker() -> None:
        time.sleep(delay_s)
        path.write_bytes(data)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _keep_writing(path: Path, delay_s: float, interval_s: float, total_writes: int) -> None:
    def _worker() -> None:
        time.sleep(delay_s)
        for i in range(total_writes):
            # ensure size+mtime keeps changing
            with open(path, "ab") as f:
                f.write(f"{i}".encode("utf-8"))
            time.sleep(interval_s)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _get_cli_app() -> Any:
    """Best-effort import of the real Thomas CLI app.

    The codebase may expose the root click/Typer app under different attribute
    names. This helper keeps the test resilient to small refactors.
    """

    mod = importlib.import_module("thomas.cli.main")

    # Common names
    for attr in ("app", "cli", "typer_app"):
        obj = getattr(mod, attr, None)
        if isinstance(obj, typer.Typer):
            return obj
        if isinstance(obj, click.core.Command):
            return obj

    # Factory patterns
    for attr in ("build_app", "create_app", "get_app"):
        fn = getattr(mod, attr, None)
        if callable(fn):
            try:
                obj = fn()
            except TypeError:
                continue
            if isinstance(obj, typer.Typer):
                return obj
            if isinstance(obj, click.core.Command):
                return obj

    raise AssertionError("Could not locate a Typer/Click app in thomas.cli.main")


def test_track_download_detects_new_file(tmp_path: Path) -> None:
    payload = b"hello download\n"
    expected_sha = sha256(payload).hexdigest()

    created_path = _write_file_later(tmp_path, "example.txt", payload, delay_s=0.15)

    result = track_download(
        DownloadTrackingInput(
            download_dir=tmp_path,
            timeout_s=2.0,
            poll_interval_s=0.05,
            stable_checks=2,
        )
    )

    assert result.file_path == created_path
    assert result.file_path.exists()
    assert result.bytes == len(payload)
    assert result.sha256 == expected_sha
    assert result.file_name == "example.txt"
    assert result.duration_s >= 0


def test_track_download_detects_overwrite_same_name(tmp_path: Path) -> None:
    existing = tmp_path / "same.txt"
    existing.write_bytes(b"old\n")

    payload = b"new download\n"
    expected_sha = sha256(payload).hexdigest()
    _overwrite_file_later(existing, payload, delay_s=0.15)

    result = track_download(
        DownloadTrackingInput(
            download_dir=tmp_path,
            timeout_s=2.0,
            poll_interval_s=0.05,
            stable_checks=2,
        )
    )

    assert result.file_path == existing
    assert result.bytes == len(payload)
    assert result.sha256 == expected_sha


def test_track_download_missing_config_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BROWSER_DOWNLOAD_DIR", raising=False)
    monkeypatch.delenv("THOMAS_DOWNLOAD_DIR", raising=False)

    with pytest.raises(DownloadTrackingError) as excinfo:
        track_download(DownloadTrackingInput(download_dir=None, timeout_s=0.2, poll_interval_s=0.05))

    assert excinfo.value.code == "BROWSER.DOWNLOAD_DIR_NOT_CONFIGURED"


def test_track_download_times_out(tmp_path: Path) -> None:
    with pytest.raises(DownloadTrackingError) as excinfo:
        track_download(
            DownloadTrackingInput(
                download_dir=tmp_path,
                timeout_s=0.25,
                poll_interval_s=0.05,
            )
        )

    assert excinfo.value.code == "BROWSER.DOWNLOAD_TIMEOUT"


def test_track_download_stabilize_timeout(tmp_path: Path) -> None:
    path = tmp_path / "growing.bin"
    _keep_writing(path, delay_s=0.05, interval_s=0.05, total_writes=20)

    with pytest.raises(DownloadTrackingError) as excinfo:
        track_download(
            DownloadTrackingInput(
                download_dir=tmp_path,
                timeout_s=0.35,
                poll_interval_s=0.05,
                stable_checks=2,
            )
        )

    assert excinfo.value.code in {"BROWSER.DOWNLOAD_STABILIZE_TIMEOUT", "BROWSER.DOWNLOAD_TIMEOUT"}


def test_cli_download_tracking_json_success(tmp_path: Path) -> None:
    runner = CliRunner()
    app = _get_cli_app()

    payload = b"cli download payload\n"
    created_path = _write_file_later(tmp_path, "cli.txt", payload, delay_s=0.15)

    res = runner.invoke(
        app,
        [
            "browser",
            "download-tracking",
            "--download-dir",
            str(tmp_path),
            "--timeout",
            "2",
            "--poll",
            "0.05",
            "--json",
        ],
    )

    assert res.exit_code == 0, res.output

    data = json.loads(res.output)
    assert data["ok"] is True
    assert Path(data["result"]["file_path"]) == created_path
    assert data["result"]["file_name"] == "cli.txt"
    assert data["result"]["bytes"] == len(payload)


def test_cli_download_tracking_json_timeout(tmp_path: Path) -> None:
    runner = CliRunner()
    app = _get_cli_app()

    res = runner.invoke(
        app,
        [
            "browser",
            "download-tracking",
            "--download-dir",
            str(tmp_path),
            "--timeout",
            "0.25",
            "--poll",
            "0.05",
            "--json",
        ],
    )

    assert res.exit_code == 2
    data = json.loads(res.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "BROWSER.DOWNLOAD_TIMEOUT"


def test_cli_download_tracking_schema() -> None:
    runner = CliRunner()
    app = _get_cli_app()

    res = runner.invoke(app, ["browser", "download-tracking", "--schema"])
    assert res.exit_code == 0

    data = json.loads(res.output)
    assert data["type"] == "object"
    assert "ok" in data.get("required", [])
