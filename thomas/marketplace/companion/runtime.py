from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .kernel import CompanionKernel
from .registry import ModuleRegistry, ModuleState


def _entrypoint_fs_path(kernel: CompanionKernel, module: ModuleState) -> Path:
    rel = str(module.entrypoint or "").replace("\\", "/").strip()
    prefix = f"modules/{module.module_id}/"
    if not rel.startswith(prefix):
        raise ValueError("entrypoint must stay inside module namespace")
    suffix = rel[len(prefix) :]
    if not suffix:
        raise ValueError("entrypoint suffix is empty")
    return kernel.paths.modules_dir / module.module_id / suffix


def _load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ModuleRuntime:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()
        self.registry = ModuleRegistry(kernel)

    def modules(self) -> list[ModuleState]:
        return self.registry.list()

    def enabled_modules(self) -> list[ModuleState]:
        return [row for row in self.modules() if row.status == "enabled"]

    def slot_index(self) -> dict[str, list[dict[str, str]]]:
        slots: dict[str, list[dict[str, str]]] = {}
        for row in self.enabled_modules():
            for slot in list(row.slots or []):
                key = str(slot or "").strip()
                if not key:
                    continue
                slots.setdefault(key, []).append(
                    {
                        "module_id": row.module_id,
                        "version": row.version,
                        "entrypoint": row.entrypoint,
                        "display_name": row.display_name,
                    }
                )
        for key in list(slots.keys()):
            slots[key].sort(key=lambda item: (item["module_id"], item["version"]))
        return slots

    def render_slot(self, slot: str) -> dict[str, Any]:
        slot_key = str(slot or "").strip()
        widgets: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for row in self.enabled_modules():
            if slot_key not in list(row.slots or []):
                continue
            try:
                fs_path = _entrypoint_fs_path(self.kernel, row)
            except Exception as exc:
                errors.append({"module_id": row.module_id, "error": str(exc)})
                continue
            if not fs_path.exists() or not fs_path.is_file():
                errors.append({"module_id": row.module_id, "error": f"entrypoint missing: {fs_path}"})
                continue
            try:
                payload = _load_json_file(fs_path)
            except Exception as exc:
                errors.append({"module_id": row.module_id, "error": f"invalid entrypoint json: {exc}"})
                continue
            widgets.append(
                {
                    "module_id": row.module_id,
                    "version": row.version,
                    "display_name": row.display_name,
                    "entrypoint": row.entrypoint,
                    "permissions": list(row.permissions),
                    "payload": payload,
                }
            )
        widgets.sort(key=lambda item: (item["module_id"], item["version"]))
        return {
            "slot": slot_key,
            "widgets": widgets,
            "errors": errors,
            "count": len(widgets),
        }

    def bootstrap(self, *, include_slot_payloads: bool = True) -> dict[str, Any]:
        modules = [m.to_dict() for m in self.modules()]
        slots = self.slot_index()
        payloads: dict[str, Any] = {}
        if include_slot_payloads:
            for slot in sorted(slots.keys()):
                payloads[slot] = self.render_slot(slot)
        return {
            "modules": modules,
            "slots": slots,
            "slot_payloads": payloads,
        }

    @staticmethod
    def installed_module_versions(modules: list[dict[str, Any]]) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in modules:
            module_id = str(row.get("module_id") or "").strip()
            version = str(row.get("version") or "").strip()
            if not module_id:
                continue
            out[module_id] = version
        return out
