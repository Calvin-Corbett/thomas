from __future__ import annotations

import json
import os
from pathlib import Path

import click

from thomas.companion.kernel import CompanionKernel
from thomas.companion.registry import ModuleRegistry
from thomas.companion.update import BundleVerifier, UpdateApplier
from thomas.core.config import AppConfig


def _kernel_from_ctx(ctx: click.Context, *, root: str) -> CompanionKernel:
    config: AppConfig = ctx.obj["config"]
    return CompanionKernel.from_config(config, root_override=root)


def _secret_from_env() -> str:
    return str(os.environ.get("THOMAS_COMPANION_UPDATE_SECRET") or "").strip()


def _require_signature_from_env(default: bool = True) -> bool:
    raw = str(os.environ.get("THOMAS_COMPANION_REQUIRE_SIGNATURE") or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


@click.group()
@click.pass_context
def companion(ctx: click.Context) -> None:
    """Companion app platform controls (kernel/modules/update pipeline)."""
    _ = ctx


@companion.command("init")
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_init(ctx: click.Context, root: str, as_json: bool) -> None:
    kernel = _kernel_from_ctx(ctx, root=root)
    paths = kernel.init_layout()
    payload = {
        "ok": True,
        "kernel_version": kernel.status().get("kernel_version"),
        "root": str(paths.root),
        "modules_dir": str(paths.modules_dir),
        "registry_file": str(paths.registry_file),
        "policy_file": str(paths.policy_file),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Companion kernel initialized: {payload['root']}")
    click.echo(f"- modules: {payload['modules_dir']}")
    click.echo(f"- registry: {payload['registry_file']}")
    click.echo(f"- policy: {payload['policy_file']}")


@companion.command("status")
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_status(ctx: click.Context, root: str, as_json: bool) -> None:
    kernel = _kernel_from_ctx(ctx, root=root)
    payload = kernel.status()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Kernel version: {payload.get('kernel_version')}")
    click.echo(f"Root: {payload.get('root')}")
    click.echo(f"Modules: {payload.get('modules_count')}")
    click.echo(f"Tailscale-only: {payload.get('tailscale_only')}")
    click.echo(f"Require signed updates: {payload.get('require_signed_updates')}")


@companion.command("module-list")
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_module_list(ctx: click.Context, root: str, as_json: bool) -> None:
    kernel = _kernel_from_ctx(ctx, root=root)
    reg = ModuleRegistry(kernel)
    rows = [m.to_dict() for m in reg.list()]
    payload = {"count": len(rows), "modules": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Installed modules: {len(rows)}")
    for item in rows:
        click.echo(
            f"- {item['module_id']} | v{item['version']} | {item['status']} | entrypoint={item['entrypoint']}"
        )


@companion.command("module-enable")
@click.argument("module_id")
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_module_enable(ctx: click.Context, module_id: str, root: str, as_json: bool) -> None:
    from datetime import datetime, timezone

    kernel = _kernel_from_ctx(ctx, root=root)
    reg = ModuleRegistry(kernel)
    row = reg.set_enabled(module_id, True, timestamp=datetime.now(timezone.utc).isoformat())
    if row is None:
        raise click.ClickException(f"module not found: {module_id}")
    payload = {"ok": True, "module": row.to_dict()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Enabled module: {module_id}")


@companion.command("module-disable")
@click.argument("module_id")
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_module_disable(ctx: click.Context, module_id: str, root: str, as_json: bool) -> None:
    from datetime import datetime, timezone

    kernel = _kernel_from_ctx(ctx, root=root)
    reg = ModuleRegistry(kernel)
    row = reg.set_enabled(module_id, False, timestamp=datetime.now(timezone.utc).isoformat())
    if row is None:
        raise click.ClickException(f"module not found: {module_id}")
    payload = {"ok": True, "module": row.to_dict()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Disabled module: {module_id}")


@companion.command("verify-bundle")
@click.option("--bundle", "bundle", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_verify_bundle(ctx: click.Context, bundle: Path, root: str, as_json: bool) -> None:
    kernel = _kernel_from_ctx(ctx, root=root)
    verifier = BundleVerifier(
        kernel,
        secret=_secret_from_env(),
        require_signature=_require_signature_from_env(default=True),
    )
    report = verifier.verify_bundle(bundle)
    payload = report.to_dict()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"bundle ok: {report.ok}")
    for err in report.errors:
        click.echo(f"ERROR: {err}")
    for warn in report.warnings:
        click.echo(f"WARN: {warn}")
    if report.module:
        click.echo(f"module: {report.module.module_id} v{report.module.version}")


@companion.command("apply-bundle")
@click.option("--bundle", "bundle", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--root", "root", default="", help="Override companion state root.")
@click.option("--execute/--dry-run", "execute", default=False, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def companion_apply_bundle(ctx: click.Context, bundle: Path, root: str, execute: bool, as_json: bool) -> None:
    kernel = _kernel_from_ctx(ctx, root=root)
    verifier = BundleVerifier(
        kernel,
        secret=_secret_from_env(),
        require_signature=_require_signature_from_env(default=True),
    )
    applier = UpdateApplier(kernel, verifier=verifier)
    result = applier.apply_bundle(bundle, dry_run=not execute)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"apply ok: {bool(result.get('ok'))}")
    click.echo(f"dry_run: {bool(result.get('dry_run'))}")
    click.echo(f"module_id: {result.get('module_id')}")
    for err in result.get("errors") or []:
        click.echo(f"ERROR: {err}")
    for warn in result.get("warnings") or []:
        click.echo(f"WARN: {warn}")


@companion.command("write-template")
@click.option("--out-dir", "out_dir", required=True, type=click.Path(path_type=Path))
@click.option("--module-id", "module_id", default="companion.home", show_default=True)
@click.option("--module-version", "module_version", default="0.1.0", show_default=True)
@click.pass_context
def companion_write_template(
    ctx: click.Context,
    out_dir: Path,
    module_id: str,
    module_version: str,
) -> None:
    """Write a starter signed-update bundle template."""
    _ = ctx
    from datetime import datetime, timezone
    from hashlib import sha256

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = out_dir / "payload" / "modules" / module_id / "ui"
    payload.mkdir(parents=True, exist_ok=True)
    screen = payload / "screen.json"
    if not screen.exists():
        screen.write_text(
            json.dumps(
                {
                    "screen_id": "home",
                    "title": "Companion Home",
                    "components": [{"type": "text", "value": "hello from module"}],
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
    entrypoint = f"modules/{module_id}/ui/screen.json"
    rel = f"modules/{module_id}/ui/screen.json"
    file_sha = sha256(screen.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "bundle_id": f"{module_id}-{module_version}",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "min_kernel_version": "0.1.0",
        "module": {
            "id": module_id,
            "version": module_version,
            "entrypoint": entrypoint,
            "slots": ["home.main"],
            "permissions": ["ui.render", "storage.read"],
            "ui_schema_version": "0.1.0",
            "display_name": "Companion Starter",
            "description": "Starter module template.",
        },
        "files": [{"path": rel, "sha256": file_sha}],
        "release_notes": "starter template",
        "signature": {"algo": "hmac-sha256", "value": "REPLACE_ME"},
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Wrote bundle template: {out_dir}")
    click.echo("Next: set signature.value using your HMAC secret.")


def register_companion_commands(cli: click.Group) -> None:
    if "companion" not in cli.commands:
        cli.add_command(companion)
