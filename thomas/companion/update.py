from __future__ import annotations

import hashlib
import hmac
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from .contracts import ModuleContract, UpdateBundleManifest, parse_semver_tuple
from .kernel import CompanionKernel, KERNEL_VERSION
from .registry import ModuleRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_rel(path: str) -> bool:
    rel = PurePosixPath(path.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts:
        return False
    if any(part == ".." for part in rel.parts):
        return False
    return True


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _semver_gte(left: str, right: str) -> bool:
    return parse_semver_tuple(left) >= parse_semver_tuple(right)


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    errors: list[str]
    warnings: list[str]
    touched_paths: list[str]
    module: Optional[ModuleContract]
    manifest: Optional[UpdateBundleManifest]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "touched_paths": list(self.touched_paths),
            "module": self.module.to_dict() if self.module else None,
            "manifest": self.manifest.to_dict() if self.manifest else None,
        }


class BundleVerifier:
    """Validate signed module-update bundles."""

    def __init__(self, kernel: CompanionKernel, *, secret: str = "", require_signature: bool = True):
        self.kernel = kernel
        self.secret = str(secret or "")
        self.require_signature = bool(require_signature)

    def verify_bundle(self, bundle_dir: Path) -> VerifyReport:
        errors: list[str] = []
        warnings: list[str] = []
        touched: list[str] = []

        root = bundle_dir.resolve()
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            return VerifyReport(
                ok=False,
                errors=["manifest.json is missing from bundle"],
                warnings=[],
                touched_paths=[],
                module=None,
                manifest=None,
            )

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = UpdateBundleManifest.from_dict(raw)
        except Exception as exc:
            return VerifyReport(
                ok=False,
                errors=[f"invalid manifest: {exc}"],
                warnings=[],
                touched_paths=[],
                module=None,
                manifest=None,
            )

        if not _semver_gte(KERNEL_VERSION, manifest.min_kernel_version):
            errors.append(
                f"kernel {KERNEL_VERSION} is below required min_kernel_version {manifest.min_kernel_version}"
            )

        module_prefix = f"modules/{manifest.module.module_id}/"
        for file_entry in manifest.files:
            rel = file_entry.path
            touched.append(rel)
            if not _safe_rel(rel):
                errors.append(f"unsafe file path in manifest.files: {rel}")
                continue
            if not rel.startswith(module_prefix):
                errors.append(
                    f"bundle file path must stay within module namespace '{module_prefix}': {rel}"
                )
            payload_path = root / "payload" / rel
            if not payload_path.exists() or not payload_path.is_file():
                errors.append(f"bundle payload file missing: payload/{rel}")
                continue
            sha = _file_sha256(payload_path)
            if sha != file_entry.sha256:
                errors.append(f"sha256 mismatch for payload/{rel}")

        sig = manifest.signature
        if sig is None:
            if self.require_signature:
                errors.append("bundle signature is required but missing")
            else:
                warnings.append("bundle signature missing (allowed by policy)")
        else:
            if not self.secret:
                if self.require_signature:
                    errors.append("signature exists but verifier secret is not configured")
                else:
                    warnings.append("signature not verified because verifier secret is missing")
            else:
                canonical = manifest.canonical_json_for_signature().encode("utf-8")
                expected = hmac.new(self.secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, sig.value):
                    errors.append("bundle signature verification failed")

        return VerifyReport(
            ok=not errors,
            errors=errors,
            warnings=warnings,
            touched_paths=sorted(set(touched)),
            module=manifest.module,
            manifest=manifest,
        )


class UpdateApplier:
    """Apply validated companion module bundles into kernel module storage."""

    def __init__(self, kernel: CompanionKernel, *, verifier: BundleVerifier):
        self.kernel = kernel
        self.verifier = verifier
        self.registry = ModuleRegistry(kernel)

    def apply_bundle(self, bundle_dir: Path, *, dry_run: bool = True) -> dict[str, Any]:
        self.kernel.init_layout()
        report = self.verifier.verify_bundle(bundle_dir)
        if not report.ok or report.manifest is None:
            return {
                "ok": False,
                "dry_run": dry_run,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
                "applied_files": [],
            }

        manifest = report.manifest
        module_id = manifest.module.module_id
        timestamp = _now_iso()
        backup_root = self.kernel.paths.backups_dir / f"{timestamp.replace(':', '')}_{module_id}"
        applied_files: list[str] = []
        copied_files: list[tuple[Path, Path]] = []

        for file_entry in manifest.files:
            rel = file_entry.path.replace("\\", "/")
            suffix = rel[len(f"modules/{module_id}/") :]
            src = bundle_dir.resolve() / "payload" / rel
            dst = self.kernel.paths.modules_dir / module_id / suffix
            applied_files.append(str(dst))

            if dry_run:
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                backup_path = backup_root / suffix
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_path)
            shutil.copy2(src, dst)
            copied_files.append((src, dst))

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "module_id": module_id,
                "bundle_id": manifest.bundle_id,
                "applied_files": applied_files,
                "errors": [],
                "warnings": list(report.warnings),
            }

        self.registry.upsert_from_contract(
            manifest.module,
            source_bundle=manifest.bundle_id,
            timestamp=timestamp,
        )
        return {
            "ok": True,
            "dry_run": False,
            "module_id": module_id,
            "bundle_id": manifest.bundle_id,
            "applied_files": applied_files,
            "errors": [],
            "warnings": list(report.warnings),
        }
