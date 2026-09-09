from __future__ import annotations

import json
from pathlib import Path

from thomas.cli.repl_settings import (
    ReplRuntimeSettings,
    load_repl_runtime_settings,
    save_repl_runtime_settings,
)


def test_load_repl_runtime_settings_defaults_when_missing(tmp_path: Path) -> None:
    state = load_repl_runtime_settings(tmp_path / "missing.json")
    assert state == ReplRuntimeSettings()


def test_repl_runtime_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "repl_runtime_state.json"
    save_repl_runtime_settings(
        path,
        ReplRuntimeSettings(
            autonomy_level=4,
            tools_policy="always",
            show_system_logs=True,
            activity_verbosity="debug",
        ),
    )
    loaded = load_repl_runtime_settings(path)
    assert loaded.autonomy_level == 4
    assert loaded.tools_policy == "always"
    assert loaded.show_system_logs is True
    assert loaded.activity_verbosity == "debug"


def test_repl_runtime_settings_normalizes_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "repl_runtime_state.json"
    path.write_text(
        json.dumps(
            {
                "autonomy_level": 99,
                "tools_policy": "off",
                "show_system_logs": 1,
                "activity_verbosity": "loud",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_repl_runtime_settings(path)
    assert loaded.autonomy_level == 4
    assert loaded.tools_policy == "never"
    assert loaded.show_system_logs is True
    assert loaded.activity_verbosity == "normal"
