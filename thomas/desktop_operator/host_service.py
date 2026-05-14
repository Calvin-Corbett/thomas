from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

from .vm import DesktopVmBootstrap, create_vm_supervisor, resolve_vm_context

INSTALLATION_STATES = (
    "not_enabled",
    "opt_in_requested",
    "host_service_not_installed",
    "host_service_installing",
    "host_service_ready",
    "relogin_required",
    "reboot_required",
    "local_vm_ready",
    "remote_fallback_available",
    "degraded",
    "unavailable",
)
REMOTE_TRUST_MODES = ("ask_every_time", "remembered", "always_allow")
DEFAULT_PIPE_NAME = r"\\.\pipe\thomas-desktop-host"
DEFAULT_SERVICE_NAME = "ThomasDesktopHostService"
DEFAULT_HOST_BOOTSTRAP_PATH = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "Thomas"
    / "desktop_operator"
    / "host-service-bootstrap.json"
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str, *, default: bool, env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get(name) or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return bool(default)


def normalize_installation_state(value: Any, *, default: str = "not_enabled") -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return raw if raw in INSTALLATION_STATES else default


def normalize_trust_mode(value: Any, *, default: str = "ask_every_time") -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": default,
        "ask": "ask_every_time",
        "ask_every_time": "ask_every_time",
        "prompt": "ask_every_time",
        "remember": "remembered",
        "remembered": "remembered",
        "saved": "remembered",
        "always": "always_allow",
        "always_allow": "always_allow",
        "allow": "always_allow",
    }
    resolved = aliases.get(raw, raw)
    return resolved if resolved in REMOTE_TRUST_MODES else default


@dataclass
class DesktopHostPosture:
    enabled: bool = False
    installation_state: str = "not_enabled"
    service_registered: bool = False
    local_vm_ready: bool = False
    remote_fallback_available: bool = False
    session_target: str = "local_vm"
    trust_mode: str = "ask_every_time"
    local_vm: dict[str, Any] = field(default_factory=dict)
    reboot_required: bool = False
    relogin_required: bool = False
    viewer: dict[str, Any] = field(default_factory=dict)
    next_action: str = ""
    note: str = ""
    magic_ready: bool = False
    install_script_path: str = ""
    uninstall_script_path: str = ""
    pipe_name: str = DEFAULT_PIPE_NAME
    service_name: str = DEFAULT_SERVICE_NAME
    state_path: str = ""
    bootstrap_manifest_path: str = ""
    bundle_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "installation_state": self.installation_state,
            "service_registered": bool(self.service_registered),
            "local_vm_ready": bool(self.local_vm_ready),
            "remote_fallback_available": bool(self.remote_fallback_available),
            "session_target": self.session_target,
            "trust_mode": self.trust_mode,
            "local_vm": dict(self.local_vm),
            "reboot_required": bool(self.reboot_required),
            "relogin_required": bool(self.relogin_required),
            "viewer": dict(self.viewer),
            "next_action": self.next_action,
            "note": self.note,
            "magic_ready": bool(self.magic_ready),
            "install_script_path": self.install_script_path,
            "uninstall_script_path": self.uninstall_script_path,
            "pipe_name": self.pipe_name,
            "service_name": self.service_name,
            "state_path": self.state_path,
            "bootstrap_manifest_path": self.bootstrap_manifest_path,
            "bundle_dir": self.bundle_dir,
        }


