import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p101_plugin_enable_and_disable_state_store import app as cli_app
from thomas.plugins.p101_plugin_enable_and_disable_state_store import (
    PluginEnablementStore,
    PluginEnablementStoreError,
)


def test_store_roundtrip_enable_disable(tmp_path: Path) -> None:
    store_path = tmp_path / "plugin_enablement.json"
    store = PluginEnablementStore(store_path)

    # Default: missing entry => enabled
    assert store.is_enabled("demo-plugin") is True

    change1 = store.set_enabled("demo-plugin", False)
    assert change1.previous_enabled is True
    assert change1.enabled is False
    assert change1.changed is True
    assert store_path.exists()
    assert store.is_enabled("demo-plugin") is False

    # Idempotent set should report changed=False
    change2 = store.set_enabled("demo-plugin", False)
    assert change2.previous_enabled is False
    assert change2.enabled is False
    assert change2.changed is False

    # Re-enable
    change3 = store.set_enabled("demo-plugin", True)
    assert change3.previous_enabled is False
    assert change3.enabled is True
    assert change3.changed is True
    assert store.is_enabled("demo-plugin") is True

    listed = store.list_enabled_states()
    assert listed["demo-plugin"] is True

    removed = store.clear("demo-plugin")
    assert removed is True
    assert store.is_enabled("demo-plugin") is True  # default again


def test_empty_file_is_treated_as_uninitialized_store(tmp_path: Path) -> None:
    store_path = tmp_path / "plugin_enablement.json"
    store_path.write_text("\n   \n", encoding="utf-8")
    store = PluginEnablementStore(store_path)
    assert store.is_enabled("anything") is True


def test_invalid_plugin_name_is_deterministic_error(tmp_path: Path) -> None:
    store = PluginEnablementStore(tmp_path / "plugin_enablement.json")
    with pytest.raises(PluginEnablementStoreError) as exc:
        store.set_enabled("bad plugin name", False)
    assert exc.value.code == "INVALID_PLUGIN_KEY"


def test_non_boolean_enabled_is_deterministic_error(tmp_path: Path) -> None:
    store = PluginEnablementStore(tmp_path / "plugin_enablement.json")
    with pytest.raises(PluginEnablementStoreError) as exc:
        store.set_enabled("demo-plugin", "false")
    assert exc.value.code == "INVALID_INPUT"


def test_corrupt_store_file_yields_deterministic_error(tmp_path: Path) -> None:
    store_path = tmp_path / "plugin_enablement.json"
    store_path.write_text("{ this is not json", encoding="utf-8")
    store = PluginEnablementStore(store_path)

    with pytest.raises(PluginEnablementStoreError) as exc:
        store.is_enabled("demo-plugin")
    assert exc.value.code == "STATE_STORE_CORRUPT"


def test_schema_mismatch_is_deterministic_error(tmp_path: Path) -> None:
    store_path = tmp_path / "plugin_enablement.json"
    store_path.write_text(
        json.dumps({"schema_version": 999, "plugins": {}}, indent=2),
        encoding="utf-8",
    )
    store = PluginEnablementStore(store_path)

    with pytest.raises(PluginEnablementStoreError) as exc:
        store.is_enabled("demo-plugin")
    assert exc.value.code == "STATE_STORE_UNSUPPORTED_SCHEMA"


def test_store_path_as_directory_is_deterministic_error(tmp_path: Path) -> None:
    store_path = tmp_path / "plugin_enablement.json"
    store_path.mkdir()
    store = PluginEnablementStore(store_path)

    with pytest.raises(PluginEnablementStoreError) as exc:
        store.set_enabled("demo-plugin", False)
    assert exc.value.code == "STATE_STORE_PATH_INVALID"


def test_cli_json_success_and_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    store_path = tmp_path / "plugin_enablement.json"

    ok = runner.invoke(cli_app, ["disable", "demo-plugin", "--store-path", str(store_path), "--json"])
    assert ok.exit_code == 0
    payload = json.loads(ok.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plugin"] == "demo-plugin"
    assert payload["result"]["enabled"] is False

    # invalid plugin key
    bad = runner.invoke(cli_app, ["disable", "bad plugin name", "--store-path", str(store_path), "--json"])
    assert bad.exit_code == 1
    payload2 = json.loads(bad.stdout)
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "INVALID_PLUGIN_KEY"
