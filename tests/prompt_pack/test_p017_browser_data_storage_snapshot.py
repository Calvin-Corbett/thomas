from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from thomas.browser.p017_browser_data_storage_snapshot import (
    BrowserDataStorageSnapshotError,
    BrowserDataStorageSnapshotRequest,
    browser_data_storage_snapshot,
)
from thomas.cli.commands.browser import p017_browser_data_storage_snapshot as cli_mod


def test_snapshot_success_creates_zip_and_manifest(tmp_path: Path) -> None:
    data_dir = tmp_path / "browser-data"
    nested = data_dir / "Local Storage"
    nested.mkdir(parents=True)

    (data_dir / "Cookies").write_text("yum", encoding="utf-8")
    (nested / "hello.txt").write_text("world", encoding="utf-8")

    out = tmp_path / "snapshot.zip"

    result = browser_data_storage_snapshot(
        BrowserDataStorageSnapshotRequest(
            data_dir=data_dir,
            output_path=out,
            overwrite=False,
            strict=True,
            include_hash=True,
            include_manifest=True,
        )
    )

    assert result.ok is True
    assert result.snapshot_path.resolve() == out.resolve()
    assert out.exists()
    assert result.file_count == 2
    assert result.sha256 is not None and len(result.sha256) == 64
    assert result.manifest_path_in_archive is not None

    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        assert "Cookies" in names
        assert "Local Storage/hello.txt" in names
        assert result.manifest_path_in_archive in names


def test_snapshot_missing_config_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force an empty HOME/USERPROFILE so default paths won't exist (cross-platform).
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("USERPROFILE", str(empty_home))
    monkeypatch.delenv("THOMAS_BROWSER_DATA_DIR", raising=False)

    with pytest.raises(BrowserDataStorageSnapshotError) as exc:
        browser_data_storage_snapshot(BrowserDataStorageSnapshotRequest(data_dir=None))

    err = exc.value
    assert err.code == "missing_config"
    assert "could not be resolved" in err.message


def test_snapshot_forces_zip_extension(tmp_path: Path) -> None:
    data_dir = tmp_path / "browser-data"
    data_dir.mkdir()
    (data_dir / "Cookies").write_text("yum", encoding="utf-8")

    out = tmp_path / "snapshot.notzip"

    result = browser_data_storage_snapshot(
        BrowserDataStorageSnapshotRequest(
            data_dir=data_dir,
            output_path=out,
            overwrite=False,
            strict=True,
            include_hash=False,
            include_manifest=True,
        )
    )

    assert result.ok is True
    assert result.snapshot_path.suffix == ".zip"
    assert result.snapshot_path.exists()


def test_snapshot_is_atomic_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "browser-data"
    nested = data_dir / "Local Storage"
    nested.mkdir(parents=True)
    (data_dir / "Cookies").write_text("yum", encoding="utf-8")
    (nested / "hello.txt").write_text("world", encoding="utf-8")

    out = tmp_path / "out.zip"

    orig_write = zipfile.ZipFile.write

    def bad_write(self: zipfile.ZipFile, filename, arcname=None, compress_type=None):
        # Fail on the second file to simulate mid-archive I/O issues.
        if str(filename).endswith("hello.txt"):
            raise OSError("simulated read failure")
        return orig_write(self, filename, arcname=arcname, compress_type=compress_type)

    monkeypatch.setattr(zipfile.ZipFile, "write", bad_write)

    with pytest.raises(BrowserDataStorageSnapshotError) as exc:
        browser_data_storage_snapshot(
            BrowserDataStorageSnapshotRequest(
                data_dir=data_dir,
                output_path=out,
                overwrite=False,
                strict=True,
                include_hash=False,
                include_manifest=True,
            )
        )
    assert exc.value.code == "external_failure"

    # Atomic guarantee: final output should not exist on failure.
    assert not out.exists()

    # Best-effort cleanup: no lingering temp files with our naming convention.
    leftovers = [
        p
        for p in tmp_path.iterdir()
        if p.is_file() and p.name.startswith("out.zip.") and p.name.endswith(".tmp")
    ]
    assert leftovers == []


def test_cli_json_success_and_failure(tmp_path: Path) -> None:
    runner = CliRunner()

    # Simulate the real CLI shape: `thomas browser <command>`
    root_app = typer.Typer()
    browser_app = typer.Typer()
    cli_mod.register(browser_app)
    root_app.add_typer(browser_app, name="browser")

    data_dir = tmp_path / "profile"
    data_dir.mkdir()
    (data_dir / "Cookies").write_text("cookie", encoding="utf-8")

    out = tmp_path / "out.zip"

    ok = runner.invoke(
        root_app,
        [
            "browser",
            cli_mod.COMMAND_NAME,
            "--data-dir",
            str(data_dir),
            "--output",
            str(out),
            "--json",
        ],
    )
    assert ok.exit_code == 0, ok.stdout
    payload = json.loads(ok.stdout)
    assert payload["ok"] is True
    assert payload["snapshot_path"].endswith("out.zip")

    # Failure: missing config, no data-dir, isolated HOME/USERPROFILE
    empty_home = tmp_path / "empty_home_2"
    empty_home.mkdir()
    fail = runner.invoke(
        root_app,
        ["browser", cli_mod.COMMAND_NAME, "--json"],
        env={"HOME": str(empty_home), "USERPROFILE": str(empty_home)},
    )
    assert fail.exit_code != 0
    payload2 = json.loads(fail.stdout)
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "missing_config"
