from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .network import TailscalePolicy

KERNEL_VERSION = "0.1.0"


@dataclass(frozen=True)
class CompanionKernelPaths:
    root: Path
    modules_dir: Path
    bundles_dir: Path
    backups_dir: Path
    logs_dir: Path
    registry_file: Path
    policy_file: Path
    devices_file: Path
    releases_file: Path


def _default_root_from_config(config: Any | None) -> Path:
    env = str(os.environ.get("THOMAS_COMPANION_STATE_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if config is not None:
        try:
            root = Path(getattr(config.memory, "root_path")).resolve()
            return (root / ".thomas" / "companion").resolve()
        except Exception:
            pass
    return (Path.home() / ".thomas" / "companion").resolve()


def build_kernel_paths(root: Path) -> CompanionKernelPaths:
    return CompanionKernelPaths(
        root=root,
        modules_dir=root / "modules",
        bundles_dir=root / "bundles",
        backups_dir=root / "backups",
        logs_dir=root / "logs",
        registry_file=root / "registry.json",
        policy_file=root / "policy.json",
        devices_file=root / "devices.json",
        releases_file=root / "releases.json",
    )


class CompanionKernel:
    """Immutable host kernel for companion module runtime."""

    def __init__(self, root: Path):
        self.paths = build_kernel_paths(root.resolve())

    @classmethod
    def from_config(cls, config: Any | None, *, root_override: str = "") -> "CompanionKernel":
        if root_override:
            root = Path(root_override).expanduser().resolve()
        else:
            root = _default_root_from_config(config)
        return cls(root=root)

    def init_layout(self) -> CompanionKernelPaths:
        p = self.paths
        p.root.mkdir(parents=True, exist_ok=True)
        p.modules_dir.mkdir(parents=True, exist_ok=True)
        p.bundles_dir.mkdir(parents=True, exist_ok=True)
        p.backups_dir.mkdir(parents=True, exist_ok=True)
        p.logs_dir.mkdir(parents=True, exist_ok=True)
        if not p.registry_file.exists():
            p.registry_file.write_text(
                json.dumps({"schema_version": 1, "modules": {}}, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        if not p.policy_file.exists():
            p.policy_file.write_text(
                json.dumps(self.default_policy(), indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        if not p.devices_file.exists():
            p.devices_file.write_text(
                json.dumps({"schema_version": 1, "devices": {}}, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        if not p.releases_file.exists():
            p.releases_file.write_text(
                json.dumps({"schema_version": 1, "releases": {}}, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        return p

    @staticmethod
    def default_policy() -> dict[str, Any]:
        tailscale = TailscalePolicy()
        return {
            "schema_version": 1,
            "kernel_version": KERNEL_VERSION,
            "tailscale_only": bool(tailscale.tailscale_only),
            "tailscale_suffix": tailscale.allowed_tailnet_suffix,
            "require_signed_updates": True,
            "immutable_kernel_paths": [
                "policy.json",
                "registry.json",
                "backups/",
                "logs/",
            ],
            "allowed_module_permissions": [
                "ui.render",
                "storage.read",
                "storage.write",
                "network.egress",
                "notifications.send",
                "device.camera.read",
                "device.mic.read",
                "device.location.read",
            ],
        }

    def load_policy(self) -> dict[str, Any]:
        self.init_layout()
        try:
            data = json.loads(self.paths.policy_file.read_text(encoding="utf-8"))
        except Exception:
            data = self.default_policy()
        if not isinstance(data, dict):
            return self.default_policy()
        return data

    def status(self) -> dict[str, Any]:
        self.init_layout()
        policy = self.load_policy()
        modules_count = 0
        devices_count = 0
        releases_count = 0
        try:
            payload = json.loads(self.paths.registry_file.read_text(encoding="utf-8"))
            mods = payload.get("modules")
            if isinstance(mods, dict):
                modules_count = len(mods)
        except Exception:
            modules_count = 0
        try:
            payload = json.loads(self.paths.devices_file.read_text(encoding="utf-8"))
            rows = payload.get("devices")
            if isinstance(rows, dict):
                devices_count = len(rows)
        except Exception:
            devices_count = 0
        try:
            payload = json.loads(self.paths.releases_file.read_text(encoding="utf-8"))
            rows = payload.get("releases")
            if isinstance(rows, dict):
                releases_count = len(rows)
        except Exception:
            releases_count = 0
        return {
            "kernel_version": KERNEL_VERSION,
            "root": str(self.paths.root),
            "modules_dir": str(self.paths.modules_dir),
            "bundles_dir": str(self.paths.bundles_dir),
            "require_signed_updates": bool(policy.get("require_signed_updates", True)),
            "tailscale_only": bool(policy.get("tailscale_only", True)),
            "modules_count": modules_count,
            "devices_count": devices_count,
            "releases_count": releases_count,
        }
