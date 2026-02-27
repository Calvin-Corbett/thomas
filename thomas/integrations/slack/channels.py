"""Channel operations for Slack integration."""

from __future__ import annotations

import logging
from typing import Any

from .integration import SlackIntegration

log = logging.getLogger(__name__)


class SlackChannels:
    """Handle channel operations in Slack."""

    def __init__(self, integration: SlackIntegration) -> None:
        """Initialize channel operations.

        Args:
            integration: SlackIntegration instance
        """
        self._integration = integration

    async def list_channels(
        self,
        types: str | None = None,
        limit: int = 100,
        exclude_archived: bool = True,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List workspace channels.

        Args:
            types: Comma-separated types: 'public_channel', 'private_channel', 'im', 'mpim'
                   Defaults to all types
            limit: Channels per page (1-999)
            exclude_archived: Skip archived channels
            cursor: Pagination cursor for next page

        Returns:
            Response with channels array and pagination cursor

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "limit": max(1, min(999, int(limit))),
            "exclude_archived": bool(exclude_archived),
        }

        if types:
            params["types"] = str(types).strip()

        if cursor:
            params["cursor"] = str(cursor).strip()

        result = await self._integration.execute("GET", "conversations.list", params=params)
        log.debug("Listed %d channels", len(result.get("channels", [])))
        return result

    async def list_all_channels(
        self,
        types: str | None = None,
        exclude_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """List all workspace channels with automatic pagination.

        Args:
            types: Comma-separated types
            exclude_archived: Skip archived channels

        Returns:
            Complete list of all channels

        Raises:
            SlackAPIError: On API errors
        """
        all_channels: list[dict[str, Any]] = []
        cursor = None

        while True:
            result = await self.list_channels(
                types=types,
                limit=100,
                exclude_archived=exclude_archived,
                cursor=cursor,
            )
            all_channels.extend(result.get("channels", []))

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return all_channels

    async def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        """Get channel details.

        Args:
            channel_id: Channel ID or name

        Returns:
            Channel object with full details

        Raises:
            SlackAPIError: On API errors
        """
        params = {"channel": str(channel_id).strip()}
        result = await self._integration.execute("GET", "conversations.info", params=params)
        log.debug("Got info for channel %s", channel_id)
        return result

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 100,
        oldest: str | None = None,
        latest: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get message history for channel.

        Args:
            channel_id: Channel ID or name
            limit: Messages per page (1-999)
            oldest: Unix timestamp of oldest message to include
            latest: Unix timestamp of newest message to include
            cursor: Pagination cursor

        Returns:
            Response with messages array and pagination info

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "channel": str(channel_id).strip(),
            "limit": max(1, min(999, int(limit))),
        }

        if oldest:
            params["oldest"] = str(oldest).strip()

        if latest:
            params["latest"] = str(latest).strip()

        if cursor:
            params["cursor"] = str(cursor).strip()

        result = await self._integration.execute("GET", "conversations.history", params=params)
        log.debug("Got history for channel %s (%d messages)", channel_id, len(result.get("messages", [])))
        return result

    async def join_channel(self, channel_id: str) -> dict[str, Any]:
        """Join a channel.

        Args:
            channel_id: Channel ID or name

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {"channel": str(channel_id).strip()}
        result = await self._integration.execute("POST", "conversations.join", data=data)
        log.info("Joined channel %s", channel_id)
        return result

    async def create_channel(
        self,
        name: str,
        is_private: bool = False,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new channel.

        Args:
            name: Channel name (lowercase, no spaces)
            is_private: Create as private channel
            description: Channel description/topic

        Returns:
            Created channel object

        Raises:
            SlackAPIError: On API errors
        """
        if not str(name).strip():
            raise ValueError("Channel name is required")

        data = {
            "name": str(name).strip().lower(),
            "is_private": bool(is_private),
        }

        if description:
            data["description"] = str(description).strip()

        result = await self._integration.execute("POST", "conversations.create", data=data)
        log.info("Created channel %s (private=%s)", name, is_private)
        return result

    async def set_topic(self, channel_id: str, topic: str) -> dict[str, Any]:
        """Set channel topic.

        Args:
            channel_id: Channel ID or name
            topic: Topic text (markdown supported)

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {
            "channel": str(channel_id).strip(),
            "topic": str(topic).strip(),
        }
        result = await self._integration.execute("POST", "conversations.setTopic", data=data)
        log.debug("Set topic for channel %s", channel_id)
        return result

    async def set_purpose(self, channel_id: str, purpose: str) -> dict[str, Any]:
        """Set channel purpose.

        Args:
            channel_id: Channel ID or name
            purpose: Purpose text

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {
            "channel": str(channel_id).strip(),
            "purpose": str(purpose).strip(),
        }
        result = await self._integration.execute("POST", "conversations.setPurpose", data=data)
        log.debug("Set purpose for channel %s", channel_id)
        return result

    async def list_members(
        self,
        channel_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List channel members.

        Args:
            channel_id: Channel ID or name
            limit: Members per page (1-999)
            cursor: Pagination cursor

        Returns:
            Response with members array and pagination info

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "channel": str(channel_id).strip(),
            "limit": max(1, min(999, int(limit))),
        }

        if cursor:
            params["cursor"] = str(cursor).strip()

        result = await self._integration.execute("GET", "conversations.members", params=params)
        log.debug("Listed %d members in channel %s", len(result.get("members", [])), channel_id)
        return result

    async def list_all_members(self, channel_id: str) -> list[str]:
        """List all channel members with automatic pagination.

        Args:
            channel_id: Channel ID or name

        Returns:
            Complete list of member user IDs

        Raises:
            SlackAPIError: On API errors
        """
        all_members: list[str] = []
        cursor = None

        while True:
            result = await self.list_members(channel_id, limit=100, cursor=cursor)
            all_members.extend(result.get("members", []))

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return all_members

    async def invite_users(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> dict[str, Any]:
        """Invite users to channel.

        Args:
            channel_id: Channel ID or name
            user_ids: List of user IDs to invite

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        if not user_ids:
            raise ValueError("At least one user_id is required")

        data = {
            "channel": str(channel_id).strip(),
            "users": ",".join(str(uid).strip() for uid in user_ids),
        }
        result = await self._integration.execute("POST", "conversations.invite", data=data)
        log.info("Invited %d users to channel %s", len(user_ids), channel_id)
        return result

    async def archive_channel(self, channel_id: str) -> dict[str, Any]:
        """Archive a channel.

        Args:
            channel_id: Channel ID or name

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {"channel": str(channel_id).strip()}
        result = await self._integration.execute("POST", "conversations.archive", data=data)
        log.info("Archived channel %s", channel_id)
        return result

    async def unarchive_channel(self, channel_id: str) -> dict[str, Any]:
        """Unarchive a channel.

        Args:
            channel_id: Channel ID or name

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {"channel": str(channel_id).strip()}
        result = await self._integration.execute("POST", "conversations.unarchive", data=data)
        log.info("Unarchived channel %s", channel_id)
        return result

    async def rename_channel(self, channel_id: str, name: str) -> dict[str, Any]:
        """Rename a channel.

        Args:
            channel_id: Channel ID or name
            name: New channel name

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        if not str(name).strip():
            raise ValueError("New channel name is required")

        data = {
            "channel": str(channel_id).strip(),
            "name": str(name).strip().lower(),
        }
        result = await self._integration.execute("POST", "conversations.rename", data=data)
        log.info("Renamed channel %s to %s", channel_id, name)
        return result

    async def leave_channel(self, channel_id: str) -> dict[str, Any]:
        """Leave a channel.

        Args:
            channel_id: Channel ID or name

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {"channel": str(channel_id).strip()}
        result = await self._integration.execute("POST", "conversations.leave", data=data)
        log.info("Left channel %s", channel_id)
        return result
