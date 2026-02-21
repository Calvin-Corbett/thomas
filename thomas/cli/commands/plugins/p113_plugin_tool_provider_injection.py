"""
CLI command for P113 - plugin tool provider injection.

This command is meant for "GAP run" automation and supports `--json` output.

The CLI implementation is intentionally defensive:
- It tries to locate/create a tool registry via Thomas' public interfaces when present.
- It produces deterministic machine-readable errors.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

try:  # pragma: no cover
    import typer
except Exception:  # pragma: no cover
    typer = None  # type: ignore

from thomas.plugins.p113_plugin_tool_provider_injection import (
    InjectionErrorCode,
    ToolProviderInjectionError,
    ToolProviderInjectionRequest,
    ToolProviderInjectionResult,
    inject_tool_provider,
)

# -----------------------------
# Public I/O contracts
# -----------------------------


@dataclass(frozen=True)
class CliInput:
    provider_id: str
    tool_name: str
    json_output: bool = False


@dataclass(frozen=True)
class CliOutput:
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload, sort_keys=True)


# -----------------------------
# Core runner (importable)
# -----------------------------


def run_cli(
    *,
    provider_id: str,
    tool_name: str,
    json_output: bool = False,
    registry: Any = None,
) -> Tuple[int, str]:
    """Execute the injection flow and return (exit_code, stdout)."""

    try:
        if registry is None:
            registry = _resolve_registry()

        req = ToolProviderInjectionRequest(provider_id=provider_id, tool_name=tool_name, enabled=True)
        result = inject_tool_provider(registry, req)

        out = CliOutput(ok=True, result=result.to_json())
        if json_output:
            return 0, out.to_json() + "\n"
        return 0, _format_human_success(result)

    except ToolProviderInjectionError as exc:
        err_payload = {"code": exc.code, "message": exc.message}
        out = CliOutput(ok=False, error=err_payload)
        if json_output:
            return 2, out.to_json() + "\n"
        return 2, _format_human_error(err_payload)

    except Exception as exc:  # pragma: no cover
        # Unexpected errors are still made deterministic.
        err_payload = {"code": InjectionErrorCode.EXTERNAL_FAILURE, "message": f"Unexpected: {exc.__class__.__name__}."}
        out = CliOutput(ok=False, error=err_payload)
        if json_output:
            return 3, out.to_json() + "\n"
        return 3, _format_human_error(err_payload)


def _format_human_success(result: ToolProviderInjectionResult) -> str:
    tools = ", ".join(result.injected_tool_names) if result.injected_tool_names else "(none)"
    return f"Injected provider '{result.provider_id}' with tools: {tools}\n"


def _format_human_error(err: Dict[str, Any]) -> str:
    return f"ERROR[{err.get('code')}]: {err.get('message')}\n"


def _resolve_registry() -> Any:
    """Best-effort registry resolution without hard-coding Thomas internals."""

    # Try common patterns in thomas.tools.registry
    try:
        from thomas.tools import registry as registry_mod  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ToolProviderInjectionError(InjectionErrorCode.MISSING_CONFIG, "Thomas tool registry module not available.") from exc

    # 1) Global singleton
    for attr in ("REGISTRY", "registry", "tool_registry", "TOOLS"):
        reg = getattr(registry_mod, attr, None)
        if reg is not None:
            return reg

    # 2) Factory function
    for attr in ("get_registry", "get_tool_registry", "default_registry"):
        fn = getattr(registry_mod, attr, None)
        if callable(fn):
            return fn()

    # 3) Class constructor
    for attr in ("ToolRegistry", "Registry"):
        cls = getattr(registry_mod, attr, None)
        if cls is not None:
            try:
                return cls()
            except Exception:
                continue

    raise ToolProviderInjectionError(
        InjectionErrorCode.MISSING_CONFIG,
        "Unable to resolve a tool registry instance from thomas.tools.registry.",
    )


# -----------------------------
# Typer integration (optional)
# -----------------------------


if typer is not None:  # pragma: no cover
    app = typer.Typer(help="P113: inject a tool provider via a plugin-like flow.")

    @app.command("p113-tool-provider-injection")
    def main(
        provider_id: str = typer.Option("p113.injected", "--provider-id", help="Injected provider identifier."),
        tool_name: str = typer.Option("p113_echo", "--tool-name", help="Tool name exposed by the injected provider."),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        code, out = run_cli(provider_id=provider_id, tool_name=tool_name, json_output=json_output)
        typer.echo(out, nl=False)
        raise typer.Exit(code=code)

else:
    app = None  # type: ignore

# Additional discovery-friendly aliases used across different Thomas CLI loaders.
COMMAND_NAME = "p113-tool-provider-injection"

# Some Thomas CLI registries expect a Click command, others expect a Typer app.
# Provide both, without making import-time assumptions about the registry.
try:  # pragma: no cover
    from typer.main import get_command as _typer_get_command  # type: ignore
except Exception:  # pragma: no cover
    _typer_get_command = None  # type: ignore

click_command = _typer_get_command(app) if (_typer_get_command is not None and app is not None) else None
COMMAND = click_command or app
command = COMMAND  # alias

# Backwards-compatible alias names some loaders use.
APP = app
CLI_APP = app


def get_app():
    return app


__all__ = [
    "CliInput",
    "CliOutput",
    "run_cli",
    "COMMAND_NAME",
    "COMMAND",
    "command",
    "APP",
    "CLI_APP",
    "click_command",
    "get_app",
    "app",
]
