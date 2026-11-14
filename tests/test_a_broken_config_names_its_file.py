"""A thomas.toml that will not parse is reported by file and line, and `thomas doctor` still runs.

A typo in thomas.toml printed a Python traceback that ended "Invalid statement (at line 1, column 1)" without
naming the file. `thomas doctor` -- the command every recovery message recommends -- died on the same line,
because the CLI group loads the config before any subcommand. So repair.cmd's last step failed on the very
problem it was there to report.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from thomas.cli.main import cli


@pytest.fixture(autouse=True)
def _quiet_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The CLI group writes THOMAS_* defaults into os.environ; give it a copy to write into.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(cli, "_first_run_checked", True, raising=False)
    monkeypatch.setattr(cli, "_update_checked", True, raising=False)
    monkeypatch.chdir(tmp_path)

    def _no_network(*args, **kwargs):
        raise httpx.ConnectError("no network in this test")

    monkeypatch.setattr(httpx, "get", _no_network)


def _run(tmp_path: Path, *args: str):
    return CliRunner().invoke(cli, ["--data-dir", str(tmp_path / "data"), *args])


def test_a_bad_config_stops_a_command_with_one_line_naming_the_file(tmp_path: Path) -> None:
    (tmp_path / "thomas.toml").write_text("[server\nport = = 1\n", encoding="utf-8")

    result = _run(tmp_path, "status")

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert str(tmp_path / "thomas.toml") in result.output
    assert "line 1" in result.output
    assert "Traceback" not in result.output


def test_a_config_that_is_not_text_stops_a_command_with_one_line_naming_the_file(tmp_path: Path) -> None:
    # A file saved in another encoding is not a TOML syntax error; it used to end in a UnicodeDecodeError traceback.
    (tmp_path / "thomas.toml").write_bytes(b"\xff\xfe\x00 not utf-8")

    result = _run(tmp_path, "status")

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert str(tmp_path / "thomas.toml") in result.output
    assert "not valid UTF-8" in result.output
    assert "Traceback" not in result.output


def test_a_config_named_with_dash_c_is_the_file_reported(tmp_path: Path) -> None:
    bad = tmp_path / "elsewhere.toml"
    bad.write_text("not toml at all\n", encoding="utf-8")

    result = _run(tmp_path, "-c", str(bad), "status")

    assert result.exit_code == 2
    assert str(bad) in result.output


def test_doctor_still_runs_on_a_bad_config_and_lists_it_first(tmp_path: Path) -> None:
    (tmp_path / "thomas.toml").write_text("[server\nport = = 1\n", encoding="utf-8")

    result = _run(tmp_path, "doctor")

    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.exit_code == 1  # the report is complete, but Thomas cannot start on this file
    issues = result.output.split("Config issues:", 1)[1].splitlines()
    assert str(tmp_path / "thomas.toml") in issues[1]
    assert "built-in defaults" in issues[1]
    assert "No model profiles defined" not in result.output  # defaults, not an empty config
    assert "Quick start (Windows): run-ui.cmd" in result.output


def test_doctor_on_a_good_config_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "thomas.toml").write_text("# a comment and no settings\n", encoding="utf-8")

    result = _run(tmp_path, "doctor")

    assert result.exit_code == 0, result.output
    assert "Config issues" not in result.output
