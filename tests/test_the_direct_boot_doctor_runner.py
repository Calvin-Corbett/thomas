"""scripts/run_boot_doctor_direct.py, the runner for when the regular CLI is broken, stamps UTC and names its config.

It kept the deprecated ``datetime.utcnow()`` (a DeprecationWarning on the Python 3.12 venv) after the same call was
removed from thomas/bootdoctor/__main__.py, and its "config load failed" warning did not say which file.
"""

from __future__ import annotations

import importlib.util
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests._bootdoctor_fakes import isolate_offline_checks

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    isolate_offline_checks(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "run_boot_doctor_direct", ROOT / "scripts" / "run_boot_doctor_direct.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Clock(datetime):
    """A clock that only answers the non-deprecated question, and answers it in UTC."""

    @classmethod
    def now(cls, tz=None):
        assert tz is timezone.utc, "the stamp must come from the UTC clock"
        return cls(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    @classmethod
    def utcnow(cls):
        raise AssertionError("datetime.utcnow() is deprecated")


def test_the_fallback_report_is_stamped_from_the_utc_clock(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "datetime", _Clock)

    path = runner._fallback_report_path(tmp_path)
    runner._write_failure_report(path, reason="startup failure", port=22127, exc=RuntimeError("boom"))

    assert path.name == "boot_doctor_20300102_030405.txt"
    assert "Generated (UTC): 2030-01-02T03:04:05Z" in path.read_text(encoding="utf-8")


def test_the_fallback_report_raises_no_deprecation_warning(runner, tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        path = runner._fallback_report_path(tmp_path)
        runner._write_failure_report(path, reason="startup failure", port=22127, exc=RuntimeError("boom"))

    assert path.exists()


def test_a_config_that_will_not_load_is_named_in_the_warning(runner, tmp_path: Path) -> None:
    bad = tmp_path / "elsewhere.toml"
    bad.write_text("[server\n", encoding="utf-8")

    config, warning = runner._load_config_safe(str(bad))

    assert str(bad.resolve()) in warning
    assert "using defaults" in warning
    assert config == runner.AppConfig()  # the built-in defaults are what carries on


def test_the_default_config_is_named_when_none_was_given(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "thomas.toml").write_text("[server\n", encoding="utf-8")

    _config, warning = runner._load_config_safe("")
    assert str((tmp_path / "thomas.toml").resolve()) in warning

    from_env = tmp_path / "env.toml"
    from_env.write_text("[server\n", encoding="utf-8")
    monkeypatch.setenv("THOMAS_CONFIG", str(from_env))
    _config, warning = runner._load_config_safe("")
    assert str(from_env.resolve()) in warning


def test_a_config_that_loads_gives_no_warning(runner, tmp_path: Path) -> None:
    good = tmp_path / "good.toml"
    good.write_text('default_model = "unit-test-model"\n', encoding="utf-8")

    config, warning = runner._load_config_safe(str(good))

    assert warning == ""
    assert config.default_model == "unit-test-model"
