from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import click

_PACK_FILE_RE = re.compile(r"^p(?P<prompt_id>\d{3})_(?P<slug>.+)$")


def _iter_pack_files(package: str) -> list[Path]:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return []
    files: list[Path] = []
    for root in spec.submodule_search_locations:
        path = Path(str(root))
        if not path.exists():
            continue
        files.extend(sorted(path.glob("p*.py")))
    return sorted(files, key=lambda p: p.name)


def _derive_command_name(stem: str, family_hint: str) -> tuple[str, str]:
    prompt_id = ""
    slug = stem
    match = _PACK_FILE_RE.match(stem)
    if match is not None:
        prompt_id = str(match.group("prompt_id"))
        slug = str(match.group("slug"))
    if family_hint and slug.startswith(f"{family_hint}_"):
        slug = slug[len(family_hint) + 1 :]
    for suffix in (
        "_command",
        "_commands",
        "_cli_group_scaffold",
        "_integration_into_cli_group",
        "_integration_into_existing_channels_module",
    ):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
            break
    slug = slug.strip("_")
    if not slug:
        slug = stem
    return slug.replace("_", "-"), prompt_id


def _ensure_unique_name(candidate: str, used: set[str], prompt_id: str) -> str:
    if candidate not in used:
        return candidate
    suffix = f"p{prompt_id}" if prompt_id else "pack"
    alt = f"{candidate}-{suffix}"
    if alt not in used:
        return alt
    idx = 2
    while True:
        name = f"{alt}-{idx}"
        if name not in used:
            return name
        idx += 1


def _add_click_candidate(obj: Any, out: list[click.Command], seen: set[int]) -> None:
    if isinstance(obj, click.Command):
        ident = id(obj)
        if ident not in seen:
            seen.add(ident)
            out.append(obj)
        return
    if isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[1], click.Command):
        _add_click_candidate(obj[1], out, seen)
        return
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            _add_click_candidate(item, out, seen)


def _discover_click_commands(module: Any) -> list[click.Command]:
    commands: list[click.Command] = []
    seen: set[int] = set()
    for attr in (
        "COMMAND",
        "CLI_COMMAND",
        "CLICK_COMMAND",
        "PARITY_COMMAND",
        "ALIAS_COMMAND",
        "NESTED_COMMAND",
    ):
        _add_click_candidate(getattr(module, attr, None), commands, seen)

    for getter in ("get_command", "get_click_command", "get_commands"):
        fn = getattr(module, getter, None)
        if not callable(fn):
            continue
        try:
            value = fn()
        except Exception:
            continue
        _add_click_candidate(value, commands, seen)
    return commands


