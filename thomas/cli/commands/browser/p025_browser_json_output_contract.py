"""CLI integration for the browser JSON output contract.

This module adds two automation-friendly capabilities to the browser command
subtree:

* ``--json``: emit a single JSON object to stdout.
* ``--json-schema``: print the JSON Schema for the JSON envelope and exit.

Implementation notes
- The module is intentionally *best-effort* and non-invasive.
- If Click is unavailable, no behavior is changed.
- Options are added with ``expose_value=False`` so existing callback signatures
  remain unchanged.
- Errors that happen before callbacks run (argument parsing/usage errors) are
  intercepted so JSON mode is still machine-readable.

The contract itself lives in ``thomas.browser.p025_browser_json_output_contract``.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any


def _try_import_click():
    try:
        import click  # type: ignore

        return click
    except ImportError:  # pragma: no cover
        return None


@dataclass(frozen=True)
class JsonOutputFlags:
    json: bool = False


def _json_default(value: Any) -> Any:  # noqa: ANN401
    """Best-effort JSON encoder for unknown objects."""

    if is_dataclass(value):
        return asdict(value)

    for attr in ("model_dump", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn()
            except (ValueError, TypeError):
                break

    return repr(value)


def _is_json_mode(ctx: Any) -> bool:  # noqa: ANN401
    try:
        obj = getattr(ctx, "obj", None)
        if isinstance(obj, dict) and obj.get("json"):
            return True
        if isinstance(obj, dict):
            thomas = obj.get("thomas")
            if isinstance(thomas, dict):
                flags = thomas.get("json_output")
                if isinstance(flags, JsonOutputFlags) and flags.json:
                    return True
    except AttributeError:
        return False
    return False


def _ctx_set_flag(ctx: Any, *, json_flag: bool) -> None:  # noqa: ANN401
    """Store flags on the Click context in a predictable way."""

    try:
        ctx.obj = ctx.obj or {}
        ctx.obj["json"] = bool(json_flag)
        ctx.obj.setdefault("thomas", {})
        ctx.obj["thomas"]["json_output"] = JsonOutputFlags(json=json_flag)
    except (ValueError, TypeError):
        return


def _has_option(command: Any, option_names: Iterable[str]) -> bool:  # noqa: ANN401
    for param in getattr(command, "params", []) or []:
        names = getattr(param, "opts", None)
        if not names:
            continue
        for name in option_names:
            if name in names:
                return True
    return False


def _make_json_option(click: Any):  # noqa: ANN401
    def _callback(ctx: Any, param: Any, value: Any) -> Any:  # noqa: ANN401
        if ctx is None or getattr(ctx, "resilient_parsing", False):
            return value
        if value:
            _ctx_set_flag(ctx, json_flag=True)
        return value

    return click.Option(
        ["--json"],
        is_flag=True,
        default=False,
        expose_value=False,
        is_eager=True,
        help="Emit machine-readable JSON output.",
        callback=_callback,
    )


def _make_json_schema_option(click: Any):  # noqa: ANN401
    def _callback(ctx: Any, param: Any, value: Any) -> Any:  # noqa: ANN401
        if not value or getattr(ctx, "resilient_parsing", False):
            return value

        from thomas.browser.p025_browser_json_output_contract import browser_json_schema

        click.echo(json.dumps(browser_json_schema(), ensure_ascii=False, separators=(",", ":")))
        ctx.exit(0)

    return click.Option(
        ["--json-schema"],
        is_flag=True,
        default=False,
        expose_value=False,
        is_eager=True,
        help="Print the JSON schema for --json output and exit.",
        callback=_callback,
    )


def attach_json_output_options(command: Any) -> bool:  # noqa: ANN401
    """Attach ``--json`` / ``--json-schema`` options to a Click command."""

    click = _try_import_click()
    if click is None:
        return False

    modified = False
    if not _has_option(command, ["--json"]):
        command.params.append(_make_json_option(click))
        modified = True
    if not _has_option(command, ["--json-schema"]):
        command.params.append(_make_json_schema_option(click))
        modified = True

    return modified


def _iter_click_command_tree(root: Any):  # noqa: ANN401
    stack = [root]
    seen_ids: set[int] = set()

    while stack:
        node = stack.pop()
        node_id = id(node)
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        yield node

        commands = getattr(node, "commands", None)
        if isinstance(commands, dict):
            for child in commands.values():
                if child is not None:
                    stack.append(child)


def _decode_text_or_base64(raw: bytes) -> tuple[str, str | None]:
    if not raw:
        return "", None
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return "", base64.b64encode(raw).decode("ascii")


class _CaptureStream:
    """A tiny file-like object that captures both text and binary writes."""

    encoding = "utf-8"

    def __init__(self) -> None:
        self._b = io.BytesIO()

    def write(self, s: Any) -> int:  # noqa: ANN401
        if isinstance(s, str):
            b = s.encode("utf-8", errors="replace")
            self._b.write(b)
            return len(s)
        if isinstance(s, (bytes, bytearray)):
            b = bytes(s)
            self._b.write(b)
            return len(b)
        text = str(s)
        b = text.encode("utf-8", errors="replace")
        self._b.write(b)
        return len(text)

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("No fileno")

    @property
    def buffer(self) -> io.BytesIO:
        return self._b

    def raw(self) -> bytes:
        return self._b.getvalue()


@contextlib.contextmanager
def _capture_logging_to(stream: _CaptureStream):
    """Capture logging output by redirecting StreamHandler streams.

    Redirecting sys.stderr/sys.stdout is not always enough because existing
    StreamHandlers may hold references to the old streams.
    """

    original: list[tuple[logging.Handler, Any]] = []

    def _patch_logger(logger: logging.Logger) -> None:
        for h in list(getattr(logger, "handlers", []) or []):
            # Only patch handlers that look like stream handlers.
            if hasattr(h, "stream"):
                original.append((h, getattr(h, "stream", None)))
                try:
                    h.stream = stream  # type: ignore[attr-defined]
                except (ValueError, TypeError):
                    continue

    try:
        _patch_logger(logging.getLogger())
        # Patch known existing loggers.
        mgr = getattr(logging.getLogger(), "manager", None)
        if mgr is not None:
            for name in list(getattr(mgr, "loggerDict", {}).keys()):
                try:
                    _patch_logger(logging.getLogger(name))
                except (ValueError, TypeError):
                    continue
        yield
    finally:
        for h, old in original:
            try:
                h.stream = old  # type: ignore[attr-defined]
            except (ValueError, TypeError):
                continue


def _wrap_callback_for_json_output(click: Any, command: Any) -> bool:  # noqa: ANN401
    """Wrap a click command callback to emit JSON on success/failure."""

    if getattr(command, "_thomas_json_wrapped", False):
        return False

    callback = getattr(command, "callback", None)
    if not callable(callback):
        return False

    def _wrapped(*args: Any, **kwargs: Any):  # noqa: ANN401
        ctx = click.get_current_context(silent=True)
        if ctx is None or not _is_json_mode(ctx):
            return callback(*args, **kwargs)

        from thomas.browser.p025_browser_json_output_contract import failure_from_exception, success

        stdout_buf = _CaptureStream()
        stderr_buf = _CaptureStream()

        exit_code: int | None = None
        envelope: dict[str, Any]

        with (
            contextlib.redirect_stdout(stdout_buf),
            contextlib.redirect_stderr(stderr_buf),
            _capture_logging_to(stderr_buf),
        ):
            try:
                result = callback(*args, **kwargs)

                stdout_text, stdout_b64 = _decode_text_or_base64(stdout_buf.raw())
                stderr_text, stderr_b64 = _decode_text_or_base64(stderr_buf.raw())

                data: dict[str, Any] = {
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "result": result,
                }
                if stdout_b64 is not None:
                    data["stdout_base64"] = stdout_b64
                if stderr_b64 is not None:
                    data["stderr_base64"] = stderr_b64

                envelope = success(data, command=getattr(ctx, "info_name", None))
            except SystemExit:
                raise
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                envelope = failure_from_exception(exc, command=getattr(ctx, "info_name", None))
                exit_code = 1
                try:
                    err_details = dict(envelope.get("error", {}).get("details") or {})
                    err_details.setdefault("stdout", _decode_text_or_base64(stdout_buf.raw())[0])
                    err_details.setdefault("stderr", _decode_text_or_base64(stderr_buf.raw())[0])
                    envelope["error"]["details"] = err_details
                except json.JSONDecodeError:
                    pass

        rendered = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=_json_default)
        click.echo(rendered)
        if exit_code is not None and ctx is not None:
            ctx.exit(exit_code)
        return None

    command.callback = _wrapped
    command._thomas_json_wrapped = True
    return True


def _wrap_command_main_for_json_errors(click: Any, command: Any) -> bool:  # noqa: ANN401
    """Wrap click.Command.main to emit JSON on parsing/usage errors."""

    if getattr(command, "_thomas_json_main_wrapped", False):
        return False

    orig_main = getattr(command, "main", None)
    if not callable(orig_main):
        return False

    def _extract_argv(m_args: tuple[Any, ...], m_kwargs: dict[str, Any]) -> list[str]:
        argv = m_kwargs.get("args")
        if argv is None and m_args:
            argv = m_args[0]
        if argv is None:
            return list(sys.argv[1:])
        if isinstance(argv, (list, tuple)):
            return [str(a) for a in argv]
        if isinstance(argv, str):
            return argv.split()
        return [str(argv)]

    def _wrapped_main(*m_args: Any, **m_kwargs: Any):  # noqa: ANN401
        argv = _extract_argv(m_args, m_kwargs)
        json_requested = "--json" in argv
        if not json_requested:
            return orig_main(*m_args, **m_kwargs)

        from thomas.browser.p025_browser_json_output_contract import failure_from_exception

        standalone_mode = bool(m_kwargs.get("standalone_mode", True))
        m_kwargs["standalone_mode"] = False

        try:
            rv = orig_main(*m_args, **m_kwargs)
            exit_code = rv if isinstance(rv, int) else 0
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            # Click's usage/parameter errors are considered invalid input.
            if isinstance(exc, (click.UsageError, click.ClickException)):
                envelope = failure_from_exception(ValueError(str(exc)), command=getattr(command, "name", None))
                exit_code = int(getattr(exc, "exit_code", 2))
            else:
                envelope = failure_from_exception(exc, command=getattr(command, "name", None))
                exit_code = int(getattr(exc, "exit_code", 1))

            click.echo(json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=_json_default))

        if standalone_mode:
            raise SystemExit(exit_code)
        return exit_code

    command.main = _wrapped_main
    command._thomas_json_main_wrapped = True
    return True


def register(root_command: Any) -> bool:  # noqa: ANN401
    """Patch a Click command tree with JSON output support."""

    click = _try_import_click()
    if click is None:
        return False

    modified_any = False
    for cmd in _iter_click_command_tree(root_command):
        modified_any = attach_json_output_options(cmd) or modified_any
        modified_any = _wrap_command_main_for_json_errors(click, cmd) or modified_any
        if not isinstance(cmd, click.Group):
            modified_any = _wrap_callback_for_json_output(click, cmd) or modified_any

    return modified_any


def _attempt_auto_patch() -> None:
    """Best-effort auto patching when the CLI does not explicitly call register()."""

    click = _try_import_click()
    if click is None:
        return

    candidates: list[tuple[str, str]] = [
        ("thomas.cli.live_browser", "browser"),
        ("thomas.cli.live_browser", "app"),
        ("thomas.cli.live_browser", "browser_app"),
        ("thomas.cli.main", "app"),
        ("thomas.cli.main", "cli"),
        ("thomas.cli.main", "main"),
        ("thomas.cli", "cli"),
    ]

    for module_name, attr in candidates:
        try:
            mod = __import__(module_name, fromlist=[attr])
            root = getattr(mod, attr, None)
            if root is None:
                continue
            if isinstance(root, click.Command):
                register(root)
                return
        except ImportError:
            continue


# Import-time auto patching is intentionally best-effort and should never crash.
_attempt_auto_patch()


def main(argv: list[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    parser = argparse.ArgumentParser(
        prog="browser json-output-contract",
        description="Inspect and apply browser JSON output contract patching.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
    parser.add_argument("--json-schema", dest="json_schema", action="store_true", default=False)
    parser.add_argument("--apply", dest="apply_patch", action="store_true", default=False)
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)

    if bool(args.json_schema):
        try:
            from thomas.browser.p025_browser_json_output_contract import browser_json_schema

            payload = browser_json_schema()
        except Exception as exc:  # pragma: no cover
            payload = {
                "ok": False,
                "error": {
                    "category": "internal_error",
                    "code": "browser_json_schema_unavailable",
                    "message": f"{type(exc).__name__}: {exc}",
                },
            }
            if args.json_mode:
                sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            else:
                sys.stderr.write(f"{payload['error']['code']}: {payload['error']['message']}\n")
            return 1

        sys.stdout.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2 if not args.json_mode else None)
        )
        sys.stdout.write("\n")
        return 0

    patched = False
    if bool(args.apply_patch):
        _attempt_auto_patch()
        patched = True

    payload = {
        "ok": True,
        "command": "browser json-output-contract",
        "patched": patched,
        "note": "JSON output contract hooks are active via CLI registration or import-time patching.",
    }
    if args.json_mode:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        sys.stdout.write(payload["note"] + "\n")
    return 0
