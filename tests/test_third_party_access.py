import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thomas.marketplace.security.third_party_access import (
    ProtectedInternalsGate,
    TrustedAgentBroker,
    TrustedAgentToken,
    build_access_request,
    production_default_seed_is_safe,
)
from thomas.preferences.store import PreferencesStore


class TestThirdPartyAccessDefaults(unittest.TestCase):
    def test_development_seed_enables_third_party_access(self) -> None:
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir,
            patch.dict(os.environ, {"THOMAS_ENV": "development"}, clear=False),
        ):
            store = PreferencesStore(db_path=str(Path(tmpdir) / "prefs.sqlite"))
            prefs = store.get()
        self.assertTrue(bool(prefs.advanced.security.allow_third_party_agent_access))
        self.assertEqual(str(prefs.advanced.security.enforcement_mode), "development")

    def test_production_seed_disables_third_party_access(self) -> None:
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir,
            patch.dict(os.environ, {"THOMAS_ENV": "production"}, clear=False),
        ):
            store = PreferencesStore(db_path=str(Path(tmpdir) / "prefs.sqlite"))
            prefs = store.get()
        self.assertFalse(bool(prefs.advanced.security.allow_third_party_agent_access))
        self.assertEqual(str(prefs.advanced.security.enforcement_mode), "protected")

    def test_production_default_seed_is_safe(self) -> None:
        self.assertTrue(production_default_seed_is_safe())


class TestTrustedAgentGate(unittest.TestCase):
    def test_gate_denies_protected_exec_without_token(self) -> None:
        broker = TrustedAgentBroker(secret=b"x" * 32, token_ttl_s=300)
        gate = ProtectedInternalsGate(
            token_broker=broker,
            allow_third_party_access=False,
            repo_root="C:/repo/Thomas",
            data_root="C:/repo/Thomas/runtime",
        )
        request = build_access_request(
            tool_name="shell.exec",
            args={"cwd": "C:/repo/Thomas"},
            cwd="C:/repo/Thomas",
            runtime_root="C:/repo/Thomas/runtime",
        )
        decision = gate.check(request, trusted_agent_token=None)
        self.assertFalse(decision.allowed)
        self.assertIn("missing_internal_token", decision.reason)

    def test_gate_allows_internal_token_with_matching_root(self) -> None:
        broker = TrustedAgentBroker(secret=b"y" * 32, token_ttl_s=300)
        gate = ProtectedInternalsGate(
            token_broker=broker,
            allow_third_party_access=False,
            repo_root="C:/repo/Thomas",
            data_root="C:/repo/Thomas/runtime",
        )
        token = broker.mint_internal_token(
            agent_id="thomas",
            session_id="sess-1",
            capabilities=["exec", "read", "write", "admin"],
            allowed_roots=["C:/repo/Thomas", "C:/repo/Thomas/runtime"],
        )
        request = build_access_request(
            tool_name="shell.exec",
            args={"cwd": "C:/repo/Thomas"},
            cwd="C:/repo/Thomas",
            runtime_root="C:/repo/Thomas/runtime",
        )
        decision = gate.check(request, trusted_agent_token=token.to_dict())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "internal_token_authorized")

    def test_gate_denies_tampered_token(self) -> None:
        broker = TrustedAgentBroker(secret=b"z" * 32, token_ttl_s=300)
        gate = ProtectedInternalsGate(
            token_broker=broker,
            allow_third_party_access=False,
            repo_root="C:/repo/Thomas",
            data_root="C:/repo/Thomas/runtime",
        )
        token = broker.mint_internal_token(
            agent_id="thomas",
            session_id="sess-2",
            capabilities=["exec"],
            allowed_roots=["C:/repo/Thomas"],
        ).to_dict()
        token["signature"] = "tampered"
        request = build_access_request(
            tool_name="shell.exec",
            args={"cwd": "C:/repo/Thomas"},
            cwd="C:/repo/Thomas",
            runtime_root="C:/repo/Thomas/runtime",
        )
        decision = gate.check(request, trusted_agent_token=token)
        self.assertFalse(decision.allowed)
        self.assertIn("signature", decision.reason)

    def test_gate_denies_expired_or_root_mismatched_token(self) -> None:
        broker = TrustedAgentBroker(secret=b"q" * 32, token_ttl_s=300)
        gate = ProtectedInternalsGate(
            token_broker=broker,
            allow_third_party_access=False,
            repo_root="C:/repo/Thomas",
            data_root="C:/repo/Thomas/runtime",
        )
        valid = broker.mint_internal_token(
            agent_id="thomas",
            session_id="sess-3",
            capabilities=["exec"],
            allowed_roots=["C:/elsewhere"],
        )
        request = build_access_request(
            tool_name="shell.exec",
            args={"cwd": "C:/repo/Thomas"},
            cwd="C:/repo/Thomas",
            runtime_root="C:/repo/Thomas/runtime",
        )
        root_mismatch = gate.check(request, trusted_agent_token=valid.to_dict())
        self.assertFalse(root_mismatch.allowed)
        self.assertEqual(root_mismatch.reason, "internal_token_root_mismatch")

        expired_unsigned = TrustedAgentToken(
            **{**valid.to_dict(), "expires_at": "2000-01-01T00:00:00Z", "signature": ""}
        )
        expired = TrustedAgentToken(
            **{**expired_unsigned.to_dict(), "signature": broker._signature_for(expired_unsigned)}
        )
        expired_decision = gate.check(request, trusted_agent_token=expired.to_dict())
        self.assertFalse(expired_decision.allowed)
        self.assertIn("expired", expired_decision.reason)


if __name__ == "__main__":
    unittest.main()
