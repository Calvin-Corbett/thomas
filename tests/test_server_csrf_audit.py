from __future__ import annotations

import re
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


def _iter_mutating_routes(app, *, prefixes: tuple[str, ...] | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for route in app.router.routes():
        method = str(getattr(route, "method", "") or "").upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        resource = getattr(route, "resource", None)
        if resource is None or not hasattr(resource, "get_info"):
            continue
        info = resource.get_info()
        raw_path = info.get("path") or info.get("formatter") or info.get("prefix")
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            continue
        if prefixes is not None and not any(raw_path.startswith(prefix) for prefix in prefixes):
            continue
        concrete = re.sub(r"\{[^}]+\}", "audit", raw_path)
        key = (method, concrete)
        if key in seen:
            continue
        seen.add(key)
        rows.append(key)
    return sorted(rows)


def _iter_guarded_mutating_routes(app) -> list[tuple[str, str]]:
    return _iter_mutating_routes(app, prefixes=("/api/", "/gateway/"))


def _iter_all_mutating_routes(app) -> list[tuple[str, str]]:
    return _iter_mutating_routes(app, prefixes=None)


def _iter_policy_snapshot_routes(payload: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for entry in list(payload.get("policies") or []):
        if not isinstance(entry, dict):
            continue
        method = str(entry.get("method") or "").strip().upper()
        sample = str(entry.get("sample_path") or "").strip()
        if not method or not sample:
            continue
        rows.append((method, sample))
    return sorted(rows)


class _BaseServerMutatingAudit(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    @property
    def _memory_root(self) -> str:
        return self._tmpdir.name


class TestServerCsrfAuditLocal(_BaseServerMutatingAudit):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._memory_root),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_cross_site_headers_are_rejected_for_all_mutating_control_plane_routes(self):
        headers = {
            "Origin": "https://evil.example",
            "Sec-Fetch-Site": "cross-site",
            "Content-Type": "application/json",
        }
        wrong_status: list[str] = []
        for method, path in _iter_guarded_mutating_routes(self.app):
            resp = await self.client.request(method, path, headers=headers, data="{}")
            if resp.status != 403:
                wrong_status.append(f"{method} {path} -> {resp.status}")
        self.assertEqual(wrong_status, [])

    async def test_workspace_mutating_routes_are_part_of_mutation_audit_surface(self):
        routes = set(_iter_guarded_mutating_routes(self.app))
        expected = {
            ("POST", "/api/workspaces"),
            ("POST", "/api/workspaces/invites/accept"),
            ("POST", "/api/workspaces/audit/invites"),
            ("PATCH", "/api/workspaces/audit/members/audit"),
            ("DELETE", "/api/workspaces/audit/members/audit"),
        }
        for row in expected:
            self.assertIn(row, routes)

    async def test_mutating_route_policy_snapshot_covers_all_mutating_http_routes(self):
        resp = await self.client.get("/api/security/mutating-routes")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()
        self.assertIn("route_count", payload)
        self.assertIn("policies", payload)

        policies = list(payload.get("policies") or [])
        self.assertEqual(int(payload.get("route_count") or 0), len(policies))
        for row in policies:
            sample = str(row.get("sample_path") or "")
            authz = str(row.get("authz") or "")
            csrf = str(row.get("csrf") or "")
            enforced_by = list(row.get("enforced_by") or [])
            if sample.startswith("/api/") or sample.startswith("/gateway/"):
                self.assertEqual(authz, "require_api_access")
                self.assertEqual(csrf, "same_origin_browser_local_mode")
                self.assertIn("authz_guard_mutating_api", enforced_by)
                self.assertIn("csrf_guard_mutating_api", enforced_by)
            elif sample.startswith("/webhooks/receive/"):
                self.assertEqual(authz, "webhook_provider_signature_or_secret")
                self.assertEqual(csrf, "not_applicable_webhook_receiver")
                self.assertIn("webhook_provider_signature_validation", enforced_by)
            else:
                self.fail(f"Unexpected mutating policy route surfaced in snapshot: {sample}")

        expected = _iter_all_mutating_routes(self.app)
        got = _iter_policy_snapshot_routes(payload)
        self.assertEqual(got, expected)

    async def test_public_webhook_receivers_are_explicitly_tracked_in_policy_snapshot(self):
        resp = await self.client.get("/api/security/mutating-routes")
        self.assertEqual(resp.status, 200)
        payload = await resp.json()

        webhook_rows: set[tuple[str, str]] = set()
        for row in list(payload.get("policies") or []):
            if not isinstance(row, dict):
                continue
            method = str(row.get("method") or "").upper()
            sample_path = str(row.get("sample_path") or "")
            if not sample_path.startswith("/webhooks/receive/"):
                continue
            webhook_rows.add((method, sample_path))

        expected = {
            ("POST", "/webhooks/receive/github"),
            ("POST", "/webhooks/receive/stripe"),
            ("POST", "/webhooks/receive/audit"),
        }
        self.assertEqual(webhook_rows, expected)


class TestServerMutatingAuthzAuditRemote(_BaseServerMutatingAudit):
    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._memory_root),
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_all_mutating_control_plane_routes_require_auth_in_remote_mode(self):
        wrong_status: list[str] = []
        for method, path in _iter_guarded_mutating_routes(self.app):
            resp = await self.client.request(method, path, data="{}")
            if resp.status != 401:
                wrong_status.append(f"{method} {path} -> {resp.status}")
        self.assertEqual(wrong_status, [])

    async def test_mutating_route_policy_snapshot_requires_auth_in_remote_mode(self):
        no_auth = await self.client.get("/api/security/mutating-routes")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/security/mutating-routes",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)


if __name__ == "__main__":
    unittest.main()
