"""Security regressions for thomas/server/routes/plugin_hosting.py.

Covers two hardening fixes:
  * X-Forwarded-For is not trusted by default, so a spoofed XFF can't mint a
    fresh per-IP rate-limit bucket and bypass the throttle.
  * API-key validation compares in constant time (hmac.compare_digest), never a
    plain ``in``/``==`` that leaks the key via timing.
"""

from __future__ import annotations

import json

import pytest

from thomas.server.routes import plugin_hosting


class _FakeTransport:
    def __init__(self, peer):
        self._peer = peer

    def get_extra_info(self, key):
        return self._peer if key == "peername" else None


class _FakeRequest:
    def __init__(self, headers=None, peer=("203.0.113.7", 5555)):
        self.headers = headers or {}
        self.transport = _FakeTransport(peer)


# --- X-Forwarded-For trust ---------------------------------------------------


def test_get_client_ip_ignores_xff_by_default(monkeypatch):
    monkeypatch.delenv("THOMAS_TRUST_FORWARDED_FOR", raising=False)
    req = _FakeRequest(headers={"X-Forwarded-For": "1.2.3.4"}, peer=("203.0.113.7", 5555))
    # The real peer is used, not the attacker-supplied header.
    assert plugin_hosting._get_client_ip(req) == "203.0.113.7"


def test_get_client_ip_honors_xff_when_operator_opts_in(monkeypatch):
    monkeypatch.setenv("THOMAS_TRUST_FORWARDED_FOR", "1")
    req = _FakeRequest(headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, peer=("10.0.0.1", 5555))
    # Left-most entry is the original client per the trusted proxy chain.
    assert plugin_hosting._get_client_ip(req) == "1.2.3.4"


def test_rate_limit_not_bypassable_by_spoofed_xff(monkeypatch):
    monkeypatch.delenv("THOMAS_TRUST_FORWARDED_FOR", raising=False)
    limiter = plugin_hosting.SimpleRateLimiter(max_per_minute=3)
    peer = ("203.0.113.7", 5555)
    allowed = 0
    for i in range(10):
        # Rotate XFF every request the way an attacker would.
        req = _FakeRequest(headers={"X-Forwarded-For": f"9.9.9.{i}"}, peer=peer)
        if limiter.check(plugin_hosting._get_client_ip(req)):
            allowed += 1
    # All requests map to the one real-peer bucket, so the limit holds.
    assert allowed == 3


# --- constant-time API-key validation ---------------------------------------


def test_validate_api_key_constant_time_path(tmp_path, monkeypatch):
    monkeypatch.delenv("THOMAS_PLUGIN_STORE_API_KEY", raising=False)
    registry = plugin_hosting.PluginRegistry(tmp_path)
    (tmp_path / "api_keys.json").write_text(
        json.dumps({"keys": {"good-key": {"active": True}, "old-key": {"active": False}}}),
        encoding="utf-8",
    )
    assert registry.validate_api_key("good-key") is True
    assert registry.validate_api_key("old-key") is False  # present but inactive
    assert registry.validate_api_key("unknown") is False
    assert registry.validate_api_key("") is False


def test_validate_api_key_env_key_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_PLUGIN_STORE_API_KEY", "env-secret")
    registry = plugin_hosting.PluginRegistry(tmp_path)
    assert registry.validate_api_key("env-secret") is True
    assert registry.validate_api_key("wrong") is False
