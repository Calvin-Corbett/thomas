from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import click

from thomas.core.config import AppConfig

OPS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "browser": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "message": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "nodes": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "gateway": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "node": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "channels": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "cron": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "memory": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "system": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "approvals": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "plugins": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "devices": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "directory": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "pairing": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "skills": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "security": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "update": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export", "ops-benchmark"),
    "webhooks": ("ops-inspect", "ops-doctor", "ops-verify", "ops-metrics", "ops-export"),
}

FAMILY_PRIORITY: dict[str, str] = {
    "gateway": "critical",
    "plugins": "critical",
    "channels": "high",
    "message": "high",
    "browser": "high",
    "nodes": "high",
    "node": "high",
    "devices": "high",
    "webhooks": "high",
    "cron": "medium",
    "memory": "medium",
    "system": "medium",
    "approvals": "medium",
    "directory": "medium",
    "pairing": "medium",
    "skills": "medium",
    "security": "critical",
    "update": "medium",
}

ENV_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "channels": (
        "THOMAS_TELEGRAM_BOT_TOKEN",
        "THOMAS_DISCORD_BOT_TOKEN",
        "THOMAS_DISCORD_WEBHOOK_URL",
        "THOMAS_SLACK_BOT_TOKEN",
        "THOMAS_SLACK_WEBHOOK_URL",
    ),
    "gateway": ("THOMAS_CONFIG",),
    "nodes": ("THOMAS_NODE_REGISTRY", "THOMAS_NODE_REGISTRY_FILE", "THOMAS_NODE_AUTH_TOKEN"),
    "node": ("THOMAS_NODE_REGISTRY", "THOMAS_NODE_REGISTRY_FILE"),
    "webhooks": ("THOMAS_WEBHOOK_SECRET",),
}

STATE_FILE_GUESSES: dict[str, tuple[str, ...]] = {
    "message": ("cli/messages.json",),
    "plugins": ("cli/plugins.json",),
    "devices": ("cli/devices.json",),
    "gateway": ("cli/gateway_state.json", "cli/gateway.log"),
    "channels": ("channels.json",),
    "memory": ("chats",),
    "cron": ("schedule.json",),
    "webhooks": ("webhooks.json",),
}


def _state_root(config: AppConfig) -> Path:
    return config.memory.root_path / ".thomas"


def _safe_list_names(group: click.Group) -> list[str]:
    return sorted(str(name).strip() for name in (group.commands or {}).keys() if str(name).strip())


def _safe_command_count(group: click.Group) -> int:
    return len(_safe_list_names(group))


def _state_paths(root: Path, family: str) -> list[Path]:
    rels = STATE_FILE_GUESSES.get(family, tuple())
    return [root / rel for rel in rels]


def _read_json_safely(path: Path) -> tuple[bool, str]:
    if not path.exists() or path.is_dir():
        return True, "missing_or_directory"
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _read_text_safely(path: Path, *, limit_bytes: int = 4096) -> tuple[bool, str]:
    if not path.exists() or path.is_dir():
        return True, "missing_or_directory"
    try:
        with path.open("rb") as fh:
            _ = fh.read(max(1, int(limit_bytes)))
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _family_capability_payload(group: click.Group, family: str) -> dict[str, Any]:
    return {
        "family": family,
        "priority": FAMILY_PRIORITY.get(family, "medium"),
        "tracked": family in OPS_BY_FAMILY,
        "command_count": _safe_command_count(group),
        "commands": _safe_list_names(group),
        "capabilities": [
            "json_output",
            "health_checks",
            "metrics_export",
            "self_validation",
            "benchmarking",
        ],
    }


def _family_metrics_payload(group: click.Group, config: AppConfig, family: str) -> dict[str, Any]:
    root = _state_root(config)
    paths = _state_paths(root, family)
    details = []
    for path in paths:
        exists = path.exists()
        size_bytes = 0
        if exists and path.is_file():
            try:
                size_bytes = int(path.stat().st_size)
            except (OSError, FileNotFoundError):
                size_bytes = 0
        details.append(
            {
                "path": str(path),
                "exists": exists,
                "is_file": path.is_file() if exists else False,
                "is_dir": path.is_dir() if exists else False,
                "size_bytes": int(size_bytes),
            }
        )
    return {
        "family": family,
        "command_count": _safe_command_count(group),
        "state_root": str(root),
        "state_artifacts": details,
    }


