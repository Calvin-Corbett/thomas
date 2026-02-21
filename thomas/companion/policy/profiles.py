from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

FALLBACK_POLICY_PROFILE_ID = "strict_global"



def _text(value: Any) -> str:
    return str(value or "").strip()



def _norm(value: Any) -> str:
    return _text(value).lower()



def _text_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = _norm(item)
            if text:
                out.append(text)
    return sorted(set(out))



def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return _norm(value) in {"1", "true", "yes", "on"}



def _profiles_dir() -> Path:
    return (Path(__file__).resolve().parent.parent / "policy_profiles").resolve()



@dataclass(frozen=True)
class PolicyProfile:
    profile_id: str
    description: str
    source_rules: list[str]
    effective_from: str
    deprecation_date: str
    enforcement_level: str
    platforms: list[str]
    distribution_channels: list[str]
    storefront_regions: list[str]
    allowed_component_types: list[str]
    forbidden_component_types: list[str]
    allowed_permissions: list[str]
    allowed_runtime_capabilities: list[str]
    blocked_url_schemes: list[str]
    allowed_webview_domains: list[str]
    allow_arbitrary_external_navigation: bool
    allowed_external_navigation_domains: list[str]
    require_store_billing_for_digital: bool
    require_moderation_for_ugc: bool
    required_moderation_controls: list[str]
    required_privacy_fields: list[str]
    required_age_gate_for_ugc: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyProfile":
        if not isinstance(data, dict):
            raise ValueError("policy profile payload must be an object")
        profile_id = _norm(data.get("profile_id"))
        if not profile_id:
            raise ValueError("policy profile_id is required")
        enforcement_level = _norm(data.get("enforcement_level")) or "block"
        if enforcement_level not in {"warn", "block"}:
            enforcement_level = "block"
        return cls(
            profile_id=profile_id,
            description=_text(data.get("description")),
            source_rules=_text_list(data.get("source_rules")),
            effective_from=_text(data.get("effective_from")),
            deprecation_date=_text(data.get("deprecation_date")),
            enforcement_level=enforcement_level,
            platforms=_text_list(data.get("platforms")) or ["*"],
            distribution_channels=_text_list(data.get("distribution_channels")) or ["*"],
            storefront_regions=_text_list(data.get("storefront_regions")) or ["*"],
            allowed_component_types=_text_list(data.get("allowed_component_types")),
            forbidden_component_types=_text_list(data.get("forbidden_component_types")),
            allowed_permissions=_text_list(data.get("allowed_permissions")),
            allowed_runtime_capabilities=_text_list(data.get("allowed_runtime_capabilities")),
            blocked_url_schemes=_text_list(data.get("blocked_url_schemes")),
            allowed_webview_domains=_text_list(data.get("allowed_webview_domains")),
            allow_arbitrary_external_navigation=_bool(
                data.get("allow_arbitrary_external_navigation"),
                default=False,
            ),
            allowed_external_navigation_domains=_text_list(
                data.get("allowed_external_navigation_domains")
            ),
            require_store_billing_for_digital=_bool(
                data.get("require_store_billing_for_digital"),
                default=False,
            ),
            require_moderation_for_ugc=_bool(data.get("require_moderation_for_ugc"), default=False),
            required_moderation_controls=_text_list(data.get("required_moderation_controls")),
            required_privacy_fields=_text_list(data.get("required_privacy_fields")),
            required_age_gate_for_ugc=_bool(data.get("required_age_gate_for_ugc"), default=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "description": self.description,
            "source_rules": list(self.source_rules),
            "effective_from": self.effective_from,
            "deprecation_date": self.deprecation_date,
            "enforcement_level": self.enforcement_level,
            "platforms": list(self.platforms),
            "distribution_channels": list(self.distribution_channels),
            "storefront_regions": list(self.storefront_regions),
            "allowed_component_types": list(self.allowed_component_types),
            "forbidden_component_types": list(self.forbidden_component_types),
            "allowed_permissions": list(self.allowed_permissions),
            "allowed_runtime_capabilities": list(self.allowed_runtime_capabilities),
            "blocked_url_schemes": list(self.blocked_url_schemes),
            "allowed_webview_domains": list(self.allowed_webview_domains),
            "allow_arbitrary_external_navigation": bool(self.allow_arbitrary_external_navigation),
            "allowed_external_navigation_domains": list(self.allowed_external_navigation_domains),
            "require_store_billing_for_digital": bool(self.require_store_billing_for_digital),
            "require_moderation_for_ugc": bool(self.require_moderation_for_ugc),
            "required_moderation_controls": list(self.required_moderation_controls),
            "required_privacy_fields": list(self.required_privacy_fields),
            "required_age_gate_for_ugc": bool(self.required_age_gate_for_ugc),
        }



def _fallback_profile() -> PolicyProfile:
    return PolicyProfile.from_dict(
        {
            "profile_id": FALLBACK_POLICY_PROFILE_ID,
            "description": "Fallback strict profile.",
            "source_rules": ["fallback.strict_global"],
            "effective_from": "2026-02-20",
            "enforcement_level": "block",
            "platforms": ["*"],
            "distribution_channels": ["*"],
            "storefront_regions": ["*"],
            "allowed_component_types": [
                "container",
                "text",
                "image",
                "icon",
                "button",
                "input",
                "toggle",
                "list",
                "tabs",
                "chart",
                "form",
                "webview",
                "map",
                "video",
            ],
            "forbidden_component_types": ["native_code_loader", "dynamic_bridge", "script"],
            "allowed_permissions": [
                "device.camera.read",
                "device.location.read",
                "device.mic.read",
                "network.egress",
                "notifications.send",
                "storage.read",
                "storage.write",
                "ui.render",
            ],
            "allowed_runtime_capabilities": [
                "camera",
                "location",
                "mic",
                "notifications",
                "push",
                "storage",
                "websocket",
            ],
            "blocked_url_schemes": ["javascript", "file", "data", "vbscript", "intent"],
            "allow_arbitrary_external_navigation": True,
            "require_moderation_for_ugc": True,
            "required_moderation_controls": ["report", "block", "terms_acceptance"],
            "required_privacy_fields": ["privacy_policy_url"],
            "required_age_gate_for_ugc": True,
        }
    )



@lru_cache(maxsize=1)
def load_policy_profiles() -> dict[str, PolicyProfile]:
    out: dict[str, PolicyProfile] = {}
    for path in sorted(_profiles_dir().glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            profile = PolicyProfile.from_dict(payload)
            out[profile.profile_id] = profile
        except Exception:
            continue
    if FALLBACK_POLICY_PROFILE_ID not in out:
        fallback = _fallback_profile()
        out[fallback.profile_id] = fallback
    return out



def clear_policy_profile_cache() -> None:
    load_policy_profiles.cache_clear()



def list_policy_profiles() -> list[PolicyProfile]:
    profiles = load_policy_profiles()
    return [profiles[key] for key in sorted(profiles.keys())]



def get_policy_profile(profile_id: str) -> PolicyProfile:
    profiles = load_policy_profiles()
    key = _norm(profile_id)
    if key and key in profiles:
        return profiles[key]
    return profiles[FALLBACK_POLICY_PROFILE_ID]



def _match_value(value: str, allowed: list[str]) -> tuple[bool, int]:
    pool = {_norm(item) for item in list(allowed or []) if _norm(item)}
    if not pool:
        return True, 0
    if "*" in pool:
        if not value:
            return True, 0
        return True, 1
    if not value:
        return False, 0
    return value in pool, 2 if value in pool else 0



def resolve_policy_profile(
    *,
    platform: str = "",
    distribution_channel: str = "",
    storefront_region: str = "",
    requested_profile_id: str = "",
) -> str:
    profiles = load_policy_profiles()
    requested = _norm(requested_profile_id)
    if requested and requested in profiles:
        return requested

    p = _norm(platform)
    d = _norm(distribution_channel)
    r = _norm(storefront_region)

    best_profile_id = FALLBACK_POLICY_PROFILE_ID
    best_score = -1

    for profile in profiles.values():
        if profile.profile_id == FALLBACK_POLICY_PROFILE_ID:
            continue

        p_ok, p_score = _match_value(p, profile.platforms)
        if not p_ok:
            continue
        d_ok, d_score = _match_value(d, profile.distribution_channels)
        if not d_ok:
            continue
        r_ok, r_score = _match_value(r, profile.storefront_regions)
        if not r_ok:
            continue

        score = p_score + d_score + r_score
        if score > best_score:
            best_score = score
            best_profile_id = profile.profile_id

    return best_profile_id
