"""Skills management compatibility CLI commands."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import click

from thomas.cli.parity_support import (
    annotate_skill_rows as _annotate_skill_rows,
)
from thomas.cli.parity_support import (
    compat_group as _compat_group,
)
from thomas.cli.parity_support import (
    forward_passthrough as _forward_passthrough,
)
from thomas.cli.parity_support import (
    mark_skill_usage as _mark_skill_usage,
)
from thomas.cli.parity_support import (
    normalize_skill_name as _normalize_skill_name,
)
from thomas.cli.parity_support import (
    save_skills_state as _save_skills_state,
)
from thomas.cli.parity_support import (
    skill_conflicts as _skill_conflicts,
)
from thomas.cli.parity_support import (
    skills_find_rows as _skills_find_rows,
)
from thomas.cli.parity_support import (
    skills_state_path as _skills_state_path,
)
from thomas.cli.parity_support import (
    skills_sync_state as _skills_sync_state,
)
from thomas.core.config import AppConfig


@click.group(name="skills", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills(ctx: click.Context, as_json: bool) -> None:
    """Manage local Codex/Thomas skills registry and diagnostics."""
    if ctx.invoked_subcommand is not None:
        return
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    payload = _skills_summary_payload(config, state)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Skills: {payload['count']} (pinned={payload['pinned_count']}, conflicts={payload['conflict_count']})")
    click.echo(f"State file: {payload['state_file']}")


@skills.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_list(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    rows = [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)]
    payload = {"count": len(rows), "skills": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Skills: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('name')} | pinned={bool(row.get('pinned'))} | "
            f"runs={int(row.get('run_count') or 0)} | path={row.get('path')}"
        )


def _skills_show_payload(config: AppConfig, name: str) -> dict[str, Any]:
    state = _skills_sync_state(config)
    rows = _skills_find_rows(state, name)
    if not rows:
        raise click.ClickException(f"skill not found: {name}")
    _mark_skill_usage(state, rows)
    _save_skills_state(config, state)
    rows = _skills_find_rows(state, name)
    return {
        "name": str(name or "").strip(),
        "match_count": len(rows),
        "entries": rows,
        "conflict": len(rows) > 1,
    }


@skills.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_show(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    payload = _skills_show_payload(config, name)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Skill: {payload['name']} (matches={payload['match_count']})")
    for row in payload["entries"]:
        click.echo(
            f"- path={row.get('path')} | pinned={bool(row.get('pinned'))} | " f"runs={int(row.get('run_count') or 0)}"
        )
        desc = str(row.get("description") or "").strip()
        if desc:
            click.echo(f"  {desc}")


@skills.command("info")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_info(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    payload = _skills_show_payload(config, name)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Skill info: {payload['name']}")
    for row in payload["entries"]:
        click.echo(f"- file={row.get('skill_file')} | source={row.get('source_root')}")


@skills.command("sync")
@click.option("--root", "include_root", default="", help="Optional extra root to scan for skills.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_sync(ctx: click.Context, include_root: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config, include_root=include_root)
    payload = _skills_summary_payload(config, state)
    payload["roots"] = list((state.get("sync") or {}).get("roots") or [])
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Skill sync complete: {payload['count']} discovered " f"across {len(payload.get('roots') or [])} roots."
    )


@skills.command("pin")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_pin(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    rows = _skills_find_rows(state, name)
    if not rows:
        raise click.ClickException(f"skill not found: {name}")
    target = _normalize_skill_name(name)
    pinned = sorted({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()} | {target})
    state["pinned"] = pinned
    _annotate_skill_rows(state)
    _save_skills_state(config, state)
    payload = {"ok": True, "name": target, "pinned_count": len(pinned)}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Pinned skill: {target}")


@skills.command("unpin")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_unpin(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    target = _normalize_skill_name(name)
    pinned = sorted(
        {
            str(x).strip().lower()
            for x in (state.get("pinned") or [])
            if str(x).strip() and str(x).strip().lower() != target
        }
    )
    removed = len(pinned) != len({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()})
    state["pinned"] = pinned
    _annotate_skill_rows(state)
    _save_skills_state(config, state)
    payload = {"ok": removed, "name": target, "pinned_count": len(pinned)}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if removed:
        click.echo(f"Unpinned skill: {target}")
    else:
        click.echo(f"Skill not pinned: {target}")
        raise SystemExit(1)


@skills.command("conflicts")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_conflicts(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    rows = [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)]
    conflicts = _skill_conflicts(rows)
    payload = {"count": len(conflicts), "conflicts": conflicts}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Skill conflicts: {len(conflicts)}")
    for row in conflicts:
        click.echo(f"- {row.get('name')} ({row.get('count')})")
        for path in row.get("paths") or []:
            click.echo(f"  {path}")


@skills.command("analytics")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_analytics(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    rows = [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)]
    conflicts = _skill_conflicts(rows)
    total_runs = sum(int(row.get("run_count") or 0) for row in rows)
    top_used = sorted(
        [
            {
                "name": str(row.get("name") or ""),
                "path": str(row.get("path") or ""),
                "run_count": int(row.get("run_count") or 0),
                "last_used_at": str(row.get("last_used_at") or ""),
            }
            for row in rows
        ],
        key=lambda item: (-int(item.get("run_count") or 0), str(item.get("name") or "").lower()),
    )[:10]
    payload = {
        "ok": True,
        "total_skills": len(rows),
        "pinned_count": len({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()}),
        "conflict_count": len(conflicts),
        "total_runs": int(total_runs),
        "top_used": top_used,
        "roots": list((state.get("sync") or {}).get("roots") or []),
        "last_sync_at": str((state.get("sync") or {}).get("last_sync_at") or ""),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Skills analytics: total={payload['total_skills']} "
        f"pinned={payload['pinned_count']} conflicts={payload['conflict_count']} runs={payload['total_runs']}"
    )


@skills.command("check")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_check(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    state = _skills_sync_state(config)
    rows = [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)]
    conflicts = _skill_conflicts(rows)
    issues: list[dict[str, Any]] = []
    for row in rows:
        file_path = Path(str(row.get("skill_file") or ""))
        if not file_path.exists():
            issues.append(
                {
                    "code": "missing_skill_file",
                    "name": str(row.get("name") or ""),
                    "path": str(file_path),
                }
            )
    if conflicts:
        for conflict in conflicts:
            issues.append(
                {
                    "code": "name_conflict",
                    "name": str(conflict.get("name") or ""),
                    "count": int(conflict.get("count") or 0),
                }
            )
    payload = {
        "ok": len(issues) == 0,
        "issues": issues,
        "summary": _skills_summary_payload(config, state),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            click.echo("Skills check passed.")
        else:
            click.echo(f"Skills check failed: {len(issues)} issue(s).")
            for issue in issues:
                click.echo(f"- {issue.get('code')}: {issue.get('name')}")
    if not payload["ok"]:
        raise SystemExit(1)


@skills.command("resolve")
@click.option("--prompt", required=True, help="Prompt text to resolve runtime skills for.")
@click.option("--route-path", default="coding_task", show_default=True, help="Route path hint (for relevance scoring).")
@click.option("--cwd", default="", help="Optional working directory used for skill discovery roots.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def skills_resolve(
    ctx: click.Context,
    prompt: str,
    route_path: str,
    cwd: str,
    as_json: bool,
) -> None:
    """Resolve runtime skill selection for a prompt (model-agnostic)."""
    from thomas.agent.skills_runtime import (
        format_runtime_skills_context,
        resolve_runtime_skills,
    )

    config: AppConfig = ctx.obj["config"]
    cwd_text = str(cwd or "").strip()
    if cwd_text:
        try:
            run_cwd = Path(cwd_text).expanduser().resolve()
        except ImportError:
            run_cwd = Path.cwd()
    else:
        run_cwd = Path.cwd()

    selection = resolve_runtime_skills(
        config,
        prompt_text=str(prompt or ""),
        relevance_text=str(prompt or ""),
        route_path=str(route_path or ""),
        cwd=run_cwd,
    )
    payload = selection.to_event_payload()
    payload["context"] = format_runtime_skills_context(selection)

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo(
        f"Runtime skills resolved: selected={int(payload.get('selected_count') or 0)} "
        f"discovered={int(payload.get('discovered_count') or 0)}"
    )
    for row in payload.get("selected") or []:
        click.echo(f"- {row.get('name')} | reason={row.get('reason')} | path={row.get('path')}")


security = _compat_group(
    "security",
    [
        ("status", "Security posture is enforced by guardrail scripts."),
        ("scan", "Use dedicated security skills/scripts for deep analysis."),
        ("audit", "Run aggregated security governance/dependency/cadence audit."),
    ],
)
update = _compat_group(
    "update",
    [
        ("check", "Use doppelganger + release hygiene checks for full verification."),
        ("status", "Release channel readiness can be inspected through quality gates."),
        ("wizard", "Upgrade wizard flow is tracked through release playbooks."),
        ("apply", "Use doppelganger rollout commands for real apply operations."),
    ],
)


@click.command(name="completion")
@click.argument("shell", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def completion_cmd(shell: str | None, as_json: bool) -> None:
    """Print shell-completion bootstrap instructions for Thomas CLI."""
    requested = str(shell or "").strip().lower()
    if requested in {"pwsh", "powershell"}:
        requested = "powershell"
    supported = {"bash", "zsh", "fish", "powershell"}
    if requested and requested not in supported:
        raise click.ClickException(f"Unsupported shell '{requested}'. Choose one of: {', '.join(sorted(supported))}.")

    default_shell = "powershell" if os.name == "nt" else "bash"
    target_shell = requested or default_shell
    mode = {
        "bash": "bash_source",
        "zsh": "zsh_source",
        "fish": "fish_source",
        "powershell": "powershell_source",
    }[target_shell]
    if target_shell == "powershell":
        command = f"$env:_THOMAS_COMPLETE='{mode}'; python -m thomas"
    else:
        command = f"_THOMAS_COMPLETE={mode} python -m thomas"

    payload = {
        "command": "completion",
        "shell": target_shell,
        "env_var": "_THOMAS_COMPLETE",
        "mode": mode,
        "generate_command": command,
        "note": "Run the command and append output to your shell profile to enable tab completion.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo(f"shell: {target_shell}")
    click.echo("generate completion script:")
    click.echo(f"  {command}")
    click.echo("note: append the output to your shell profile to persist completion.")


@click.command(name="qr", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def qr_cmd(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Generate a device pairing token (compat wrapper over `devices pair`)."""
    extras = [str(x) for x in args]
    has_name = any(item == "--name" or item.startswith("--name=") for item in extras)
    if not has_name:
        extras.extend(["--name", f"qr-{int(time.time())}"])
    _forward_passthrough(ctx, ["devices", "pair"], tuple(extras))


@click.command(
    name="plugin",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def plugin_cmd(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Claude-style singular plugin alias (maps to `plugins ...`)."""
    extras = [str(x) for x in args]
    if not extras:
        extras = ["--help"]
    _forward_passthrough(ctx, ["plugins"], tuple(extras))


def _skills_summary_payload(config: AppConfig, state: dict[str, Any]) -> dict[str, Any]:
    """Generate a skills summary payload from state."""
    rows = [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)]
    conflicts = _skill_conflicts(rows)
    pinned = sorted({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()})
    return {
        "count": len(rows),
        "unique_names": len(
            {str(row.get("name") or "").strip().lower() for row in rows if str(row.get("name") or "").strip()}
        ),
        "pinned_count": len(pinned),
        "conflict_count": len(conflicts),
        "state_file": str(_skills_state_path(config)),
        "sync": dict(state.get("sync") or {}),
    }
