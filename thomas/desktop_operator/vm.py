from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import DesktopVmContext

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_DEFAULT_HELPER_PORT = 18734


def _env_bool(name: str, *, default: bool, env: dict[str, str] | None = None) -> bool:
    source = env or os.environ
    raw = str(source.get(name) or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return bool(default)


def resolve_vm_context() -> DesktopVmContext:
    isolated = _env_bool("THOMAS_DESKTOP_VM_ISOLATED", default=True)
    host = socket.gethostname()
    vm_id = str(os.environ.get("THOMAS_DESKTOP_VM_ID") or "").strip() or (f"{host}-desktop-vm" if isolated else host)
    provider = str(os.environ.get("THOMAS_DESKTOP_VM_PROVIDER") or "").strip() or (
        "hyperv_local_vm" if isolated else "host_session"
    )
    isolation_mode = str(os.environ.get("THOMAS_DESKTOP_VM_MODE") or "").strip() or (
        "dedicated_vm" if isolated else "shared_session"
    )
    viewer_mode = str(os.environ.get("THOMAS_DESKTOP_VM_VIEWER_MODE") or "").strip() or (
        "hyperv_console" if isolated else "none"
    )
    viewer_url = str(os.environ.get("THOMAS_DESKTOP_VM_VIEWER_URL") or "").strip()
    viewer_label = str(os.environ.get("THOMAS_DESKTOP_VM_VIEWER_LABEL") or "").strip() or (
        "Hyper-V console" if viewer_mode == "hyperv_console" else viewer_mode.replace("_", " ").strip().title()
    )
    viewer_takeover_supported = _env_bool(
        "THOMAS_DESKTOP_VM_TAKEOVER_SUPPORTED",
        default=bool(isolated),
    )
    return DesktopVmContext(
        vm_id=vm_id,
        provider=provider,
        isolation_mode=isolation_mode,
        isolated=isolated,
        viewer_mode=viewer_mode,
        viewer_url=viewer_url,
        viewer_label=viewer_label,
        viewer_takeover_supported=viewer_takeover_supported,
    )


@dataclass(frozen=True)
class DesktopVmBootstrap:
    vm_context: DesktopVmContext
    vm_name: str
    snapshot_name: str
    helper_base_url: str
    helper_token: str
    helper_host: str
    helper_port: int
    artifact_ingress_dir: str
    artifact_egress_dir: str
    control_dir: str
    guest_workspace: str
    guest_artifact_dir: str
    guest_launch_script_path: str
    guest_register_task_script_path: str
    guest_bootstrap_manifest_path: str
    guest_bundle_zip_path: str
    startup_command: str
    launch_mode: str
    managed: bool
    helper_ready: bool
    powershell_direct_available: bool
    viewer_mode: str = "none"
    viewer_url: str = ""
    viewer_label: str = ""
    viewer_takeover_supported: bool = False
    viewer_command: str = ""
    bootstrap_manifest_path: str = ""
    refusal_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "vm": self.vm_context.to_dict(),
            "vm_name": self.vm_name,
            "snapshot_name": self.snapshot_name,
            "helper_base_url": self.helper_base_url,
            "helper_host": self.helper_host,
            "helper_port": int(self.helper_port),
            "helper_token_present": bool(self.helper_token),
            "artifact_ingress_dir": self.artifact_ingress_dir,
            "artifact_egress_dir": self.artifact_egress_dir,
            "control_dir": self.control_dir,
            "guest_workspace": self.guest_workspace,
            "guest_artifact_dir": self.guest_artifact_dir,
            "guest_launch_script_path": self.guest_launch_script_path,
            "guest_register_task_script_path": self.guest_register_task_script_path,
            "guest_bootstrap_manifest_path": self.guest_bootstrap_manifest_path,
            "guest_bundle_zip_path": self.guest_bundle_zip_path,
            "startup_command": self.startup_command,
            "launch_mode": self.launch_mode,
            "managed": bool(self.managed),
            "helper_ready": bool(self.helper_ready),
            "powershell_direct_available": bool(self.powershell_direct_available),
            "viewer_mode": self.viewer_mode,
            "viewer_url": self.viewer_url,
            "viewer_label": self.viewer_label,
            "viewer_takeover_supported": bool(self.viewer_takeover_supported),
            "viewer_command": self.viewer_command,
            "bootstrap_manifest_path": self.bootstrap_manifest_path,
            "refusal_reason": self.refusal_reason,
        }


