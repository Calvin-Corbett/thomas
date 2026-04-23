"""Security features for webhook delivery and verification."""

import hashlib
import hmac
from datetime import datetime, timedelta

from thomas.marketplace.webhooks._exceptions import SignatureVerificationError
from thomas.marketplace.webhooks._types import Secret, Signature


class SignatureGenerator:
    """Generates HMAC signatures for webhook payloads.

    Uses SHA-256 with a shared secret for payload verification.
    """

    @staticmethod
    def generate(
        payload: bytes,
        secret: str,
        algorithm: str = "hmac-sha256",
        timestamp: datetime | None = None,
    ) -> Signature:
        """Generate a signature for a payload.

        Args:
            payload: The payload bytes to sign.
            secret: The shared secret key.
            algorithm: The signature algorithm.
            timestamp: Optional timestamp for replay protection.

        Returns:
            A Signature object.
        """
        if not payload:
            raise ValueError("Payload cannot be empty")

        if not secret:
            raise ValueError("Secret cannot be empty")

        if algorithm != "hmac-sha256":
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        if timestamp is None:
            timestamp = datetime.utcnow()

        message = f"{timestamp.isoformat()}.{payload.decode('utf-8')}"
        sig = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )

        return Signature(
            algorithm=algorithm,
            value=sig.hexdigest(),
            timestamp=timestamp,
        )

    @staticmethod
    def generate_from_dict(
        data: dict,
        secret: str,
        algorithm: str = "hmac-sha256",
    ) -> Signature:
        """Generate a signature from a dictionary.

        Args:
            data: Dictionary to sign.
            secret: The shared secret key.
            algorithm: The signature algorithm.

        Returns:
            A Signature object.
        """
        import json

        payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return SignatureGenerator.generate(payload, secret, algorithm)


