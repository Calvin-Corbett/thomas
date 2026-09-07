from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ALLOWED_PERMISSIONS = {
    "ui.render",
    "storage.read",
    "storage.write",
    "network.egress",
    "notifications.send",
    "device.camera.read",
    "device.mic.read",
    "device.location.read",
    # Desktop operator permissions — these gate the desktop_operator
    # extension's access to screen / window introspection, accessibility
    # tree reads, input injection, and VM control. Without these in the
    # allowlist, the desktop_operator extension cannot enroll.
    "device.screen.read",
    "device.window.read",
    "device.accessibility.read",
    "device.input.write",
    "device.vm.control",
}


def allowed_permissions() -> list[str]:
    return sorted(_ALLOWED_PERMISSIONS)


def _norm_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _as_list_of_text(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text)
    return out


def _validate_semver(value: str, *, field: str) -> str:
    text = _norm_text(value, field=field)
    if not _SEMVER_RE.match(text):
        raise ValueError(f"{field} must be semver 'x.y.z'")
    return text


def _validate_module_id(module_id: str) -> str:
    text = _norm_text(module_id, field="module.id")
    if not _MODULE_ID_RE.match(text):
        raise ValueError("module.id must match ^[a-z0-9][a-z0-9_.-]{2,63}$")
    return text


