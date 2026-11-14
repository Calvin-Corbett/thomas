"""First-run setup must produce usable runtime configuration and preferences."""

import os
from pathlib import Path
from unittest.mock import patch

import click
import pytest
import yaml
from click.testing import CliRunner

from thomas.cli.commands import quickstart, setup_wizard
from thomas.cli.commands.setup_config import PERSONALITY_DESCRIPTIONS, save_personality
from thomas.core.config import load_config


@pytest.fixture(autouse=True)
def isolated_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("THOMAS_")}
    environment.update(THOMAS_USER_DIR=str(tmp_path / "user"), THOMAS_DATA_DIR=str(tmp_path / "data"))
    # load_config itself adds runtime environment defaults; restore those too.
    with patch.dict(os.environ, environment, clear=True):
        yield


def _identity_path() -> Path:
    return Path(os.environ["THOMAS_USER_DIR"]) / "config.yaml"


def _seed_identity():
    path = _identity_path()
    path.parent.mkdir(parents=True)
    original = {
        "identity": {"name": "My Thomas", "personality": "Existing custom style", "system_prompt_suffix": "Keep this"},
        "other": {"enabled": True, "items": [1, "keep"]},
    }
    path.write_text(yaml.safe_dump(original), encoding="utf-8")
    return original


def _assert_valid_config(path):
    cfg = load_config(Path(path))
    assert cfg.validate() == []
    assert cfg.default_model == "default"
    assert cfg.get_model().name == "default"
    return cfg


@pytest.mark.parametrize("writer", ["wizard", "quickstart"])
@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic"])
def test_generated_config_round_trips_literal_values(writer, provider):
    base_url = 'https://example.invalid/v1?value="quoted"&path=C:\\models'
    api_key = "" if provider == "ollama" else 'key-"\\\n\t\x00\x7f-🦊'
    model = 'model-"\\\nwith literal [section]-🦊'
    if writer == "wizard":
        path = Path("thomas.toml")
        path.write_text(setup_wizard._generate_config(provider, base_url, api_key, model, "balanced"), encoding="utf-8")
    else:
        path = quickstart._write_minimal_config(base_url, api_key, model, provider)
    cfg = _assert_valid_config(path)
    selected = cfg.get_model()
    assert (selected.base_url, selected.api_key, selected.model) == (base_url, api_key, model)
    assert selected.provider == ("anthropic" if provider == "anthropic" else "openai_compat")
    assert not _identity_path().exists(), "Rendering model configuration must not modify identity preferences."


@pytest.mark.parametrize("choice,style", [(1, "casual"), (2, "balanced"), (3, "professional")])
def test_wizard_saves_selected_personality_and_preserves_other_preferences(monkeypatch, choice, style):
    original = _seed_identity()
    monkeypatch.setattr(setup_wizard, "_detect_existing_config", lambda: None)
    monkeypatch.setattr(setup_wizard, "_detect_ollama", lambda: False)
    monkeypatch.setattr(setup_wizard, "_test_connection", lambda *_args: (True, "hello"))
    cli = click.Group()
    setup_wizard.register_setup_commands(cli)
    result = CliRunner().invoke(cli, ["setup"], input=f"2\nexample-key\n1\n{choice}\nn\n")
    assert result.exit_code == 0, result.output
    assert "Setup Complete" in result.output
    _assert_valid_config("thomas.toml")
    original["identity"]["personality"] = PERSONALITY_DESCRIPTIONS[style]
    assert yaml.safe_load(_identity_path().read_text(encoding="utf-8")) == original
    from thomas.agent.prompt_templates import _load_user_identity_config

    assert _load_user_identity_config()["personality"] == PERSONALITY_DESCRIPTIONS[style]


@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_quickstart_uses_balanced_only_when_no_personality_exists(monkeypatch, cloud, existing):
    original = _seed_identity() if existing else None
    monkeypatch.setattr(quickstart, "_detect_ollama_models", lambda: [] if cloud else ["local-test"])
    cli = click.Group()
    quickstart.register_quickstart_commands(cli)
    result = CliRunner().invoke(cli, ["quickstart"], input="1\nexample-key\n" if cloud else "")
    assert result.exit_code == 0, result.output
    _assert_valid_config("thomas.toml")
    saved = yaml.safe_load(_identity_path().read_text(encoding="utf-8"))
    if existing:
        assert saved == original
    else:
        assert saved == {"identity": {"personality": PERSONALITY_DESCRIPTIONS["balanced"]}}


@pytest.mark.parametrize(
    "content", ["identity: [broken", "- list-root", "just a string", "identity: a scalar", "identity: null", "false"]
)
def test_invalid_user_configuration_is_not_overwritten(content):
    path = _identity_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(click.ClickException, match="Could not save personality preferences"):
        save_personality("professional")
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    "content", ["", "   \n\n", " \t\n", "# my settings\n# nothing yet\n", "null", "~\n", "null  # nothing set\n"]
)
def test_an_empty_user_configuration_counts_as_empty(content):
    path = _identity_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert save_personality("professional") == path
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "identity": {"personality": PERSONALITY_DESCRIPTIONS["professional"]}
    }


@pytest.mark.parametrize("content", ["", "null", "# nothing yet\n"])
def test_quickstart_saves_balanced_over_an_empty_user_configuration(monkeypatch, content):
    path = _identity_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(quickstart, "_detect_ollama_models", lambda: ["local-test"])
    cli = click.Group()
    quickstart.register_quickstart_commands(cli)
    result = CliRunner().invoke(cli, ["quickstart"])
    assert result.exit_code == 0, result.output
    assert "OK: Config saved" in result.output
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "identity": {"personality": PERSONALITY_DESCRIPTIONS["balanced"]}
    }


def test_setup_saves_the_chosen_style_over_a_null_user_configuration(monkeypatch):
    path = _identity_path()
    path.parent.mkdir(parents=True)
    path.write_text("null\n", encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "_detect_existing_config", lambda: None)
    monkeypatch.setattr(setup_wizard, "_detect_ollama", lambda: False)
    monkeypatch.setattr(setup_wizard, "_test_connection", lambda *_args: (True, "hello"))
    cli = click.Group()
    setup_wizard.register_setup_commands(cli)
    result = CliRunner().invoke(cli, ["setup"], input="2\nexample-key\n1\n3\nn\n")
    assert result.exit_code == 0, result.output
    assert "Setup Complete" in result.output
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "identity": {"personality": PERSONALITY_DESCRIPTIONS["professional"]}
    }


def test_quickstart_reports_identity_save_failure_before_success(monkeypatch):
    path = _identity_path()
    path.parent.mkdir(parents=True)
    path.write_text("identity: [broken", encoding="utf-8")
    monkeypatch.setattr(quickstart, "_detect_ollama_models", lambda: ["local-test"])
    cli = click.Group()
    quickstart.register_quickstart_commands(cli)
    result = CliRunner().invoke(cli, ["quickstart"])
    assert result.exit_code != 0
    assert "Could not save personality preferences" in result.output
    assert "OK: Config saved" not in result.output
    assert "Next: thomas chat" not in result.output