class SignatureVerifier:
    """Verifies webhook signatures using timing-safe comparison."""

    @staticmethod
    def verify(
        payload: bytes,
        signature_value: str,
        secret: str,
        timestamp_str: str,
        algorithm: str = "hmac-sha256",
        tolerance_seconds: int = 300,
    ) -> bool:
        """Verify a signature with replay protection.

        Uses timing-safe comparison to prevent timing attacks.

        Args:
            payload: The payload bytes that were signed.
            signature_value: The signature to verify (hex string).
            secret: The shared secret key.
            timestamp_str: Timestamp of signature (ISO format).
            algorithm: The signature algorithm.
            tolerance_seconds: How old a signature can be.

        Returns:
            True if signature is valid, False otherwise.

        Raises:
            SignatureVerificationError: If verification fails.
        """
        if not payload:
            raise SignatureVerificationError("Payload cannot be empty")

        if not signature_value:
            raise SignatureVerificationError("Signature value cannot be empty")

        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, AttributeError) as e:
            raise SignatureVerificationError(f"Invalid timestamp format: {e}")

        age_seconds = (datetime.utcnow() - timestamp).total_seconds()
        if age_seconds > tolerance_seconds:
            raise SignatureVerificationError(f"Signature too old: {age_seconds}s > {tolerance_seconds}s")

        expected_sig = SignatureGenerator.generate(
            payload,
            secret,
            algorithm,
            timestamp,
        )

        if not SignatureVerifier._timing_safe_compare(signature_value, expected_sig.value):
            raise SignatureVerificationError("Signature mismatch")

        return True

    @staticmethod
    def _timing_safe_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time to prevent timing attacks.

        Args:
            a: First string.
            b: Second string.

        Returns:
            True if strings are equal, False otherwise.
        """
        return hmac.compare_digest(a.encode(), b.encode())


class SecretRotator:
    """Manages secret rotation with grace period.

    Maintains both old and new secrets during transition.
    """

    def __init__(self, grace_period_hours: int = 24) -> None:
        """Initialize the secret rotator.

        Args:
            grace_period_hours: Hours to accept old secret after rotation.
        """
        self.grace_period_hours = grace_period_hours
        self._active_secret: Secret | None = None
        self._previous_secret: Secret | None = None
        self._rotation_time: datetime | None = None

    def set_secret(self, secret: Secret) -> None:
        """Set the active secret (usually the primary).

        Args:
            secret: The secret to set as active.
        """
        self._active_secret = secret

    def rotate(self, new_secret: Secret) -> None:
        """Rotate to a new secret with grace period.

        Args:
            new_secret: The new secret to activate.
        """
        self._previous_secret = self._active_secret
        self._active_secret = new_secret
        self._rotation_time = datetime.utcnow()

    def get_active_secret(self) -> Secret | None:
        """Get the currently active secret.

        Returns:
            The active Secret object, or None.
        """
        return self._active_secret

    def get_all_valid_secrets(self) -> list:
        """Get all currently valid secrets (active + grace period old).

        Returns:
            List of valid Secret objects.
        """
        secrets = []

        if self._active_secret:
            secrets.append(self._active_secret)

        if self._previous_secret and self._rotation_time:
            age = datetime.utcnow() - self._rotation_time
            grace_period = timedelta(hours=self.grace_period_hours)
            if age < grace_period:
                secrets.append(self._previous_secret)

        return secrets

    def verify_with_any_valid(
        self,
        payload: bytes,
        signature_value: str,
        timestamp_str: str,
    ) -> tuple[bool, str | None]:
        """Verify signature against any valid secret.

        Args:
            payload: The payload bytes.
            signature_value: The signature to verify.
            timestamp_str: Timestamp of signature.

        Returns:
            Tuple of (is_valid, secret_used_id or None).
        """
        for secret in self.get_all_valid_secrets():
            try:
                SignatureVerifier.verify(
                    payload,
                    signature_value,
                    secret.value,
                    timestamp_str,
                )
                return True, secret.id
            except SignatureVerificationError:
                continue

        return False, None


class IPAllowlist:
    """IP address allowlisting for webhook sources."""

    def __init__(self) -> None:
        """Initialize the IP allowlist."""
        self._allowed_ips: set = set()
        self._enabled = True

    def add_ip(self, ip_address: str) -> None:
        """Add an IP address to the allowlist.

        Args:
            ip_address: The IP address to allow.

        Raises:
            ValueError: If IP address is invalid.
        """
        if not self._is_valid_ip(ip_address):
            raise ValueError(f"Invalid IP address: {ip_address}")

        self._allowed_ips.add(ip_address)

    def remove_ip(self, ip_address: str) -> None:
        """Remove an IP address from the allowlist.

        Args:
            ip_address: The IP address to remove.
        """
        self._allowed_ips.discard(ip_address)

    def is_allowed(self, ip_address: str) -> bool:
        """Check if an IP address is allowed.

        Args:
            ip_address: The IP address to check.

        Returns:
            True if IP is allowed or allowlist is disabled, False otherwise.
        """
        if not self._enabled:
            return True

        return ip_address in self._allowed_ips

    def enable(self) -> None:
        """Enable IP allowlist enforcement."""
        self._enabled = True

    def disable(self) -> None:
        """Disable IP allowlist enforcement."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Check if allowlist is enabled.

        Returns:
            True if allowlist is enabled.
        """
        return self._enabled

    def list_ips(self) -> list:
        """List all allowed IP addresses.

        Returns:
            Sorted list of allowed IP addresses.
        """
        return sorted(self._allowed_ips)

    @staticmethod
    def _is_valid_ip(ip_address: str) -> bool:
        """Validate IP address format.

        Args:
            ip_address: The IP address to validate.

        Returns:
            True if valid IPv4 or IPv6 address.
        """
        import ipaddress

        try:
            ipaddress.ip_address(ip_address)
            return True
        except ValueError:
            return False


class RequestValidator:
    """Validates incoming webhook requests."""

    @staticmethod
    def validate_headers(headers: dict[str, str]) -> dict[str, str]:
        """Validate and extract webhook headers.

        Args:
            headers: Request headers.

        Returns:
            Extracted webhook headers.

        Raises:
            SignatureVerificationError: If required headers are missing.
        """
        required_headers = ["x-webhook-signature", "x-webhook-timestamp"]
        missing = [h for h in required_headers if h not in headers]

        if missing:
            raise SignatureVerificationError(f"Missing required headers: {', '.join(missing)}")

        return {
            "signature": headers.get("x-webhook-signature", ""),
            "timestamp": headers.get("x-webhook-timestamp", ""),
        }

    @staticmethod
    def validate_timestamp(timestamp_str: str, tolerance_seconds: int = 300) -> bool:
        """Validate request timestamp for replay protection.

        Args:
            timestamp_str: Timestamp string (ISO format).
            tolerance_seconds: Tolerance for timestamp age.

        Returns:
            True if timestamp is valid and recent.

        Raises:
            SignatureVerificationError: If timestamp is invalid or too old.
        """
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, AttributeError) as e:
            raise SignatureVerificationError(f"Invalid timestamp: {e}")

        age_seconds = (datetime.utcnow() - timestamp).total_seconds()
        if age_seconds > tolerance_seconds:
            raise SignatureVerificationError(f"Request too old: {age_seconds}s > {tolerance_seconds}s")

        if age_seconds < -tolerance_seconds:
            raise SignatureVerificationError("Request timestamp in the future")

        return True