class DesktopHostCapabilityService:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
        run_command: Any | None = None,
        launch_process: Any | None = None,
    ) -> None:
        self.env = dict(env or os.environ)
        base_root = (
            Path(root_dir).resolve()
            if root_dir is not None
            else (resolve_thomas_data_dir() / "desktop_operator" / "host_service").resolve()
        )
        self.root_dir = base_root
        self.artifacts_dir = Path(
            self.env.get("THOMAS_ARTIFACTS_DIR") or (self.root_dir.parent.parent / "artifacts")
        ).resolve()
        self.install_dir = self.root_dir / "install"
        self.state_path = self.root_dir / "state.json"
        self.authkey_path = self.install_dir / "host.authkey"
        self.install_script_path = self.install_dir / "install-host-service.ps1"
        self.uninstall_script_path = self.install_dir / "uninstall-host-service.ps1"
        bootstrap_path = self.env.get("THOMAS_DESKTOP_HOST_BOOTSTRAP_PATH")
        if bootstrap_path:
            self.bootstrap_config_path = Path(bootstrap_path).resolve()
        elif root_dir is not None:
            self.bootstrap_config_path = (self.root_dir / "host-service-bootstrap.json").resolve()
        else:
            self.bootstrap_config_path = DEFAULT_HOST_BOOTSTRAP_PATH.resolve()
        self.pipe_name = str(self.env.get("THOMAS_DESKTOP_HOST_PIPE") or DEFAULT_PIPE_NAME).strip() or DEFAULT_PIPE_NAME
        self.service_name = (
            str(self.env.get("THOMAS_DESKTOP_HOST_SERVICE_NAME") or DEFAULT_SERVICE_NAME).strip()
            or DEFAULT_SERVICE_NAME
        )
        self._run_command = run_command or subprocess.run
        self._launch_process = launch_process or subprocess.Popen

    def request_opt_in(self, *, hidden_by_default: bool = True) -> DesktopHostPosture:
        state = self._load_state()
        state["enabled"] = True
        state["hidden_by_default"] = bool(hidden_by_default)
        state["installation_state"] = "opt_in_requested"
        state["session_target"] = "local_vm"
        state["remote_fallback_available"] = True
        state["next_action"] = "Install the Thomas Desktop Host Service."
        self._save_state(state)
        return self.install_host_capability(stage_only=True)

    def disable(self) -> DesktopHostPosture:
        state = self._load_state()
        state.update(
            {
                "enabled": False,
                "installation_state": "not_enabled",
                "next_action": "Enable isolated desktop mode in Thomas settings.",
                "reboot_required": False,
                "relogin_required": False,
                "magic_ready": False,
            }
        )
        self._save_state(state)
        return self.status()

    def install_host_capability(self, *, stage_only: bool = True) -> DesktopHostPosture:
        state = self._load_state()
        state["enabled"] = True
        self._ensure_install_assets()
        if stage_only:
            state["installation_state"] = "host_service_not_installed"
            state["next_action"] = "Request one Windows admin consent to install the isolated desktop host capability."
        else:
            state["service_registered"] = True
            state["installation_state"] = "host_service_ready"
            state["next_action"] = "Prepare the local worker VM."
        if _env_bool("THOMAS_DESKTOP_HOST_REBOOT_REQUIRED", default=False, env=self.env):
            state["reboot_required"] = True
            state["installation_state"] = "reboot_required"
            state["next_action"] = "Restart Windows to finish isolated desktop setup."
        if _env_bool("THOMAS_DESKTOP_HOST_RELOGIN_REQUIRED", default=False, env=self.env):
            state["relogin_required"] = True
            state["installation_state"] = "relogin_required"
            state["next_action"] = "Sign out and back in to finish isolated desktop setup."
        if _env_bool("THOMAS_DESKTOP_HOST_SERVICE_INSTALLED", default=False, env=self.env):
            state["service_registered"] = True
            if state.get("installation_state") not in {"local_vm_ready", "reboot_required", "relogin_required"}:
                state["installation_state"] = "host_service_ready"
                state["next_action"] = "Prepare the local worker VM."
        self._save_state(state)
        return self.status()

    def set_remote_trust_mode(self, trust_mode: str) -> DesktopHostPosture:
        state = self._load_state()
        state["trust_mode"] = normalize_trust_mode(trust_mode)
        self._save_state(state)
        return self.status()

    def configure_local_vm_source(
        self,
        *,
        source_type: str,
        vm_name: str = "",
        template_vhdx: str = "",
        switch_name: str = "",
    ) -> DesktopHostPosture:
        state = self._load_state()
        current = self._local_vm_config_from_state(state)
        normalized_source = str(source_type or current.get("source_type") or "unconfigured").strip().lower()
        if normalized_source not in {"unconfigured", "existing_vm", "template_disk"}:
            raise ValueError("unsupported local VM source type")
        next_config = {
            "source_type": normalized_source,
            "vm_name": str(vm_name or current.get("vm_name") or "").strip(),
            "template_vhdx": str(template_vhdx or "").strip(),
            "switch_name": str(switch_name or "").strip(),
        }
        if not next_config["vm_name"]:
            next_config["vm_name"] = resolve_vm_context().vm_id
        if normalized_source != "template_disk":
            next_config["template_vhdx"] = ""
        if normalized_source == "unconfigured":
            next_config["switch_name"] = ""
        state["local_vm"] = next_config
        state["note"] = ""
        if normalized_source == "existing_vm":
            state["next_action"] = "Validate the configured worker VM and bootstrap the guest helper."
        elif normalized_source == "template_disk":
            state["next_action"] = "Create the worker VM from the configured template disk."
        else:
            state["next_action"] = "Select an existing worker VM or a template disk."
        self._save_state(state)
        return self.status()

    def launch_host_service_install(self) -> dict[str, Any]:
        self.install_host_capability(stage_only=True)
        command = self._install_launch_command()
        result: dict[str, Any] = {
            "ok": False,
            "launched": False,
            "command": command,
            "install_script_path": str(self.install_script_path),
            "note": "",
        }
        try:
            completed = self._run_command(command, capture_output=True, text=True, timeout=30)
            ok = int(getattr(completed, "returncode", 1)) == 0
            result.update(
                {
                    "ok": ok,
                    "launched": ok,
                    "exit_code": int(getattr(completed, "returncode", 1)),
                    "stdout": str(getattr(completed, "stdout", "") or ""),
                    "stderr": str(getattr(completed, "stderr", "") or ""),
                }
            )
            state = self._load_state()
            if ok:
                state["installation_state"] = "host_service_installing"
                state["next_action"] = "Approve the Windows admin prompt to install isolated desktop mode."
            else:
                state["installation_state"] = "host_service_not_installed"
                state["note"] = str(
                    result.get("stderr") or result.get("stdout") or "host install launch failed"
                ).strip()
            self._save_state(state)
            result["posture"] = self.status().to_dict()
            return result
        except Exception as exc:  # noqa: BLE001
            state = self._load_state()
            state["installation_state"] = "host_service_not_installed"
            state["note"] = f"{type(exc).__name__}: {exc}"
            self._save_state(state)
            result["note"] = state["note"]
            result["posture"] = self.status().to_dict()
            return result

    def launch_host_service_uninstall(self) -> dict[str, Any]:
        command = self._uninstall_launch_command()
        result: dict[str, Any] = {
            "ok": False,
            "launched": False,
            "command": command,
            "uninstall_script_path": str(self.uninstall_script_path),
            "note": "",
        }
        try:
            completed = self._run_command(command, capture_output=True, text=True, timeout=30)
            ok = int(getattr(completed, "returncode", 1)) == 0
            result.update(
                {
                    "ok": ok,
                    "launched": ok,
                    "exit_code": int(getattr(completed, "returncode", 1)),
                    "stdout": str(getattr(completed, "stdout", "") or ""),
                    "stderr": str(getattr(completed, "stderr", "") or ""),
                }
            )
            if ok:
                posture = self.disable()
            else:
                posture = self.status()
            result["posture"] = posture.to_dict()
            return result
        except Exception as exc:  # noqa: BLE001
            result["note"] = f"{type(exc).__name__}: {exc}"
            result["posture"] = self.status().to_dict()
            return result

    def launch_viewer(self) -> dict[str, Any]:
        posture = self.status()
        viewer = dict(posture.viewer)
        result: dict[str, Any] = {
            "ok": False,
            "launched": False,
            "viewer": viewer,
            "note": "",
        }
        if not bool(viewer.get("available")):
            result["note"] = "viewer is not available for the current isolated desktop state"
            return result

        try:
            viewer_url = str(viewer.get("url") or "").strip()
            viewer_command = str(viewer.get("command") or "").strip()
            if viewer_url:
                command = ["powershell", "-NoProfile", "-Command", f"Start-Process '{viewer_url}'"]
            elif viewer_command:
                quoted = viewer_command.replace("'", "''")
                command = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Start-Process powershell -ArgumentList @('-NoProfile','-Command','{quoted}')",
                ]
            else:
                result["note"] = "viewer metadata is present but does not include a launch target"
                return result
            self._launch_process(command)
            result["ok"] = True
            result["launched"] = True
            result["command"] = command
            return result
        except Exception as exc:  # noqa: BLE001
            result["note"] = f"{type(exc).__name__}: {exc}"
            return result

    def set_remote_fallback_available(self, available: bool = True) -> DesktopHostPosture:
        state = self._load_state()
        state["remote_fallback_available"] = bool(available)
        self._save_state(state)
        return self.status()

    def ensure_local_vm_ready(self) -> DesktopHostPosture:
        state = self._load_state()
        if not bool(state.get("enabled")):
            return self.status()
        bootstrap_manifest_path = ""
        viewer = self._default_viewer()
        try:
            supervisor = create_vm_supervisor(
                resolve_vm_context(),
                artifacts_dir=self.artifacts_dir,
                env=self._desktop_vm_env(state),
            )
            bootstrap = supervisor.ensure_ready()
            bootstrap_manifest_path = bootstrap.bootstrap_manifest_path
            viewer = self._viewer_from_bootstrap(bootstrap, fallback=viewer)
            state["note"] = str(bootstrap.refusal_reason or "").strip()
            if bootstrap.helper_ready or _env_bool("THOMAS_DESKTOP_VM_READY", default=False, env=self.env):
                state["service_registered"] = True
                state["local_vm_ready"] = True
                state["installation_state"] = "local_vm_ready"
                state["session_target"] = "local_vm"
                state["next_action"] = "Start an isolated desktop session."
            elif bool(state.get("service_registered")):
                state["local_vm_ready"] = False
                state["installation_state"] = "host_service_ready"
                state["next_action"] = state["note"] or "Bootstrap the local worker VM."
        except Exception as exc:  # noqa: BLE001
            state["note"] = f"{type(exc).__name__}: {exc}"
            if state.get("enabled"):
                state["installation_state"] = "degraded"
                state["next_action"] = "Retry worker bootstrap or use remote fallback."
        state["bootstrap_manifest_path"] = bootstrap_manifest_path
        state["viewer"] = viewer
        self._save_state(state)
        return self.status(viewer_fallback=viewer)

    def get_remote_fallback_options(self) -> dict[str, Any]:
        posture = self.status()
        return {
            "available": bool(posture.remote_fallback_available),
            "trust_mode": posture.trust_mode,
            "session_target": posture.session_target,
            "viewer": dict(posture.viewer),
        }

    def status(
        self,
        *,
        viewer_fallback: dict[str, Any] | None = None,
        vm_bootstrap: DesktopVmBootstrap | None = None,
    ) -> DesktopHostPosture:
        state = self._load_state()
        enabled = bool(state.get("enabled", False))
        installation_state = normalize_installation_state(state.get("installation_state"), default="not_enabled")
        if not enabled:
            installation_state = "not_enabled"
        service_registered = bool(
            state.get("service_registered", False)
            or _env_bool("THOMAS_DESKTOP_HOST_SERVICE_INSTALLED", default=False, env=self.env)
        )
        reboot_required = bool(
            state.get("reboot_required", False)
            or _env_bool("THOMAS_DESKTOP_HOST_REBOOT_REQUIRED", default=False, env=self.env)
        )
        relogin_required = bool(
            state.get("relogin_required", False)
            or _env_bool("THOMAS_DESKTOP_HOST_RELOGIN_REQUIRED", default=False, env=self.env)
        )
        local_vm_ready = bool(
            state.get("local_vm_ready", False) or _env_bool("THOMAS_DESKTOP_VM_READY", default=False, env=self.env)
        )
        remote_fallback_available = bool(state.get("remote_fallback_available", False) or enabled)
        trust_mode = normalize_trust_mode(state.get("trust_mode"), default="ask_every_time")
        session_target = str(state.get("session_target") or "local_vm").strip() or "local_vm"
        local_vm = self._local_vm_config_from_state(state)
        note = str(state.get("note") or "").strip()
        next_action = str(state.get("next_action") or "").strip()
        bootstrap_manifest_path = str(state.get("bootstrap_manifest_path") or "").strip()

        viewer = self._default_viewer()
        persisted_viewer = state.get("viewer")
        if isinstance(persisted_viewer, dict) and persisted_viewer:
            viewer.update({k: v for k, v in persisted_viewer.items() if v is not None})
        if isinstance(viewer_fallback, dict) and viewer_fallback:
            viewer.update({k: v for k, v in viewer_fallback.items() if v is not None})
        if vm_bootstrap is not None:
            viewer.update(self._viewer_from_bootstrap(vm_bootstrap, fallback=viewer))
            if vm_bootstrap.bootstrap_manifest_path:
                bootstrap_manifest_path = vm_bootstrap.bootstrap_manifest_path
            local_vm_ready = bool(local_vm_ready or vm_bootstrap.helper_ready)
            if vm_bootstrap.vm_name:
                local_vm["vm_name"] = str(vm_bootstrap.vm_name)
        if reboot_required:
            installation_state = "reboot_required"
            next_action = next_action or "Restart Windows to finish isolated desktop setup."
        elif relogin_required:
            installation_state = "relogin_required"
            next_action = next_action or "Sign out and back in to finish isolated desktop setup."
        elif enabled and local_vm_ready:
            installation_state = "local_vm_ready"
            session_target = "local_vm"
            next_action = next_action or "Start an isolated desktop session."
        elif enabled and service_registered:
            installation_state = "host_service_ready"
            next_action = next_action or "Prepare the local worker VM."
        elif enabled and installation_state in {"not_enabled", "opt_in_requested"}:
            installation_state = "host_service_not_installed"
            next_action = next_action or "Install the Thomas Desktop Host Service."
        elif not enabled:
            next_action = next_action or "Enable isolated desktop mode in Thomas settings."

        if enabled and service_registered and not local_vm_ready and local_vm.get("source_type") == "unconfigured":
            next_action = note or "Select an existing worker VM or a template disk."
        if installation_state == "degraded" and not next_action:
            next_action = "Retry worker bootstrap or use remote fallback."
        if installation_state == "remote_fallback_available":
            session_target = "remote_worker"
        local_vm["configured"] = bool(
            (local_vm.get("source_type") == "existing_vm" and local_vm.get("vm_name"))
            or (
                local_vm.get("source_type") == "template_disk"
                and local_vm.get("vm_name")
                and local_vm.get("template_vhdx")
            )
        )
        magic_ready = (
            enabled and installation_state == "local_vm_ready" and not reboot_required and not relogin_required
        )
        return DesktopHostPosture(
            enabled=enabled,
            installation_state=installation_state,
            service_registered=service_registered,
            local_vm_ready=local_vm_ready,
            remote_fallback_available=remote_fallback_available,
            session_target=session_target,
            trust_mode=trust_mode,
            local_vm=local_vm,
            reboot_required=reboot_required,
            relogin_required=relogin_required,
            viewer=viewer,
            next_action=next_action,
            note=note,
            magic_ready=magic_ready,
            install_script_path=str(self.install_script_path),
            uninstall_script_path=str(self.uninstall_script_path),
            pipe_name=self.pipe_name,
            service_name=self.service_name,
            state_path=str(self.state_path),
            bootstrap_manifest_path=bootstrap_manifest_path,
            bundle_dir=str(self.install_dir),
        )

    def _default_state(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "installation_state": "not_enabled",
            "service_registered": False,
            "local_vm_ready": False,
            "remote_fallback_available": False,
            "session_target": "local_vm",
            "trust_mode": "ask_every_time",
            "local_vm": self._default_local_vm_config(),
            "reboot_required": False,
            "relogin_required": False,
            "hidden_by_default": True,
            "next_action": "Enable isolated desktop mode in Thomas settings.",
            "note": "",
            "bootstrap_manifest_path": "",
            "viewer": self._default_viewer(),
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()
        state = self._default_state()
        if isinstance(payload, dict):
            state.update(payload)
        state["installation_state"] = normalize_installation_state(
            state.get("installation_state"), default="not_enabled"
        )
        state["trust_mode"] = normalize_trust_mode(state.get("trust_mode"), default="ask_every_time")
        state["viewer"] = state.get("viewer") if isinstance(state.get("viewer"), dict) else self._default_viewer()
        state["local_vm"] = self._local_vm_config_from_state(state)
        return state

    def _save_state(self, state: Mapping[str, Any]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["installation_state"] = normalize_installation_state(
            payload.get("installation_state"), default="not_enabled"
        )
        payload["trust_mode"] = normalize_trust_mode(payload.get("trust_mode"), default="ask_every_time")
        payload["viewer"] = payload.get("viewer") if isinstance(payload.get("viewer"), dict) else self._default_viewer()
        payload["local_vm"] = self._local_vm_config_from_state(payload)
        self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _install_launch_command(self) -> list[str]:
        script = str(self.install_script_path).replace("'", "''")
        ps = (
            "Start-Process -FilePath 'powershell.exe' -Verb RunAs "
            f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','{script}')"
        )
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]

    def _uninstall_launch_command(self) -> list[str]:
        script = str(self.uninstall_script_path).replace("'", "''")
        ps = (
            "Start-Process -FilePath 'powershell.exe' -Verb RunAs "
            f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','{script}')"
        )
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]

    def _ensure_install_assets(self) -> None:
        self.install_dir.mkdir(parents=True, exist_ok=True)
        if not self.authkey_path.exists():
            authkey = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
            self.authkey_path.write_text(authkey, encoding="utf-8")
        self.bootstrap_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.bootstrap_config_path.write_text(
            json.dumps(
                {
                    "service_name": self.service_name,
                    "pipe_name": self.pipe_name,
                    "root_dir": str(self.root_dir),
                    "authkey_path": str(self.authkey_path),
                    "state_path": str(self.state_path),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        runner_module = "thomas.desktop_operator.host_service_runner"
        install_script = f"""$ErrorActionPreference = 'Stop'
$serviceName = '{self.service_name}'
$python = '{sys.executable}'
$pipeName = '{self.pipe_name}'
$stateDir = '{self.root_dir}'
$commonArgs = @('-m', '{runner_module}', '--service-name', $serviceName, '--pipe-name', $pipeName, '--root-dir', $stateDir)
try {{
  & $python @($commonArgs + @('stop')) | Out-Null
}} catch {{}}
try {{
  & $python @($commonArgs + @('remove')) | Out-Null
}} catch {{}}
& $python @($commonArgs + @('install', '--startup', 'auto')) | Out-Null
& $python @($commonArgs + @('start')) | Out-Null
Write-Output ('SERVICE=' + $serviceName)
Write-Output ('PIPE=' + $pipeName)
"""
        uninstall_script = f"""$serviceName = '{self.service_name}'
$python = '{sys.executable}'
$pipeName = '{self.pipe_name}'
$stateDir = '{self.root_dir}'
$commonArgs = @('-m', '{runner_module}', '--service-name', $serviceName, '--pipe-name', $pipeName, '--root-dir', $stateDir)
try {{
  & $python @($commonArgs + @('stop')) | Out-Null
}} catch {{}}
try {{
  & $python @($commonArgs + @('remove')) | Out-Null
}} catch {{}}
Write-Output ('SERVICE_REMOVED=' + $serviceName)
"""
        self.install_script_path.write_text(install_script, encoding="utf-8")
        self.uninstall_script_path.write_text(uninstall_script, encoding="utf-8")

    def _desktop_vm_env(self, state: Mapping[str, Any]) -> dict[str, str]:
        merged = dict(self.env)
        local_vm = self._local_vm_config_from_state(state)
        source_type = str(local_vm.get("source_type") or "unconfigured").strip().lower()
        merged["THOMAS_DESKTOP_VM_NAME"] = str(local_vm.get("vm_name") or resolve_vm_context().vm_id)
        if source_type in {"existing_vm", "template_disk"}:
            merged["THOMAS_DESKTOP_VM_MANAGE"] = "1"
        if source_type == "template_disk":
            merged["THOMAS_DESKTOP_VM_TEMPLATE_VHDX"] = str(local_vm.get("template_vhdx") or "")
            if local_vm.get("switch_name"):
                merged["THOMAS_DESKTOP_VM_SWITCH_NAME"] = str(local_vm.get("switch_name") or "")
        return merged

    def _default_local_vm_config(self) -> dict[str, Any]:
        return {
            "source_type": "unconfigured",
            "vm_name": resolve_vm_context().vm_id,
            "template_vhdx": "",
            "switch_name": "",
        }

    def _local_vm_config_from_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(self._default_local_vm_config())
        existing = state.get("local_vm")
        if isinstance(existing, dict):
            payload.update({k: v for k, v in existing.items() if v is not None})
        payload["source_type"] = str(payload.get("source_type") or "unconfigured").strip().lower()
        if payload["source_type"] not in {"unconfigured", "existing_vm", "template_disk"}:
            payload["source_type"] = "unconfigured"
        payload["vm_name"] = (
            str(payload.get("vm_name") or resolve_vm_context().vm_id).strip() or resolve_vm_context().vm_id
        )
        payload["template_vhdx"] = str(payload.get("template_vhdx") or "").strip()
        payload["switch_name"] = str(payload.get("switch_name") or "").strip()
        return payload

    @staticmethod
    def _default_viewer() -> dict[str, Any]:
        return {
            "available": False,
            "mode": "none",
            "label": "",
            "url": "",
            "command": "",
            "takeover_supported": False,
        }

    @staticmethod
    def _viewer_from_bootstrap(
        bootstrap: DesktopVmBootstrap,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        viewer = dict(fallback or {})
        viewer.update(
            {
                "available": bool(
                    bootstrap.viewer_url or bootstrap.viewer_command or bootstrap.viewer_mode not in {"", "none"}
                ),
                "mode": bootstrap.viewer_mode,
                "label": bootstrap.viewer_label,
                "url": bootstrap.viewer_url,
                "command": bootstrap.viewer_command,
                "takeover_supported": bool(bootstrap.viewer_takeover_supported),
            }
        )
        return viewer


_GLOBAL_HOST_SERVICE: DesktopHostCapabilityService | None = None


def get_global_desktop_host_service() -> DesktopHostCapabilityService:
    global _GLOBAL_HOST_SERVICE
    if _GLOBAL_HOST_SERVICE is None:
        _GLOBAL_HOST_SERVICE = DesktopHostCapabilityService()
    return _GLOBAL_HOST_SERVICE
