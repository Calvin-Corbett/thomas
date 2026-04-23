import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.plugins.p104_plugin_update_planner import (
    PluginUpdatePlannerConfigError,
    PluginUpdatePlannerExternalError,
    PluginUpdatePlannerInputError,
    SemVer,
    plan_plugin_updates,
)
from thomas.cli.commands.plugins import p104_plugin_update_planner as cli_mod


def test_semver_prerelease_ordering():
    assert SemVer.parse("1.0.0-alpha") < SemVer.parse("1.0.0-alpha.1")
    assert SemVer.parse("1.0.0-alpha.1") < SemVer.parse("1.0.0-alpha.beta")
    assert SemVer.parse("1.0.0-alpha.beta") < SemVer.parse("1.0.0-beta")
    assert SemVer.parse("1.0.0-beta") < SemVer.parse("1.0.0-beta.2")
    assert SemVer.parse("1.0.0-beta.2") < SemVer.parse("1.0.0-beta.11")
    assert SemVer.parse("1.0.0-beta.11") < SemVer.parse("1.0.0-rc.1")
    assert SemVer.parse("1.0.0-rc.1") < SemVer.parse("1.0.0")


def test_plan_plugin_updates_success_inline_available_versions_list():
    req = {
        "installed": [
            {"id": "alpha", "version": "1.2.3"},
            {"id": "bravo", "version": "2.0.0", "pinned": True},
            "charlie@0.1.0",
        ],
        "available": {
            "alpha": ["1.2.3", "1.3.0"],
            "bravo": ["2.0.1", "3.0.0"],
            "charlie": {"versions": ["0.1.0", "0.1.1-alpha.1"]},
        },
    }
    resp = plan_plugin_updates(req)
    assert resp["ok"] is True
    assert resp["summary"]["total"] == 3

    alpha = next(a for a in resp["actions"] if a["id"] == "alpha")
    assert alpha["status"] == "update"
    assert alpha["bump"] == "minor"
    assert alpha["recommended"] is True

    bravo = next(a for a in resp["actions"] if a["id"] == "bravo")
    assert bravo["status"] == "update"
    assert bravo["recommended"] is False
    assert "pinned" in bravo["reason"].lower()

    charlie = next(a for a in resp["actions"] if a["id"] == "charlie")
    # prerelease excluded by default -> latest becomes 0.1.0, so up_to_date
    assert charlie["status"] == "up_to_date"


def test_plan_plugin_updates_missing_catalog_config():
    with pytest.raises(PluginUpdatePlannerConfigError):
        plan_plugin_updates({"installed": [{"id": "alpha", "version": "1.0.0"}]})


def test_plan_plugin_updates_invalid_version():
    with pytest.raises(PluginUpdatePlannerInputError):
        plan_plugin_updates({"installed": [{"id": "alpha", "version": "not-a-version"}], "available": {"alpha": "1.0.1"}})


def test_plan_plugin_updates_external_failure_url(monkeypatch):
    import thomas.plugins.p104_plugin_update_planner as mod
    class DummyRequests:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")
    monkeypatch.setattr(mod, "requests", DummyRequests())
    with pytest.raises(PluginUpdatePlannerExternalError):
        plan_plugin_updates(
            {
                "installed": [{"id": "alpha", "version": "1.0.0"}],
                "catalog_url": "https://example.invalid/catalog.json",
                "timeout_s": 0.01,
            }
        )


def test_cli_json_output(tmp_path: Path):
    installed_path = tmp_path / "installed.json"
    catalog_path = tmp_path / "catalog.json"
    installed_path.write_text(json.dumps([{"id": "alpha", "version": "1.0.0"}]), encoding="utf-8")
    catalog_path.write_text(json.dumps({"alpha": ["1.0.0", "1.0.1"]}), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.COMMAND,
        ["--installed", str(installed_path), "--catalog", str(catalog_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["summary"]["update"] == 1
