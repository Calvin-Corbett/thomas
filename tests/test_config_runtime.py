from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.core.config import (
    AppConfig,
    EmbedConfig,
    FailoverConfig,
    JournalConfig,
    MemoryConfig,
    ModelConfig,
    QualityConfig,
    SecurityConfig,
    ServerConfig,
    ToolsConfig,
    _auto_discover_bool_fields,
    _build_model_config,
    _coerce_types,
    _collect_unknown_core_keys,
    _default_data_dir,
    _env_override,
    _is_subpath,
    apply_runtime_data_env_defaults,
    load_config,
    normalize_profile_name,
    normalize_security_profile,
    resolve_thomas_data_dir,
    security_capabilities_for_profile,
    security_profile_options,
)


@pytest.fixture(autouse=True)
def _restore_env() -> None:
    original = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_profile_normalization_and_path_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_profile_name(" Demo/Profile ") == "Demo-Profile"
    with pytest.raises(ValueError):
        normalize_profile_name("..")

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "base"))
    monkeypatch.setenv("THOMAS_PROFILE", "alpha")
    assert resolve_thomas_data_dir() == (tmp_path / "base" / "alpha").resolve()
    assert _is_subpath(tmp_path / "base" / "alpha" / "child", tmp_path / "base")
    assert not _is_subpath(Path("C:/elsewhere"), tmp_path / "base")


