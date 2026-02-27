"""Privacy controls and data protection.

This module handles granular privacy settings, block/mute management,
GDPR-style data export, account deletion with purge, consent tracking,
IP-based geofencing, anonymous interaction mode, and privacy impact scoring.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ._types import PrivacySetting


class PrivacyManager:
    """Manages user privacy and data protection.

    Attributes:
        privacy_settings: Per-user privacy configuration
        content_visibility: Per-content visibility settings
        consent_records: GDPR consent tracking
        data_exports: Requested data exports
        ip_whitelist: IP addresses allowed to access account
        anonymous_sessions: Anonymous interaction sessions
    """

    def __init__(self) -> None:
        """Initialize privacy manager."""
        self.privacy_settings: dict[UUID, dict[str, Any]] = {}
        self.content_visibility: dict[UUID, dict[str, PrivacySetting]] = {}
        self.consent_records: dict[UUID, dict[str, Any]] = {}
        self.data_exports: dict[UUID, str] = {}  # user_id -> export_file_path
        self.ip_whitelist: dict[UUID, set[str]] = {}
        self.anonymous_sessions: dict[str, UUID] = {}  # session_id -> user_id (if known)
        self.muted_keywords: dict[UUID, set[str]] = {}
        self.privacy_impact_log: list[dict[str, Any]] = []

    def initialize_privacy_settings(self, user_id: UUID) -> dict[str, Any]:
        """Initialize privacy settings for new user.

        Args:
            user_id: User ID

        Returns:
            Privacy settings dictionary
        """
        settings = {
            "profile_visibility": PrivacySetting.PUBLIC,
            "post_visibility": PrivacySetting.PUBLIC,
            "allow_dms": True,
            "allow_mentions": True,
            "allow_tags": False,
            "search_indexing": True,
            "analytics_tracking": True,
            "third_party_sharing": False,
            "geofencing_enabled": False,
            "ip_based_access": False,
            "two_factor_enabled": False,
            "created_at": datetime.utcnow(),
        }

        self.privacy_settings[user_id] = settings
        return settings

    def update_privacy_setting(self, user_id: UUID, setting_name: str, value: Any) -> None:
        """Update a privacy setting.

        Args:
            user_id: User ID
            setting_name: Setting name
            value: New value
        """
        if user_id not in self.privacy_settings:
            self.initialize_privacy_settings(user_id)

        self.privacy_settings[user_id][setting_name] = value
        self.privacy_settings[user_id]["updated_at"] = datetime.utcnow()

    def get_privacy_settings(self, user_id: UUID) -> dict[str, Any]:
        """Get user's privacy settings.

        Args:
            user_id: User ID

        Returns:
            Privacy settings dictionary
        """
        if user_id not in self.privacy_settings:
            return self.initialize_privacy_settings(user_id)

        return self.privacy_settings[user_id]

    def set_content_visibility(self, content_id: UUID, visibility: PrivacySetting) -> None:
        """Set visibility for specific content.

        Args:
            content_id: Content ID (post/comment)
            visibility: Visibility level
        """
        if content_id not in self.content_visibility:
            self.content_visibility[content_id] = {}

        self.content_visibility[content_id]["level"] = visibility
        self.content_visibility[content_id]["updated_at"] = datetime.utcnow()

    def get_content_visibility(self, content_id: UUID) -> PrivacySetting:
        """Get visibility level for content.

        Args:
            content_id: Content ID

        Returns:
            PrivacySetting level
        """
        if content_id in self.content_visibility:
            return self.content_visibility[content_id].get("level", PrivacySetting.PUBLIC)

        return PrivacySetting.PUBLIC

    def record_consent(self, user_id: UUID, consent_type: str, value: bool, ip_address: str | None = None) -> None:
        """Record consent decision (GDPR).

        Args:
            user_id: User ID
            consent_type: Type of consent (marketing, analytics, etc.)
            value: Consent given (True/False)
            ip_address: IP address where consent was given
        """
        if user_id not in self.consent_records:
            self.consent_records[user_id] = {}

        self.consent_records[user_id][consent_type] = {
            "value": value,
            "timestamp": datetime.utcnow(),
            "ip_address": ip_address,
        }

    def has_consent(self, user_id: UUID, consent_type: str) -> bool:
        """Check if user has given consent.

        Args:
            user_id: User ID
            consent_type: Type of consent

        Returns:
            True if user consented
        """
        if user_id not in self.consent_records:
            return False

        consent = self.consent_records[user_id].get(consent_type)
        return consent.get("value", False) if consent else False

    def add_ip_to_whitelist(self, user_id: UUID, ip_address: str) -> None:
        """Add IP address to user's whitelist.

        Args:
            user_id: User ID
            ip_address: IP address
        """
        if user_id not in self.ip_whitelist:
            self.ip_whitelist[user_id] = set()

        self.ip_whitelist[user_id].add(ip_address)

    def remove_ip_from_whitelist(self, user_id: UUID, ip_address: str) -> None:
        """Remove IP address from whitelist.

        Args:
            user_id: User ID
            ip_address: IP address
        """
        if user_id in self.ip_whitelist:
            self.ip_whitelist[user_id].discard(ip_address)

    def check_ip_whitelisted(self, user_id: UUID, ip_address: str) -> bool:
        """Check if IP is whitelisted.

        Args:
            user_id: User ID
            ip_address: IP address

        Returns:
            True if IP is whitelisted
        """
        if user_id not in self.ip_whitelist:
            return True  # No whitelist = all IPs allowed

        return ip_address in self.ip_whitelist[user_id]

    def mute_keyword(self, user_id: UUID, keyword: str) -> None:
        """Add keyword to user's mute list.

        Args:
            user_id: User ID
            keyword: Keyword to mute
        """
        if user_id not in self.muted_keywords:
            self.muted_keywords[user_id] = set()

        self.muted_keywords[user_id].add(keyword.lower())

    def unmute_keyword(self, user_id: UUID, keyword: str) -> None:
        """Remove keyword from mute list.

        Args:
            user_id: User ID
            keyword: Keyword to unmute
        """
        if user_id in self.muted_keywords:
            self.muted_keywords[user_id].discard(keyword.lower())

    def is_keyword_muted(self, user_id: UUID, text: str) -> bool:
        """Check if text contains muted keywords.

        Args:
            user_id: User ID
            text: Text to check

        Returns:
            True if muted keywords found
        """
        if user_id not in self.muted_keywords:
            return False

        text_lower = text.lower()
        for keyword in self.muted_keywords[user_id]:
            if keyword in text_lower:
                return True

        return False

    def get_muted_keywords(self, user_id: UUID) -> set[str]:
        """Get user's muted keywords.

        Args:
            user_id: User ID

        Returns:
            Set of muted keywords
        """
        return self.muted_keywords.get(user_id, set())

    def export_user_data(self, user_id: UUID) -> str:
        """Export user's data (GDPR Article 15).

        Returns JSON export of all user data.

        Args:
            user_id: User ID

        Returns:
            JSON string of exported data
        """
        export_data = {
            "export_date": datetime.utcnow().isoformat(),
            "user_id": str(user_id),
            "privacy_settings": self.privacy_settings.get(user_id, {}),
            "consent_records": {
                k: {
                    "value": v.get("value"),
                    "timestamp": v.get("timestamp", "").isoformat()
                    if hasattr(v.get("timestamp"), "isoformat")
                    else str(v.get("timestamp")),
                }
                for k, v in self.consent_records.get(user_id, {}).items()
            },
            "muted_keywords": list(self.muted_keywords.get(user_id, set())),
            "ip_whitelist": list(self.ip_whitelist.get(user_id, set())),
        }

        export_json = json.dumps(export_data, indent=2)

        # Store reference
        export_id = str(uuid4())
        self.data_exports[user_id] = export_id

        return export_json

    def delete_user_data(self, user_id: UUID) -> dict[str, int]:
        """Delete user account and associated data (GDPR Article 17).

        Args:
            user_id: User ID

        Returns:
            Dictionary with deletion counts
        """
        deletion_counts = {"privacy_settings": 0, "consent_records": 0, "content": 0, "interactions": 0}

        # Delete privacy settings
        if user_id in self.privacy_settings:
            del self.privacy_settings[user_id]
            deletion_counts["privacy_settings"] = 1

        # Delete consent records
        if user_id in self.consent_records:
            del self.consent_records[user_id]
            deletion_counts["consent_records"] = 1

        # Delete from other collections
        self.ip_whitelist.pop(user_id, None)
        self.muted_keywords.pop(user_id, None)
        self.data_exports.pop(user_id, None)

        return deletion_counts

    def create_anonymous_session(self, user_id: UUID | None = None) -> str:
        """Create anonymous session.

        Args:
            user_id: Optional user ID for anonymous user

        Returns:
            Session ID
        """
        session_id = str(uuid4())
        if user_id:
            self.anonymous_sessions[session_id] = user_id

        return session_id

    def get_session_user(self, session_id: str) -> UUID | None:
        """Get user ID for session (if logged in).

        Args:
            session_id: Session ID

        Returns:
            User ID or None for anonymous
        """
        return self.anonymous_sessions.get(session_id)

    def calculate_privacy_score(self, user_id: UUID) -> dict[str, Any]:
        """Calculate privacy impact score.

        Returns score 0-100 (higher = more private).

        Args:
            user_id: User ID

        Returns:
            Privacy score and breakdown
        """
        settings = self.get_privacy_settings(user_id)

        score = 50  # Base score

        # Privacy-enhancing settings
        if settings.get("profile_visibility") == PrivacySetting.PRIVATE:
            score += 20
        elif settings.get("profile_visibility") == PrivacySetting.FRIENDS_ONLY:
            score += 10

        if not settings.get("allow_dms", True):
            score += 5

        if not settings.get("allow_mentions", True):
            score += 5

        if not settings.get("search_indexing", True):
            score += 10

        if not settings.get("analytics_tracking", True):
            score += 10

        if not settings.get("third_party_sharing", False):
            score += 10

        if settings.get("ip_based_access", False):
            score += 5

        if settings.get("two_factor_enabled", False):
            score += 5

        score = min(score, 100)  # Cap at 100

        return {
            "overall_score": score,
            "privacy_level": "high" if score >= 70 else "medium" if score >= 40 else "low",
            "settings_breakdown": {
                "profile_visibility": str(settings.get("profile_visibility", "unknown")),
                "search_indexing": settings.get("search_indexing", True),
                "analytics_tracking": settings.get("analytics_tracking", True),
                "third_party_sharing": settings.get("third_party_sharing", False),
                "ip_based_access": settings.get("ip_based_access", False),
                "two_factor_enabled": settings.get("two_factor_enabled", False),
            },
        }

    def get_data_retention_policy(self) -> dict[str, int]:
        """Get data retention policy.

        Returns:
            Dictionary mapping data type to retention days
        """
        return {
            "posts": 2555,  # ~7 years
            "messages": 1825,  # 5 years
            "analytics": 365,  # 1 year
            "audit_logs": 2555,  # 7 years
            "user_activity": 730,  # 2 years
            "failed_login_attempts": 90,  # 3 months
        }

    def should_purge_data(self, user_id: UUID, data_type: str, created_at: datetime) -> bool:
        """Check if data should be purged based on retention policy.

        Args:
            user_id: User ID
            data_type: Type of data
            created_at: Data creation timestamp

        Returns:
            True if should be purged
        """
        policy = self.get_data_retention_policy()
        retention_days = policy.get(data_type, 730)
        cutoff = datetime.utcnow() - timedelta(days=retention_days)

        return created_at < cutoff

    def check_geofence(
        self, user_id: UUID, latitude: float, longitude: float, allowed_countries: list[str] | None = None
    ) -> bool:
        """Check if user access is allowed from location.

        Args:
            user_id: User ID
            latitude: Access latitude
            longitude: Access longitude
            allowed_countries: List of allowed country codes

        Returns:
            True if access allowed
        """
        settings = self.get_privacy_settings(user_id)

        if not settings.get("geofencing_enabled", False):
            return True

        # Simplified geofencing (real implementation would use GIS)
        # For demo, allow US by default
        allowed = allowed_countries or ["US"]

        # In real implementation, would lookup location from lat/long
        # For now, return True
        return True
