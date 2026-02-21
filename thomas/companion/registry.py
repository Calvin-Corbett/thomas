from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .contracts import ModuleContract
from .kernel import CompanionKernel


@dataclass(frozen=True)
class ModuleState:
    module_id: str
    version: str
    status: str
    entrypoint: str
    display_name: str
    description: str
    slots: list[str]
    permissions: list[str]
    source_bundle: str
    installed_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleState":
        return cls(
            module_id=str(data.get("module_id") or ""),
            version=str(data.get("version") or ""),
            status=str(data.get("status") or "disabled"),
            entrypoint=str(data.get("entrypoint") or ""),
            display_name=str(data.get("display_name") or ""),
            description=str(data.get("description") or ""),
            slots=list(data.get("slots") or []),
            permissions=list(data.get("permissions") or []),
            source_bundle=str(data.get("source_bundle") or ""),
            installed_at=str(data.get("installed_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "version": self.version,
            "status": self.status,
            "entrypoint": self.entrypoint,
            "display_name": self.display_name,
            "description": self.description,
            "slots": list(self.slots),
            "permissions": list(self.permissions),
            "source_bundle": self.source_bundle,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
        }


class ModuleRegistry:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()

    def _load(self) -> dict[str, Any]:
        path = self.kernel.paths.registry_file
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"schema_version": 1, "modules": {}}
        if not isinstance(payload, dict):
            payload = {"schema_version": 1, "modules": {}}
        modules = payload.get("modules")
        if not isinstance(modules, dict):
            payload["modules"] = {}
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.kernel.paths.registry_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def list(self) -> list[ModuleState]:
        payload = self._load()
        modules = payload.get("modules") or {}
        out: list[ModuleState] = []
        for module_id, item in modules.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["module_id"] = module_id
            out.append(ModuleState.from_dict(row))
        out.sort(key=lambda m: m.module_id)
        return out

    def get(self, module_id: str) -> Optional[ModuleState]:
        payload = self._load()
        item = (payload.get("modules") or {}).get(module_id)
        if not isinstance(item, dict):
            return None
        row = dict(item)
        row["module_id"] = module_id
        return ModuleState.from_dict(row)

    def upsert_from_contract(self, module: ModuleContract, *, source_bundle: str, timestamp: str) -> ModuleState:
        payload = self._load()
        modules = payload.setdefault("modules", {})
        if not isinstance(modules, dict):
            modules = {}
            payload["modules"] = modules
        old = modules.get(module.module_id) if isinstance(modules.get(module.module_id), dict) else {}
        installed_at = str(old.get("installed_at") or timestamp)
        modules[module.module_id] = {
            "version": module.version,
            "status": "enabled",
            "entrypoint": module.entrypoint,
            "display_name": module.display_name,
            "description": module.description,
            "slots": list(module.slots),
            "permissions": list(module.permissions),
            "source_bundle": source_bundle,
            "installed_at": installed_at,
            "updated_at": timestamp,
        }
        self._save(payload)
        return self.get(module.module_id) or ModuleState.from_dict({"module_id": module.module_id})

    def set_enabled(self, module_id: str, enabled: bool, *, timestamp: str) -> Optional[ModuleState]:
        payload = self._load()
        modules = payload.get("modules")
        if not isinstance(modules, dict):
            return None
        item = modules.get(module_id)
        if not isinstance(item, dict):
            return None
        item["status"] = "enabled" if enabled else "disabled"
        item["updated_at"] = timestamp
        modules[module_id] = item
        self._save(payload)
        return self.get(module_id)
