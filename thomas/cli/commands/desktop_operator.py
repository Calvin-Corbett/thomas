from __future__ import annotations

import json

import click

from thomas.desktop_operator.host_service import get_global_desktop_host_service
from thomas.desktop_operator.manager import get_global_desktop_operator_manager
from thomas.desktop_operator.runtime import resolve_artifacts_dir
from thomas.desktop_operator.vm import create_vm_supervisor, resolve_vm_context


def _effective_env(
    *,
    vm_name: str,
    vm_address: str,
    helper_port: int | None,
    managed: bool,
    dev_loopback_ok: bool,
) -> dict[str, str]:
    env: dict[str, str] = {}
    if vm_name:
        env["THOMAS_DESKTOP_VM_NAME"] = vm_name
    if vm_address:
        env["THOMAS_DESKTOP_VM_ADDRESS"] = vm_address
    if helper_port is not None:
        env["THOMAS_DESKTOP_HELPER_PORT"] = str(int(helper_port))
    env["THOMAS_DESKTOP_VM_MANAGE"] = "1" if managed else "0"
    env["THOMAS_DESKTOP_VM_DEV_LOOPBACK_OK"] = "1" if dev_loopback_ok else "0"
    return env


@click.group(name="desktop-operator")
def desktop_operator_group() -> None:
    """Inspect and prepare the Thomas desktop operator VM/workflow surface."""


