from __future__ import annotations

import os

from click.testing import CliRunner

from thomas.cli.main import cli

NUDGE = "Thomas isn't configured yet"


def _arm_first_run_nudge(monkeypatch, tmp_path) -> None:
    """A fresh process with no thomas.toml anywhere and no THOMAS_* model config."""
    monkeypatch.setattr(cli, "_update_checked", True, raising=False)
    monkeypatch.setattr(cli, "_first_run_checked", False, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    for key in list(os.environ):
        if key.startswith("THOMAS_MODELS_"):
            monkeypatch.delenv(key)


def _run_version(tmp_path):
    return CliRunner().invoke(cli, ["--data-dir", str(tmp_path / "data"), "version"])


def test_nudge_shown_when_nothing_configures_thomas(tmp_path, monkeypatch) -> None:
    _arm_first_run_nudge(monkeypatch, tmp_path)
    result = _run_version(tmp_path)
    assert NUDGE in result.output, result.output


def test_nudge_silent_when_env_configures_a_model(tmp_path, monkeypatch) -> None:
    """Env-configured deployments (containers, CI, benchmarks) are configured, not first runs."""
    _arm_first_run_nudge(monkeypatch, tmp_path)
    monkeypatch.setenv("THOMAS_DEFAULT_MODEL", "bench")
    monkeypatch.setenv("THOMAS_MODELS_BENCH_PROVIDER", "openai_compat")
    result = _run_version(tmp_path)
    assert NUDGE not in result.output, result.output


def test_detect_env_config_true_when_env_configures_a_model(monkeypatch) -> None:
    from thomas.cli.commands.setup_wizard import _detect_env_config

    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("THOMAS_MODELS_BENCH_PROVIDER", "openai_compat")
    assert _detect_env_config() is True


def test_detect_env_config_false_when_env_is_clean(monkeypatch) -> None:
    from thomas.cli.commands.setup_wizard import _detect_env_config

    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    for key in list(os.environ):
        if key.startswith("THOMAS_MODELS_"):
            monkeypatch.delenv(key)
    assert _detect_env_config() is False