class HyperVDesktopVmSupervisor:
    def __init__(
        self,
        *,
        vm_context: DesktopVmContext,
        artifacts_dir: Path,
        env: dict[str, str] | None = None,
        run_command: Callable[..., Any] | None = None,
    ) -> None:
        self.vm_context = vm_context
        self.artifacts_dir = Path(artifacts_dir).resolve()
        self.env = dict(env or os.environ)
        self._run_command = run_command or subprocess.run

    def ensure_ready(self) -> DesktopVmBootstrap:
        bootstrap = self.build_bootstrap()
        if not self.vm_context.isolated:
            return bootstrap
        if bootstrap.managed:
            self.restore_snapshot(bootstrap)
            self.start_vm(bootstrap)
        if bootstrap.powershell_direct_available:
            self.bootstrap_guest_helper(bootstrap)
        if bootstrap.helper_base_url and bootstrap.helper_token:
            launch_mode = "remote_helper_bootstrapped" if bootstrap.powershell_direct_available else "remote_helper"
            return DesktopVmBootstrap(
                **{**bootstrap.__dict__, "helper_ready": True, "launch_mode": launch_mode, "refusal_reason": ""}
            )
        if _env_bool("THOMAS_DESKTOP_VM_DEV_LOOPBACK_OK", default=False, env=self.env):
            return DesktopVmBootstrap(
                **{
                    **bootstrap.__dict__,
                    "launch_mode": "dev_loopback",
                    "helper_ready": False,
                    "refusal_reason": "VM helper endpoint is not configured; dev loopback fallback was requested.",
                }
            )
        return DesktopVmBootstrap(
            **{
                **bootstrap.__dict__,
                "launch_mode": "guest_bootstrap_required",
                "helper_ready": False,
                "refusal_reason": (
                    "Desktop VM bootstrap package is ready, but the guest helper endpoint is not configured. "
                    "Set THOMAS_DESKTOP_VM_ADDRESS and THOMAS_DESKTOP_HELPER_PORT, or provide PowerShell Direct guest credentials."
                ),
            }
        )

    def build_bootstrap(self) -> DesktopVmBootstrap:
        vm_name = str(self.env.get("THOMAS_DESKTOP_VM_NAME") or "").strip() or self.vm_context.vm_id
        snapshot_name = str(self.env.get("THOMAS_DESKTOP_VM_SNAPSHOT") or "").strip() or "thomas-clean"
        guest_workspace = str(self.env.get("THOMAS_DESKTOP_VM_GUEST_WORKSPACE") or "").strip() or r"C:\ThomasDesktop"
        guest_artifact_dir = (
            str(self.env.get("THOMAS_DESKTOP_VM_GUEST_ARTIFACT_DIR") or "").strip() or rf"{guest_workspace}\artifacts"
        )
        helper_base_url_override = str(self.env.get("THOMAS_DESKTOP_HELPER_BASE_URL") or "").strip()
        helper_host = str(
            self.env.get("THOMAS_DESKTOP_VM_ADDRESS") or self.env.get("THOMAS_DESKTOP_HELPER_HOST") or ""
        ).strip()
        helper_port = int(str(self.env.get("THOMAS_DESKTOP_HELPER_PORT") or _DEFAULT_HELPER_PORT).strip())
        helper_token = str(self.env.get("THOMAS_DESKTOP_HELPER_TOKEN") or "").strip() or secrets.token_urlsafe(32)
        helper_base_url = helper_base_url_override or (f"http://{helper_host}:{helper_port}" if helper_host else "")
        managed = _env_bool("THOMAS_DESKTOP_VM_MANAGE", default=False, env=self.env)
        powershell_direct_available = bool(
            str(self.env.get("THOMAS_DESKTOP_VM_GUEST_USERNAME") or "").strip()
            and str(self.env.get("THOMAS_DESKTOP_VM_GUEST_PASSWORD") or "").strip()
        )
        viewer_mode_override = str(self.env.get("THOMAS_DESKTOP_VM_VIEWER_MODE") or "").strip()
        viewer_mode = viewer_mode_override or str(self.vm_context.viewer_mode or "").strip()
        if self.vm_context.isolated and viewer_mode in {"", "none"} and not viewer_mode_override:
            viewer_mode = "hyperv_console"
        if not viewer_mode:
            viewer_mode = "none"
        viewer_url = str(self.env.get("THOMAS_DESKTOP_VM_VIEWER_URL") or self.vm_context.viewer_url or "").strip()
        viewer_label = str(
            self.env.get("THOMAS_DESKTOP_VM_VIEWER_LABEL") or self.vm_context.viewer_label or ""
        ).strip() or (
            "Hyper-V console" if viewer_mode == "hyperv_console" else viewer_mode.replace("_", " ").strip().title()
        )
        viewer_takeover_supported = _env_bool(
            "THOMAS_DESKTOP_VM_TAKEOVER_SUPPORTED",
            default=bool(self.vm_context.viewer_takeover_supported or self.vm_context.isolated),
            env=self.env,
        )
        viewer_command = str(self.env.get("THOMAS_DESKTOP_VM_VIEWER_COMMAND") or "").strip()
        if not viewer_command and viewer_mode == "hyperv_console":
            viewer_command = f'vmconnect.exe localhost "{vm_name}"'

        bridge_root = (self.artifacts_dir / "vm_bridge" / vm_name).resolve()
        ingress_dir = bridge_root / "ingress"
        egress_dir = bridge_root / "egress"
        control_dir = bridge_root / "control"
        ingress_dir.mkdir(parents=True, exist_ok=True)
        egress_dir.mkdir(parents=True, exist_ok=True)
        control_dir.mkdir(parents=True, exist_ok=True)

        guest_launch_script_path = control_dir / "launch-helper.ps1"
        guest_register_task_script_path = control_dir / "register-helper-task.ps1"
        guest_bootstrap_manifest_path = control_dir / "guest-bootstrap.json"
        guest_bundle_zip_path = control_dir / "guest-helper-bundle.zip"
        bootstrap_manifest_path = control_dir / "bootstrap.json"
        self._build_guest_bundle(guest_bundle_zip_path)

        launch_script = self._guest_launch_script(
            helper_port=helper_port,
            helper_token=helper_token,
            guest_artifact_dir=guest_artifact_dir,
        )
        guest_launch_script_path.write_text(launch_script, encoding="utf-8")
        register_script = self._guest_register_task_script(
            launch_script_path=rf"{guest_workspace}\control\launch-helper.ps1",
        )
        guest_register_task_script_path.write_text(register_script, encoding="utf-8")

        guest_manifest = {
            "vm": self.vm_context.to_dict(),
            "vm_name": vm_name,
            "guest_workspace": guest_workspace,
            "guest_artifact_dir": guest_artifact_dir,
            "helper_host": helper_host,
            "helper_port": helper_port,
            "helper_token": helper_token,
            "host_ingress_dir": str(ingress_dir),
            "host_egress_dir": str(egress_dir),
            "control_dir": str(control_dir),
            "launch_script_path": rf"{guest_workspace}\control\launch-helper.ps1",
            "register_task_script_path": rf"{guest_workspace}\control\register-helper-task.ps1",
            "bundle_zip_path": rf"{guest_workspace}\control\guest-helper-bundle.zip",
        }
        guest_bootstrap_manifest_path.write_text(
            json.dumps(guest_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        manifest = {
            "vm": self.vm_context.to_dict(),
            "vm_name": vm_name,
            "snapshot_name": snapshot_name,
            "guest_workspace": guest_workspace,
            "guest_artifact_dir": guest_artifact_dir,
            "artifact_ingress_dir": str(ingress_dir),
            "artifact_egress_dir": str(egress_dir),
            "control_dir": str(control_dir),
            "helper_host": helper_host,
            "helper_port": helper_port,
            "helper_base_url": helper_base_url,
            "helper_token_present": bool(helper_token),
            "managed": bool(managed),
            "powershell_direct_available": bool(powershell_direct_available),
            "guest_bundle_zip_path": str(guest_bundle_zip_path),
            "viewer_mode": viewer_mode,
            "viewer_url": viewer_url,
            "viewer_label": viewer_label,
            "viewer_takeover_supported": bool(viewer_takeover_supported),
            "viewer_command": viewer_command,
        }
        bootstrap_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return DesktopVmBootstrap(
            vm_context=self.vm_context,
            vm_name=vm_name,
            snapshot_name=snapshot_name,
            helper_base_url=helper_base_url,
            helper_token=helper_token,
            helper_host=helper_host,
            helper_port=helper_port,
            artifact_ingress_dir=str(ingress_dir),
            artifact_egress_dir=str(egress_dir),
            control_dir=str(control_dir),
            guest_workspace=guest_workspace,
            guest_artifact_dir=guest_artifact_dir,
            guest_launch_script_path=str(guest_launch_script_path),
            guest_register_task_script_path=str(guest_register_task_script_path),
            guest_bootstrap_manifest_path=str(guest_bootstrap_manifest_path),
            guest_bundle_zip_path=str(guest_bundle_zip_path),
            startup_command=(
                f"python -m thomas.desktop_operator.helper_main --host 0.0.0.0 --port {helper_port} "
                f"--token '{helper_token}' --artifact-dir '{guest_artifact_dir}' --vm-id '{self.vm_context.vm_id}' "
                f"--vm-provider '{self.vm_context.provider}' --vm-mode '{self.vm_context.isolation_mode}'"
                + (" --isolated" if self.vm_context.isolated else "")
            ),
            launch_mode="host_session" if not self.vm_context.isolated else "preprovisioned_vm",
            managed=managed,
            helper_ready=bool(helper_base_url and helper_token),
            powershell_direct_available=bool(powershell_direct_available),
            viewer_mode=viewer_mode,
            viewer_url=viewer_url,
            viewer_label=viewer_label,
            viewer_takeover_supported=bool(viewer_takeover_supported),
            viewer_command=viewer_command,
            bootstrap_manifest_path=str(bootstrap_manifest_path),
        )

    def restore_snapshot(self, bootstrap: DesktopVmBootstrap) -> None:
        self._run_powershell(
            f"Restore-VMSnapshot -VMName '{bootstrap.vm_name}' -Name '{bootstrap.snapshot_name}' -Confirm:$false"
        )

    def start_vm(self, bootstrap: DesktopVmBootstrap) -> None:
        self._run_powershell(f"Start-VM -Name '{bootstrap.vm_name}'")

    def stop_vm(self, bootstrap: DesktopVmBootstrap) -> None:
        self._run_powershell(f"Stop-VM -Name '{bootstrap.vm_name}' -TurnOff -Force")

    def bootstrap_guest_helper(self, bootstrap: DesktopVmBootstrap) -> None:
        username = str(self.env.get("THOMAS_DESKTOP_VM_GUEST_USERNAME") or "").strip()
        password = str(self.env.get("THOMAS_DESKTOP_VM_GUEST_PASSWORD") or "").strip()
        if not username or not password:
            return
        guest_workspace = bootstrap.guest_workspace.replace("'", "''")
        guest_artifact_dir = bootstrap.guest_artifact_dir.replace("'", "''")
        launch_command = bootstrap.startup_command.replace("'", "''")
        script = (
            "$secure = ConvertTo-SecureString '" + password.replace("'", "''") + "' -AsPlainText -Force; "
            "$cred = New-Object System.Management.Automation.PSCredential('"
            + username.replace("'", "''")
            + "', $secure); "
            "Invoke-Command -VMName '" + bootstrap.vm_name.replace("'", "''") + "' -Credential $cred -ScriptBlock { "
            "param($workspace, $artifactDir, $command) "
            "New-Item -ItemType Directory -Force -Path $workspace | Out-Null; "
            "New-Item -ItemType Directory -Force -Path (Join-Path $workspace 'control') | Out-Null; "
            "New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null; "
            "Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command',$command -WindowStyle Hidden; "
            "} -ArgumentList '" + guest_workspace + "','" + guest_artifact_dir + "','" + launch_command + "'"
        )
        self._run_powershell(script)

    def _guest_launch_script(self, *, helper_port: int, helper_token: str, guest_artifact_dir: str) -> str:
        vm_provider = str(self.vm_context.provider or "hyperv_local_vm")
        vm_mode = str(self.vm_context.isolation_mode or "dedicated_vm")
        vm_id = str(self.vm_context.vm_id or "thomas-desktop-vm")
        isolated_flag = " --isolated" if self.vm_context.isolated else ""
        return f"""$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $root
$bundleZip = Join-Path $root 'guest-helper-bundle.zip'
$bundleRoot = Join-Path $workspace 'bundle'
if (-not (Test-Path (Join-Path $bundleRoot 'thomas\\desktop_operator\\helper_main.py'))) {{
  if (-not (Test-Path $bundleZip)) {{
    throw "Missing guest helper bundle: $bundleZip"
  }}
  if (Test-Path $bundleRoot) {{
    Remove-Item -Recurse -Force $bundleRoot
  }}
  Expand-Archive -Path $bundleZip -DestinationPath $bundleRoot -Force
}}
$python = Join-Path $workspace '.venv\\Scripts\\python.exe'
if (-not (Test-Path $python)) {{
  $python = 'python'
}}
$artifactDir = '{guest_artifact_dir}'
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
Push-Location $bundleRoot
try {{
  & $python -m thomas.desktop_operator.helper_main --host 0.0.0.0 --port {helper_port} --token '{helper_token}' --artifact-dir $artifactDir --vm-id '{vm_id}' --vm-provider '{vm_provider}' --vm-mode '{vm_mode}'{isolated_flag}
}} finally {{
  Pop-Location
}}
"""

    def _build_guest_bundle(self, bundle_zip_path: Path) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        bundle_files = [
            repo_root / "thomas" / "__init__.py",
            repo_root / "thomas" / "desktop_operator" / "__init__.py",
            repo_root / "thomas" / "desktop_operator" / "app_adapters.py",
            repo_root / "thomas" / "desktop_operator" / "contracts.py",
            repo_root / "thomas" / "desktop_operator" / "helper_main.py",
            repo_root / "thomas" / "desktop_operator" / "helper_service.py",
            repo_root / "thomas" / "desktop_operator" / "runtime.py",
            repo_root / "thomas" / "desktop_operator" / "vm.py",
            repo_root / "thomas" / "desktop_operator" / "windows_adapter.py",
            repo_root / "thomas" / "core" / "__init__.py",
            repo_root / "thomas" / "core" / "config.py",
            repo_root / "thomas" / "vision" / "__init__.py",
            repo_root / "thomas" / "vision" / "ocr_fallback.py",
        ]
        bundle_zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in bundle_files:
                if not path.exists():
                    continue
                archive.write(path, arcname=str(path.relative_to(repo_root)).replace("\\\\", "/"))

    def _guest_register_task_script(self, *, launch_script_path: str) -> str:
        return f"""$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "{launch_script_path}"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName 'ThomasDesktopOperatorHelper' -Action $action -Trigger $trigger -Description 'Thomas Desktop Operator guest helper' -Force | Out-Null
"""

    def _run_powershell(self, command: str) -> None:
        completed = self._run_command(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            stdout = str(getattr(completed, "stdout", "") or "").strip()
            detail = stderr or stdout or "unknown powershell failure"
            raise RuntimeError(detail)


def create_vm_supervisor(
    vm_context: DesktopVmContext,
    *,
    artifacts_dir: Path,
    env: dict[str, str] | None = None,
    run_command: Callable[..., Any] | None = None,
) -> HyperVDesktopVmSupervisor:
    return HyperVDesktopVmSupervisor(
        vm_context=vm_context,
        artifacts_dir=artifacts_dir,
        env=env,
        run_command=run_command,
    )