@desktop_operator_group.command("status")
@click.option("--json-output", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def desktop_operator_status(json_output: bool) -> None:
    """Show the current desktop operator status, VM posture, helper connectivity, and host-service readiness."""
    manager = get_global_desktop_operator_manager()
    payload = manager.status_snapshot()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo("Desktop Operator")
    click.echo(f"  service: {payload.get('service_id')}")
    click.echo(f"  running: {bool(payload.get('running'))}")
    click.echo(f"  connection mode: {payload.get('connection_mode') or 'unknown'}")
    vm = payload.get("vm") if isinstance(payload.get("vm"), dict) else {}
    click.echo(f"  vm: {vm.get('vm_id') or '-'} ({vm.get('provider') or '-'}, isolated={bool(vm.get('isolated'))})")
    host = payload.get("host_posture") if isinstance(payload.get("host_posture"), dict) else {}
    if host:
        click.echo(f"  isolated desktop: {host.get('installation_state') or 'not_enabled'}")
        click.echo(f"  session target: {host.get('session_target') or 'local_vm'}")
        click.echo(f"  trust mode: {host.get('trust_mode') or 'ask_every_time'}")
        click.echo(f"  local vm ready: {bool(host.get('local_vm_ready'))}")
        if host.get("next_action"):
            click.echo(f"  next action: {host.get('next_action')}")
    bootstrap = payload.get("vm_bootstrap") if isinstance(payload.get("vm_bootstrap"), dict) else {}
    if bootstrap:
        click.echo(f"  vm bootstrap: {bootstrap.get('launch_mode') or '-'}")
        click.echo(f"  guest workspace: {bootstrap.get('guest_workspace') or '-'}")
        click.echo(f"  helper ready: {bool(bootstrap.get('helper_ready'))}")
        if bootstrap.get("refusal_reason"):
            click.echo(f"  note: {bootstrap.get('refusal_reason')}")
    viewer = payload.get("viewer") if isinstance(payload.get("viewer"), dict) else {}
    if viewer:
        click.echo(f"  viewer: {viewer.get('label') or viewer.get('mode') or '-'}")
        click.echo(f"  viewer available: {bool(viewer.get('available'))}")
        if viewer.get("url"):
            click.echo(f"  viewer url: {viewer.get('url')}")
        if viewer.get("command"):
            click.echo(f"  viewer command: {viewer.get('command')}")
    if payload.get("last_error"):
        click.echo(f"  last error: {payload.get('last_error')}")


@desktop_operator_group.command("enable-isolated")
@click.option("--json-output", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def desktop_operator_enable_isolated(json_output: bool) -> None:
    """Stage the isolated desktop host capability without requiring manual shell setup."""
    service = get_global_desktop_host_service()
    posture = service.request_opt_in(hidden_by_default=True)
    posture = service.install_host_capability(stage_only=True)
    payload = posture.to_dict()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("Isolated Desktop Mode")
    click.echo(f"  state: {payload.get('installation_state')}")
    click.echo(f"  install script: {payload.get('install_script_path') or '-'}")
    click.echo(f"  uninstall script: {payload.get('uninstall_script_path') or '-'}")
    click.echo(f"  trust mode: {payload.get('trust_mode') or 'ask_every_time'}")
    if payload.get("next_action"):
        click.echo(f"  next action: {payload.get('next_action')}")


@desktop_operator_group.command("install-host")
@click.option("--json-output", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def desktop_operator_install_host(json_output: bool) -> None:
    """Request one Windows admin consent prompt to install the isolated desktop host service."""
    service = get_global_desktop_host_service()
    service.request_opt_in(hidden_by_default=True)
    launch = service.launch_host_service_install()
    if json_output:
        click.echo(json.dumps(launch, ensure_ascii=False, indent=2))
        return
    posture = launch.get("posture") if isinstance(launch.get("posture"), dict) else {}
    click.echo("Desktop Host Install")
    click.echo(f"  launched: {bool(launch.get('launched'))}")
    click.echo(f"  state: {posture.get('installation_state') or '-'}")
    if posture.get("next_action"):
        click.echo(f"  next action: {posture.get('next_action')}")
    if launch.get("note"):
        click.echo(f"  note: {launch.get('note')}")


@desktop_operator_group.command("bootstrap")
@click.option("--vm-name", default="", help="Override the local desktop worker VM name.")
@click.option("--vm-address", default="", help="Guest VM IP/hostname for the helper endpoint.")
@click.option("--helper-port", type=int, default=None, help="Guest helper TCP port.")
@click.option(
    "--managed/--no-managed",
    default=False,
    show_default=True,
    help="Allow Thomas to restore/start the VM with Hyper-V.",
)
@click.option(
    "--dev-loopback-ok", is_flag=True, help="Permit local helper fallback when the VM helper is not configured."
)
@click.option("--json-output", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def desktop_operator_bootstrap(
    vm_name: str,
    vm_address: str,
    helper_port: int | None,
    managed: bool,
    dev_loopback_ok: bool,
    json_output: bool,
) -> None:
    """Prepare the desktop worker VM bridge, guest bootstrap scripts, and manifest package."""
    vm_context = resolve_vm_context()
    artifacts_dir = resolve_artifacts_dir()
    env = _effective_env(
        vm_name=str(vm_name or "").strip(),
        vm_address=str(vm_address or "").strip(),
        helper_port=helper_port,
        managed=bool(managed),
        dev_loopback_ok=bool(dev_loopback_ok),
    )
    supervisor = create_vm_supervisor(vm_context, artifacts_dir=artifacts_dir, env=env)
    bootstrap = supervisor.build_bootstrap().to_dict()
    bootstrap["next_steps"] = [
        "Copy the generated control scripts into the guest workspace if the VM does not already share the bridge directory.",
        "Ensure Python and the Thomas package are available inside the guest.",
        "Provide THOMAS_DESKTOP_VM_ADDRESS plus helper port, or guest credentials for PowerShell Direct bootstrap.",
        "Use the staged host-service install flow before expecting users to manage Windows features manually.",
        "Run thomas desktop-operator status --json after the helper is reachable to confirm remote_vm connectivity.",
    ]
    if json_output:
        click.echo(json.dumps(bootstrap, ensure_ascii=False, indent=2))
        return

    click.echo("Desktop Operator VM Bootstrap")
    click.echo(f"  vm name: {bootstrap.get('vm_name')}")
    click.echo(f"  snapshot: {bootstrap.get('snapshot_name')}")
    click.echo(f"  helper endpoint: {bootstrap.get('helper_base_url') or '(not configured yet)'}")
    click.echo(f"  host ingress: {bootstrap.get('artifact_ingress_dir')}")
    click.echo(f"  host egress: {bootstrap.get('artifact_egress_dir')}")
    click.echo(f"  guest workspace: {bootstrap.get('guest_workspace')}")
    click.echo(f"  guest launch script: {bootstrap.get('guest_launch_script_path')}")
    click.echo(f"  guest scheduled-task script: {bootstrap.get('guest_register_task_script_path')}")
    click.echo(f"  startup command: {bootstrap.get('startup_command')}")
    click.echo(f"  viewer: {bootstrap.get('viewer_label') or bootstrap.get('viewer_mode') or '-'}")
    if bootstrap.get("viewer_url"):
        click.echo(f"  viewer url: {bootstrap.get('viewer_url')}")
    if bootstrap.get("viewer_command"):
        click.echo(f"  viewer command: {bootstrap.get('viewer_command')}")
    if bootstrap.get("refusal_reason"):
        click.echo(f"  note: {bootstrap.get('refusal_reason')}")
    click.echo("  next steps:")
    for step in bootstrap["next_steps"]:
        click.echo(f"    - {step}")


def register_desktop_operator_commands(cli) -> None:
    cli.add_command(desktop_operator_group)