def _validate_permissions(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        if item not in _ALLOWED_PERMISSIONS:
            raise ValueError(f"unsupported permission: {item}")
        out.append(item)
    return sorted(set(out))


SURFACE_TYPE_DECLARATIVE = "declarative"
SURFACE_TYPE_SURFACE = "surface"
SURFACE_TYPE_LIVE = "live"

# How a module's entrypoint should be interpreted by the companion host:
#   declarative — entrypoint is a JSON component tree the host renders natively
#   surface     — entrypoint is an HTML document rendered in a sandboxed frame
#   live        — entrypoint is a path served live by Thomas (no offline copy)
_ALLOWED_SURFACE_TYPES = {
    SURFACE_TYPE_DECLARATIVE,
    SURFACE_TYPE_SURFACE,
    SURFACE_TYPE_LIVE,
}

DEFAULT_SURFACE_TYPE = SURFACE_TYPE_DECLARATIVE


def allowed_surface_types() -> list[str]:
    return sorted(_ALLOWED_SURFACE_TYPES)


def _validate_surface_type(value: Any) -> str:
    """Default to declarative so manifests written before this field stay valid."""
    text = str(value or "").strip().lower()
    if not text:
        return DEFAULT_SURFACE_TYPE
    if text not in _ALLOWED_SURFACE_TYPES:
        raise ValueError(
            f"module.surface_type must be one of {sorted(_ALLOWED_SURFACE_TYPES)}: got {text!r}"
        )
    return text


def _validate_slots(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        key = str(item).strip()
        if not key:
            continue
        if "/" in key or "\\" in key:
            raise ValueError(f"slot names must be logical keys, not paths: {item}")
        out.append(key)
    return sorted(set(out))


def parse_semver_tuple(value: str) -> tuple[int, int, int]:
    v = _validate_semver(value, field="version")
    parts = v.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


@dataclass(frozen=True)
class ModuleContract:
    """Stable module contract for companion runtime."""

    module_id: str
    version: str
    entrypoint: str
    slots: list[str]
    permissions: list[str]
    ui_schema_version: str
    display_name: str
    description: str
    surface_type: str = DEFAULT_SURFACE_TYPE

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleContract:
        if not isinstance(data, dict):
            raise ValueError("module payload must be an object")
        module_id = _validate_module_id(data.get("id"))
        version = _validate_semver(str(data.get("version") or ""), field="module.version")
        entrypoint = _norm_text(data.get("entrypoint"), field="module.entrypoint")
        slots = _validate_slots(_as_list_of_text(data.get("slots"), field="module.slots"))
        permissions = _validate_permissions(_as_list_of_text(data.get("permissions"), field="module.permissions"))
        ui_schema_version = _validate_semver(str(data.get("ui_schema_version") or ""), field="module.ui_schema_version")
        display_name = _norm_text(data.get("display_name"), field="module.display_name")
        description = str(data.get("description") or "").strip()
        surface_type = _validate_surface_type(data.get("surface_type"))
        return cls(
            module_id=module_id,
            version=version,
            entrypoint=entrypoint,
            slots=slots,
            permissions=permissions,
            ui_schema_version=ui_schema_version,
            display_name=display_name,
            description=description,
            surface_type=surface_type,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.module_id,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "slots": list(self.slots),
            "permissions": list(self.permissions),
            "ui_schema_version": self.ui_schema_version,
            "display_name": self.display_name,
            "description": self.description,
        }
        # Only emit surface_type when it is not the default. This dict feeds
        # canonical_json_for_signature(), so always emitting it would change the
        # signed bytes of every manifest written before the field existed and
        # break verification for bundles already signed in the field. An explicit
        # surface_type still lands in the payload, so the signature covers it.
        if self.surface_type != DEFAULT_SURFACE_TYPE:
            payload["surface_type"] = self.surface_type
        return payload


@dataclass(frozen=True)
class BundleFile:
    path: str
    sha256: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleFile:
        if not isinstance(data, dict):
            raise ValueError("bundle.files item must be an object")
        path = _norm_text(data.get("path"), field="bundle.files[].path").replace("\\", "/")
        sha = _norm_text(data.get("sha256"), field="bundle.files[].sha256").lower()
        if not re.match(r"^[a-f0-9]{64}$", sha):
            raise ValueError("bundle.files[].sha256 must be 64 lowercase hex chars")
        return cls(path=path, sha256=sha)

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class BundleSignature:
    algo: str
    value: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleSignature:
        if not isinstance(data, dict):
            raise ValueError("signature must be an object")
        algo = _norm_text(data.get("algo"), field="signature.algo").lower()
        value = _norm_text(data.get("value"), field="signature.value").lower()
        if algo != "hmac-sha256":
            raise ValueError("signature.algo must be 'hmac-sha256'")
        if not re.match(r"^[a-f0-9]{64}$", value):
            raise ValueError("signature.value must be 64 lowercase hex chars")
        return cls(algo=algo, value=value)

    def to_dict(self) -> dict[str, str]:
        return {"algo": self.algo, "value": self.value}


@dataclass(frozen=True)
class UpdateBundleManifest:
    """Signed module update bundle contract."""

    schema_version: int
    bundle_id: str
    created_at: str
    min_kernel_version: str
    module: ModuleContract
    files: list[BundleFile]
    release_notes: str
    signature: BundleSignature | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateBundleManifest:
        if not isinstance(data, dict):
            raise ValueError("manifest must be an object")
        try:
            schema_version = int(data.get("schema_version"))
        except Exception as exc:
            raise ValueError("schema_version must be an integer") from exc
        if schema_version != 1:
            raise ValueError("schema_version must be 1")
        bundle_id = _norm_text(data.get("bundle_id"), field="bundle_id")
        created_at = _norm_text(data.get("created_at"), field="created_at")
        min_kernel_version = _validate_semver(str(data.get("min_kernel_version") or ""), field="min_kernel_version")
        module = ModuleContract.from_dict(data.get("module") or {})
        files_raw = data.get("files")
        if not isinstance(files_raw, list) or not files_raw:
            raise ValueError("files must be a non-empty list")
        files = [BundleFile.from_dict(item) for item in files_raw]
        release_notes = str(data.get("release_notes") or "").strip()
        sig_raw = data.get("signature")
        signature = BundleSignature.from_dict(sig_raw) if isinstance(sig_raw, dict) else None
        return cls(
            schema_version=schema_version,
            bundle_id=bundle_id,
            created_at=created_at,
            min_kernel_version=min_kernel_version,
            module=module,
            files=files,
            release_notes=release_notes,
            signature=signature,
        )

    def to_dict(self, *, include_signature: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "min_kernel_version": self.min_kernel_version,
            "module": self.module.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "release_notes": self.release_notes,
        }
        if include_signature and self.signature is not None:
            out["signature"] = self.signature.to_dict()
        return out

    def canonical_json_for_signature(self) -> str:
        """Canonicalized JSON payload used for HMAC verification."""
        payload = self.to_dict(include_signature=False)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
