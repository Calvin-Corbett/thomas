"""
Plugins CLI command: plugin-update-planner

Outputs:
- default: human-readable summary
- --json: machine-readable JSON payload (stable formatting)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import click

from thomas.plugins.p104_plugin_update_planner import PluginUpdatePlannerError, plan_plugin_updates


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise click.ClickException(f"File not found: {path}") from e
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON in {path}: {e}") from e


def _write_json(data: Any) -> str:
    # Stable for automation: sorted keys + compact separators.
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _render_human(result: Dict[str, Any]) -> str:
    summary = result.get("summary", {})
    lines = [
        "Plugin update plan",
        f"- total: {summary.get('total', 0)}",
        f"- updates: {summary.get('update', 0)}",
        f"- up_to_date: {summary.get('up_to_date', 0)}",
        f"- unknown: {summary.get('unknown', 0)}",
        "",
    ]
    for a in result.get("actions", []):
        pid = a.get("id")
        status = a.get("status")
        cur = a.get("current_version")
        lat = a.get("latest_version")
        bump = a.get("bump")
        risk = a.get("risk")
        rec = a.get("recommended")
        reason = a.get("reason")
        if status == "update":
            tag = "RECOMMENDED" if rec else "REVIEW"
            lines.append(f"* {pid}: {cur} -> {lat}  (bump={bump}, risk={risk})  [{tag}] {reason}")
        elif status == "up_to_date":
            lines.append(f"* {pid}: {cur}  (up to date)")
        else:
            lines.append(f"* {pid}: {cur}  (unknown)  {reason}")
    return "\n".join(lines).rstrip() + "\n"


def _run(
    installed: Path,
    catalog_path: Optional[Path],
    catalog_url: Optional[str],
    json_out: bool,
    include_prereleases: bool,
    timeout_s: float,
) -> int:
    req: Dict[str, Any] = {
        "installed": _read_json_file(installed),
        "include_prereleases": include_prereleases,
        "timeout_s": timeout_s,
    }
    if catalog_path is not None:
        req["catalog_path"] = str(catalog_path)
    elif catalog_url is not None:
        req["catalog_url"] = catalog_url
    else:
        raise click.ClickException("Missing catalog source: provide --catalog or --catalog-url.")

    try:
        result = plan_plugin_updates(req)
    except PluginUpdatePlannerError as e:
        if json_out:
            click.echo(_write_json(e.to_dict()))
            return 2
        raise click.ClickException(f"{e.code}: {e.message}") from e

    if json_out:
        click.echo(_write_json(result))
    else:
        click.echo(_render_human(result), nl=False)
    return 0


def _make_command(name: str) -> click.Command:
    @click.command(name=name)
    @click.option(
        "--installed",
        "installed_path",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Path to JSON describing installed plugins (list or wrapper object).",
    )
    @click.option(
        "--catalog",
        "catalog_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Path to JSON mapping plugin id -> version(s), or entries list.",
    )
    @click.option(
        "--catalog-url",
        "catalog_url",
        type=str,
        default=None,
        help="URL to JSON mapping plugin id -> version(s), or entries list.",
    )
    @click.option("--include-prereleases", is_flag=True, help="Consider prerelease versions when selecting latest.")
    @click.option("--timeout-s", type=float, default=10.0, show_default=True, help="HTTP timeout for --catalog-url.")
    @click.option("--json", "json_out", is_flag=True, help="Emit machine-readable JSON.")
    def cmd(
        installed_path: Path,
        catalog_path: Optional[Path],
        catalog_url: Optional[str],
        include_prereleases: bool,
        timeout_s: float,
        json_out: bool,
    ) -> None:
        """Plan plugin updates without applying them."""
        raise SystemExit(
            _run(
                installed=installed_path,
                catalog_path=catalog_path,
                catalog_url=catalog_url,
                json_out=json_out,
                include_prereleases=include_prereleases,
                timeout_s=timeout_s,
            )
        )

    return cmd


COMMAND = _make_command("plugin-update-planner")
ALIAS_COMMAND = _make_command("p104-plugin-update-planner")
COMMANDS = [COMMAND, ALIAS_COMMAND]


def get_commands() -> list[click.Command]:
    """Optional discovery hook for command loaders that call a getter."""
    return COMMANDS
