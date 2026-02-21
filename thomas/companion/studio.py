from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import ModuleContract
from .kernel import CompanionKernel, KERNEL_VERSION


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(text or "").strip())
    return value.strip("-") or "x"


def _safe_rel(path: str) -> bool:
    rel = PurePosixPath(path.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts:
        return False
    if any(part == ".." for part in rel.parts):
        return False
    return True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class StudioBuildResult:
    bundle_dir: str
    manifest: dict[str, Any]
    files: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_dir": self.bundle_dir,
            "manifest": dict(self.manifest),
            "files": [dict(item) for item in self.files],
            "file_count": len(self.files),
        }


class BundleStudio:
    def __init__(self, kernel: CompanionKernel, *, secret: str = "", require_signature: bool = True):
        self.kernel = kernel
        self.secret = str(secret or "").strip()
        self.require_signature = bool(require_signature)
        self.kernel.init_layout()

    def _normalize_module_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_payload = payload.get("module")
        if not isinstance(module_payload, dict):
            module_payload = {
                "id": payload.get("module_id"),
                "version": payload.get("module_version"),
                "entrypoint": payload.get("entrypoint"),
                "slots": payload.get("slots"),
                "permissions": payload.get("permissions"),
                "ui_schema_version": payload.get("ui_schema_version"),
                "display_name": payload.get("display_name"),
                "description": payload.get("description"),
            }

        module_id = str(module_payload.get("id") or "").strip()
        if not module_id:
            raise ValueError("module.id is required")
        module_payload["entrypoint"] = (
            str(module_payload.get("entrypoint") or "").strip()
            or f"modules/{module_id}/ui/screen.json"
        )
        slots = module_payload.get("slots")
        if not isinstance(slots, list) or not slots:
            module_payload["slots"] = ["home.main"]
        perms = module_payload.get("permissions")
        if not isinstance(perms, list) or not perms:
            module_payload["permissions"] = ["ui.render", "storage.read"]
        module_payload["ui_schema_version"] = (
            str(module_payload.get("ui_schema_version") or "").strip() or "0.1.0"
        )
        module_payload["display_name"] = (
            str(module_payload.get("display_name") or "").strip() or module_id
        )
        module_payload["description"] = str(module_payload.get("description") or "").strip()
        return module_payload

    def build_bundle(self, payload: dict[str, Any]) -> StudioBuildResult:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        module_payload = self._normalize_module_payload(payload)
        module = ModuleContract.from_dict(module_payload)

        module_prefix = f"modules/{module.module_id}/"
        if not str(module.entrypoint).replace("\\", "/").startswith(module_prefix):
            raise ValueError("module.entrypoint must stay within module namespace")

        output_dir_raw = str(payload.get("output_dir") or "").strip()
        overwrite = bool(payload.get("overwrite", False))
        if output_dir_raw:
            bundle_dir = Path(output_dir_raw).expanduser().resolve()
        else:
            stamp = _now_iso().replace(":", "").replace("-", "").replace("+", "_")
            bundle_dir = (
                self.kernel.paths.bundles_dir
                / "studio"
                / f"{_slug(module.module_id)}-{_slug(module.version)}-{stamp}"
            ).resolve()

        if bundle_dir.exists():
            if not overwrite:
                raise ValueError(f"output_dir already exists: {bundle_dir}")
        bundle_dir.mkdir(parents=True, exist_ok=True)
        payload_root = bundle_dir / "payload"
        payload_root.mkdir(parents=True, exist_ok=True)

        entry_rel = str(module.entrypoint).replace("\\", "/")
        entry_path = payload_root / entry_rel
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        screen_payload = payload.get("screen_payload")
        if screen_payload is None:
            screen_payload = {
                "screen_id": "home",
                "title": module.display_name,
                "components": [{"type": "text", "value": "hello from Thomas studio"}],
            }
        entry_path.write_text(
            json.dumps(screen_payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

        extra_files = payload.get("extra_files")
        if isinstance(extra_files, list):
            for item in extra_files:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("path") or "").strip().replace("\\", "/")
                if not rel:
                    continue
                if not _safe_rel(rel):
                    raise ValueError(f"unsafe extra_files path: {rel}")
                if not rel.startswith(module_prefix):
                    raise ValueError(
                        f"extra_files path must stay within module namespace '{module_prefix}': {rel}"
                    )
                dst = payload_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                content = item.get("content")
                if isinstance(content, (dict, list)):
                    text = json.dumps(content, ensure_ascii=True, indent=2) + "\n"
                else:
                    text = str(content or "")
                dst.write_text(text, encoding="utf-8")

        file_rows: list[dict[str, str]] = []
        for file_path in sorted(payload_root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(payload_root).as_posix()
            if not rel.startswith(module_prefix):
                continue
            file_rows.append({"path": rel, "sha256": _sha256_file(file_path)})
        if not file_rows:
            raise ValueError("bundle has no payload files")

        created_at = _now_iso()
        manifest_without_sig: dict[str, Any] = {
            "schema_version": 1,
            "bundle_id": (
                str(payload.get("bundle_id") or "").strip()
                or f"{module.module_id}-{module.version}"
            ),
            "created_at": created_at,
            "min_kernel_version": (
                str(payload.get("min_kernel_version") or "").strip()
                or KERNEL_VERSION
            ),
            "module": module.to_dict(),
            "files": file_rows,
            "release_notes": str(payload.get("release_notes") or "").strip(),
        }

        manifest = dict(manifest_without_sig)
        canonical = json.dumps(
            manifest_without_sig,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

        if self.secret:
            signature = hmac.new(self.secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
            manifest["signature"] = {"algo": "hmac-sha256", "value": signature}
        elif self.require_signature:
            raise ValueError("THOMAS_COMPANION_UPDATE_SECRET is required to sign studio bundles")

        (bundle_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return StudioBuildResult(
            bundle_dir=str(bundle_dir),
            manifest=manifest,
            files=file_rows,
        )
