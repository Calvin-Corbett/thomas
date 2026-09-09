from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.system.config_validator import validate_config


@pytest.fixture(autouse=True)
def _clear_thomas_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("THOMAS_"):
            monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "thomas.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_remote_mode_without_api_token_is_error(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "cloud"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "remote"

[models.cloud]
provider = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
""".strip(),
    )

    report = validate_config(cfg)
    assert report["ok"] is False
    assert any("server.api_token" in item["message"] for item in report["errors"])


def test_remote_mode_security_warnings_are_emitted(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "remote"
api_token = "token-123"
allow_unauthenticated_version = true

[tools]
allow_shell = true

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
    )

    report = validate_config(cfg)
    assert report["ok"] is True
    codes = {item["code"] for item in report["warnings"]}
    assert "server.remote.allow_unauthenticated_version" in codes
    assert "tools.allow_shell" in codes


def test_default_remote_profile_missing_key_is_blocking_error(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "cloud"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[models.cloud]
provider = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
""".strip(),
    )

    report = validate_config(cfg)
    assert report["ok"] is False
    assert any(item["code"] == "models.default_profile_missing_key" for item in report["errors"])


def test_non_default_remote_profile_missing_key_is_warning(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"

[models.cloud]
provider = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
""".strip(),
    )

    report = validate_config(cfg)
    assert report["ok"] is True
    assert any(item["code"] == "models.profile_missing_key" for item in report["warnings"])


def test_remote_mode_webhook_signature_disable_is_blocking_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "remote"
api_token = "token-123"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
    )

    monkeypatch.setenv("THOMAS_WEBHOOK_REQUIRE_SIGNATURES", "0")
    report = validate_config(cfg)
    assert report["ok"] is False
    assert any(item["code"] == "server.remote.webhook_signatures_disabled" for item in report["errors"])


def test_remote_mode_webhook_signature_enforcement_warns_when_provider_secrets_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "remote"
api_token = "token-123"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
    )

    monkeypatch.setenv("THOMAS_WEBHOOK_REQUIRE_SIGNATURES", "1")
    report = validate_config(cfg)
    warning_codes = {item["code"] for item in report["warnings"]}
    assert "webhooks.github.signature_secret_missing" in warning_codes
    assert "webhooks.stripe.signature_secret_missing" in warning_codes


def test_remote_mode_webhook_secret_warnings_clear_when_secrets_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "remote"
api_token = "token-123"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
    )

    monkeypatch.setenv("THOMAS_WEBHOOK_REQUIRE_SIGNATURES", "1")
    monkeypatch.setenv("THOMAS_GITHUB_WEBHOOK_SECRET", "gh-secret")
    monkeypatch.setenv("THOMAS_STRIPE_WEBHOOK_SECRET", "whsec-secret")
    report = validate_config(cfg)
    warning_codes = {item["code"] for item in report["warnings"]}
    assert "webhooks.github.signature_secret_missing" not in warning_codes
    assert "webhooks.stripe.signature_secret_missing" not in warning_codes


def test_invalid_webhook_signature_env_value_reports_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
default_model = "local"

[memory]
root = "{(tmp_path / "runtime").as_posix()}"

[server]
access_mode = "local"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
    )

    monkeypatch.setenv("THOMAS_WEBHOOK_REQUIRE_SIGNATURES", "maybe")
    report = validate_config(cfg)
    warning_codes = {item["code"] for item in report["warnings"]}
    assert "webhooks.require_signatures.invalid_env" in warning_codes
