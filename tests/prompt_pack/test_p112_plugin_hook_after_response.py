from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Make the repository root importable even when pytest chooses a different
# collection root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thomas.cli.commands.plugins.p112_plugin_hook_after_response import app as cli_app
from thomas.plugins.p112_plugin_hook_after_response import (
    AfterResponseHookConfigError,
    AfterResponseHookExternalError,
    AfterResponseHookInputError,
    run_after_response_hook,
)


def test_hook_success_inspect() -> None:
    result = run_after_response_hook(
        request={"response_text": "hello world"},
        config={"enabled": True, "sink": "none"},
    )

    assert result.response_text == "hello world"
    assert result.char_count == len("hello world")
    assert result.word_count == 2
    assert len(result.sha256) == 64
    assert result.written_to is None


def test_hook_success_file_sink(tmp_path) -> None:
    target = tmp_path / "out.txt"
    result = run_after_response_hook(
        request={"response_text": "line-1"},
        config={"enabled": True, "sink": "file", "file_path": str(target)},
    )

    assert result.written_to == str(target)
    assert target.read_text(encoding="utf-8") == "line-1\n"


def test_hook_missing_config_is_deterministic() -> None:
    with pytest.raises(AfterResponseHookConfigError) as exc:
        run_after_response_hook(request={"response_text": "x"}, config=None)
    assert exc.value.code == "missing_config"


def test_hook_invalid_input_is_deterministic() -> None:
    with pytest.raises(AfterResponseHookInputError) as exc:
        run_after_response_hook(request={"response_text": 123}, config={"enabled": True})
    assert exc.value.code == "invalid_input"
    assert exc.value.details.get("field") == "response_text"


def test_hook_external_failure_is_deterministic(tmp_path) -> None:
    # Using a directory path as the file sink target should fail predictably.
    with pytest.raises(AfterResponseHookExternalError) as exc:
        run_after_response_hook(
            request={"response_text": "x"},
            config={"enabled": True, "sink": "file", "file_path": str(tmp_path)},
        )
    assert exc.value.code == "external_failure"
    assert exc.value.details.get("file_path") == str(tmp_path)


def test_cli_json_success() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["--response", "hello", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["word_count"] == 1


def test_cli_json_failure_missing_file_path() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["--sink", "file", "--json"])
    assert res.exit_code == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_config"


def test_cli_schema_envelope() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["--schema", "envelope"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["title"] == "AfterResponseHookEnvelope"