def test_default_data_dir_prefers_platform_conventions(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", "C:/Temp/LocalAppData")
        assert _default_data_dir() == Path("C:/Temp/LocalAppData/Thomas").resolve()
    else:
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-home")
        assert _default_data_dir() == Path("/tmp/xdg-home/thomas").resolve()


def test_apply_runtime_data_env_defaults_sets_stateful_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_HOME", raising=False)
    mapping = apply_runtime_data_env_defaults(
        base_dir=tmp_path / "base",
        effective_dir=tmp_path / "base" / "demo",
        profile="demo",
    )
    assert mapping["THOMAS_PROFILE"] == "demo"
    assert os.environ["THOMAS_HOME"] == str(tmp_path / "base" / "demo")
    assert os.environ["THOMAS_RUNS_DB_PATH"].endswith(".thomas\\runs.sqlite3") or os.environ[
        "THOMAS_RUNS_DB_PATH"
    ].endswith(".thomas/runs.sqlite3")


def test_env_override_and_type_coercion_cover_nested_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_MODELS_CLOUD_TIMEOUT_S", "45.5")
    monkeypatch.setenv("THOMAS_MODELS_CLOUD_MAX_TOKENS", "2048")
    monkeypatch.setenv("THOMAS_FAILOVER_PROFILES", "local,codex")
    monkeypatch.setenv("THOMAS_SERVER_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("THOMAS_QUALITY_ENFORCE", "true")
    data: dict[str, object] = {}
    _env_override(data)
    _coerce_types(data)

    assert data["models"]["cloud"]["timeout_s"] == 45.5
    assert data["models"]["cloud"]["max_tokens"] == 2048
    assert data["failover"]["profiles"] == ["local", "codex"]
    assert data["server"]["rate_limit_enabled"] is False
    assert data["quality"]["enforce"] is True


def test_bool_field_discovery_and_model_builder() -> None:
    bool_fields = _auto_discover_bool_fields()
    assert "allow_shell" in bool_fields
    assert "enabled" in bool_fields

    cfg = _build_model_config(
        "cloud",
        {
            "provider": "openai_compat",
            "base_url": "https://example.test/v1",
            "model": "gpt-test",
            "extra_headers": {"X-Test": "1"},
            "query": {"region": "us"},
            "reasoning_effort": "high",
        },
    )
    assert cfg.name == "cloud"
    assert cfg.extra_headers == {"X-Test": "1"}
    assert cfg.query == {"region": "us"}
    assert cfg.reasoning_effort == "high"


def test_validation_helpers_cover_models_server_quality_and_failover() -> None:
    model = ModelConfig(name="bad", provider="openai_compat", model="", base_url="", temperature=3, timeout_s=0)
    errors = model.validate()
    assert any("model is required" in item for item in errors)
    assert any("temperature must be 0-2" in item for item in errors)
    assert any("timeout_s must be >= 1" in item for item in errors)

    model2 = ModelConfig(
        name="bad2",
        provider="openai_compat",
        model="real",
        base_url="",
        max_tokens=0,
        context_window=0,
        chat_path="chat",
        models_path="models",
    )
    errors2 = model2.validate()
    assert any("max_tokens must be >= 1" in item for item in errors2)
    assert any("context_window must be >= 1" in item for item in errors2)
    assert any("chat_path should start with '/'" in item for item in errors2)
    assert any("models_path should start with '/'" in item for item in errors2)
    assert any("base_url is required" in item for item in errors2)

    assert EmbedConfig(device="bogus").validate()
    assert ServerConfig(access_mode="weird").validate()
    assert ServerConfig(access_mode="remote", api_token="").validate()
    assert QualityConfig(max_auto_retries=-1).validate()
    assert QualityConfig(max_auto_retries=4).validate()
    assert SecurityConfig(profile="oops").validate()
    assert normalize_security_profile("Builder") == "hands_on"
    assert security_capabilities_for_profile("locked")["update_apply_allowed"] is False
    assert any(item["id"] == "balanced" for item in security_profile_options())

    app = AppConfig(
        models={
            "primary": ModelConfig(name="primary", provider="codex", model="gpt"),
            "backup": ModelConfig(name="backup", provider="codex", model="gpt-backup"),
        },
        default_model="primary",
        failover=FailoverConfig(enabled=True, profiles=["backup", "primary", "backup"]),
        security=SecurityConfig(profile="hands_on"),
    )
    chain = app.failover_chain("primary")
    assert [cfg.name for cfg in chain] == ["backup"]
    assert app.get_model().name == "primary"
    assert app.security_profile == "hands_on"
    assert app.security_capabilities()["assistant_guided_installs"] is True
    with pytest.raises(KeyError):
        app.get_model("missing")

    implicit = AppConfig(
        models={
            "primary": ModelConfig(name="primary", provider="codex", model="gpt"),
            "backup": ModelConfig(name="backup", provider="codex", model="gpt-backup"),
            "third": ModelConfig(name="third", provider="codex", model="gpt-third"),
        },
        default_model="primary",
        failover=FailoverConfig(enabled=True, profiles=[]),
    )
    assert [cfg.name for cfg in implicit.failover_chain("primary")] == ["backup", "third"]
    assert implicit.failover_chain("") == []

    disabled = AppConfig(models={"primary": ModelConfig(name="primary", provider="codex", model="gpt")})
    disabled.failover.enabled = False
    assert disabled.failover_chain("primary") == []

    invalid_app = AppConfig(
        models={},
        default_model="missing",
        max_agent_iterations=101,
        failover=FailoverConfig(enabled=True, profiles=["ghost"], cooldown_seconds=-1),
        unknown_core_keys=["server.bogus"],
    )
    invalid_errors = invalid_app.validate()
    assert any("No model profiles defined" in item for item in invalid_errors)
    assert any("default_model 'missing'" in item for item in invalid_errors)
    assert any("max_agent_iterations must be <= 100" in item for item in invalid_errors)
    assert any("failover.cooldown_seconds must be >= 0" in item for item in invalid_errors)
    assert any("Unknown core config key 'server.bogus'" in item for item in invalid_errors)


def test_collect_unknown_core_keys_marks_only_core_violations() -> None:
    unknown = _collect_unknown_core_keys(
        {
            "default_model": "local",
            "models": {"local": {"model": "dummy", "bogus": True}},
            "server": {"access_mode": "local", "wrong": True},
            "security": {"profile": "balanced", "bogus": True},
            "tools": {"allow_shell": True, "web_search": {"enabled": True}},
            "workspace": {"ignored": True},
            "mystery": 1,
        }
    )
    assert "models.local.bogus" in unknown
    assert "server.wrong" in unknown
    assert "security.bogus" in unknown
    assert "mystery" in unknown
    assert "workspace" not in unknown

    unknown2 = _collect_unknown_core_keys(
        {
            "models": {"local": "not-a-dict"},
            "dep_scanner": {"ignored": True},
            "notifications": {"ignored": True},
            "top_dict": {"oops": True},
        }
    )
    assert "top_dict" in unknown2
    assert "dep_scanner" not in unknown2
    assert "notifications" not in unknown2


def test_helper_paths_and_runtime_objects_expose_resolved_paths(tmp_path: Path) -> None:
    assert MemoryConfig(root=str(tmp_path / "runtime")).root_path == (tmp_path / "runtime").resolve()
    assert ToolsConfig(sandbox_root=str(tmp_path / "sandbox")).sandbox_path == (tmp_path / "sandbox").resolve()
    assert JournalConfig(dir=str(tmp_path / "journal")).dir_path == (tmp_path / "journal").resolve()


def test_env_override_ignores_invalid_model_fields_and_allows_extension_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THOMAS_MODELS_LOCAL_NOT_REAL", "x")
    monkeypatch.setenv("THOMAS_POLICY_ENABLED", "true")
    monkeypatch.setenv("THOMAS_WORKSPACE_ROOT", "repo")
    data: dict[str, object] = {}
    _env_override(data)
    assert data["policy"]["enabled"] == "true"
    assert data["workspace"]["root"] == "repo"
    assert "models" not in data or "local" not in data.get("models", {}) or "not_real" not in data["models"]["local"]


def test_coerce_types_handles_nested_profiles_and_non_string_values() -> None:
    data: dict[str, object] = {
        "max_agent_iterations": "9",
        "server": {"rate_limit_max_requests": "12", "rate_limit_enabled": "yes"},
        "models": {"local": {"top_p": "0.5", "timeout_s": "3.25"}},
        "failover": {"profiles": ["already", "list"]},
    }
    _coerce_types(data)
    assert data["max_agent_iterations"] == 9
    assert data["server"]["rate_limit_max_requests"] == 12
    assert data["server"]["rate_limit_enabled"] is True
    assert data["models"]["local"]["top_p"] == 0.5
    assert data["models"]["local"]["timeout_s"] == 3.25
    assert data["failover"]["profiles"] == ["already", "list"]


def test_load_config_defaults_profile_runtime_env_and_production_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "thomas.toml"
    cfg_path.write_text(
        "\n".join(
            [
                'default_model = "local"',
                "max_agent_iterations = 12",
                "",
                "[models.local]",
                'provider = "openai_compat"',
                'base_url = "http://127.0.0.1:11434/v1"',
                'model = "llama"',
                "",
                "[memory]",
                'data_dir = "state"',
                'profile = "beta"',
                'root = "runtime"',
                "",
                "[journal]",
                'dir = "notes"',
                "",
                "[keybindings]",
                'accept = "ctrl-enter"',
                "",
                "[tools]",
                "allow_shell = true",
                "",
                "[server]",
                'access_mode = "remote"',
                'api_token = "secret"',
                "",
                "[quality]",
                "enforce = false",
                "",
                "[security]",
                'profile = "review_only"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_ENV", "production")
    monkeypatch.delenv("THOMAS_ALLOW_REMOTE_PRODUCTION", raising=False)

    cfg = load_config(cfg_path, data_dir=tmp_path / "data-root", profile="demo")

    assert cfg.default_model == "local"
    assert cfg.max_agent_iterations == 12
    assert cfg.memory.profile == "demo"
    assert cfg.memory.root == "runtime"
    assert cfg.memory.data_dir == str((tmp_path / "data-root").resolve())
    assert os.environ["THOMAS_HOME"] == str(resolve_thomas_data_dir(tmp_path / "data-root", "demo"))
    assert os.environ["THOMAS_RUNTIME_DIR"].endswith("demo\\runtime") or os.environ["THOMAS_RUNTIME_DIR"].endswith(
        "demo/runtime"
    )
    assert cfg.journal.dir == "notes"
    assert cfg.journal.dir_path == Path("notes").resolve()
    assert cfg.keybindings["accept"] == "ctrl-enter"
    assert cfg.is_production is True
    assert cfg.is_development is False
    assert cfg.tools.allow_shell is False
    assert cfg.quality.enforce is True
    assert cfg.server.access_mode == "local"
    assert cfg.security.profile == "review_only"
    assert cfg.security_capabilities()["update_apply_allowed"] is False
    assert cfg.config_path == cfg_path.resolve()


def test_load_config_creates_default_profiles_and_preserves_remote_when_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THOMAS_ENV", "production")
    monkeypatch.setenv("THOMAS_ALLOW_REMOTE_PRODUCTION", "1")
    monkeypatch.setenv("THOMAS_SERVER_ACCESS_MODE", "remote")
    monkeypatch.setenv("THOMAS_SERVER_API_TOKEN", "secret")
    cfg = load_config(tmp_path / "missing.toml")
    assert {"codex", "local"}.issubset(cfg.models.keys())
    assert cfg.models["codex"].provider == "codex"
    assert cfg.server.access_mode == "remote"


def test_load_config_uses_env_path_invalid_environment_and_fallback_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "env-config.toml"
    cfg_path.write_text(
        "\n".join(
            [
                "[models.local]",
                'model = "dummy"',
                'base_url = "http://127.0.0.1:11434/v1"',
                "",
                "[memory]",
                'profile = "beta"',
                "",
                "[failover]",
                "profiles = 123",
                "",
                "[keybindings]",
                'accept = "ctrl-enter"',
                "",
                "journal = 'not-a-dict'",
                "keybindings = 'also-not-a-dict'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_CONFIG", str(cfg_path))
    monkeypatch.setenv("THOMAS_ENV", "staging")
    monkeypatch.setenv("THOMAS_PROFILE", "env-demo")

    cfg = load_config()

    assert cfg.environment == "development"
    assert cfg.memory.profile == "env-demo"
    assert cfg.failover.profiles == []
    assert cfg.keybindings["accept"] == "ctrl-enter"
    assert cfg.keybindings["journal"] == "not-a-dict"
    assert cfg.keybindings["keybindings"] == "also-not-a-dict"
    assert cfg.journal.enabled is True
    assert cfg.config_path == cfg_path.resolve()


def test_load_config_without_explicit_root_uses_effective_data_dir_when_subpath_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "subpath.toml"
    cfg_path.write_text(
        "\n".join(
            [
                "[models.local]",
                'model = "dummy"',
                'base_url = "http://127.0.0.1:11434/v1"',
                "",
                "[memory]",
                'profile = "demo"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("thomas.core.config._is_subpath", lambda path, parent: False)

    cfg = load_config(cfg_path, data_dir=tmp_path / "data")

    assert cfg.memory.root.endswith("runtime")
    assert Path(cfg.memory.root).is_absolute()