def _family_doctor_payload(group: click.Group, config: AppConfig, family: str) -> dict[str, Any]:
    root = _state_root(config)
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "check": "state_root_exists",
            "ok": root.exists() and root.is_dir(),
            "detail": str(root),
        }
    )
    checks.append(
        {
            "check": "subcommand_count_nonzero",
            "ok": _safe_command_count(group) > 0,
            "detail": str(_safe_command_count(group)),
        }
    )

    for path in _state_paths(root, family):
        if not path.exists() or path.is_dir():
            checks.append(
                {
                    "check": f"state_file_{path.name}",
                    "ok": True,
                    "detail": "missing_or_directory",
                }
            )
            continue
        if path.suffix.lower() == ".json":
            ok, detail = _read_json_safely(path)
            checks.append({"check": f"state_json_{path.name}", "ok": ok, "detail": detail})
        else:
            ok, detail = _read_text_safely(path)
            checks.append({"check": f"state_file_{path.name}", "ok": ok, "detail": detail})

    return {
        "family": family,
        "ok": all(bool(c.get("ok")) for c in checks),
        "checks": checks,
    }


def _family_verify_payload(group: click.Group, config: AppConfig, family: str) -> dict[str, Any]:
    env_keys = ENV_REQUIREMENTS.get(family, tuple())
    env_state = {key: bool(str(os.environ.get(key) or "").strip()) for key in env_keys}
    cfg_payload = {
        "default_model": str(config.default_model or ""),
        "model_count": len(config.models),
        "api_token_set": bool(str(config.server.api_token or "").strip()),
    }
    return {
        "family": family,
        "ok": True,
        "command_count": _safe_command_count(group),
        "env_requirements": env_state,
        "config": cfg_payload,
    }


def _family_export_payload(group: click.Group, config: AppConfig, family: str) -> dict[str, Any]:
    root = _state_root(config)
    return {
        "family": family,
        "capability": _family_capability_payload(group, family),
        "metrics": _family_metrics_payload(group, config, family),
        "state_root": str(root),
    }


def _family_benchmark_payload(group: click.Group, config: AppConfig, family: str, samples: int) -> dict[str, Any]:
    sample_count = max(1, int(samples))
    durations_ms: list[float] = []
    for _ in range(sample_count):
        start = time.perf_counter()
        _ = _family_metrics_payload(group, config, family)
        _ = _family_capability_payload(group, family)
        durations_ms.append((time.perf_counter() - start) * 1000.0)
    avg_ms = sum(durations_ms) / float(len(durations_ms))
    max_ms = max(durations_ms) if durations_ms else 0.0
    min_ms = min(durations_ms) if durations_ms else 0.0
    return {
        "family": family,
        "samples": sample_count,
        "avg_ms": round(avg_ms, 3),
        "min_ms": round(min_ms, 3),
        "max_ms": round(max_ms, 3),
        "ok": True,
    }


def _emit_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"family: {payload.get('family')}")
    ok = payload.get("ok")
    if ok is not None:
        click.echo(f"ok: {ok}")
    for key in ("command_count", "samples", "avg_ms", "min_ms", "max_ms"):
        if key in payload:
            click.echo(f"{key}: {payload[key]}")


def _write_export(payload: dict[str, Any], output: str) -> str | None:
    target = str(output or "").strip()
    if not target:
        return None
    path = Path(target).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _make_ops_command(family: str, op: str, group: click.Group) -> click.Command:
    @click.command(name=op)
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.option("--output", default="", help="Optional JSON output path.")
    @click.option("--samples", default=5, show_default=True, type=int, help="Benchmark sample count.")
    @click.pass_context
    def _cmd(ctx: click.Context, as_json: bool, output: str, samples: int) -> None:
        obj = ctx.obj if isinstance(ctx.obj, dict) else {}
        config = obj.get("config")
        if config is None:
            raise click.ClickException("Missing CLI context config.")
        if op == "ops-inspect":
            payload = _family_capability_payload(group, family)
        elif op == "ops-doctor":
            payload = _family_doctor_payload(group, config, family)
        elif op == "ops-verify":
            payload = _family_verify_payload(group, config, family)
        elif op == "ops-metrics":
            payload = _family_metrics_payload(group, config, family)
        elif op == "ops-export":
            payload = _family_export_payload(group, config, family)
        elif op == "ops-benchmark":
            payload = _family_benchmark_payload(group, config, family, samples=samples)
        else:
            payload = {"family": family, "ok": False, "error": f"unsupported op: {op}"}

        written = _write_export(payload, output)
        if written:
            payload["written_to"] = written

        _emit_payload(payload, as_json=as_json)
        if payload.get("ok") is False:
            raise SystemExit(1)

    return _cmd


def _iter_tracked_families() -> Iterable[str]:
    return OPS_BY_FAMILY.keys()


def register_quality_ops(cli: click.Group) -> int:
    added = 0
    for family in _iter_tracked_families():
        cmd = cli.commands.get(family)
        if not isinstance(cmd, click.Group):
            continue
        for op in OPS_BY_FAMILY.get(family, tuple()):
            if op in cmd.commands:
                continue
            cmd.add_command(_make_ops_command(family, op, cmd))
            added += 1
    return added
