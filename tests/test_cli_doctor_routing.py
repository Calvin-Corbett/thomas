from __future__ import annotations

from click.testing import CliRunner

import thomas.cli._commands_base as commands_base
from thomas.cli.doctor import doctor_command
from thomas.cli.main import cli


def _disable_startup_nudges(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_first_run_checked", True, raising=False)
    monkeypatch.setattr(cli, "_update_checked", True, raising=False)


def test_doctor_routes_repair_options_to_setup_diagnostics(tmp_path, monkeypatch) -> None:
    _disable_startup_nudges(monkeypatch)
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        commands_base,
        "_doctor_cmd",
        lambda _ctx, port, full: calls.append((port, full)),
    )

    result = CliRunner().invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "doctor",
            "--port",
            "9012",
            "--full",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(9012, True)]


def test_architecture_doctor_has_a_distinct_command_name(tmp_path, monkeypatch) -> None:
    _disable_startup_nudges(monkeypatch)

    setup_help = CliRunner().invoke(
        cli,
        ["--data-dir", str(tmp_path / "data"), "doctor", "--help"],
    )
    architecture_help = CliRunner().invoke(
        cli,
        ["--data-dir", str(tmp_path / "data"), "architecture-doctor", "--help"],
    )

    assert setup_help.exit_code == 0, setup_help.output
    assert "--port" in setup_help.output
    assert "--full" in setup_help.output
    assert architecture_help.exit_code == 0, architecture_help.output
    assert "Run Thomas architecture health checks." in architecture_help.output
    assert cli.commands["doctor"] is commands_base.doctor
    assert cli.commands["architecture-doctor"] is doctor_command
