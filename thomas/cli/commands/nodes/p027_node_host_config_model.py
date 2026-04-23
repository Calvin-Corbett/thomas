"""CLI command: nodes host-config-model

Print the node-host configuration model (JSON Schema + optional hints).

Machine-readable mode: --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from thomas.nodes.p027_node_host_config_model import (
    NodeHostConfigModelError,
    NodeHostConfigModelRequest,
    node_host_config_model,
)

COMMAND_GROUP = "nodes"
COMMAND_NAME = "host-config-model"
HELP = "Print the node-host configuration model (JSON Schema)."


def build_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Optional path to a config file to include current nodeHost settings.",
    )
    parser.add_argument(
        "--include-current",
        action="store_true",
        help="Include current nodeHost settings from --config.",
    )
    parser.add_argument(
        "--no-example",
        action="store_true",
        help="Omit the example snippet from output.",
    )
    parser.add_argument(
        "--no-ui-hints",
        action="store_true",
        help="Omit UI hints from output.",
    )


def _dumps(payload: dict, *, json_mode: bool) -> str:
    if json_mode:
        return json.dumps(payload, sort_keys=True)
    return json.dumps(payload, indent=2, sort_keys=True)


def _success_envelope(result: dict) -> dict:
    # Keep `schema` at the top level for client convenience, but also include `ok`
    # for tooling that expects a standard success flag.
    return {"ok": True, **result}


def _error_envelope(err: NodeHostConfigModelError) -> dict:
    return {"ok": False, "error": err.to_dict()}


def run_from_args(args: argparse.Namespace) -> int:
    try:
        req = NodeHostConfigModelRequest(
            config_path=args.config_path,
            include_current=bool(args.include_current),
            include_example=not bool(args.no_example),
            include_ui_hints=not bool(args.no_ui_hints),
        )
        result = node_host_config_model(req).to_dict()
    except NodeHostConfigModelError as e:
        sys.stdout.write(_dumps(_error_envelope(e), json_mode=bool(args.json_mode)) + "\n")
        return 2

    sys.stdout.write(_dumps(_success_envelope(result), json_mode=bool(args.json_mode)) + "\n")
    return 0


def cli(argv: Sequence[str] | None = None) -> int:
    """Entrypoint usable by tests."""

    parser = argparse.ArgumentParser(prog=f"{COMMAND_GROUP} {COMMAND_NAME}")
    build_parser(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_from_args(args)


# Optional Typer integration (Thomas may use Typer for command registration).
def register(app: object) -> None:  # pragma: no cover
    """Register this command on a Typer app if available."""

    try:
        import typer  # type: ignore
    except ImportError:
        return

    if not hasattr(app, "command"):
        return

    @app.command(COMMAND_NAME, help=HELP)  # type: ignore[misc]
    def _cmd(
        json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),  # type: ignore[name-defined]
        config_path: Path | None = typer.Option(None, "--config", help="Optional path to a config file."),
        include_current: bool = typer.Option(
            False, "--include-current", help="Include current nodeHost settings from --config."
        ),
        no_example: bool = typer.Option(False, "--no-example", help="Omit the example snippet."),  # type: ignore[name-defined]
        no_ui_hints: bool = typer.Option(False, "--no-ui-hints", help="Omit UI hints."),  # type: ignore[name-defined]
    ) -> None:
        ns = argparse.Namespace(
            json_mode=json_mode,
            config_path=str(config_path) if config_path is not None else None,
            include_current=include_current,
            no_example=no_example,
            no_ui_hints=no_ui_hints,
        )
        rc = run_from_args(ns)
        raise typer.Exit(code=rc)


def get_command_spec() -> dict:
    """Return a lightweight command spec for registries."""

    return {
        "group": COMMAND_GROUP,
        "name": COMMAND_NAME,
        "help": HELP,
        "build_parser": build_parser,
        "run_from_args": run_from_args,
    }


COMMAND_SPEC = get_command_spec()

# Registry-friendly aliases (different parts of the codebase may look for different names).
SPEC = COMMAND_SPEC
COMMAND = COMMAND_SPEC
COMMANDS = [COMMAND_SPEC]


def _try_build_parity_command() -> object | None:
    """Best-effort bridge into Thomas' parity command registry."""

    try:
        from thomas.cli import parity_compat  # type: ignore
    except ImportError:
        return None

    import inspect

    for attr_name in ("ParityCommand", "Command", "ParityCommandSpec", "ParitySpec"):
        cls = getattr(parity_compat, attr_name, None)
        if cls is None:
            continue
        try:
            sig = inspect.signature(cls)
        except ImportError:
            continue

        kwargs: dict[str, object] = {}
        for pname in sig.parameters.keys():
            if pname in ("group", "command_group"):
                kwargs[pname] = COMMAND_GROUP
            elif pname in ("name", "command_name", "command"):
                kwargs[pname] = COMMAND_NAME
            elif pname in ("help", "description"):
                kwargs[pname] = HELP
            elif pname in ("build_parser", "parser_builder", "add_parser"):
                kwargs[pname] = build_parser
            elif pname in ("run", "handler", "callback", "fn"):
                kwargs[pname] = run_from_args

        try:
            return cls(**kwargs)
        except Exception:  # REVIEWED: broad catch
            continue

    return None


PARITY_COMMAND = _try_build_parity_command()
PARITY_COMMANDS = [PARITY_COMMAND] if PARITY_COMMAND is not None else []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli())
