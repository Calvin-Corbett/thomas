from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import click
from click.testing import CliRunner

from thomas.cli.commands.companion import register_companion_commands


@dataclass
class _Memory:
    root_path: Path


@dataclass
class _ConfigStub:
    memory: _Memory


def _build_cli() -> click.Group:
    @click.group()
    @click.pass_context
    def cli(ctx: click.Context) -> None:
        _ = ctx

    register_companion_commands(cli)
    return cli


def test_companion_init_and_status_json(tmp_path: Path) -> None:
    cli = _build_cli()
    runner = CliRunner()
    cfg = _ConfigStub(memory=_Memory(root_path=tmp_path))
    root = tmp_path / "companion-state"

    init_res = runner.invoke(cli, ["companion", "init", "--root", str(root), "--json"], obj={"config": cfg})
    assert init_res.exit_code == 0, init_res.output
    init_payload = json.loads(init_res.output)
    assert init_payload["ok"] is True
    assert Path(init_payload["root"]).exists()

    status_res = runner.invoke(
        cli,
        ["companion", "status", "--root", str(root), "--json"],
        obj={"config": cfg},
    )
    assert status_res.exit_code == 0, status_res.output
    status_payload = json.loads(status_res.output)
    assert status_payload["kernel_version"] == "0.1.0"
    assert status_payload["modules_count"] == 0
