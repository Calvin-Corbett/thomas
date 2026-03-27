from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT / "definitions" / "marketplace-surface-policy.json"

_DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "strict_proxy_families": [
        "browser",
        "gateway",
        "channel",
        "channels",
        "message",
        "messages",
        "plugin",
        "plugins",
        "openai",
        "responses",
        "mission",
        "missions",
    ],
    "hidden_ids": [],
    "hidden_prefixes": [],
    "hidden_terms": [],
    "scaffold_ids": [],
    "scaffold_prefixes": [],
    "scaffold_tags": ["scaffold", "placeholder", "proxy", "noop"],
    "scaffold_terms": ["placeholder", "proxy/noop", "proxy noop", "not implemented", "stub"],
}


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _safe_text(item).lower()
        if text and text not in out:
            out.append(text)
    return out


def _policy_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env_path = _safe_text(os.environ.get("THOMAS_MARKETPLACE_POLICY_PATH"))
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_POLICY_PATH


def load_marketplace_surface_policy(path: Path | None = None) -> dict[str, Any]:
    resolved = _policy_path(path)
    payload = dict(_DEFAULT_POLICY)
    if resolved.exists():
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            payload.update(loaded)
    for key in (
        "strict_proxy_families",
        "hidden_ids",
        "hidden_prefixes",
        "hidden_terms",
        "scaffold_ids",
        "scaffold_prefixes",
        "scaffold_tags",
        "scaffold_terms",
    ):
        payload[key] = _string_list(payload.get(key))
    payload["schema_version"] = int(payload.get("schema_version") or 1)
    return payload


def family_requires_strict_entrypoint(
    family_hint: str,
    *,
    policy: Mapping[str, Any] | None = None,
) -> bool:
    family = _safe_text(family_hint).lower()
    if not family:
        return False
    loaded = policy if isinstance(policy, Mapping) else load_marketplace_surface_policy()
    strict = {
        _safe_text(item).lower()
        for item in (loaded.get("strict_proxy_families") if isinstance(loaded, Mapping) else [])
        if _safe_text(item)
    }
    return family in strict


def _normalized_text_blob(row: Mapping[str, Any]) -> str:
    parts = [
        _safe_text(row.get("id") or row.get("plugin_id")).lower(),
        _safe_text(row.get("name")).lower(),
        _safe_text(row.get("display_name")).lower(),
        _safe_text(row.get("subtitle")).lower(),
        _safe_text(row.get("description")).lower(),
        _safe_text(row.get("source")).lower(),
        " ".join(_string_list(row.get("tags"))),
        " ".join(_string_list(row.get("categories"))),
        " ".join(_string_list(row.get("capabilities"))),
    ]
    return " ".join(part for part in parts if part)


def _matches_exact_or_prefix(
    plugin_id: str,
    *,
    exact: list[str],
    prefixes: list[str],
) -> bool:
    if plugin_id in exact:
        return True
    return any(prefix and plugin_id.startswith(prefix) for prefix in prefixes)


def classify_marketplace_row(
    row: Mapping[str, Any],
    *,
    installable_candidate: bool,
    installable_reason: str = "hosted_bundle_present",
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    loaded = policy if isinstance(policy, Mapping) else load_marketplace_surface_policy()
    plugin_id = _safe_text(row.get("id") or row.get("plugin_id")).lower()
    tags = set(_string_list(row.get("tags")))
    text_blob = _normalized_text_blob(row)
    explicit_availability = _safe_text(row.get("availability")).lower()
    hidden_ids = list(loaded.get("hidden_ids") or [])
    hidden_prefixes = list(loaded.get("hidden_prefixes") or [])
    hidden_terms = list(loaded.get("hidden_terms") or [])
    scaffold_ids = list(loaded.get("scaffold_ids") or [])
    scaffold_prefixes = list(loaded.get("scaffold_prefixes") or [])
    scaffold_tags = set(_string_list(loaded.get("scaffold_tags")))
    scaffold_terms = list(loaded.get("scaffold_terms") or [])

    if (
        explicit_availability == "hidden"
        or _matches_exact_or_prefix(plugin_id, exact=hidden_ids, prefixes=hidden_prefixes)
        or any(term and term in text_blob for term in hidden_terms)
    ):
        return {
            "availability": "hidden",
            "eligibility_reason": "suppressed_by_policy",
            "promotion_status": "suppressed",
            "shipped_surface": False,
            "needs_review": False,
        }

    scaffold_match = _matches_exact_or_prefix(plugin_id, exact=scaffold_ids, prefixes=scaffold_prefixes)
    scaffold_term_match = any(term and term in text_blob for term in scaffold_terms)
    scaffold_tag_match = bool(tags & scaffold_tags)
    if explicit_availability == "scaffold" or scaffold_match or scaffold_term_match or scaffold_tag_match:
        reason = "proxy_noop" if "proxy" in text_blob or "noop" in text_blob else "placeholder_surface"
        return {
            "availability": "scaffold",
            "eligibility_reason": reason,
            "promotion_status": "blocked",
            "shipped_surface": False,
            "needs_review": True,
        }

    if explicit_availability == "catalog_only" and not installable_candidate:
        return {
            "availability": "catalog_only",
            "eligibility_reason": "missing_hosted_bundle",
            "promotion_status": "inventory_only",
            "shipped_surface": False,
            "needs_review": False,
        }

    if installable_candidate:
        return {
            "availability": "installable",
            "eligibility_reason": installable_reason,
            "promotion_status": "official_hosted",
            "shipped_surface": True,
            "needs_review": False,
        }

    return {
        "availability": "catalog_only",
        "eligibility_reason": "missing_hosted_bundle",
        "promotion_status": "inventory_only",
        "shipped_surface": False,
        "needs_review": False,
    }


def row_is_visible(
    row: Mapping[str, Any],
    *,
    include_catalog_only: bool = True,
    include_scaffold: bool = False,
    include_hidden: bool = False,
) -> bool:
    availability = _safe_text(row.get("availability")).lower()
    if availability == "hidden":
        return include_hidden
    if availability == "scaffold":
        return include_scaffold
    if availability == "catalog_only":
        return include_catalog_only
    return True
