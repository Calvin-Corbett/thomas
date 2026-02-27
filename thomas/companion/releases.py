from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import parse_semver_tuple
from .kernel import CompanionKernel
from .update import BundleVerifier


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_key(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(text or "").strip())
    return value.strip("-") or "x"


def _semver_gt(left: str, right: str) -> bool:
    try:
        return parse_semver_tuple(left) > parse_semver_tuple(right)
    except ImportError:
        return False


def _normalize_text_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            out.append(text)
    return sorted(set(out))


def _clamp_rollout_pct(value: Any) -> int:
    try:
        n = int(value)
    except (ValueError, TypeError):
        n = 100
    return max(0, min(100, n))


def _nonneg_int(value: Any, *, default: int = 0) -> int:
    try:
        n = int(value)
    except (ValueError, TypeError):
        n = int(default)
    return max(0, n)


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    digits = re.findall(r"\d+", str(value or ""))
    if not digits:
        return None
    nums = [int(digits[0])]
    nums.append(int(digits[1]) if len(digits) > 1 else 0)
    nums.append(int(digits[2]) if len(digits) > 2 else 0)
    return nums[0], nums[1], nums[2]


def _app_version_gte(actual: str, minimum: str) -> bool:
    want = str(minimum or "").strip()
    if not want:
        return True
    a = _version_tuple(actual)
    b = _version_tuple(want)
    if a is None or b is None:
        return False
    return a >= b


