from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from thomas.companion.kernel import CompanionKernel
from thomas.companion.update import VerifyReport

from .profiles import PolicyProfile, get_policy_profile, resolve_policy_profile

_EXECUTABLE_EXTENSIONS = {
    ".aab",
    ".apk",
    ".app",
    ".bat",
    ".class",
    ".com",
    ".dex",
    ".dll",
    ".dylib",
    ".exe",
    ".ipa",
    ".jar",
    ".js",
    ".mjs",
    ".msi",
    ".ps1",
    ".py",
    ".sh",
    ".so",
    ".wasm",
}

_COMMAND_INVOCATION_KEYS = {
    "command",
    "commands",
    "cmd",
    "exec",
    "execute",
    "run",
    "run_command",
    "script",
    "python_script",
    "shell",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return _norm(value) in {"1", "true", "yes", "on"}


def _string_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = _norm(item)
            if text:
                out.append(text)
    elif isinstance(value, str):
        for item in value.split(","):
            text = _norm(item)
            if text:
                out.append(text)
    return sorted(set(out))


@dataclass(frozen=True)
class ComplianceViolation:
    code: str
    severity: str
    message: str
    path: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class ComplianceReport:
    report_id: str
    ok: bool
    checked_at: str
    policy_profile_id: str
    enforcement_level: str
    violations: list[ComplianceViolation]
    warnings: list[str]
    inputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "ok": self.ok,
            "checked_at": self.checked_at,
            "policy_profile_id": self.policy_profile_id,
            "enforcement_level": self.enforcement_level,
            "violations": [item.to_dict() for item in self.violations],
            "warnings": list(self.warnings),
            "counts": {
                "violations": len(self.violations),
                "blocking_violations": len([item for item in self.violations if item.severity == "block"]),
                "warnings": len(self.warnings),
            },
            "inputs": dict(self.inputs),
        }


