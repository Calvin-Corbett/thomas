"""Memory and recall management commands."""

from __future__ import annotations

import json
from typing import Any

import click

from thomas.cli.parity_support import (
    compat_group as _compat_group,
)
from thomas.cli.parity_support import (
    skill_conflicts as _skill_conflicts,
)
from thomas.core.config import AppConfig


@click.group(name="memory")
@click.pass_context
def memory(ctx: click.Context) -> None:
    """Memory subsystem commands."""
    _ = ctx


def _memory_json_option(fn):  # noqa: ANN001
    return click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")(fn)


def _memory_run_mode_option(fn):  # noqa: ANN001
    return click.option(
        "--run/--describe",
        "run_mode",
        default=False,
        show_default=True,
        help=_MEMORY_RUN_MODE_HELP,
    )(fn)


@memory.command("status")
@_memory_json_option
@click.pass_context
def memory_status(ctx: click.Context, as_json: bool) -> None:
    """Show memory store status."""
    config: AppConfig = ctx.obj["config"]
    root = config.memory.root_path / ".thomas"
    chat_count = len(list((root / "chats").glob("*.json"))) if (root / "chats").exists() else 0
    payload = {
        "ok": True,
        "root": str(root),
        "chat_files": chat_count,
        "v2_enabled": bool(os.environ.get("THOMAS_MEMORY_V2_ENABLED")),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"memory root: {root}")
        click.echo(f"chat files: {chat_count}")
        click.echo(f"v2 enabled: {payload['v2_enabled']}")


_MEMORY_OPERATION_NOTES: dict[str, str] = {
    "search": "Search memory snapshots.",
    "list": "List memory snapshots.",
    "index": "Run memory index maintenance.",
    "compact": "Run memory compaction.",
}
_MEMORY_RUNTIME_HINT = "Use `python -m thomas memory status --json` to verify memory state."
_MEMORY_DESCRIBE_RUN_HINT = (
    "Pass --run to attempt execution; unimplemented operations return a structured non-zero error."
)
_MEMORY_RUN_MODE_HELP = "Execute backend operation (--run) or describe compatibility surface (--describe)."


def _memory_payload(
    action: str,
    *,
    mode: str,
    ok: bool,
    executed: bool,
    target: str = "",
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "command": "memory",
        "action": action,
        "mode": str(mode or "run"),
        "executed": bool(executed),
        "target": str(target or "").strip(),
        "timestamp_utc": _utc_iso(),
    }


def _memory_describe_payload(action: str, *, target: str = "") -> dict[str, Any]:
    payload = _memory_payload(action, mode="describe", ok=False, executed=False, target=target)
    payload["note"] = _MEMORY_OPERATION_NOTES.get(action, "Memory compatibility surface.")
    payload["run_hint"] = _MEMORY_DESCRIBE_RUN_HINT
    return payload


def _memory_runtime_error_payload(action: str, message: str, *, target: str = "") -> dict[str, Any]:
    payload = _memory_payload(action, mode="run", ok=False, executed=False, target=target)
    payload["error"] = {
        "category": "runtime_error",
        "code": "memory_operation_failed",
        "message": str(message or "").strip(),
        "hint": _MEMORY_RUNTIME_HINT,
    }
    return payload


def _memory_success_payload(action: str, *, details: dict[str, Any] | None = None, target: str = "") -> dict[str, Any]:
    extras = dict(details or {})
    ok = bool(extras.pop("ok", True))
    return {
        **_memory_payload(action, mode="run", ok=ok, executed=True, target=target),
        **extras,
    }


def _memory_unimplemented_payload(action: str, *, target: str = "") -> dict[str, Any]:
    return _compat_not_implemented_payload(
        "memory",
        action,
        message=f"`memory {action}` has no executable backend implementation in this build.",
        hint=_MEMORY_RUNTIME_HINT,
        target=target,
        mode="run",
    )


def _memory_emit_describe(action: str, *, as_json: bool, target: str = "") -> None:
    payload = _memory_describe_payload(action, target=target)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"memory {action}: compatibility surface only (describe mode)")
    click.echo(f"- note: {payload['note']}")
    if target:
        click.echo(f"- target: {target}")
    click.echo(f"- run_hint: {payload['run_hint']}")


