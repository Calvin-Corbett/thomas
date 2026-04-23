"""Tests for webhook security features."""

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.webhooks._exceptions import SignatureVerificationError
from thomas.marketplace.webhooks._types import Secret
from thomas.marketplace.webhooks.security import (
    IPAllowlist,
    RequestValidator,
    SecretRotator,
    SignatureGenerator,
    SignatureVerifier,
)


class TestSignatureGenerator:
    """Test HMAC signature generation."""

    def test_generate_signature(self):
        """Test generating a signature."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"

        sig = SignatureGenerator.generate(payload, secret)

        assert sig.value
        assert sig.algorithm == "hmac-sha256"
        assert sig.timestamp

    def test_generate_signature_from_dict(self):
        """Test generating signature from dictionary."""
        data = {"order_id": "123", "amount": 99.99}
        secret = "test_secret_key"

        sig = SignatureGenerator.generate_from_dict(data, secret)

        assert sig.value
        assert sig.algorithm == "hmac-sha256"

    def test_generate_signature_empty_payload_raises_error(self):
        """Test that empty payload raises error."""
        with pytest.raises(ValueError):
            SignatureGenerator.generate(b"", "secret")

    def test_generate_signature_empty_secret_raises_error(self):
        """Test that empty secret raises error."""
        with pytest.raises(ValueError):
            SignatureGenerator.generate(b"payload", "")

    def test_generate_signature_consistent(self):
        """Test that signature is deterministic."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"
        timestamp = datetime(2024, 1, 15, 10, 30, 0)

        sig1 = SignatureGenerator.generate(payload, secret, timestamp=timestamp)
        sig2 = SignatureGenerator.generate(payload, secret, timestamp=timestamp)

        assert sig1.value == sig2.value