class ComplianceReportStore:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()
        self.path = self.kernel.paths.logs_dir / "compliance_reports.jsonl"

    def append(
        self,
        report: ComplianceReport,
        *,
        actor: str,
        peer_identity: str,
        bundle_dir: Path,
    ) -> None:
        payload = report.to_dict()
        payload["actor"] = _text(actor) or "api"
        payload["peer_identity"] = _text(peer_identity)
        payload["bundle_dir"] = str(bundle_dir)
        line = json.dumps(payload, ensure_ascii=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _payload_entrypoint_path(bundle_dir: Path, manifest: Any) -> Path | None:
    try:
        rel = str(manifest.module.entrypoint or "").replace("\\", "/").strip()
        if not rel:
            return None
        return (bundle_dir / "payload" / rel).resolve()
    except json.JSONDecodeError:
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _json_payload_files(
    *,
    bundle_dir: Path,
    manifest: Any,
) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if manifest is None:
        return out
    for file_entry in list(getattr(manifest, "files", []) or []):
        if isinstance(file_entry, dict):
            rel = _text(file_entry.get("path"))
        else:
            rel = _text(getattr(file_entry, "path", ""))
        if not rel:
            continue
        if Path(rel).suffix.lower() != ".json":
            continue
        payload_path = (bundle_dir / "payload" / rel).resolve()
        if not payload_path.exists() or not payload_path.is_file():
            continue
        payload = _read_json(payload_path)
        if payload is None:
            continue
        out.append((rel, payload))
    return out


def _json_payload_violation_path(*, rel_path: str, command_path: str) -> str:
    normalized = str(command_path or "").strip()
    if normalized == "$":
        normalized = ""
    elif normalized.startswith("$."):
        normalized = normalized[2:]
    return f"manifest.files[{rel_path}]" + (f".{normalized}" if normalized else "")


def _collect_component_nodes(
    node: Any, *, path: str = "$", out: list[tuple[str, dict[str, Any]]] | None = None
) -> list[tuple[str, dict[str, Any]]]:
    rows = out if out is not None else []
    if isinstance(node, dict):
        if "type" in node:
            rows.append((path, node))
        for key, value in node.items():
            child_path = f"{path}.{key}"
            _collect_component_nodes(value, path=child_path, out=rows)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _collect_component_nodes(value, path=f"{path}[{idx}]", out=rows)
    return rows


def _collect_url_refs(node: Any, *, path: str = "$", out: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    rows = out if out is not None else []
    if isinstance(node, dict):
        for key, value in node.items():
            key_norm = _norm(key)
            child_path = f"{path}.{key}"
            if key_norm in {"url", "href", "src", "target_url", "link"} and isinstance(value, str):
                text = _text(value)
                if text:
                    rows.append((child_path, text))
            _collect_url_refs(value, path=child_path, out=rows)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _collect_url_refs(value, path=f"{path}[{idx}]", out=rows)
    return rows


def _collect_command_like_nodes(
    node: Any, *, path: str = "$", out: list[tuple[str, Any]] | None = None
) -> list[tuple[str, Any]]:
    rows = out if out is not None else []
    if isinstance(node, dict):
        for key, value in node.items():
            key_norm = _norm(key)
            child_path = f"{path}.{key}"
            if key_norm in _COMMAND_INVOCATION_KEYS:
                rows.append((child_path, value))
            _collect_command_like_nodes(value, path=child_path, out=rows)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _collect_command_like_nodes(value, path=f"{path}[{idx}]", out=rows)
    return rows


def collect_command_invocation_paths(payload: Any, *, root_path: str = "$") -> list[str]:
    if not isinstance(payload, (dict, list)):
        return []
    normalized_root = str(root_path or "$").strip() or "$"
    return [path for path, _ in _collect_command_like_nodes(payload, path=normalized_root)]


def _make_report_id(
    *,
    checked_at: str,
    profile_id: str,
    bundle_dir: Path,
    bundle_id: str,
) -> str:
    seed = f"{checked_at}|{profile_id}|{bundle_dir}|{bundle_id}".encode()
    digest = hashlib.sha256(seed).hexdigest()[:12]
    stamp = checked_at.replace("-", "").replace(":", "").replace("+", "_")
    return f"cr.{stamp}.{digest}"


class PolicyComplianceService:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.store = ComplianceReportStore(kernel)

    def check_bundle(
        self,
        *,
        bundle_dir: Path,
        verify_report: VerifyReport,
        platform: str = "",
        distribution_channel: str = "",
        storefront_region: str = "",
        policy_profile_id: str = "",
        runtime_capability_set: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        commerce_model: str = "",
        store_billing_enabled: bool = False,
        ugc_enabled: bool = False,
        moderation_controls: list[str] | None = None,
        age_gate_enabled: bool = False,
        collects_personal_data: bool = False,
        privacy_policy_url: str = "",
        url_allowlist: list[str] | None = None,
        actor: str = "api",
        peer_identity: str = "",
    ) -> ComplianceReport:
        checked_at = _now_iso()
        profile_id = resolve_policy_profile(
            platform=platform,
            distribution_channel=distribution_channel,
            storefront_region=storefront_region,
            requested_profile_id=policy_profile_id,
        )
        profile = get_policy_profile(profile_id)

        runtime_caps = _string_list(runtime_capability_set)
        requested_caps = _string_list(required_capabilities)
        moderation = _string_list(moderation_controls)
        input_allowlist = _string_list(url_allowlist)
        privacy_url = _text(privacy_policy_url)

        violations: list[ComplianceViolation] = []
        warnings: list[str] = list(verify_report.warnings or [])

        def add_violation(
            *,
            code: str,
            severity: str,
            message: str,
            path: str,
            remediation: str,
        ) -> None:
            sev = _norm(severity) or "warn"
            if sev not in {"warn", "block"}:
                sev = "warn"
            if sev == "block" and profile.enforcement_level == "warn":
                sev = "warn"
            violations.append(
                ComplianceViolation(
                    code=code,
                    severity=sev,
                    message=message,
                    path=path,
                    remediation=remediation,
                )
            )

        if not verify_report.ok or verify_report.manifest is None:
            for err in list(verify_report.errors or ["bundle verify failed"]):
                add_violation(
                    code="bundle.verify.failed",
                    severity="block",
                    message=str(err),
                    path="manifest.json",
                    remediation="Fix manifest/signature and run verify before ship.",
                )
            report = self._finalize_report(
                checked_at=checked_at,
                profile=profile,
                violations=violations,
                warnings=warnings,
                bundle_dir=bundle_dir,
                bundle_id="",
                input_context={
                    "platform": _norm(platform),
                    "distribution_channel": _norm(distribution_channel),
                    "storefront_region": _norm(storefront_region),
                    "policy_profile_id": profile.profile_id,
                },
            )
            self.store.append(report, actor=actor, peer_identity=peer_identity, bundle_dir=bundle_dir)
            return report

        manifest = verify_report.manifest
        module = manifest.module

        if profile.profile_id in {"ios_app_store", "android_play_store"}:
            if not _norm(platform):
                add_violation(
                    code="targeting.platform_required",
                    severity="block",
                    message=(f"platform is required for production profile {profile.profile_id}"),
                    path="platform",
                    remediation="Set platform explicitly (ios/android) before ship.",
                )
            if not _norm(distribution_channel):
                add_violation(
                    code="targeting.distribution_channel_required",
                    severity="block",
                    message=(f"distribution_channel is required for production profile {profile.profile_id}"),
                    path="distribution_channel",
                    remediation="Set distribution_channel explicitly (app_store/play_store).",
                )
            if not _norm(storefront_region):
                add_violation(
                    code="targeting.storefront_region_required",
                    severity="block",
                    message=(f"storefront_region is required for production profile {profile.profile_id}"),
                    path="storefront_region",
                    remediation="Set storefront_region (for example US) before ship.",
                )

        requested_permissions = {_norm(item) for item in list(module.permissions or []) if _norm(item)}
        allowed_permissions = set(profile.allowed_permissions)
        forbidden_permissions = sorted(requested_permissions - allowed_permissions)
        if forbidden_permissions:
            add_violation(
                code="module.permissions.not_allowed",
                severity="block",
                message=f"module requests unsupported permissions for profile {profile.profile_id}: {', '.join(forbidden_permissions)}",
                path="manifest.module.permissions",
                remediation="Remove unsupported permissions or ship to a compatible profile.",
            )

        allowed_caps = set(profile.allowed_runtime_capabilities)
        unsupported_required_caps = sorted(set(requested_caps) - allowed_caps)
        if unsupported_required_caps:
            add_violation(
                code="release.required_capabilities.not_allowed",
                severity="block",
                message=f"required capabilities are not allowed by profile {profile.profile_id}: {', '.join(unsupported_required_caps)}",
                path="release.required_capabilities",
                remediation="Reduce required_capabilities to profile-supported capabilities.",
            )

        if runtime_caps and requested_caps:
            missing_runtime = sorted(set(requested_caps) - set(runtime_caps))
            if missing_runtime:
                warnings.append(
                    "runtime capability set does not include requested release capabilities: "
                    + ", ".join(missing_runtime)
                )

        for file_entry in list(manifest.files or []):
            rel = _text(getattr(file_entry, "path", "")).replace("\\", "/")
            suffix = Path(rel).suffix.lower()
            if suffix in _EXECUTABLE_EXTENSIONS:
                add_violation(
                    code="bundle.file.executable_blocked",
                    severity="block",
                    message=f"bundle file extension '{suffix}' is blocked for store-safe payloads",
                    path=f"manifest.files[{rel}]",
                    remediation="Ship declarative payload artifacts only (json/images/fonts) and remove executable/script files.",
                )

        entry_payload = None
        entry_path = _payload_entrypoint_path(bundle_dir, manifest)
        if entry_path is None or not entry_path.exists() or not entry_path.is_file():
            add_violation(
                code="bundle.entrypoint.missing",
                severity="block",
                message="module entrypoint payload is missing",
                path="manifest.module.entrypoint",
                remediation="Ensure entrypoint points to a payload json file inside the bundle.",
            )
        else:
            entry_payload = _read_json(entry_path)
            if entry_payload is None:
                add_violation(
                    code="bundle.entrypoint.invalid_json",
                    severity="block",
                    message="module entrypoint payload is not valid JSON",
                    path=str(entry_path),
                    remediation="Ensure entrypoint payload is valid JSON.",
                )
            elif not isinstance(entry_payload, (dict, list)):
                add_violation(
                    code="bundle.entrypoint.invalid_payload_type",
                    severity="block",
                    message=("module entrypoint payload must be a JSON object or array for companion rendering."),
                    path="manifest.module.entrypoint",
                    remediation="Use a JSON object or array as the module entrypoint payload.",
                )

        payload_commerce_model = _norm(commerce_model)
        payload_store_billing_enabled = bool(store_billing_enabled)
        payload_ugc_enabled = bool(ugc_enabled)
        payload_age_gate_enabled = bool(age_gate_enabled)
        payload_collects_personal_data = bool(collects_personal_data)
        payload_moderation_controls = list(moderation)
        payload_url_allowlist = list(input_allowlist)

        if isinstance(entry_payload, dict):
            payload_commerce_model = payload_commerce_model or _norm(entry_payload.get("commerce_model"))
            payload_store_billing_enabled = payload_store_billing_enabled or _bool(
                entry_payload.get("store_billing_enabled"),
                default=False,
            )
            payload_ugc_enabled = payload_ugc_enabled or _bool(entry_payload.get("ugc_enabled"), default=False)
            payload_age_gate_enabled = payload_age_gate_enabled or _bool(
                entry_payload.get("age_gate_enabled"),
                default=False,
            )
            payload_collects_personal_data = payload_collects_personal_data or _bool(
                entry_payload.get("collects_personal_data"),
                default=False,
            )
            privacy_url = privacy_url or _text(entry_payload.get("privacy_policy_url"))
            payload_moderation_controls = payload_moderation_controls or _string_list(
                entry_payload.get("moderation_controls")
            )
            payload_url_allowlist = payload_url_allowlist or _string_list(entry_payload.get("url_allowlist"))
            if not payload_url_allowlist:
                payload_url_allowlist = _string_list(entry_payload.get("external_navigation_allowlist"))

        if payload_commerce_model:
            allowed_commerce_models = {"digital_in_app", "physical_or_off_app", "enterprise_internal"}
            if payload_commerce_model not in allowed_commerce_models:
                warnings.append(
                    f"unknown commerce_model '{payload_commerce_model}' (expected one of: {', '.join(sorted(allowed_commerce_models))})"
                )

        if (
            payload_commerce_model == "digital_in_app"
            and profile.require_store_billing_for_digital
            and not payload_store_billing_enabled
        ):
            add_violation(
                code="commerce.store_billing_required",
                severity="block",
                message=(
                    "digital_in_app modules require store_billing_enabled=true for profile " f"{profile.profile_id}"
                ),
                path="commerce_model",
                remediation="Enable store billing or classify feature as physical_or_off_app/enterprise_internal.",
            )

        if payload_ugc_enabled and profile.require_moderation_for_ugc:
            required_controls = set(profile.required_moderation_controls)
            found_controls = set(payload_moderation_controls)
            missing_controls = sorted(required_controls - found_controls)
            if missing_controls:
                add_violation(
                    code="ugc.moderation_controls_missing",
                    severity="block",
                    message=f"UGC is enabled but moderation controls are missing: {', '.join(missing_controls)}",
                    path="moderation_controls",
                    remediation="Add required UGC controls (report/block/terms_acceptance) before ship.",
                )
            if profile.required_age_gate_for_ugc and not payload_age_gate_enabled:
                add_violation(
                    code="ugc.age_gate_required",
                    severity="block",
                    message="UGC is enabled but age_gate_enabled is false",
                    path="age_gate_enabled",
                    remediation="Enable age gating for UGC-enabled experiences.",
                )

        if payload_collects_personal_data and "privacy_policy_url" in set(profile.required_privacy_fields):
            if not privacy_url:
                add_violation(
                    code="privacy.policy_url_required",
                    severity="block",
                    message="collects_personal_data=true requires privacy_policy_url",
                    path="privacy_policy_url",
                    remediation="Set an HTTPS privacy policy URL before shipping.",
                )
            else:
                parsed_privacy = urlsplit(privacy_url)
                if parsed_privacy.scheme.lower() != "https" or not parsed_privacy.netloc:
                    add_violation(
                        code="privacy.policy_url_invalid",
                        severity="block",
                        message="privacy_policy_url must be an absolute HTTPS URL",
                        path="privacy_policy_url",
                        remediation="Set privacy_policy_url to an absolute HTTPS URL.",
                    )

        if isinstance(entry_payload, (dict, list)):
            component_nodes = _collect_component_nodes(entry_payload)
            allowed_components = set(profile.allowed_component_types)
            forbidden_components = set(profile.forbidden_component_types)
            for node_path, node in component_nodes:
                ctype = _norm(node.get("type"))
                if not ctype:
                    continue
                if ctype in forbidden_components:
                    add_violation(
                        code="component.type_forbidden",
                        severity="block",
                        message=f"component type '{ctype}' is forbidden for profile {profile.profile_id}",
                        path=node_path,
                        remediation="Replace forbidden component types with approved declarative primitives.",
                    )
                    continue
                if allowed_components and ctype not in allowed_components:
                    add_violation(
                        code="component.type_not_allowed",
                        severity="block",
                        message=f"component type '{ctype}' is not allowed for profile {profile.profile_id}",
                        path=node_path,
                        remediation="Use only allowed component primitives from studio capabilities.",
                    )
                if ctype == "webview":
                    webview_url = _text(node.get("url") or node.get("src") or node.get("href"))
                    if webview_url:
                        parsed = urlsplit(webview_url)
                        scheme = parsed.scheme.lower()
                        if scheme and scheme != "https":
                            add_violation(
                                code="component.webview.non_https",
                                severity="block",
                                message="webview URL must use https",
                                path=node_path,
                                remediation="Use HTTPS webview URLs only.",
                            )
                        if profile.allowed_webview_domains and parsed.hostname:
                            allowed_domains = set(profile.allowed_webview_domains)
                            host = parsed.hostname.lower()
                            if host not in allowed_domains:
                                add_violation(
                                    code="component.webview.domain_not_allowed",
                                    severity="block",
                                    message=(
                                        f"webview domain '{host}' is not in allowed_webview_domains for profile {profile.profile_id}"
                                    ),
                                    path=node_path,
                                    remediation="Add domain to profile allowlist or point webview to an allowed host.",
                                )

            url_refs = _collect_url_refs(entry_payload)
            blocked_schemes = set(profile.blocked_url_schemes)
            combined_allowlist = set(payload_url_allowlist) | set(profile.allowed_external_navigation_domains)
            for ref_path, raw_url in url_refs:
                parsed = urlsplit(raw_url)
                scheme = parsed.scheme.lower()
                host = _norm(parsed.hostname)
                if scheme in blocked_schemes:
                    add_violation(
                        code="url.scheme_blocked",
                        severity="block",
                        message=f"URL scheme '{scheme}' is blocked by policy profile {profile.profile_id}",
                        path=ref_path,
                        remediation="Use approved URL schemes only (typically https).",
                    )
                    continue
                if scheme and scheme not in {"https", "http", "ws", "wss"}:
                    add_violation(
                        code="url.scheme_not_allowed",
                        severity="block",
                        message=f"URL scheme '{scheme}' is not allowed in companion payloads",
                        path=ref_path,
                        remediation="Use https URLs or relative paths.",
                    )
                    continue
                if (
                    scheme in {"http", "https"}
                    and host
                    and not profile.allow_arbitrary_external_navigation
                    and combined_allowlist
                    and host not in combined_allowlist
                ):
                    add_violation(
                        code="url.host_not_allowlisted",
                        severity="block",
                        message=f"host '{host}' is not in the external navigation allowlist",
                        path=ref_path,
                        remediation="Add host to url_allowlist or remove external navigation.",
                    )

        for rel, payload_obj in _json_payload_files(bundle_dir=bundle_dir, manifest=manifest):
            if not isinstance(payload_obj, (dict, list)):
                continue
            command_nodes = _collect_command_like_nodes(payload_obj)
            for command_path, _ in command_nodes:
                add_violation(
                    code="payload.command_invocation_blocked",
                    severity="block",
                    message="payload contains command/tool invocation fields that can trigger external execution",
                    path=_json_payload_violation_path(
                        rel_path=str(rel or ""),
                        command_path=command_path,
                    ),
                    remediation="Remove command/script/tool-invocation keys from companion payloads.",
                )

        report = self._finalize_report(
            checked_at=checked_at,
            profile=profile,
            violations=violations,
            warnings=warnings,
            bundle_dir=bundle_dir,
            bundle_id=str(manifest.bundle_id),
            input_context={
                "platform": _norm(platform),
                "distribution_channel": _norm(distribution_channel),
                "storefront_region": _norm(storefront_region),
                "policy_profile_id": profile.profile_id,
                "runtime_capability_set": list(runtime_caps),
                "required_capabilities": list(requested_caps),
                "commerce_model": payload_commerce_model,
                "store_billing_enabled": bool(payload_store_billing_enabled),
                "ugc_enabled": bool(payload_ugc_enabled),
                "moderation_controls": list(payload_moderation_controls),
                "age_gate_enabled": bool(payload_age_gate_enabled),
                "collects_personal_data": bool(payload_collects_personal_data),
                "privacy_policy_url": privacy_url,
                "url_allowlist": sorted(set(payload_url_allowlist)),
            },
        )
        self.store.append(report, actor=actor, peer_identity=peer_identity, bundle_dir=bundle_dir)
        return report

    @staticmethod
    def _finalize_report(
        *,
        checked_at: str,
        profile: PolicyProfile,
        violations: list[ComplianceViolation],
        warnings: list[str],
        bundle_dir: Path,
        bundle_id: str,
        input_context: dict[str, Any],
    ) -> ComplianceReport:
        has_block = any(item.severity == "block" for item in violations)
        report_id = _make_report_id(
            checked_at=checked_at,
            profile_id=profile.profile_id,
            bundle_dir=bundle_dir,
            bundle_id=bundle_id,
        )
        return ComplianceReport(
            report_id=report_id,
            ok=not has_block,
            checked_at=checked_at,
            policy_profile_id=profile.profile_id,
            enforcement_level=profile.enforcement_level,
            violations=violations,
            warnings=warnings,
            inputs=input_context,
        )