def _memory_emit_error_text(payload: dict[str, Any]) -> None:
    err = payload.get("error")
    if isinstance(err, dict):
        click.echo(f"{err.get('code', 'memory_operation_failed')}: {err.get('message', 'unknown')}", err=True)
        hint = str(err.get("hint") or "").strip()
        if hint:
            click.echo(f"hint: {hint}", err=True)
        return
    click.echo(f"memory_operation_failed: {payload.get('error', 'unknown')}", err=True)


def _memory_error_exit_code(payload: dict[str, Any]) -> int:
    err = payload.get("error")
    if isinstance(err, dict) and str(err.get("category") or "") == "not_implemented":
        return 2
    return 1


def _memory_emit_result(payload: dict[str, Any], *, as_json: bool, success_text: str = "") -> None:
    ok = bool(payload.get("ok", False))
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        if not ok:
            raise SystemExit(_memory_error_exit_code(payload))
        return
    if ok:
        if success_text:
            click.echo(success_text)
        return
    _memory_emit_error_text(payload)
    raise SystemExit(_memory_error_exit_code(payload))


def _resolve_memory_backend(
    action: str,
    *,
    module_name: str,
    symbol: str,
    target: str = "",
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = str(getattr(exc, "name", "") or "").strip()
        if missing == module_name:
            return None, _memory_unimplemented_payload(action, target=target)
        return None, _memory_runtime_error_payload(action, f"{type(exc).__name__}: {exc}", target=target)
    except ImportError as exc:
        return None, _memory_runtime_error_payload(action, f"{type(exc).__name__}: {exc}", target=target)
    except Exception as exc:
        return None, _memory_runtime_error_payload(action, f"{type(exc).__name__}: {exc}", target=target)

    impl = getattr(module, symbol, None)
    if not callable(impl):
        return None, _memory_runtime_error_payload(
            action,
            f"AttributeError: {module_name}.{symbol} is not callable",
            target=target,
        )
    return impl, None


def _run_memory_maintenance(
    ctx: click.Context,
    *,
    action: str,
    module_name: str,
    symbol: str,
    run_mode: bool,
    as_json: bool,
    success_text: str,
    operation_kwargs: dict[str, Any] | None = None,
) -> None:
    if not run_mode:
        _memory_emit_describe(action, as_json=as_json)
        return

    operation, error_payload = _resolve_memory_backend(action, module_name=module_name, symbol=symbol)
    if error_payload is not None:
        _memory_emit_result(error_payload, as_json=as_json)
        return

    config: AppConfig = ctx.obj["config"]
    kwargs = dict(operation_kwargs or {})
    try:
        result = operation(config, **kwargs)
        details = dict(result) if isinstance(result, dict) else {"result": result}
        payload = _memory_success_payload(action, details=details)
    except Exception as exc:
        payload = _memory_runtime_error_payload(action, f"{type(exc).__name__}: {exc}")
    _memory_emit_result(payload, as_json=as_json, success_text=success_text)


def _memory_emit_search_output(payload: dict[str, Any], *, as_json: bool, query: str) -> None:
    if as_json or not bool(payload.get("ok", False)):
        _memory_emit_result(payload, as_json=as_json)
        return
    click.echo(f"Found {payload['count']} results for '{query}':")
    for row in payload.get("results", []):
        if isinstance(row, dict):
            click.echo(
                f"  - {row.get('file', row.get('id', '?'))}: {str(row.get('preview', row.get('text', '')))[:120]}"
            )


@memory.command("search")
@click.argument("query", nargs=-1, required=True)
@_memory_json_option
@click.option("--limit", "max_results", type=int, default=10, show_default=True, help="Maximum results.")
@_memory_run_mode_option
@click.pass_context
def memory_search(
    ctx: click.Context,
    query: tuple[str, ...],
    as_json: bool,
    max_results: int,
    run_mode: bool,
) -> None:
    """Search memory store."""
    query_str = " ".join(query)
    if not run_mode:
        _memory_emit_describe("search", as_json=as_json, target=query_str)
        return

    search_memory, error_payload = _resolve_memory_backend(
        "search",
        module_name="thomas.memory.search",
        symbol="search_memory",
        target=query_str,
    )
    if error_payload is not None:
        _memory_emit_result(error_payload, as_json=as_json)
        return

    config: AppConfig = ctx.obj["config"]
    try:
        results = search_memory(config, query_str, limit=max_results)
        payload = _memory_success_payload(
            "search",
            target=query_str,
            details={
                "query": query_str,
                "count": len(results),
                "results": results,
            },
        )
    except Exception as exc:
        payload = _memory_runtime_error_payload("search", f"{type(exc).__name__}: {exc}", target=query_str)
    _memory_emit_search_output(payload, as_json=as_json, query=query_str)


@memory.command("list")
@_memory_json_option
@click.option("--limit", type=int, default=20, show_default=True, help="Maximum snapshot rows.")
@_memory_run_mode_option
@click.pass_context
def memory_list(ctx: click.Context, as_json: bool, limit: int, run_mode: bool) -> None:
    """List memory snapshots."""
    _run_memory_maintenance(
        ctx,
        action="list",
        module_name="thomas.memory.listing",
        symbol="list_memory",
        run_mode=run_mode,
        as_json=as_json,
        success_text="Memory snapshots listed.",
        operation_kwargs={"limit": int(limit)},
    )


@memory.command("index")
@_memory_json_option
@_memory_run_mode_option
@click.pass_context
def memory_index(ctx: click.Context, as_json: bool, run_mode: bool) -> None:
    """Run memory index maintenance."""
    _run_memory_maintenance(
        ctx,
        action="index",
        module_name="thomas.memory.indexer",
        symbol="reindex_memory",
        run_mode=run_mode,
        as_json=as_json,
        success_text="Memory index maintenance complete.",
    )


@memory.command("compact")
@_memory_json_option
@_memory_run_mode_option
@click.pass_context
def memory_compact(ctx: click.Context, as_json: bool, run_mode: bool) -> None:
    """Run memory compaction."""
    _run_memory_maintenance(
        ctx,
        action="compact",
        module_name="thomas.memory.compaction",
        symbol="compact_memory",
        run_mode=run_mode,
        as_json=as_json,
        success_text="Memory compaction complete.",
    )


system = _compat_group(
    "system",
    [
        ("status", "System command family is active."),
        ("health", "Health endpoints are reachable through gateway commands."),
        ("doctor", "Use `doctor` for full diagnostics."),
        ("env", "Environment variable presence map."),
        ("event", "Event stream is exposed by observability pipelines."),
        ("heartbeat", "Heartbeat checks are available through health flows."),
        ("presence", "Presence telemetry is available through status channels."),
    ],
)
approvals = _compat_group(
    "approvals",
    [
        ("list", "Approval queue is exposed through nodes pending-approvals."),
        ("status", "Approval workflow is wired."),
        ("get", "Approval detail lookup is available through mission APIs."),
        ("set", "Approval policy state can be set through guardrail controls."),
        ("allowlist", "Allowlist policy is enforced by guardrail layers."),
        ("approve", "Use node action commands for execution-level approvals."),
        ("reject", "Use node action commands for execution-level rejections."),
    ],
)
directory = _compat_group(
    "directory",
    [
        ("list", "Directory view is backed by paired devices."),
        ("add", "Use devices pair for durable entries."),
        ("remove", "Use devices revoke/remove flows for durable records."),
    ],
)
pairing = _compat_group(
    "pairing",
    [
        ("start", "Use devices pair --name <name> for full pairing."),
        ("status", "Pairing support is active through devices commands."),
        ("list", "List paired identities through devices directory."),
        ("approve", "Approve pairing intents through device/approval flows."),
        ("reset", "Revoke old tokens and re-run devices pair."),
    ],
)


def _skills_summary_payload(config: AppConfig, state: dict[str, Any]) -> dict[str, Any]:
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
