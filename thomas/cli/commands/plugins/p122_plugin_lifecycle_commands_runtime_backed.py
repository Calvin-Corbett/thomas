from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.plugins import p122_plugin_lifecycle_commands_runtime_backed as plc


def _exit_code_for_error(err: plc.PluginLifecycleError) -> int:
    """Map deterministic errors to stable exit codes.

    - 2: caller error (invalid input / missing config)
    - 3: runtime communication / response issues
    - 4: plugin not found
    - 5: runtime operation failed
    """

    return {
        "invalid_request": 2,
        "missing_runtime_config": 2,
        "runtime_unavailable": 3,
        "runtime_response_error": 3,
        "plugin_not_found": 4,
        "runtime_operation_failed": 5,
    }.get(getattr(err, "code", ""), 1)


def _emit_result(result: plc.PluginLifecycleResult, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=None, sort_keys=True))
        return

    if result.action == "list":
        if not result.plugins:
            typer.echo("No plugins reported by runtime")
            return
        for p in result.plugins:
            typer.echo(f"{p.name}\t{p.status}")
        return

    if result.plugin_state is not None:
        p = result.plugin_state
        typer.echo(f"{p.name}: {p.status}")
        return

    typer.echo("OK")


def _emit_error(
    err: plc.PluginLifecycleError,
    *,
    action: str,
    plugin: str | None,
    json_output: bool,
) -> None:
    error_info = err.to_error_info()

    if json_output:
        result = plc.PluginLifecycleResult(
            ok=False,
            action=action,  # type: ignore[arg-type]
            plugin=plugin,
            error=error_info,
        )
        typer.echo(json.dumps(result.to_dict(), indent=None, sort_keys=True))
        return

    typer.echo(f"Error [{error_info.code}]: {error_info.message}", err=True)


def _common_options() -> dict[str, Any]:
    """Shared typer.Option instances."""

    return {
        "gateway_url": typer.Option(
            None,
            "--gateway-url",
            help="Base URL for the running Thomas gateway (overrides env/config).",
            envvar="THOMAS_GATEWAY_URL",
        ),
        "config": typer.Option(
            None,
            "--config",
            help="Optional config file (JSON/TOML) to locate the gateway URL.",
            exists=True,
            dir_okay=False,
            file_okay=True,
            readable=True,
        ),
        "timeout": typer.Option(
            plc.DEFAULT_TIMEOUT_S,
            "--timeout",
            help="HTTP timeout in seconds.",
        ),
        "json_output": typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON.",
        ),
    }


def _register_commands(app: typer.Typer) -> None:
    opts = _common_options()

    @app.command("list")
    def list_cmd(
        gateway_url: Optional[str] = opts["gateway_url"],
        config: Optional[Path] = opts["config"],
        timeout: float = opts["timeout"],
        json_output: bool = opts["json_output"],
    ) -> None:
        """List plugins as reported by the runtime."""

        try:
            result = plc.list_plugins(gateway_url=gateway_url, config_path=config, timeout_s=timeout)
            _emit_result(result, json_output=json_output)
        except plc.PluginLifecycleError as err:
            _emit_error(err, action="list", plugin=None, json_output=json_output)
            raise typer.Exit(code=_exit_code_for_error(err)) from err

    @app.command("status")
    def status_cmd(
        plugin: str = typer.Argument(..., help="Plugin identifier"),
        gateway_url: Optional[str] = opts["gateway_url"],
        config: Optional[Path] = opts["config"],
        timeout: float = opts["timeout"],
        json_output: bool = opts["json_output"],
    ) -> None:
        """Get runtime status for a plugin."""

        try:
            result = plc.plugin_status(plugin, gateway_url=gateway_url, config_path=config, timeout_s=timeout)
            _emit_result(result, json_output=json_output)
        except plc.PluginLifecycleError as err:
            _emit_error(err, action="status", plugin=plugin, json_output=json_output)
            raise typer.Exit(code=_exit_code_for_error(err)) from err

    @app.command("start")
    def start_cmd(
        plugin: str = typer.Argument(..., help="Plugin identifier"),
        gateway_url: Optional[str] = opts["gateway_url"],
        config: Optional[Path] = opts["config"],
        timeout: float = opts["timeout"],
        json_output: bool = opts["json_output"],
    ) -> None:
        """Start a plugin in the runtime."""

        try:
            result = plc.start_plugin(plugin, gateway_url=gateway_url, config_path=config, timeout_s=timeout)
            _emit_result(result, json_output=json_output)
        except plc.PluginLifecycleError as err:
            _emit_error(err, action="start", plugin=plugin, json_output=json_output)
            raise typer.Exit(code=_exit_code_for_error(err)) from err

    @app.command("stop")
    def stop_cmd(
        plugin: str = typer.Argument(..., help="Plugin identifier"),
        gateway_url: Optional[str] = opts["gateway_url"],
        config: Optional[Path] = opts["config"],
        timeout: float = opts["timeout"],
        json_output: bool = opts["json_output"],
    ) -> None:
        """Stop a plugin in the runtime."""

        try:
            result = plc.stop_plugin(plugin, gateway_url=gateway_url, config_path=config, timeout_s=timeout)
            _emit_result(result, json_output=json_output)
        except plc.PluginLifecycleError as err:
            _emit_error(err, action="stop", plugin=plugin, json_output=json_output)
            raise typer.Exit(code=_exit_code_for_error(err)) from err

    @app.command("restart")
    def restart_cmd(
        plugin: str = typer.Argument(..., help="Plugin identifier"),
        gateway_url: Optional[str] = opts["gateway_url"],
        config: Optional[Path] = opts["config"],
        timeout: float = opts["timeout"],
        json_output: bool = opts["json_output"],
    ) -> None:
        """Restart a plugin in the runtime."""

        try:
            result = plc.restart_plugin(plugin, gateway_url=gateway_url, config_path=config, timeout_s=timeout)
            _emit_result(result, json_output=json_output)
        except plc.PluginLifecycleError as err:
            _emit_error(err, action="restart", plugin=plugin, json_output=json_output)
            raise typer.Exit(code=_exit_code_for_error(err)) from err


def _resolve_parent_plugins_app() -> typer.Typer | None:
    """Try to attach commands to the existing `plugins` command group."""

    try:
        import thomas.cli.commands.plugins as plugins_pkg

        for attr in ("app", "plugins_app", "typer_app"):
            candidate = getattr(plugins_pkg, attr, None)
            if isinstance(candidate, typer.Typer):
                return candidate
    except Exception:
        return None

    return None


_standalone_app = typer.Typer(help="Manage plugin lifecycle via the runtime gateway")
_register_commands(_standalone_app)

_parent_app = _resolve_parent_plugins_app()
if _parent_app is not None and _parent_app is not _standalone_app:
    _register_commands(_parent_app)


def get_typer_app() -> typer.Typer:
    """Return a standalone Typer app containing only the lifecycle commands."""

    return _standalone_app


def register(app: typer.Typer) -> None:
    """Registration hook for CLIs that use explicit command registration."""

    _register_commands(app)


app = _standalone_app

try:  # pragma: no cover
    cli = typer.main.get_command(app)
except Exception:  # pragma: no cover
    cli = None
