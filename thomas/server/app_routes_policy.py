"""Helpers for route policy snapshots used during server startup."""

from __future__ import annotations

import re
import time
from typing import Any


def build_mutating_route_policy_snapshot(router: Any) -> dict[str, Any]:
    """Build a security policy snapshot for all mutating routes."""
    policies: list[dict[str, Any]] = []
    for resource in router.resources():
        for route in resource:
            method = str(route.method or "GET").upper()
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue

            raw_path = str(resource.canonical or "")
            sample_path = re.sub(r"\{[^}]+\}", "audit", raw_path)

            if raw_path.startswith("/webhooks/receive/"):
                policies.append(
                    {
                        "method": method,
                        "path": raw_path,
                        "sample_path": sample_path,
                        "authz": "webhook_provider_signature_or_secret",
                        "csrf": "not_applicable_webhook_receiver",
                        "enforced_by": ["webhook_provider_signature_validation"],
                    }
                )
                continue
            if (
                sample_path.startswith("/api/")
                or sample_path.startswith("/gateway/")
                or sample_path.startswith("/openai-compat/")
                or sample_path.startswith("/v1/")
                or sample_path == "/probe"
            ):
                policies.append(
                    {
                        "method": method,
                        "path": raw_path,
                        "sample_path": sample_path,
                        "authz": "require_api_access",
                        "csrf": "same_origin_or_optional_custom_header",
                        "enforced_by": ["authz_guard_mutating_api", "csrf_guard_mutating_api"],
                    }
                )
                continue
            policies.append(
                {
                    "method": method,
                    "path": raw_path,
                    "sample_path": sample_path,
                    "authz": "unknown",
                    "csrf": "unknown",
                    "enforced_by": [],
                }
            )
    policies.sort(key=lambda row: (str(row.get("method") or ""), str(row.get("sample_path") or "")))
    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "defaults": {"authz": "require_api_access", "csrf": "same_origin_or_optional_custom_header"},
        "route_count": len(policies),
        "policies": policies,
    }