def _rollout_bucket(release_id: str, device_id: str) -> int:
    key = f"{release_id}:{device_id}".encode()
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass(frozen=True)
class ReleaseRecord:
    release_id: str
    channel: str
    created_at: str
    bundle_id: str
    bundle_dir: str
    manifest_path: str
    module_id: str
    module_version: str
    min_kernel_version: str
    release_notes: str
    published_by: str
    rollout_pct: int
    target_devices: list[str]
    exclude_devices: list[str]
    min_app_version: str
    required_capabilities: list[str]
    status: str
    policy_profile_id: str
    compliance_report_id: str
    compliance_status: str
    compliance_violations: int
    compliance_warnings: int
    compliance_checked_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleaseRecord:
        return cls(
            release_id=str(data.get("release_id") or ""),
            channel=str(data.get("channel") or "stable"),
            created_at=str(data.get("created_at") or ""),
            bundle_id=str(data.get("bundle_id") or ""),
            bundle_dir=str(data.get("bundle_dir") or ""),
            manifest_path=str(data.get("manifest_path") or ""),
            module_id=str(data.get("module_id") or ""),
            module_version=str(data.get("module_version") or ""),
            min_kernel_version=str(data.get("min_kernel_version") or ""),
            release_notes=str(data.get("release_notes") or ""),
            published_by=str(data.get("published_by") or ""),
            rollout_pct=_clamp_rollout_pct(data.get("rollout_pct", 100)),
            target_devices=_normalize_text_list(data.get("target_devices")),
            exclude_devices=_normalize_text_list(data.get("exclude_devices")),
            min_app_version=str(data.get("min_app_version") or ""),
            required_capabilities=_normalize_text_list(data.get("required_capabilities")),
            status=str(data.get("status") or "active").strip() or "active",
            policy_profile_id=str(data.get("policy_profile_id") or "strict_global"),
            compliance_report_id=str(data.get("compliance_report_id") or ""),
            compliance_status=str(data.get("compliance_status") or "unknown"),
            compliance_violations=_nonneg_int(data.get("compliance_violations"), default=0),
            compliance_warnings=_nonneg_int(data.get("compliance_warnings"), default=0),
            compliance_checked_at=str(data.get("compliance_checked_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "channel": self.channel,
            "created_at": self.created_at,
            "bundle_id": self.bundle_id,
            "bundle_dir": self.bundle_dir,
            "manifest_path": self.manifest_path,
            "module_id": self.module_id,
            "module_version": self.module_version,
            "min_kernel_version": self.min_kernel_version,
            "release_notes": self.release_notes,
            "published_by": self.published_by,
            "rollout_pct": int(self.rollout_pct),
            "target_devices": list(self.target_devices),
            "exclude_devices": list(self.exclude_devices),
            "min_app_version": self.min_app_version,
            "required_capabilities": list(self.required_capabilities),
            "status": self.status,
            "policy_profile_id": self.policy_profile_id,
            "compliance_report_id": self.compliance_report_id,
            "compliance_status": self.compliance_status,
            "compliance_violations": int(self.compliance_violations),
            "compliance_warnings": int(self.compliance_warnings),
            "compliance_checked_at": self.compliance_checked_at,
        }


class ReleaseRegistry:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()

    def _load(self) -> dict[str, Any]:
        path = self.kernel.paths.releases_file
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"schema_version": 1, "releases": {}}
        if not isinstance(payload, dict):
            payload = {"schema_version": 1, "releases": {}}
        releases = payload.get("releases")
        if not isinstance(releases, dict):
            payload["releases"] = {}
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.kernel.paths.releases_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def get(self, release_id: str) -> ReleaseRecord | None:
        rid = str(release_id or "").strip()
        if not rid:
            return None
        payload = self._load()
        item = (payload.get("releases") or {}).get(rid)
        if not isinstance(item, dict):
            return None
        row = dict(item)
        row["release_id"] = rid
        return ReleaseRecord.from_dict(row)

    def list(
        self,
        *,
        channel: str = "",
        module_id: str = "",
        limit: int = 200,
    ) -> list[ReleaseRecord]:
        payload = self._load()
        rows = payload.get("releases") or {}
        out: list[ReleaseRecord] = []
        ch = str(channel or "").strip().lower()
        mid = str(module_id or "").strip()
        lim = max(1, min(1000, int(limit or 200)))
        for release_id, item in rows.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["release_id"] = str(release_id)
            rel = ReleaseRecord.from_dict(row)
            if ch and rel.channel.lower() != ch:
                continue
            if mid and rel.module_id != mid:
                continue
            out.append(rel)
        out.sort(key=lambda rel: (rel.created_at, rel.release_id), reverse=True)
        return out[:lim]

    def publish_from_bundle(
        self,
        bundle_dir: Path,
        *,
        channel: str,
        published_by: str,
        verifier: BundleVerifier,
        rollout_pct: int = 100,
        target_devices: list[str] | None = None,
        exclude_devices: list[str] | None = None,
        min_app_version: str = "",
        required_capabilities: list[str] | None = None,
        status: str = "active",
        policy_profile_id: str = "strict_global",
        compliance_report_id: str = "",
        compliance_status: str = "unknown",
        compliance_violations: int = 0,
        compliance_warnings: int = 0,
        compliance_checked_at: str = "",
        timestamp: str = "",
    ) -> dict[str, Any]:
        now = str(timestamp or _now_iso())
        report = verifier.verify_bundle(bundle_dir)
        if not report.ok or report.manifest is None:
            return {
                "ok": False,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
                "release": None,
            }

        manifest = report.manifest
        module = manifest.module
        channel_norm = str(channel or "stable").strip() or "stable"
        release_id = (
            f"{_safe_key(channel_norm)}."
            f"{_safe_key(module.module_id)}."
            f"{_safe_key(module.version)}."
            f"{now.replace(':', '').replace('-', '').replace('+', '_')}"
        )

        payload = self._load()
        releases = payload.get("releases")
        if not isinstance(releases, dict):
            releases = {}
            payload["releases"] = releases
        releases[release_id] = {
            "channel": channel_norm,
            "created_at": now,
            "bundle_id": manifest.bundle_id,
            "bundle_dir": str(bundle_dir.resolve()),
            "manifest_path": str(bundle_dir.resolve() / "manifest.json"),
            "module_id": module.module_id,
            "module_version": module.version,
            "min_kernel_version": manifest.min_kernel_version,
            "release_notes": manifest.release_notes,
            "published_by": str(published_by or "api").strip() or "api",
            "rollout_pct": _clamp_rollout_pct(rollout_pct),
            "target_devices": _normalize_text_list(target_devices),
            "exclude_devices": _normalize_text_list(exclude_devices),
            "min_app_version": str(min_app_version or "").strip(),
            "required_capabilities": _normalize_text_list(required_capabilities),
            "status": str(status or "active").strip() or "active",
            "policy_profile_id": str(policy_profile_id or "strict_global").strip() or "strict_global",
            "compliance_report_id": str(compliance_report_id or "").strip(),
            "compliance_status": str(compliance_status or "unknown").strip() or "unknown",
            "compliance_violations": _nonneg_int(compliance_violations, default=0),
            "compliance_warnings": _nonneg_int(compliance_warnings, default=0),
            "compliance_checked_at": str(compliance_checked_at or "").strip(),
        }
        self._save(payload)
        rel = self.get(release_id)
        return {
            "ok": rel is not None,
            "errors": [],
            "warnings": list(report.warnings),
            "release": rel.to_dict() if rel else None,
        }

    def set_rollout(
        self,
        release_id: str,
        *,
        rollout_pct: int | None = None,
        target_devices: list[str] | None = None,
        exclude_devices: list[str] | None = None,
        min_app_version: str | None = None,
        required_capabilities: list[str] | None = None,
        status: str | None = None,
    ) -> ReleaseRecord | None:
        rid = str(release_id or "").strip()
        if not rid:
            return None
        payload = self._load()
        releases = payload.get("releases")
        if not isinstance(releases, dict):
            return None
        row = releases.get(rid)
        if not isinstance(row, dict):
            return None
        if rollout_pct is not None:
            row["rollout_pct"] = _clamp_rollout_pct(rollout_pct)
        if target_devices is not None:
            row["target_devices"] = _normalize_text_list(target_devices)
        if exclude_devices is not None:
            row["exclude_devices"] = _normalize_text_list(exclude_devices)
        if min_app_version is not None:
            row["min_app_version"] = str(min_app_version or "").strip()
        if required_capabilities is not None:
            row["required_capabilities"] = _normalize_text_list(required_capabilities)
        if status is not None:
            row["status"] = str(status or "active").strip() or "active"
        releases[rid] = row
        self._save(payload)
        return self.get(rid)

    def promote_release(
        self,
        release_id: str,
        *,
        channel: str,
        actor: str,
        timestamp: str = "",
    ) -> dict[str, Any]:
        src = self.get(release_id)
        if src is None:
            return {"ok": False, "error": f"release not found: {release_id}", "release": None}
        now = str(timestamp or _now_iso())
        channel_norm = str(channel or "stable").strip() or "stable"
        new_release_id = (
            f"{_safe_key(channel_norm)}."
            f"{_safe_key(src.module_id)}."
            f"{_safe_key(src.module_version)}."
            f"{now.replace(':', '').replace('-', '').replace('+', '_')}"
        )
        payload = self._load()
        releases = payload.get("releases")
        if not isinstance(releases, dict):
            releases = {}
            payload["releases"] = releases
        releases[new_release_id] = {
            "channel": channel_norm,
            "created_at": now,
            "bundle_id": src.bundle_id,
            "bundle_dir": src.bundle_dir,
            "manifest_path": src.manifest_path,
            "module_id": src.module_id,
            "module_version": src.module_version,
            "min_kernel_version": src.min_kernel_version,
            "release_notes": src.release_notes,
            "published_by": str(actor or "api").strip() or "api",
            "rollout_pct": int(src.rollout_pct),
            "target_devices": list(src.target_devices),
            "exclude_devices": list(src.exclude_devices),
            "min_app_version": src.min_app_version,
            "required_capabilities": list(src.required_capabilities),
            "status": src.status,
            "policy_profile_id": src.policy_profile_id,
            "compliance_report_id": src.compliance_report_id,
            "compliance_status": src.compliance_status,
            "compliance_violations": src.compliance_violations,
            "compliance_warnings": src.compliance_warnings,
            "compliance_checked_at": src.compliance_checked_at,
            "promoted_from": src.release_id,
        }
        self._save(payload)
        rel = self.get(new_release_id)
        return {
            "ok": rel is not None,
            "error": "",
            "release": rel.to_dict() if rel else None,
        }

    def latest_by_module(self, *, channel: str) -> dict[str, ReleaseRecord]:
        ch = str(channel or "stable").strip() or "stable"
        rows = self.list(channel=ch, limit=1000)
        out: dict[str, ReleaseRecord] = {}
        for rel in rows:
            current = out.get(rel.module_id)
            if current is None:
                out[rel.module_id] = rel
                continue
            if _semver_gt(rel.module_version, current.module_version):
                out[rel.module_id] = rel
                continue
            if rel.module_version == current.module_version and rel.created_at > current.created_at:
                out[rel.module_id] = rel
        return out

    def resolve_updates(
        self,
        *,
        channel: str,
        installed_modules: dict[str, str],
        device_id: str = "",
        app_version: str = "",
        capabilities: list[str] | None = None,
    ) -> list[ReleaseRecord]:
        installed = {str(k): str(v or "") for k, v in dict(installed_modules or {}).items()}
        rows = self.list(channel=channel, limit=2000)
        latest: dict[str, ReleaseRecord] = {}
        for rel in rows:
            if not self._release_allowed_for_device(
                rel,
                device_id=device_id,
                app_version=app_version,
                capabilities=capabilities,
            ):
                continue
            current = latest.get(rel.module_id)
            if current is None:
                latest[rel.module_id] = rel
                continue
            if _semver_gt(rel.module_version, current.module_version):
                latest[rel.module_id] = rel
                continue
            if rel.module_version == current.module_version and rel.created_at > current.created_at:
                latest[rel.module_id] = rel
        out: list[ReleaseRecord] = []
        for module_id, rel in latest.items():
            current = installed.get(module_id, "0.0.0")
            if _semver_gt(rel.module_version, current):
                out.append(rel)
        out.sort(key=lambda rel: (rel.module_id, rel.module_version))
        return out

    def release_allowed_for_device(
        self,
        release: ReleaseRecord,
        *,
        device_id: str,
        app_version: str,
        capabilities: list[str] | None,
        pinned: bool = False,
    ) -> bool:
        return self._release_allowed_for_device(
            release,
            device_id=device_id,
            app_version=app_version,
            capabilities=capabilities,
            ignore_rollout=bool(pinned),
            ignore_targeting=bool(pinned),
        )

    @staticmethod
    def _release_allowed_for_device(
        release: ReleaseRecord,
        *,
        device_id: str,
        app_version: str,
        capabilities: list[str] | None,
        ignore_rollout: bool = False,
        ignore_targeting: bool = False,
    ) -> bool:
        if str(release.status or "active").strip().lower() != "active":
            return False
        did = str(device_id or "").strip()
        if did:
            if not ignore_targeting:
                if did in set(release.exclude_devices):
                    return False
                if release.target_devices and did not in set(release.target_devices):
                    return False
            if not ignore_rollout:
                pct = int(release.rollout_pct)
                if pct <= 0:
                    return False
                if pct < 100 and _rollout_bucket(release.release_id, did) >= pct:
                    return False
        if not _app_version_gte(app_version, release.min_app_version):
            return False
        caps = {str(x).strip() for x in list(capabilities or []) if str(x).strip()}
        if any(req not in caps for req in list(release.required_capabilities)):
            return False
        return True
