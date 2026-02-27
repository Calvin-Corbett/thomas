from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .kernel import CompanionKernel


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_installed_modules(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        out: dict[str, str] = {}
        for key, val in value.items():
            module_id = str(key or "").strip()
            if not module_id:
                continue
            out[module_id] = str(val or "").strip()
        return out
    if isinstance(value, list):
        out: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            module_id = str(item.get("module_id") or item.get("id") or "").strip()
            if not module_id:
                continue
            out[module_id] = str(item.get("version") or "").strip()
        return out
    return {}


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    platform: str
    app_version: str
    channel: str
    distribution_channel: str
    storefront_region: str
    app_build_id: str
    tailscale_identity: str
    capabilities: list[str]
    runtime_capability_set: list[str]
    installed_modules: dict[str, str]
    metadata: dict[str, Any]
    policy_profile: str
    pinned_release_id: str
    pinned_at: str
    created_at: str
    last_seen_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceRecord:
        return cls(
            device_id=str(data.get("device_id") or ""),
            platform=str(data.get("platform") or ""),
            app_version=str(data.get("app_version") or ""),
            channel=str(data.get("channel") or "stable"),
            distribution_channel=str(data.get("distribution_channel") or "unknown"),
            storefront_region=str(data.get("storefront_region") or ""),
            app_build_id=str(data.get("app_build_id") or ""),
            tailscale_identity=str(data.get("tailscale_identity") or ""),
            capabilities=[str(x) for x in list(data.get("capabilities") or []) if str(x).strip()],
            runtime_capability_set=[
                str(x)
                for x in list(data.get("runtime_capability_set") or data.get("capabilities") or [])
                if str(x).strip()
            ],
            installed_modules=_normalize_installed_modules(data.get("installed_modules")),
            metadata=dict(data.get("metadata") or {}),
            policy_profile=str(data.get("policy_profile") or "strict_global"),
            pinned_release_id=str(data.get("pinned_release_id") or ""),
            pinned_at=str(data.get("pinned_at") or ""),
            created_at=str(data.get("created_at") or ""),
            last_seen_at=str(data.get("last_seen_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "platform": self.platform,
            "app_version": self.app_version,
            "channel": self.channel,
            "distribution_channel": self.distribution_channel,
            "storefront_region": self.storefront_region,
            "app_build_id": self.app_build_id,
            "tailscale_identity": self.tailscale_identity,
            "capabilities": list(self.capabilities),
            "runtime_capability_set": list(self.runtime_capability_set),
            "installed_modules": dict(self.installed_modules),
            "metadata": dict(self.metadata),
            "policy_profile": self.policy_profile,
            "pinned_release_id": self.pinned_release_id,
            "pinned_at": self.pinned_at,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
        }


class DeviceRegistry:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()

    def _load(self) -> dict[str, Any]:
        path = self.kernel.paths.devices_file
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"schema_version": 1, "devices": {}}
        if not isinstance(payload, dict):
            payload = {"schema_version": 1, "devices": {}}
        rows = payload.get("devices")
        if not isinstance(rows, dict):
            payload["devices"] = {}
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.kernel.paths.devices_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def get(self, device_id: str) -> DeviceRecord | None:
        did = str(device_id or "").strip()
        if not did:
            return None
        payload = self._load()
        item = (payload.get("devices") or {}).get(did)
        if not isinstance(item, dict):
            return None
        row = dict(item)
        row["device_id"] = did
        return DeviceRecord.from_dict(row)

    def list(self, *, channel: str = "") -> list[DeviceRecord]:
        channel_norm = str(channel or "").strip().lower()
        payload = self._load()
        rows = payload.get("devices") or {}
        out: list[DeviceRecord] = []
        for device_id, item in rows.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["device_id"] = str(device_id)
            parsed = DeviceRecord.from_dict(row)
            if channel_norm and parsed.channel.lower() != channel_norm:
                continue
            out.append(parsed)
        out.sort(key=lambda row: (row.last_seen_at, row.device_id), reverse=True)
        return out

    def upsert(
        self,
        *,
        device_id: str,
        platform: str,
        app_version: str,
        channel: str,
        distribution_channel: str = "",
        storefront_region: str = "",
        app_build_id: str = "",
        tailscale_identity: str,
        capabilities: list[str],
        runtime_capability_set: list[str] | None = None,
        installed_modules: dict[str, str],
        metadata: dict[str, Any],
        policy_profile: str = "",
        timestamp: str = "",
    ) -> DeviceRecord:
        did = str(device_id or "").strip()
        if not did:
            raise ValueError("device_id is required")
        now = str(timestamp or _now_iso())

        payload = self._load()
        devices = payload.get("devices")
        if not isinstance(devices, dict):
            devices = {}
            payload["devices"] = devices

        old = devices.get(did) if isinstance(devices.get(did), dict) else {}
        created_at = str(old.get("created_at") or now)
        devices[did] = {
            "platform": str(platform or old.get("platform") or "").strip(),
            "app_version": str(app_version or old.get("app_version") or "").strip(),
            "channel": str(channel or old.get("channel") or "stable").strip() or "stable",
            "distribution_channel": (
                str(distribution_channel or old.get("distribution_channel") or "unknown").strip() or "unknown"
            ),
            "storefront_region": str(storefront_region or old.get("storefront_region") or "").strip(),
            "app_build_id": str(app_build_id or old.get("app_build_id") or "").strip(),
            "tailscale_identity": str(tailscale_identity or old.get("tailscale_identity") or "").strip(),
            "capabilities": [
                str(x).strip() for x in list(capabilities or old.get("capabilities") or []) if str(x).strip()
            ],
            "runtime_capability_set": [
                str(x).strip()
                for x in list(
                    runtime_capability_set
                    if runtime_capability_set is not None
                    else old.get("runtime_capability_set") or capabilities or old.get("capabilities") or []
                )
                if str(x).strip()
            ],
            "installed_modules": _normalize_installed_modules(
                installed_modules if installed_modules else old.get("installed_modules")
            ),
            "metadata": dict(metadata or old.get("metadata") or {}),
            "policy_profile": str(policy_profile or old.get("policy_profile") or "strict_global").strip()
            or "strict_global",
            "pinned_release_id": str(old.get("pinned_release_id") or "").strip(),
            "pinned_at": str(old.get("pinned_at") or "").strip(),
            "created_at": created_at,
            "last_seen_at": now,
        }
        self._save(payload)
        return self.get(did) or DeviceRecord.from_dict({"device_id": did})

    def set_pinned_release(
        self,
        device_id: str,
        release_id: str,
        *,
        timestamp: str = "",
    ) -> DeviceRecord | None:
        did = str(device_id or "").strip()
        rid = str(release_id or "").strip()
        if not did:
            return None
        payload = self._load()
        devices = payload.get("devices")
        if not isinstance(devices, dict):
            return None
        row = devices.get(did)
        if not isinstance(row, dict):
            return None
        now = str(timestamp or _now_iso())
        row["pinned_release_id"] = rid
        row["pinned_at"] = now if rid else ""
        row["last_seen_at"] = now
        devices[did] = row
        self._save(payload)
        return self.get(did)
