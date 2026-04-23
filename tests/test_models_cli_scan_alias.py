from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

import thomas.cli.main as cli_main
from thomas.cli.main import cli


def _write_min_config(path: Path) -> Path:
    cfg = path / "thomas.toml"
    cfg.write_text(
        """
default_model = "local"

[memory]
root = "./runtime"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
        encoding="utf-8",
    )
    return cfg


def test_models_scan_routes_to_shared_discovery_helper(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)
    calls: list[tuple[str | None, float]] = []

    def _fake_run(ctx, model_name: str | None, timeout_s: float) -> None:
        calls.append((model_name, timeout_s))
        click.echo("stubbed discovery")

    monkeypatch.setattr(cli_main, "_run_models_discover", _fake_run)

    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "models", "scan", "--timeout", "1"])

    assert result.exit_code == 0, result.output
    assert "stubbed discovery" in result.output
    assert calls == [(None, 1.0)]


def test_models_discover_routes_to_shared_discovery_helper(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)
    calls: list[tuple[str | None, float]] = []

    def _fake_run(ctx, model_name: str | None, timeout_s: float) -> None:
        calls.append((model_name, timeout_s))
        click.echo("stubbed discovery")

    monkeypatch.setattr(cli_main, "_run_models_discover", _fake_run)

    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "models", "discover", "--timeout", "1"])

    assert result.exit_code == 0, result.output
    assert "stubbed discovery" in result.output
    assert calls == [(None, 1.0)]


@pytest.mark.parametrize("subcommand", ["scan", "discover"])
def test_models_commands_surface_discovery_failures_without_traceback(
    tmp_path: Path, monkeypatch, subcommand: str
) -> None:
    cfg = _write_min_config(tmp_path)

    import thomas.models.discovery as discovery_mod

    def _boom(*_args, **_kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(discovery_mod, "discover_models", _boom)

    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "models", subcommand, "--timeout", "1"])

    assert result.exit_code == 1
    assert "Error: model discovery failed (RuntimeError): backend unavailable" in result.output
    assert "Traceback" not in result.output
    assert "Context' object is not iterable" not in result.output


def test_models_scan_and_discover_emit_same_output_for_same_results(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)

    import thomas.models.discovery as discovery_mod

    def _fake_discovery(*_args, **_kwargs):
        return [SimpleNamespace(id="model.one"), SimpleNamespace(id="model.two")]

    monkeypatch.setattr(discovery_mod, "discover_models", _fake_discovery)

    runner = CliRunner()
    scan = runner.invoke(cli, ["-c", str(cfg), "models", "scan", "--timeout", "1"])
    discover = runner.invoke(cli, ["-c", str(cfg), "models", "discover", "--timeout", "1"])

    assert scan.exit_code == 0, scan.output
    assert discover.exit_code == 0, discover.output
    assert scan.output == discover.output


@pytest.mark.parametrize("subcommand", ["scan", "discover"])
def test_models_commands_reject_non_positive_timeout(tmp_path: Path, subcommand: str) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["-c", str(cfg), "models", subcommand, "--timeout", "0"])

    assert result.exit_code == 2
    assert "Invalid value for --timeout" in result.output
    assert "must be greater than 0" in result.output
    assert "Traceback" not in result.output


def test_models_discover_unknown_profile_is_user_facing(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["-c", str(cfg), "models", "discover", "--model", "missing", "--timeout", "1"],
    )

    assert result.exit_code == 2
    assert "Invalid value for --model" in result.output
    assert "unknown model profile 'missing'" in result.output
    assert "Traceback" not in result.output
    assert "Context' object is not iterable" not in result.output


def test_models_scan_rejects_model_option_without_traceback(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["-c", str(cfg), "models", "scan", "--model", "missing", "--timeout", "1"],
    )

    assert result.exit_code == 2
    assert "No such option: --model" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("subcommand", ["scan", "discover"])
def test_models_commands_surface_click_exceptions_without_traceback(
    tmp_path: Path, monkeypatch, subcommand: str
) -> None:
    cfg = _write_min_config(tmp_path)

    import thomas.models.discovery as discovery_mod

    def _boom(*_args, **_kwargs):
        raise click.ClickException("boom")

    monkeypatch.setattr(discovery_mod, "discover_models", _boom)

    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "models", subcommand, "--timeout", "1"])

    assert result.exit_code == 1
    assert "Error: boom" in result.output
    assert "Traceback" not in result.output
    assert "Context' object is not iterable" not in result.output


def test_models_scan_and_discover_empty_discovery_parity(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_min_config(tmp_path)

    import thomas.models.discovery as discovery_mod

    def _fake_discovery(*_args, **_kwargs):
        return []

    monkeypatch.setattr(discovery_mod, "discover_models", _fake_discovery)

    runner = CliRunner()
    scan = runner.invoke(cli, ["-c", str(cfg), "models", "scan", "--timeout", "1"])
    discover = runner.invoke(cli, ["-c", str(cfg), "models", "discover", "--timeout", "1"])

    assert scan.exit_code == discover.exit_code
    assert scan.output == discover.output
