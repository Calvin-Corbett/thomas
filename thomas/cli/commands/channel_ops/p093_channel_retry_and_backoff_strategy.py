"""CLI command: channel retry/backoff strategy.

This command is intended for operators and automation to:
- validate retry policy configuration
- preview the computed backoff schedule

The surrounding Thomas CLI typically discovers channel operation modules and
registers them under a `channels` command group.

To maximize compatibility with different command-wiring styles, this module
exposes:
- `register(subparsers)` for argparse-based CLIs
- `get_click_command()` (and alias `get_command`) for click-based CLIs
- `COMMAND_NAME` + `COMMAND_ALIASES`

Machine readable output:
- `--json` emits a single JSON object with stable keys
- `--schema` prints the JSON schema for that JSON payload

"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from thomas.channels.p093_channel_retry_and_backoff_strategy import (
    ChannelRetryConfigError,
    ChannelRetryError,
    RetryPlan,
    RetryPolicy,
    build_retry_plan,
    policy_from_mapping,
    retry_plan_json_schema,
)


COMMAND_NAME = "retry-backoff"
COMMAND_ALIASES = ("retry-strategy", "backoff-strategy")


@dataclass(frozen=True, slots=True)
class RetryBackoffCliRequest:
    """Input contract for the CLI entrypoint."""

    config_path: str | None
    attempts: int | None
    base_delay_s: float | None
    max_delay_s: float | None
    backoff_factor: float | None
    jitter: float | None
    jitter_seed: int | None
    json: bool
    schema: bool


@dataclass(frozen=True, slots=True)
class RetryBackoffCliError:
    """Machine-friendly error payload."""

    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class RetryBackoffCliResponse:
    """Output contract.

    Success:
        {"ok": true, "plan": {...}}

    Failure:
        {"ok": false, "error": {"code": "...", "message": "..."}}
    """

    ok: bool
    plan: RetryPlan | None = None
    error: RetryBackoffCliError | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            assert self.plan is not None
            return {"ok": True, "plan": self.plan.to_dict()}
        assert self.error is not None
        return {"ok": False, "error": self.error.to_dict()}


def _load_json_file(path: str) -> Mapping[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ChannelRetryConfigError(
            "config_not_found", f"Retry policy config file not found: {path}"
        )

    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChannelRetryConfigError(
            "config_read_failed", f"Unable to read retry policy config file: {path}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChannelRetryConfigError(
            "invalid_config_json",
            f"Retry policy config file is not valid JSON: {path}",
        ) from exc

    if not isinstance(data, dict):
        raise ChannelRetryConfigError(
            "invalid_config_format",
            "Retry policy config JSON must be an object at the top level",
        )

    return data


def _resolve_policy(req: RetryBackoffCliRequest) -> RetryPolicy:
    # Start from file config (if provided), then overlay explicit CLI options.
    data: dict[str, Any] = {}
    if req.config_path:
        data.update(_load_json_file(req.config_path))

    if req.attempts is not None:
        data["max_attempts"] = req.attempts
    if req.base_delay_s is not None:
        data["base_delay_s"] = req.base_delay_s
    if req.max_delay_s is not None:
        data["max_delay_s"] = req.max_delay_s
    if req.backoff_factor is not None:
        data["backoff_factor"] = req.backoff_factor
    if req.jitter is not None:
        data["jitter"] = req.jitter
    if req.jitter_seed is not None:
        data["jitter_seed"] = req.jitter_seed

    # policy_from_mapping is strict about mapping presence, but accepts an empty
    # mapping and fills in defaults.
    return policy_from_mapping(data)


def cli_json_schema() -> dict[str, Any]:
    plan_schema = retry_plan_json_schema()

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "plan": plan_schema,
            "error": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
        "allOf": [
            {
                "if": {"properties": {"ok": {"const": True}}},
                "then": {"required": ["plan"]},
            },
            {
                "if": {"properties": {"ok": {"const": False}}},
                "then": {"required": ["error"]},
            },
        ],
    }


def run_from_request(req: RetryBackoffCliRequest) -> RetryBackoffCliResponse:
    policy = _resolve_policy(req)
    plan = build_retry_plan(policy)
    return RetryBackoffCliResponse(ok=True, plan=plan)


def _emit_response(resp: RetryBackoffCliResponse, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(resp.to_dict(), sort_keys=True))
        return

    if not resp.ok:
        assert resp.error is not None
        print(f"ERROR[{resp.error.code}]: {resp.error.message}", file=sys.stderr)
        return

    assert resp.plan is not None
    print("Retry policy:")
    for k, v in resp.plan.policy.to_dict().items():
        print(f"  {k}: {v}")

    print("\nBackoff schedule:")
    for step in resp.plan.steps:
        print(f"  retry #{step.retry_index}: wait {step.delay_s:.3f}s ({step.reason})")
    print(f"\nTotal planned delay: {resp.plan.total_delay_s:.3f}s")


def _emit_error(err: ChannelRetryError | Exception, *, as_json: bool) -> None:
    if isinstance(err, ChannelRetryError):
        payload = RetryBackoffCliResponse(
            ok=False, error=RetryBackoffCliError(code=err.code, message=str(err))
        )
    else:
        payload = RetryBackoffCliResponse(
            ok=False,
            error=RetryBackoffCliError(
                code="unexpected_error", message=f"Unexpected error: {err}"  # stable prefix
            ),
        )

    _emit_response(payload, as_json=as_json)


# ---------------------------------------------------------------------------
# Argparse integration (expected by thomas/cli/commands/channels.py)
# ---------------------------------------------------------------------------


def register(subparsers: Any) -> None:
    """Register the subcommand with an argparse subparsers object."""

    add_parser = getattr(subparsers, "add_parser", None)
    if add_parser is None:
        raise TypeError("register() expected an argparse subparsers object")

    parser = add_parser(
        COMMAND_NAME,
        aliases=list(COMMAND_ALIASES),
        help="Preview/validate channel retry + backoff schedule",
    )

    parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a JSON retry policy file",
        default=None,
    )

    # Use None defaults so we can distinguish explicit overrides.
    parser.add_argument("--attempts", type=int, default=None)
    parser.add_argument("--base-delay", dest="base_delay_s", type=float, default=None)
    parser.add_argument("--max-delay", dest="max_delay_s", type=float, default=None)
    parser.add_argument("--factor", dest="backoff_factor", type=float, default=None)
    parser.add_argument("--jitter", type=float, default=None)
    parser.add_argument("--jitter-seed", dest="jitter_seed", type=int, default=None)

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for --json output and exit",
    )

    parser.set_defaults(func=_handle_args, handler=_handle_args)


def _handle_args(args: Any) -> None:
    req = RetryBackoffCliRequest(
        config_path=getattr(args, "config_path", None),
        attempts=getattr(args, "attempts", None),
        base_delay_s=getattr(args, "base_delay_s", None),
        max_delay_s=getattr(args, "max_delay_s", None),
        backoff_factor=getattr(args, "backoff_factor", None),
        jitter=getattr(args, "jitter", None),
        jitter_seed=getattr(args, "jitter_seed", None),
        json=bool(getattr(args, "json", False)),
        schema=bool(getattr(args, "schema", False)),
    )

    if req.schema:
        print(json.dumps(cli_json_schema(), indent=2, sort_keys=True))
        return

    try:
        resp = run_from_request(req)
        _emit_response(resp, as_json=req.json)
    except ChannelRetryError as err:
        _emit_error(err, as_json=req.json)
        raise SystemExit(2) from err
    except Exception as err:
        _emit_error(err, as_json=req.json)
        raise SystemExit(1) from err


# ---------------------------------------------------------------------------
# Click integration (best-effort)
# ---------------------------------------------------------------------------


def get_click_command() -> Any:
    """Return a click.Command for this operation.

    If click is not available, raises ImportError.
    """

    import click  # type: ignore

    @click.command(name=COMMAND_NAME)
    @click.option("--config", "config_path", type=click.Path(exists=False), default=None)
    @click.option("--attempts", type=int, default=None)
    @click.option("--base-delay", "base_delay_s", type=float, default=None)
    @click.option("--max-delay", "max_delay_s", type=float, default=None)
    @click.option("--factor", "backoff_factor", type=float, default=None)
    @click.option("--jitter", type=float, default=None)
    @click.option("--jitter-seed", "jitter_seed", type=int, default=None)
    @click.option("--json", "json_flag", is_flag=True, default=False)
    @click.option("--schema", "schema_flag", is_flag=True, default=False)
    def _cmd(
        config_path: str | None,
        attempts: int | None,
        base_delay_s: float | None,
        max_delay_s: float | None,
        backoff_factor: float | None,
        jitter: float | None,
        jitter_seed: int | None,
        json_flag: bool,
        schema_flag: bool,
    ) -> None:
        req = RetryBackoffCliRequest(
            config_path=config_path,
            attempts=attempts,
            base_delay_s=base_delay_s,
            max_delay_s=max_delay_s,
            backoff_factor=backoff_factor,
            jitter=jitter,
            jitter_seed=jitter_seed,
            json=json_flag,
            schema=schema_flag,
        )

        if req.schema:
            click.echo(json.dumps(cli_json_schema(), indent=2, sort_keys=True))
            return

        try:
            resp = run_from_request(req)
            if req.json:
                click.echo(json.dumps(resp.to_dict(), sort_keys=True))
                return

            assert resp.plan is not None
            click.echo("Retry policy:")
            for k, v in resp.plan.policy.to_dict().items():
                click.echo(f"  {k}: {v}")
            click.echo("\nBackoff schedule:")
            for step in resp.plan.steps:
                click.echo(
                    f"  retry #{step.retry_index}: wait {step.delay_s:.3f}s ({step.reason})"
                )
            click.echo(f"\nTotal planned delay: {resp.plan.total_delay_s:.3f}s")
        except ChannelRetryError as err:
            _emit_error(err, as_json=req.json)
            raise SystemExit(2) from err
        except Exception as err:
            _emit_error(err, as_json=req.json)
            raise SystemExit(1) from err

    return _cmd


# Common aliases used by some command discovery implementations.
get_command = get_click_command
