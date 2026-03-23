"""Secrets management with vault, rotation, encryption, and access control.

Provides secret storage, encryption, rotation policies,
access control, and audit logging.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SecretType(Enum):
    """Secret types."""

    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    CONNECTION_STRING = "connection_string"
    OAUTH_TOKEN = "oauth_token"


class AccessLevel(Enum):
    """Access control levels."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


@dataclass
class Secret:
    """Secret data."""

    name: str
    secret_type: SecretType
    value: str  # Encrypted
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    rotation_enabled: bool = False
    rotation_period_days: int = 90

    def is_expired(self) -> bool:
        """Check if secret is expired."""
        if self.expires_at:
            return datetime.utcnow() > self.expires_at
        return False

    def needs_rotation(self) -> bool:
        """Check if secret needs rotation."""
        if not self.rotation_enabled:
            return False
        age = datetime.utcnow() - self.updated_at
        return age.days >= self.rotation_period_days


@dataclass
class AccessPolicy:
    """Access control policy."""

    principal: str  # User, service, or group
    secret_name: str
    access_level: AccessLevel
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None

    def is_valid(self) -> bool:
        """Check if policy is valid."""
        if self.expires_at:
            return datetime.utcnow() <= self.expires_at
        return True


@dataclass
class AuditEntry:
    """Audit log entry."""

    timestamp: datetime = field(default_factory=datetime.utcnow)
    action: str = ""
    principal: str = ""
    secret_name: str = ""
    result: str = "success"
    details: str = ""


class SecretEncryption:
    """Secret encryption."""

    @staticmethod
    def encrypt(value: str) -> str:
        """Encrypt secret value."""
        # Simplified - use base64 for demo
        return base64.b64encode(value.encode()).decode()

    @staticmethod
    def decrypt(encrypted: str) -> str:
        """Decrypt secret value."""
        # Simplified - decode from base64
        return base64.b64decode(encrypted.encode()).decode()


class SecretVault:
    """Secret vault."""

    def __init__(self):
        self.secrets: dict[str, Secret] = {}
        self.policies: dict[str, list[AccessPolicy]] = {}
        self.audit_log: list[AuditEntry] = []

    def store_secret(
        self, name: str, value: str, secret_type: SecretType, metadata: dict[str, Any] | None = None
    ) -> Secret:
        """Store secret in vault."""
        encrypted_value = SecretEncryption.encrypt(value)
        secret = Secret(name=name, secret_type=secret_type, value=encrypted_value, metadata=metadata or {})
        self.secrets[name] = secret

        self.audit_log.append(
            AuditEntry(action="store_secret", secret_name=name, details=f"Stored secret of type {secret_type.value}")
        )

        return secret

    def retrieve_secret(self, name: str, principal: str) -> str | None:
        """Retrieve secret if authorized."""
        secret = self.secrets.get(name)
        if not secret:
            return None

        if not self._check_access(principal, name, AccessLevel.READ):
            self.audit_log.append(
                AuditEntry(action="retrieve_secret", principal=principal, secret_name=name, result="denied")
            )
            return None

        if secret.is_expired():
            return None

        decrypted = SecretEncryption.decrypt(secret.value)

        self.audit_log.append(AuditEntry(action="retrieve_secret", principal=principal, secret_name=name))

        return decrypted

    def rotate_secret(self, name: str, new_value: str) -> bool:
        """Rotate secret."""
        secret = self.secrets.get(name)
        if not secret:
            return False

        encrypted_value = SecretEncryption.encrypt(new_value)
        secret.value = encrypted_value
        secret.updated_at = datetime.utcnow()

        self.audit_log.append(AuditEntry(action="rotate_secret", secret_name=name))

        return True

    def delete_secret(self, name: str, principal: str) -> bool:
        """Delete secret."""
        if not self._check_access(principal, name, AccessLevel.ADMIN):
            return False

        if name in self.secrets:
            del self.secrets[name]
            self.audit_log.append(AuditEntry(action="delete_secret", principal=principal, secret_name=name))
            return True

        return False

    def grant_access(self, principal: str, secret_name: str, access_level: AccessLevel) -> bool:
        """Grant access to secret."""
        if secret_name not in self.secrets:
            return False

        if secret_name not in self.policies:
            self.policies[secret_name] = []

        policy = AccessPolicy(principal=principal, secret_name=secret_name, access_level=access_level)
        self.policies[secret_name].append(policy)

        self.audit_log.append(
            AuditEntry(
                action="grant_access",
                principal=principal,
                secret_name=secret_name,
                details=f"Granted {access_level.value} access",
            )
        )

        return True

    def revoke_access(self, principal: str, secret_name: str) -> bool:
        """Revoke access to secret."""
        if secret_name not in self.policies:
            return False

        self.policies[secret_name] = [p for p in self.policies[secret_name] if p.principal != principal]

        self.audit_log.append(AuditEntry(action="revoke_access", principal=principal, secret_name=secret_name))

        return True

    def _check_access(self, principal: str, secret_name: str, required_level: AccessLevel) -> bool:
        """Check access permission."""
        policies = self.policies.get(secret_name, [])

        for policy in policies:
            if policy.principal == principal and policy.is_valid():
                if policy.access_level.value >= required_level.value:
                    return True

        return False

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit log."""
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "action": e.action,
                "principal": e.principal,
                "secret_name": e.secret_name,
                "result": e.result,
            }
            for e in self.audit_log[-limit:]
        ]

    def get_rotation_candidates(self) -> list[str]:
        """Get secrets needing rotation."""
        candidates = []
        for name, secret in self.secrets.items():
            if secret.needs_rotation():
                candidates.append(name)
        return candidates
