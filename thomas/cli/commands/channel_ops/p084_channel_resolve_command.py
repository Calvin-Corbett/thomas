"""
CLI wiring for `thomas channels resolve`.

This module is intentionally flexible about the surrounding CLI framework. The Thomas
codebase historically uses one of:
- Typer (preferred)
- Click (Typer is Click under the hood)
- argparse

`thomas/cli/commands/channels.py` is expected to import and/or call `register(...)` from
modules in `thomas/cli/commands/channel_ops/`.

The command's user-facing name is `resolve` (not "p084_*").
"""

from __future__ import annotations

import importlib
import io
import json
import os
from collections.abc import Mapping
from typing import Any, TextIO

try:
    from thomas.marketplace.channels.p084_channel_resolve_command import (
        ChannelResolveError,
        ChannelResolveRequest,
        resolve_channel,
        result_json_schema,
    )
except ImportError:  # pragma: no cover
    from thomas.channels.p084_channel_resolve_command import (
    ChannelResolveError,
    ChannelResolveRequest,
    resolve_channel,
    result_json_schema,
)

COMMAND_NAME = "resolve"
HELP = "Resolve a channel reference to a canonical destination."

_COMMAND_NAME = COMMAND_NAME


def register(target: Any) -> None:
    """
    Register the `channels resolve` subcommand with whatever command container is used.

    - Typer: `target` is a `typer.Typer`
    - Click: `target` is a `click.Group`
    - argparse: `target` is an `argparse._SubParsersAction`
    """
    if _try_register_typer(target):
        return
    if _try_register_click(target):
        return
    _register_argparse(target)


# Compatibility aliases (different command loaders use different names)


def add_parser(target: Any) -> None:
    register(target)


def add_subcommand(target: Any) -> None:
    register(target)


def configure_parser(target: Any) -> None:
    register(target)


