"""User operations for Slack integration."""

from __future__ import annotations

import logging
import time
from typing import Any

from .integration import SlackIntegration

log = logging.getLogger(__name__)


class SlackUsers:
    """Handle user operations in Slack."""

    def __init__(self, integration: SlackIntegration) -> None:
        """Initialize user operations.

        Args:
            integration: SlackIntegration instance
        """
        self._integration = integration

    async def list_users(
        self,
        limit: int = 100,
        cursor: str | None = None,
        include_locale: bool = True,
    ) -> dict[str, Any]:
        """List workspace users.

        Args:
            limit: Users per page (1-999)
            cursor: Pagination cursor
            include_locale: Include user locale info

        Returns:
            Response with members array and pagination info

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "limit": max(1, min(999, int(limit))),
            "include_locale": bool(include_locale),
        }

        if cursor:
            params["cursor"] = str(cursor).strip()

        result = await self._integration.execute("GET", "users.list", params=params)
        log.debug("Listed %d users", len(result.get("members", [])))
        return result

    async def list_all_users(self) -> list[dict[str, Any]]:
        """List all workspace users with automatic pagination.

        Returns:
            Complete list of all users

        Raises:
            SlackAPIError: On API errors
        """
        all_users: list[dict[str, Any]] = []
        cursor = None

        while True:
            result = await self.list_users(limit=100, cursor=cursor)
            all_users.extend(result.get("members", []))

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return all_users

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Get user profile information.

        Args:
            user_id: Slack user ID

        Returns:
            User profile object

        Raises:
            SlackAPIError: On API errors
        """
        params = {"user": str(user_id).strip()}
        result = await self._integration.execute("GET", "users.info", params=params)
        log.debug("Got info for user %s", user_id)
        return result

    async def get_user_by_email(self, email: str) -> dict[str, Any]:
        """Look up user by email address.

        Args:
            email: User email address

        Returns:
            User object

        Raises:
            SlackAPIError: On API errors
        """
        if not str(email).strip():
            raise ValueError("Email is required")

        params = {"email": str(email).strip()}
        result = await self._integration.execute("GET", "users.lookupByEmail", params=params)
        log.debug("Looked up user by email")
        return result

    async def get_presence(self, user_id: str) -> dict[str, Any]:
        """Get user presence status (online/away).

        Args:
            user_id: Slack user ID

        Returns:
            Presence info with status

        Raises:
            SlackAPIError: On API errors
        """
        params = {"user": str(user_id).strip()}
        result = await self._integration.execute("GET", "users.getPresence", params=params)
        log.debug("Got presence for user %s: %s", user_id, result.get("presence"))
        return result

    async def set_presence(self, presence: str) -> dict[str, Any]:
        """Set bot presence status.

        Args:
            presence: 'active' or 'away'

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        if str(presence).strip() not in ("active", "away"):
            raise ValueError("presence must be 'active' or 'away'")

        data = {"presence": str(presence).strip()}
        result = await self._integration.execute("POST", "users.setPresence", data=data)
        log.debug("Set bot presence to %s", presence)
        return result

    async def set_status(
        self,
        status_text: str | None = None,
        status_emoji: str | None = None,
        expiration_s: int | None = None,
    ) -> dict[str, Any]:
        """Set user status (as authenticated user).

        Args:
            status_text: Status text (e.g., "In a meeting")
            status_emoji: Status emoji (e.g., "calendar" for :calendar:)
            expiration_s: Seconds until status expires (default: doesn't expire)

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        profile = {}

        if status_text is not None:
            profile["status_text"] = str(status_text).strip()

        if status_emoji is not None:
            emoji = str(status_emoji).strip().lstrip(":")
            profile["status_emoji"] = f":{emoji}:"

        if not profile:
            raise ValueError("At least one of status_text or status_emoji is required")

        data = {"profile": profile}

        if expiration_s is not None:
            data["expiration"] = int(time.time()) + max(0, int(expiration_s))

        result = await self._integration.execute("POST", "users.profile.set", data=data, use_bot_token=False)
        log.debug("Set user status")
        return result

    async def clear_status(self) -> dict[str, Any]:
        """Clear user status.

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        profile = {
            "status_text": "",
            "status_emoji": "",
        }
        data = {"profile": profile}
        result = await self._integration.execute("POST", "users.profile.set", data=data, use_bot_token=False)
        log.debug("Cleared user status")
        return result

    async def search_users(self, query: str) -> list[dict[str, Any]]:
        """Search users by name or email (client-side search).

        Args:
            query: Search query (name or email)

        Returns:
            List of matching user objects

        Note:
            This is a client-side search through list_users.
            For more advanced search, use the Slack search API.

        Raises:
            SlackAPIError: On API errors
        """
        if not str(query).strip():
            raise ValueError("Search query is required")

        query_lower = str(query).strip().lower()
        all_users = await self.list_all_users()

        results: list[dict[str, Any]] = []
        for user in all_users:
            name = str(user.get("name", "")).lower()
            email = str(user.get("profile", {}).get("email", "")).lower()
            real_name = str(user.get("real_name", "")).lower()

            if query_lower in name or query_lower in email or query_lower in real_name:
                results.append(user)

        log.debug("Found %d users matching query '%s'", len(results), query)
        return results

    def get_display_name(self, user: dict[str, Any]) -> str:
        """Get user display name from user object.

        Args:
            user: User object from API

        Returns:
            Display name (real_name or name fallback)
        """
        real_name = str(user.get("real_name", "")).strip()
        if real_name:
            return real_name

        name = str(user.get("name", "")).strip()
        if name:
            return name

        return "Unknown User"

    def get_user_email(self, user: dict[str, Any]) -> str | None:
        """Get user email from user object.

        Args:
            user: User object from API

        Returns:
            User email or None
        """
        profile = user.get("profile", {})
        email = str(profile.get("email", "")).strip()
        return email if email else None

    def get_user_avatar(self, user: dict[str, Any]) -> str | None:
        """Get user avatar URL from user object.

        Args:
            user: User object from API

        Returns:
            Avatar URL or None
        """
        profile = user.get("profile", {})
        avatar = str(profile.get("image_192", "")).strip()
        return avatar if avatar else None

    def is_user_active(self, user: dict[str, Any]) -> bool:
        """Check if user is active (not deleted/deactivated).

        Args:
            user: User object from API

        Returns:
            True if user is active
        """
        return not user.get("deleted", False)

    def is_bot_user(self, user: dict[str, Any]) -> bool:
        """Check if user is a bot.

        Args:
            user: User object from API

        Returns:
            True if user is bot
        """
        return user.get("is_bot", False)

    def is_app_user(self, user: dict[str, Any]) -> bool:
        """Check if user is an app user.

        Args:
            user: User object from API

        Returns:
            True if user is app user
        """
        return user.get("is_app_user", False)

    def get_user_title(self, user: dict[str, Any]) -> str | None:
        """Get user title from profile.

        Args:
            user: User object from API

        Returns:
            User title or None
        """
        profile = user.get("profile", {})
        title = str(profile.get("title", "")).strip()
        return title if title else None

    def get_user_department(self, user: dict[str, Any]) -> str | None:
        """Get user department from profile.

        Args:
            user: User object from API

        Returns:
            User department or None
        """
        profile = user.get("profile", {})
        dept = str(profile.get("dept", "")).strip()
        return dept if dept else None

    async def get_users_in_team(self, team_id: str | None = None) -> list[dict[str, Any]]:
        """Get all active users in team (convenience wrapper).

        Args:
            team_id: Optional team ID (for multi-team workspaces)

        Returns:
            List of active user objects

        Raises:
            SlackAPIError: On API errors
        """
        users = await self.list_all_users()
        # Filter out deleted and bot users
        return [u for u in users if not u.get("deleted", False) and not u.get("is_bot", False)]
