from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
from click.testing import CliRunner

from thomas.cli.quality_ops import OPS_BY_FAMILY, register_quality_ops


def _build_root_cli() -> click.Group:
    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        _ = ctx

    for family in OPS_BY_FAMILY.keys():

        @click.group(name=family)
        @click.pass_context
        def _family(ctx: click.Context) -> None:
            _ = ctx

        root.add_command(_family)
    return root


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(root_path=tmp_path),
        models={"gpt-5": {"model": "gpt-5"}},
        default_model="gpt-5",
        server=SimpleNamespace(api_token=""),
    )


def test_quality_ops_registration_count() -> None:
    cli = _build_root_cli()
    added = register_quality_ops(cli)
    expected = sum(len(ops) for ops in OPS_BY_FAMILY.values())
    assert added == expected

    for family, ops in OPS_BY_FAMILY.items():
        group = cli.commands[family]
        assert isinstance(group, click.Group)
        for op in ops:
            assert op in group.commands


def test_quality_ops_commands_emit_json(tmp_path: Path) -> None:
    cli = _build_root_cli()
    register_quality_ops(cli)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    res = runner.invoke(cli, ["browser", "ops-inspect", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["family"] == "browser"
    assert "capabilities" in payload
    assert "priority" in payload

    export_path = tmp_path / "quality_export.json"
    res_export = runner.invoke(
        cli,
        ["memory", "ops-export", "--json", "--output", str(export_path)],
        obj={"config": cfg},
    )
    assert res_export.exit_code == 0, res_export.output
    assert export_path.exists()
    saved = json.loads(export_path.read_text(encoding="utf-8"))
    assert saved["family"] == "memory"


def test_quality_ops_doctor_tolerates_non_json_state_files(tmp_path: Path) -> None:
    cli = _build_root_cli()
    register_quality_ops(cli)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    state_dir = tmp_path / ".thomas" / "cli"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "gateway.log").write_text("plain text log line\n", encoding="utf-8")
    (state_dir / "gateway_state.json").write_text("{}", encoding="utf-8")

    res = runner.invoke(cli, ["gateway", "ops-doctor", "--json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["family"] == "gateway"
    assert payload["ok"] is True
