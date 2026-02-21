"""CLI command: `thomas plugins doctor`.

This command is a thin wrapper over :func:`thomas.plugins.p119_plugin_doctor_command.run_plugin_doctor`.
It supports:
- human-readable output by default
- machine-readable JSON output via `--json`

The module exports:
- `COMMAND` (a Click command object) for Click-based CLIs
- `register(target)` best-effort registration for Click, Typer, or argparse-style CLIs
"""

from __future__ import annotations

import json
from typing import Any, Optional

try:
    import click
except Exception:  # pragma: no cover
    click = None  # type: ignore[assignment]

try:
    import typer
except Exception:  # pragma: no cover
    typer = None  # type: ignore[assignment]

from thomas.plugins.p119_plugin_doctor_command import (
    PluginDoctorError,
    PluginDoctorReport,
    PluginDoctorRequest,
    run_plugin_doctor,
)


def _format_human(report: PluginDoctorReport) -> str:
    lines = []
    lines.append(f"Plugin diagnostics: {'OK' if report.ok else 'PROBLEMS FOUND'}")
    if report.inspected:
        lines.append(f"Inspected plugins: {len(report.inspected)}")
    for check in report.checks:
        lines.append(f"- [{check.status.upper()}] {check.id}: {check.summary}")
    return "\n".join(lines)


def _emit_report(report: PluginDoctorReport, *, json_mode: bool) -> str:
    if json_mode:
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    return _format_human(report)


def _emit_error(err: PluginDoctorError, *, json_mode: bool) -> str:
    payload = {"ok": False, "error": {"code": err.code, "message": str(err)}}
    if json_mode:
        return json.dumps(payload, indent=2, sort_keys=True)
    return f"ERROR[{err.code}]: {err}"


def run_cli(
    *,
    plugin: Optional[str] = None,
    config_path: Optional[str] = None,
    include_hidden: bool = False,
    strict: bool = False,
    json_mode: bool = False,
) -> tuple[int, str]:
    """Programmatic entrypoint used by tests and by the CLI wrapper."""
    try:
        report = run_plugin_doctor(
            PluginDoctorRequest(
                plugin=plugin,
                config_path=config_path,
                include_hidden=include_hidden,
                strict=strict,
            )
        )
    except PluginDoctorError as e:
        return e.exit_code, _emit_error(e, json_mode=json_mode)

    return (0 if report.ok else 1), _emit_report(report, json_mode=json_mode)


# ----------------------------
# Click command
# ----------------------------

if click is not None:

    @click.command(name="doctor")  # type: ignore[misc]
    @click.option("--plugin", default=None, help="Inspect only one plugin module.")
    @click.option("--config", "config_path", default=None, help="Config file path to validate exists.")
    @click.option(
        "--include-hidden",
        is_flag=True,
        default=False,
        help="Include plugins starting with '_' in discovery.",
    )
    @click.option("--strict", is_flag=True, default=False, help="Treat warnings as failures.")
    @click.option("--json", "json_mode", is_flag=True, default=False, help="Emit JSON.")
    def doctor_command(
        plugin: Optional[str],
        config_path: Optional[str],
        include_hidden: bool,
        strict: bool,
        json_mode: bool,
    ) -> None:
        exit_code, out = run_cli(
            plugin=plugin,
            config_path=config_path,
            include_hidden=include_hidden,
            strict=strict,
            json_mode=json_mode,
        )

        # In JSON mode, keep output on stdout for automation.
        if json_mode:
            click.echo(out)
        else:
            click.echo(out, err=(exit_code != 0))

        raise SystemExit(exit_code)


    COMMAND = doctor_command
else:  # pragma: no cover
    COMMAND = None


# ----------------------------
# Typer command (registration helper)
# ----------------------------

if typer is not None:

    def _typer_doctor(
        plugin: Optional[str] = typer.Option(None, "--plugin", help="Inspect only one plugin module."),
        config_path: Optional[str] = typer.Option(
            None, "--config", help="Config file path to validate exists."
        ),
        include_hidden: bool = typer.Option(
            False, "--include-hidden", help="Include plugins starting with '_' in discovery."
        ),
        strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
        json_mode: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        exit_code, out = run_cli(
            plugin=plugin,
            config_path=config_path,
            include_hidden=include_hidden,
            strict=strict,
            json_mode=json_mode,
        )
        typer.echo(out)
        raise typer.Exit(code=exit_code)

else:  # pragma: no cover
    _typer_doctor = None  # type: ignore[assignment]


# ----------------------------
# Registration helper
# ----------------------------

def register(target: Any) -> None:
    """Register the command on a supported CLI target (best-effort)."""
    if target is None:
        return

    # Click Group
    if click is not None and COMMAND is not None and hasattr(target, "add_command"):
        try:
            target.add_command(COMMAND)  # type: ignore[attr-defined]
            return
        except Exception:
            pass

    # Typer App
    if typer is not None and _typer_doctor is not None and hasattr(target, "command"):
        try:
            target.command("doctor")(_typer_doctor)  # type: ignore[attr-defined]
            return
        except Exception:
            pass

    # argparse subparsers
    if hasattr(target, "add_parser"):
        parser = target.add_parser("doctor", help="Run plugin diagnostics.")
        parser.add_argument("--plugin", default=None)
        parser.add_argument("--config", dest="config_path", default=None)
        parser.add_argument("--include-hidden", action="store_true", default=False)
        parser.add_argument("--strict", action="store_true", default=False)
        parser.add_argument("--json", dest="json_mode", action="store_true", default=False)

        def _runner(ns: Any) -> int:
            code, out = run_cli(
                plugin=getattr(ns, "plugin", None),
                config_path=getattr(ns, "config_path", None),
                include_hidden=getattr(ns, "include_hidden", False),
                strict=getattr(ns, "strict", False),
                json_mode=getattr(ns, "json_mode", False),
            )
            print(out)
            return code

        parser.set_defaults(func=_runner)
        return

    # If we get here, we couldn't attach the command.
    raise RuntimeError("Unsupported CLI target for plugins doctor registration")