class TestSignatureVerifier:
    """Test signature verification."""

    def test_verify_valid_signature(self):
        """Test verifying a valid signature."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"
        timestamp = datetime.utcnow()

        sig = SignatureGenerator.generate(payload, secret, timestamp=timestamp)

        verified = SignatureVerifier.verify(
            payload,
            sig.value,
            secret,
            timestamp.isoformat(),
        )

        assert verified

    def test_verify_invalid_signature(self):
        """Test verifying an invalid signature."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"
        timestamp = datetime.utcnow()

        with pytest.raises(SignatureVerificationError):
            SignatureVerifier.verify(
                payload,
                "invalid_signature",
                secret,
                timestamp.isoformat(),
            )

    def test_verify_expired_signature(self):
        """Test that old signatures are rejected."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"
        old_timestamp = datetime.utcnow() - timedelta(minutes=10)

        sig = SignatureGenerator.generate(payload, secret, timestamp=old_timestamp)

        with pytest.raises(SignatureVerificationError):
            SignatureVerifier.verify(
                payload,
                sig.value,
                secret,
                old_timestamp.isoformat(),
                tolerance_seconds=300,
            )

    def test_verify_future_signature(self):
        """Test that future timestamps are rejected."""
        payload = b'{"order_id": "123"}'
        secret = "test_secret_key"
        future_timestamp = datetime.utcnow() + timedelta(minutes=10)

        sig = SignatureGenerator.generate(payload, secret, timestamp=future_timestamp)

        with pytest.raises(SignatureVerificationError):
            SignatureVerifier.verify(
                payload,
                sig.value,
                secret,
                future_timestamp.isoformat(),
            )

    def test_verify_empty_payload_raises_error(self):
        """Test that empty payload raises error."""
        with pytest.raises(SignatureVerificationError):
            SignatureVerifier.verify(
                b"",
                "sig",
                "secret",
                datetime.utcnow().isoformat(),
            )

    def test_verify_modified_payload(self):
        """Test that modified payload fails verification."""
        payload1 = b'{"order_id": "123"}'
        payload2 = b'{"order_id": "456"}'
        secret = "test_secret_key"
        timestamp = datetime.utcnow()

        sig = SignatureGenerator.generate(payload1, secret, timestamp=timestamp)

        with pytest.raises(SignatureVerificationError):
            SignatureVerifier.verify(
                payload2,
                sig.value,
                secret,
                timestamp.isoformat(),
            )


class TestSecretRotator:
    """Test secret rotation with grace period."""

    def test_set_active_secret(self):
        """Test setting an active secret."""
        rotator = SecretRotator()
        secret = Secret()

        rotator.set_secret(secret)

        assert rotator.get_active_secret() == secret

    def test_rotate_secret(self):
        """Test rotating secrets."""
        rotator = SecretRotator()
        secret1 = Secret()
        secret2 = Secret()

        rotator.set_secret(secret1)
        rotator.rotate(secret2)

        assert rotator.get_active_secret() == secret2

    def test_get_all_valid_secrets(self):
        """Test getting both active and grace period secrets."""
        rotator = SecretRotator(grace_period_hours=1)
        secret1 = Secret()
        secret2 = Secret()

        rotator.set_secret(secret1)
        rotator.rotate(secret2)

        valid = rotator.get_all_valid_secrets()

        assert len(valid) == 2
        assert secret1 in valid
        assert secret2 in valid

    def test_grace_period_expiration(self):
        """Test that old secret is removed after grace period."""
        rotator = SecretRotator(grace_period_hours=0)
        secret1 = Secret()
        secret2 = Secret()

        rotator.set_secret(secret1)
        rotator.rotate(secret2)

        import time

        time.sleep(0.1)

        valid = rotator.get_all_valid_secrets()

        assert len(valid) == 1
        assert secret2 in valid

    def test_verify_with_any_valid_secret(self):
        """Test verification against any valid secret."""
        rotator = SecretRotator()
        secret1 = Secret(value="secret1")
        secret2 = Secret(value="secret2")

        rotator.set_secret(secret1)

        payload = b'{"order_id": "123"}'
        sig = SignatureGenerator.generate(payload, secret1.value)

        valid, secret_id = rotator.verify_with_any_valid(
            payload,
            sig.value,
            sig.timestamp.isoformat(),
        )

        assert valid
        assert secret_id == secret1.id


class TestIPAllowlist:
    """Test IP address allowlisting."""

    def test_add_ip(self):
        """Test adding an IP to allowlist."""
        allowlist = IPAllowlist()
        allowlist.add_ip("192.168.1.1")

        assert "192.168.1.1" in allowlist.list_ips()

    def test_add_ipv6(self):
        """Test adding IPv6 address."""
        allowlist = IPAllowlist()
        allowlist.add_ip("::1")

        assert "::1" in allowlist.list_ips()

    def test_invalid_ip_raises_error(self):
        """Test that invalid IP raises error."""
        allowlist = IPAllowlist()

        with pytest.raises(ValueError):
            allowlist.add_ip("not.an.ip.address")

    def test_remove_ip(self):
        """Test removing an IP from allowlist."""
        allowlist = IPAllowlist()
        allowlist.add_ip("192.168.1.1")
        allowlist.remove_ip("192.168.1.1")

        assert "192.168.1.1" not in allowlist.list_ips()

    def test_is_allowed(self):
        """Test checking if IP is allowed."""
        allowlist = IPAllowlist()
        allowlist.add_ip("192.168.1.1")

        assert allowlist.is_allowed("192.168.1.1")
        assert not allowlist.is_allowed("192.168.1.2")

    def test_disable_allowlist(self):
        """Test disabling allowlist enforcement."""
        allowlist = IPAllowlist()
        allowlist.add_ip("192.168.1.1")
        allowlist.disable()

        assert allowlist.is_allowed("192.168.1.2")

    def test_enable_allowlist(self):
        """Test enabling allowlist enforcement."""
        allowlist = IPAllowlist()
        allowlist.add_ip("192.168.1.1")
        allowlist.disable()
        allowlist.enable()

        assert not allowlist.is_allowed("192.168.1.2")


class TestRequestValidator:
    """Test request validation."""

    def test_validate_headers_present(self):
        """Test validating required headers."""
        headers = {
            "x-webhook-signature": "sig_123",
            "x-webhook-timestamp": "2024-01-15T10:30:00",
        }

        result = RequestValidator.validate_headers(headers)

        assert result["signature"] == "sig_123"
        assert result["timestamp"] == "2024-01-15T10:30:00"

    def test_validate_headers_missing_signature(self):
        """Test validation fails with missing signature."""
        headers = {"x-webhook-timestamp": "2024-01-15T10:30:00"}

        with pytest.raises(SignatureVerificationError):
            RequestValidator.validate_headers(headers)

    def test_validate_headers_missing_timestamp(self):
        """Test validation fails with missing timestamp."""
        headers = {"x-webhook-signature": "sig_123"}

        with pytest.raises(SignatureVerificationError):
            RequestValidator.validate_headers(headers)

    def test_validate_timestamp_valid(self):
        """Test validating a recent timestamp."""
        timestamp = datetime.utcnow()

        result = RequestValidator.validate_timestamp(timestamp.isoformat())

        assert result

    def test_validate_timestamp_too_old(self):
        """Test that old timestamp is rejected."""
        timestamp = datetime.utcnow() - timedelta(minutes=10)

        with pytest.raises(SignatureVerificationError):
            RequestValidator.validate_timestamp(
                timestamp.isoformat(),
                tolerance_seconds=300,
            )

    def test_validate_timestamp_invalid_format(self):
        """Test validation fails with invalid timestamp format."""
        with pytest.raises(SignatureVerificationError):
            RequestValidator.validate_timestamp("not-a-timestamp")