def _invoke_click_command(
    command: click.Command,
    argv: Sequence[str],
    prog_name: str,
    *,
    ctx_obj: Any | None = None,
) -> dict[str, Any]:
    try:
        rv = command.main(
            args=list(argv),
            prog_name=prog_name,
            standalone_mode=False,
            obj=ctx_obj,
        )
        code = int(rv) if isinstance(rv, int) else 0
        return {
            "ok": code == 0,
            "mode": "click",
            "exit_code": code,
            "entrypoint": str(getattr(command, "name", "") or command.__class__.__name__),
        }
    except SystemExit as exc:
        code = int(exc.code or 0)
        return {
            "ok": code == 0,
            "mode": "click",
            "exit_code": code,
            "entrypoint": str(getattr(command, "name", "") or command.__class__.__name__),
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "click",
            "exit_code": 1,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _main_accepts_argv(main_fn: Any) -> bool:
    try:
        sig = inspect.signature(main_fn)
    except Exception:
        return True
    params = list(sig.parameters.values())
    if not params:
        return False
    first = params[0]
    if first.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
        return True
    return first.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def _invoke_main(module: Any, argv: Sequence[str]) -> dict[str, Any]:
    main_fn = getattr(module, "main", None)
    if not callable(main_fn):
        return {"ok": True, "mode": "noop", "exit_code": 0}
    try:
        if _main_accepts_argv(main_fn):
            rv = main_fn(list(argv))
        else:
            rv = main_fn()
        code = int(rv) if isinstance(rv, int) else 0
        return {
            "ok": code == 0,
            "mode": "main",
            "exit_code": code,
            "entrypoint": "main",
        }
    except SystemExit as exc:
        code = int(exc.code or 0)
        return {
            "ok": code == 0,
            "mode": "main",
            "exit_code": code,
            "entrypoint": "main",
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "main",
            "exit_code": 1,
            "error": f"{type(exc).__name__}: {exc}",
        }


def invoke_pack_module(
    module_name: str,
    argv: Sequence[str],
    *,
    prog_name: str,
    ctx_obj: Any | None = None,
) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return {
            "ok": False,
            "mode": "import",
            "exit_code": 1,
            "error": f"{type(exc).__name__}: {exc}",
        }

    commands = _discover_click_commands(module)
    if commands:
        return _invoke_click_command(commands[0], argv, prog_name=prog_name, ctx_obj=ctx_obj)
    return _invoke_main(module, argv)


def _build_pack_proxy_command(
    *,
    command_name: str,
    module_name: str,
    prompt_id: str,
) -> click.Command:
    @click.command(
        name=command_name,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    @click.option("--run/--describe", default=False, show_default=True, help="Run this pack module.")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.pass_context
    def _proxy(ctx: click.Context, run: bool, as_json: bool) -> None:
        extra_args = list(ctx.args)
        should_run = bool(run or extra_args)
        suppress_text = False
        payload: dict[str, Any]
        if should_run:
            forwarded_args = list(extra_args)
            # In run mode, treat proxy-level --json as a request for module-level
            # JSON whenever possible.
            if as_json and "--json" not in forwarded_args:
                forwarded_args.append("--json")
            suppress_text = any(arg in {"--json", "--schema"} for arg in forwarded_args)
            payload = invoke_pack_module(
                module_name,
                forwarded_args,
                prog_name=str(ctx.command_path),
                ctx_obj=ctx.obj,
            )
            payload.update({"module": module_name, "prompt_id": prompt_id, "args": forwarded_args})
        else:
            payload = {
                "ok": True,
                "mode": "describe",
                "module": module_name,
                "prompt_id": prompt_id,
                "command": command_name,
                "note": "Command is wired. Pass args or --run to execute module entrypoints.",
            }

        if as_json and should_run:
            # Let the invoked module own JSON output to avoid mixed JSON payloads.
            pass
        elif as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        elif suppress_text and should_run:
            pass
        else:
            mode = str(payload.get("mode") or "")
            if mode == "describe":
                click.echo(f"{command_name}: wired to {module_name} ({prompt_id or 'pack'})")
                click.echo("Pass args or --run to execute the module.")
            elif bool(payload.get("ok", False)):
                click.echo(f"{command_name}: executed via {mode}")
            else:
                click.echo(f"{command_name}: failed via {mode}", err=True)
                click.echo(str(payload.get("error") or "unknown error"), err=True)

        if not bool(payload.get("ok", False)):
            raise SystemExit(int(payload.get("exit_code") or 1))

    return _proxy


def register_pack_proxy_commands(
    group: click.Group,
    *,
    package: str,
    family_hint: str = "",
    include_prefix: str = "",
    exclude_modules: Iterable[str] | None = None,
) -> int:
    excluded = {str(x).strip() for x in (exclude_modules or []) if str(x).strip()}
    used = set(str(name).strip() for name in group.commands.keys())
    added = 0

    for path in _iter_pack_files(package):
        stem = path.stem
        raw_slug = stem
        match = _PACK_FILE_RE.match(stem)
        if match is not None:
            raw_slug = str(match.group("slug"))
        if include_prefix and not raw_slug.startswith(include_prefix):
            continue

        module_name = f"{package}.{stem}"
        if module_name in excluded:
            continue

        base_name, prompt_id = _derive_command_name(stem, family_hint=family_hint)
        command_name = _ensure_unique_name(base_name, used, prompt_id)
        if command_name in group.commands:
            continue

        group.add_command(
            _build_pack_proxy_command(
                command_name=command_name,
                module_name=module_name,
                prompt_id=prompt_id,
            )
        )
        used.add(command_name)
        added += 1
    return added