def _run(
    reference: str | None = None,
    *,
    json_output: bool = False,
    json_schema: bool = False,
    config: Mapping[str, Any] | None = None,
    telegram_resolver: Any | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """
    Framework-agnostic implementation of the command.

    Returns the desired process exit code.
    """
    out_f = out or io.StringIO()
    err_f = err or io.StringIO()

    try:
        if json_schema:
            _emit_json(out_f, {"ok": True, "schema": result_json_schema()})
            return 0

        cfg = config if config is not None else _load_config_best_effort()
        resolver = telegram_resolver if telegram_resolver is not None else _build_telegram_resolver_best_effort(cfg)

        # Let the core resolver own validation (deterministic error codes).
        result = resolve_channel(
            ChannelResolveRequest(reference=reference or "", config=cfg), telegram_resolver=resolver
        )

        if json_output:
            _emit_json(out_f, {"ok": True, "result": result.to_dict()})
        else:
            _emit_human(out_f, result)
        return 0

    except ChannelResolveError as exc:
        if json_output or json_schema:
            _emit_json(out_f, {"ok": False, "error": exc.to_dict()})
        else:
            err_f.write(f"Error ({exc.code}): {exc.message}\n")
        return int(exc.exit_code)

    except (OSError, FileNotFoundError):  # pragma: no cover
        # Last-ditch defense: never crash with a traceback in CLI use.
        if json_output or json_schema:
            _emit_json(out_f, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Internal error."}})
        else:
            err_f.write("Error (INTERNAL_ERROR): Internal error.\n")
        return 99

    finally:
        # If we were passed file handles, do nothing.
        # If we used internal StringIO buffers, flush them to stdout/stderr.
        if out is None:
            print(out_f.getvalue(), end="")
        if err is None:
            print(err_f.getvalue(), end="", file=os.sys.stderr)


def _emit_human(out: TextIO, result: Any) -> None:
    out.write(f"Integration: {result.integration}\n")
    out.write(f"Channel ID:  {result.channel_id}\n")
    if result.username:
        out.write(f"Username:   {result.username}\n")
    if result.title:
        out.write(f"Title:      {result.title}\n")
    if result.kind:
        out.write(f"Kind:       {result.kind}\n")
    out.write(f"Reference:  {result.normalized_reference}\n")


def _emit_json(out: TextIO, payload: Mapping[str, Any]) -> None:
    out.write(json.dumps(payload, sort_keys=True))
    out.write("\n")


def _load_config_best_effort() -> Mapping[str, Any] | None:
    """
    Best-effort config loader that tries common Thomas patterns.

    The resolve logic can operate without a config object in some cases (e.g. when
    a resolver is injected), so this returns None if not found.
    """
    candidates = [
        ("thomas.config", "load_config"),
        ("thomas.config", "get_config"),
        ("thomas.settings", "load_settings"),
        ("thomas.cli.main", "load_config"),
    ]
    for module_name, fn_name in candidates:
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            try:
                cfg = fn()
            except ImportError:
                continue
            if isinstance(cfg, Mapping):
                return cfg
    return None


def _build_telegram_resolver_best_effort(config: Mapping[str, Any] | None) -> Any | None:
    """
    Best-effort Telegram resolver builder.

    Prefers using the existing Telegram integration if available. Falls back to a simple
    HTTP-based resolver if we can locate a bot token.
    """
    try:
        telegram_mod = importlib.import_module("thomas.integrations.telegram")
    except ImportError:
        telegram_mod = None

    if telegram_mod is not None:
        # Common patterns: module-level factory functions.
        for fn_name in ("build_resolver", "build_client", "get_client", "create_client", "create_integration"):
            fn = getattr(telegram_mod, fn_name, None)
            if callable(fn):
                try:
                    return fn(config) if config is not None else fn()
                except TypeError:
                    try:
                        return fn()
                    except ImportError:
                        pass
                except ImportError:
                    pass

        # Common patterns: classes.
        for cls_name in ("TelegramIntegration", "TelegramClient", "TelegramBot", "Telegram"):
            cls = getattr(telegram_mod, cls_name, None)
            if cls is None:
                continue

            # Prefer classmethod constructors.
            for cm_name in ("from_config", "from_settings", "from_env"):
                cm = getattr(cls, cm_name, None)
                if callable(cm):
                    try:
                        return cm(config) if config is not None else cm()
                    except (ValueError, TypeError):
                        pass

            # Try direct construction with a token if we can find one.
            token = _extract_telegram_token(config)
            if token:
                try:
                    return cls(token)
                except AttributeError:
                    pass

            # Try no-arg construction.
            try:
                return cls()
            except AttributeError:
                pass

    # Fallback: minimal resolver via HTTP if token exists.
    token = _extract_telegram_token(config)
    if token:
        return _TelegramHttpResolver(token=token)

    return None


def _extract_telegram_token(config: Mapping[str, Any] | None) -> str | None:
    """
    Try to locate a Telegram bot token.

    We try config first, then env vars.
    """
    if isinstance(config, Mapping):
        # Likely shapes:
        # - {"integrations": {"telegram": {"bot_token": "..."} } }
        # - {"telegram": {"token": "..."}}
        # - {"telegram_bot_token": "..."}
        integrations = config.get("integrations")
        if isinstance(integrations, Mapping):
            tg = integrations.get("telegram")
            if isinstance(tg, Mapping):
                for k in ("bot_token", "token", "api_token"):
                    v = tg.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()

        tg2 = config.get("telegram")
        if isinstance(tg2, Mapping):
            for k in ("bot_token", "token", "api_token"):
                v = tg2.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

        for k in ("telegram_bot_token", "telegram_token", "bot_token"):
            v = config.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    for env_k in ("TELEGRAM_BOT_TOKEN", "THOMAS_TELEGRAM_BOT_TOKEN", "THOMAS_TELEGRAM_TOKEN"):
        v = os.environ.get(env_k)
        if v and v.strip():
            return v.strip()

    return None


class _TelegramHttpResolver:
    """
    Minimal Telegram resolver using the Bot API `getChat`.

    This exists as a fallback only; prefer using `thomas.integrations.telegram` when available.
    """

    def __init__(self, *, token: str) -> None:
        self._token = token

    def get_chat(self, reference: str) -> Any:
        import urllib.parse
        import urllib.request

        # Telegram API expects chat_id; usernames should include '@'
        chat_id = reference
        url = f"https://api.telegram.org/bot{self._token}/getChat?chat_id={urllib.parse.quote(str(chat_id))}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("telegram getChat request failed") from exc

        if not isinstance(data, Mapping) or not data.get("ok"):
            raise RuntimeError("telegram getChat returned non-ok response")

        return data.get("result") or {}


def _try_register_typer(target: Any) -> bool:
    try:
        import typer  # type: ignore
    except ImportError:
        return False

    try:
        Typer = typer.Typer  # noqa: N806
    except ImportError:
        return False

    if not isinstance(target, Typer):
        return False

    @target.command(_COMMAND_NAME, help="Resolve a channel reference to a canonical destination.")
    def _resolve_command(
        reference: str = typer.Argument("", help="Channel reference or alias (e.g. @name, t.me/name, telegram:@name)."),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
        json_schema: bool = typer.Option(False, "--json-schema", help="Emit JSON schema for the JSON output."),
    ) -> None:
        exit_code = _run(reference, json_output=json_output, json_schema=json_schema)
        raise typer.Exit(code=exit_code)

    return True


def _try_register_click(target: Any) -> bool:
    try:
        import click  # type: ignore
    except ImportError:
        return False

    if not isinstance(target, click.core.Group):
        return False

    @click.command(_COMMAND_NAME, help="Resolve a channel reference to a canonical destination.")
    @click.argument("reference", required=False, default="")
    @click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
    @click.option("--json-schema", "json_schema", is_flag=True, help="Emit JSON schema for the JSON output.")
    def _cmd(reference: str, json_output: bool, json_schema: bool) -> None:
        raise SystemExit(_run(reference, json_output=json_output, json_schema=json_schema))

    target.add_command(_cmd, name=_COMMAND_NAME)
    return True


def _register_argparse(target: Any) -> None:
    """
    Register for argparse.

    The expected shape is an argparse subparsers action (has add_parser()).
    """
    if not hasattr(target, "add_parser"):
        # Nothing to do; keep deterministic behavior by not throwing during import-time registration.
        return

    parser = target.add_parser(_COMMAND_NAME, help="Resolve a channel reference to a canonical destination.")
    parser.add_argument(
        "reference", nargs="?", default="", help="Channel reference or alias (e.g. @name, t.me/name, telegram:@name)."
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--json-schema", dest="json_schema", action="store_true", help="Emit JSON schema for the JSON output."
    )
    parser.set_defaults(func=_argparse_entrypoint)


def _argparse_entrypoint(args: Any) -> int:
    return _run(
        getattr(args, "reference", ""),
        json_output=bool(getattr(args, "json_output", False)),
        json_schema=bool(getattr(args, "json_schema", False)),
    )
