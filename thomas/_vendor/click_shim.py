"""Minimal click-compatible shim using only Python stdlib.

Provides enough click API compatibility for Thomas CLI to work without
the click package installed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ClickException(Exception):
    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message

    def show(self) -> None:
        if self.message:
            sys.stderr.write(f"Error: {self.message}\n")


class BadParameter(ClickException):
    pass


class UsageError(ClickException):
    pass


class Abort(ClickException):
    pass


class Context:
    def __init__(self, command=None, parent=None, info_name=None, params=None, args=None):
        self.command, self.parent, self.info_name = command, parent, info_name
        self.params, self.args, self.obj = params or {}, args or [], {}
        self._invoked_subcommand: str | None = None

    def ensure_object(self, object_type: type) -> Any:
        if not isinstance(self.obj, object_type):
            self.obj = object_type()
        return self.obj

    def invoke(self, callback: Callable, *args: Any, **kwargs: Any) -> Any:
        return callback(*args, **kwargs)

    def get_help(self) -> str:
        return self.command.get_help(self) if self.command else ""

    @property
    def invoked_subcommand(self) -> str | None:
        return self._invoked_subcommand


class Parameter:
    def __init__(
        self,
        param_decls: list[str],
        type: Any = None,
        required: bool = False,
        default: Any = None,
        help: str | None = None,
        **kwargs: Any,
    ):
        self.param_decls, self.type, self.required, self.default, self.help = param_decls, type, required, default, help
        self.name = self._get_name(param_decls)
        self.kwargs = kwargs

    def _get_name(self, param_decls: list[str]) -> str:
        for decl in param_decls:
            if not decl.startswith("-"):
                return decl
        return param_decls[-1].lstrip("-").replace("-", "_")

    def add_to_parser(self, parser: argparse.ArgumentParser) -> None:
        raise NotImplementedError


class Argument(Parameter):
    def __init__(self, param_decls: list[str], type: Any = None, required: bool = True, **kwargs: Any):
        super().__init__(param_decls, type=type, required=required, **kwargs)

    def add_to_parser(self, parser: argparse.ArgumentParser) -> None:
        kwargs = {"nargs": "?"} if not self.required else {}
        if self.default is not None:
            kwargs["default"] = self.default
        parser.add_argument(self.name, help=self.help, **kwargs)


class Option(Parameter):
    def __init__(
        self,
        param_decls: list[str],
        type: Any = None,
        is_flag: bool = False,
        multiple: bool = False,
        show_default: bool = False,
        **kwargs: Any,
    ):
        super().__init__(param_decls, type=type, **kwargs)
        self.is_flag, self.multiple, self.show_default = is_flag, multiple, show_default

    def add_to_parser(self, parser: argparse.ArgumentParser) -> None:
        kwargs = {}
        if self.is_flag:
            kwargs["action"] = "store_true"
        if self.multiple:
            kwargs["nargs"] = "*"
        if self.help:
            kwargs["help"] = self.help
        if self.default is not None:
            kwargs["default"] = self.default
        parser.add_argument(*self.param_decls, **kwargs)


class Command:
    def __init__(
        self,
        name: str,
        callback: Callable,
        params: list[Parameter] | None = None,
        help: str | None = None,
        **kwargs: Any,
    ):
        self.name, self.callback, self.params = name, callback, params or []
        self.help = help or (callback.__doc__ or "").strip()
        self.invoke_without_command = kwargs.get("invoke_without_command", False)

    def get_help(self, ctx: Context) -> str:
        ht = f"Usage: {self.name}\n"
        if self.help:
            ht += f"\n{self.help}\n"
        if self.params:
            ht += "\nOptions:\n"
            for p in self.params:
                if isinstance(p, Option):
                    ht += f"  {', '.join(p.param_decls)}"
                    if p.help:
                        ht += f"  {p.help}"
                    ht += "\n"
        return ht

    def invoke(self, ctx: Context, **params: Any) -> Any:
        import inspect

        sig = inspect.signature(self.callback)
        call_kwargs = {
            pn: (ctx if pn == "ctx" else params.get(pn)) for pn in sig.parameters if pn == "ctx" or pn in params
        }
        return self.callback(**call_kwargs)


class Group(Command):
    def __init__(
        self,
        name: str | None = None,
        callback: Callable | None = None,
        commands: dict[str, Command] | None = None,
        **kwargs: Any,
    ):
        self.name, self.callback, self.commands = name, callback, commands or {}
        self.params: list[Parameter] = []
        self.help = (callback.__doc__ or "").strip() if callback else ""
        self.invoke_without_command = kwargs.get("invoke_without_command", False)

    def add_command(self, cmd: Command, name: str | None = None) -> None:
        self.commands[name or cmd.name] = cmd

    def command(self, name: str | None = None, **kwargs: Any) -> Callable:
        def decorator(f: Callable) -> Callable:
            params = getattr(f, "__click_params__", [])
            cmd = Command(name or f.__name__, f, params=params, help=f.__doc__, **kwargs)
            self.add_command(cmd, name or f.__name__)
            return f

        return decorator

    def group(self, name: str | None = None, **kwargs: Any) -> Callable:
        def decorator(f: Callable) -> Group:
            params = getattr(f, "__click_params__", [])
            grp = Group(name or f.__name__, f, **kwargs)
            grp.params = params
            self.add_command(grp, name or f.__name__)
            return grp  # type: ignore

        return decorator

    def get_help(self, ctx: Context) -> str:
        ht = f"Usage: {self.name or 'cli'}\n"
        if self.help:
            ht += f"\n{self.help}\n"
        if self.params:
            ht += "\nOptions:\n"
            for p in self.params:
                if isinstance(p, Option):
                    ht += f"  {', '.join(p.param_decls)}"
                    if p.help:
                        ht += f"  {p.help}"
                    ht += "\n"
        if self.commands:
            ht += "\nCommands:\n"
            for cn, c in self.commands.items():
                ht += f"  {cn}"
                if c.help:
                    ht += f"    {c.help.split(chr(10))[0]}"
                ht += "\n"
        return ht

    def invoke(self, ctx: Context, **params: Any) -> Any:
        import inspect

        if self.callback:
            sig = inspect.signature(self.callback)
            call_kwargs = {
                pn: (ctx if pn == "ctx" else params.get(pn)) for pn in sig.parameters if pn == "ctx" or pn in params
            }
            self.callback(**call_kwargs)
        sc = ctx._invoked_subcommand
        if sc and sc in self.commands:
            sub_ctx = Context(command=self.commands[sc], parent=ctx, info_name=sc, params=params)
            sub_ctx.obj = ctx.obj
            return self.commands[sc].invoke(sub_ctx, **params)


class ParamType:
    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        return value


class PathType(ParamType):
    def __init__(self, exists: bool | None = None, dir_okay: bool = True, path_type: type | None = None):
        self.exists, self.dir_okay, self.path_type = exists, dir_okay, path_type or Path

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if value is None:
            return None
        p = self.path_type(value)
        if self.exists is not None:
            if self.exists and not p.exists():
                raise BadParameter(f"Path does not exist: {value}")
            if not self.exists and p.exists():
                raise BadParameter(f"Path already exists: {value}")
        return p


class ChoiceType(ParamType):
    def __init__(self, choices: list[str], case_sensitive: bool = True):
        self.choices, self.case_sensitive = choices, case_sensitive

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if value is None:
            return None
        candidates = self.choices if self.case_sensitive else [c.lower() for c in self.choices]
        check = value if self.case_sensitive else value.lower()
        if check not in candidates:
            raise BadParameter(f"Invalid choice: {value}. Valid: {', '.join(self.choices)}")
        return value


class IntRangeType(ParamType):
    def __init__(self, min: int | None = None, max: int | None = None):
        self.min, self.max = min, max

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if value is None:
            return None
        try:
            val = int(value)
        except (TypeError, ValueError):
            raise BadParameter(f"Invalid integer: {value}")
        if self.min is not None and val < self.min:
            raise BadParameter(f"Value {val} is less than minimum {self.min}")
        if self.max is not None and val > self.max:
            raise BadParameter(f"Value {val} is greater than maximum {self.max}")
        return val


class _INT(ParamType):
    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise BadParameter(f"Invalid integer: {value}")


class _STRING(ParamType):
    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        return str(value) if value is not None else None


class _BOOL(ParamType):
    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "on")
        return bool(value)


class _File(ParamType):
    def __init__(self, mode: str = "r"):
        self.mode = mode

    def convert(self, value: Any, param: Parameter | None, ctx: Context | None) -> Any:
        if value is None or not isinstance(value, str):
            return value
        return open(value, self.mode)


INT, STRING, BOOL, File = _INT(), _STRING(), _BOOL(), _File


def echo(message: Any = "", file: Any = None, nl: bool = True, err: bool = False) -> None:
    output_file = sys.stderr if err else sys.stdout
    output_file.write(str(message) if message else "")
    if nl:
        output_file.write("\n")
    output_file.flush()


def secho(
    message: Any = "", file: Any = None, nl: bool = True, err: bool = False, color: bool | None = None, **styles: Any
) -> None:
    echo(message, file=file, nl=nl, err=err)


def style(text: str, **styles: Any) -> str:
    return text


def Path(exists: bool | None = None, dir_okay: bool = True, path_type: type | None = None) -> ParamType:
    return PathType(exists=exists, dir_okay=dir_okay, path_type=path_type or globals()["Path"])


def Choice(choices: list[str], case_sensitive: bool = True) -> ParamType:
    return ChoiceType(choices, case_sensitive=case_sensitive)


def IntRange(min: int | None = None, max: int | None = None) -> ParamType:
    return IntRangeType(min=min, max=max)


def option(*param_decls: str, **attrs: Any) -> Callable:
    def decorator(f: Callable) -> Callable:
        if not hasattr(f, "__click_params__"):
            f.__click_params__ = []
        f.__click_params__.insert(0, Option(list(param_decls), **attrs))
        return f

    return decorator


def argument(*param_decls: str, **attrs: Any) -> Callable:
    def decorator(f: Callable) -> Callable:
        if not hasattr(f, "__click_params__"):
            f.__click_params__ = []
        f.__click_params__.append(Argument(list(param_decls), **attrs))
        return f

    return decorator


def pass_context(f: Callable) -> Callable:
    f.__click_pass_context__ = True
    return f


def command(name: str | None = None, **attrs: Any) -> Callable:
    def decorator(f: Callable) -> Callable:
        params = getattr(f, "__click_params__", [])
        f.__click_command__ = Command(name or f.__name__, f, params=params, **attrs)
        return f

    return decorator


def group(name: str | None = None, **attrs: Any) -> Callable:
    def decorator(f: Callable) -> Group:
        params = getattr(f, "__click_params__", [])
        grp = Group(name or f.__name__, f, **attrs)
        grp.params = params
        return grp  # type: ignore

    return decorator


def main(
    prog_name: str | None = None, complete_var: str | None = None, standalone_mode: bool = True, **extra: Any
) -> Callable:
    def decorator(f: Callable) -> Callable:
        grp = f if isinstance(f, Group) else group()(f)

        def cli_runner(obj: Any = None, *args: Any, **kwargs: Any) -> Any:
            return _invoke_group(grp, obj=obj, args=sys.argv[1:])

        return cli_runner

    return decorator


def _invoke_group(grp: Group, obj: Any = None, args: list[str] | None = None) -> None:
    if args is None:
        args = sys.argv[1:]
    ctx = Context(command=grp, info_name=grp.name, args=args)
    ctx.obj = obj or {}
    parser = argparse.ArgumentParser(prog=grp.name or "cli", add_help=False)
    for param in grp.params:
        param.add_to_parser(parser)
    if grp.commands:
        subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")
        for cn, cmd in grp.commands.items():
            sp = subparsers.add_parser(cn, add_help=False)
            for param in cmd.params:
                param.add_to_parser(sp)
    try:
        parsed, remaining = parser.parse_known_args(args)
    except SystemExit:
        raise
    params = {k: v for k, v in vars(parsed).items() if k != "subcommand"}
    if parsed.subcommand:
        ctx._invoked_subcommand = parsed.subcommand
        sp = argparse.ArgumentParser(prog=f"{grp.name} {parsed.subcommand}", add_help=False)
        cmd = grp.commands.get(parsed.subcommand)
        if cmd:
            for param in cmd.params:
                param.add_to_parser(sp)
            sub_parsed = sp.parse_args(remaining or args[len(args) - len(remaining) :])
            params.update(vars(sub_parsed))
    try:
        grp.invoke(ctx, **params)
    except ClickException as e:
        e.show()
        sys.exit(1)
    except Abort:
        sys.exit(1)


__all__ = [
    "Context",
    "Command",
    "Group",
    "Parameter",
    "Option",
    "Argument",
    "ClickException",
    "BadParameter",
    "UsageError",
    "Abort",
    "ParamType",
    "PathType",
    "ChoiceType",
    "IntRangeType",
    "INT",
    "STRING",
    "BOOL",
    "File",
    "Path",
    "Choice",
    "IntRange",
    "echo",
    "secho",
    "style",
    "option",
    "argument",
    "pass_context",
    "command",
    "group",
    "main",
]
