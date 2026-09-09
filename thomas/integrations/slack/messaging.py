"""Message operations for Slack integration."""

from __future__ import annotations

import logging
import re
from typing import Any

from .integration import SlackAPIError, SlackIntegration

log = logging.getLogger(__name__)


class SlackMessaging:
    """Handle message operations in Slack."""

    def __init__(self, integration: SlackIntegration) -> None:
        """Initialize messaging operations.

        Args:
            integration: SlackIntegration instance
        """
        self._integration = integration

    async def send_message(
        self,
        channel: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        metadata: dict[str, Any] | None = None,
        reply_broadcast: bool = False,
    ) -> dict[str, Any]:
        """Send message to channel or thread.

        Args:
            channel: Channel ID or name
            text: Plain text message
            blocks: Block Kit blocks for rich formatting
            thread_ts: Timestamp of thread to reply in
            metadata: Message metadata
            reply_broadcast: Share thread reply to channel

        Returns:
            API response with ts and channel

        Raises:
            SlackAPIError: On API errors
        """
        if not text and not blocks:
            raise ValueError("Either text or blocks must be provided")

        data = {"channel": str(channel).strip()}

        if text:
            data["text"] = str(text).strip()

        if blocks:
            if not isinstance(blocks, list):
                raise ValueError("blocks must be a list of Block Kit objects")
            data["blocks"] = blocks

        if thread_ts:
            data["thread_ts"] = str(thread_ts).strip()

        if reply_broadcast:
            data["reply_broadcast"] = True

        if metadata:
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a dict")
            data["metadata"] = metadata

        result = await self._integration.execute("POST", "chat.postMessage", data=data)
        log.debug("Message sent to %s (ts=%s)", channel, result.get("ts"))
        return result

    async def update_message(
        self,
        channel: str,
        ts: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update existing message.

        Args:
            channel: Channel ID or name
            ts: Message timestamp (from send_message response)
            text: New plain text
            blocks: New Block Kit blocks
            metadata: New metadata

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        if not text and not blocks:
            raise ValueError("Either text or blocks must be provided")

        data = {
            "channel": str(channel).strip(),
            "ts": str(ts).strip(),
        }

        if text:
            data["text"] = str(text).strip()

        if blocks:
            if not isinstance(blocks, list):
                raise ValueError("blocks must be a list")
            data["blocks"] = blocks

        if metadata:
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a dict")
            data["metadata"] = metadata

        result = await self._integration.execute("POST", "chat.update", data=data)
        log.debug("Message updated in %s (ts=%s)", channel, ts)
        return result

    async def delete_message(self, channel: str, ts: str) -> dict[str, Any]:
        """Delete message.

        Args:
            channel: Channel ID or name
            ts: Message timestamp

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        data = {
            "channel": str(channel).strip(),
            "ts": str(ts).strip(),
        }
        result = await self._integration.execute("POST", "chat.delete", data=data)
        log.debug("Message deleted from %s", channel)
        return result

    async def reply_to_thread(
        self,
        channel: str,
        thread_ts: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Reply to message thread.

        Args:
            channel: Channel ID or name
            thread_ts: Parent message timestamp
            text: Plain text reply
            blocks: Block Kit blocks

        Returns:
            API response with ts

        Raises:
            SlackAPIError: On API errors
        """
        return await self.send_message(
            channel,
            text=text,
            blocks=blocks,
            thread_ts=thread_ts,
        )

    async def add_reaction(
        self,
        channel: str,
        ts: str,
        emoji: str,
    ) -> dict[str, Any]:
        """Add emoji reaction to message.

        Args:
            channel: Channel ID or name
            ts: Message timestamp
            emoji: Emoji name (without colons, e.g., 'thumbsup')

        Returns:
            API response

        Raises:
            SlackAPIError: On API errors
        """
        emoji_clean = str(emoji).strip().strip(":")
        data = {
            "channel": str(channel).strip(),
            "timestamp": str(ts).strip(),
            "name": emoji_clean,
        }
        result = await self._integration.execute("POST", "reactions.add", data=data)
        log.debug("Reaction added to message in %s", channel)
        return result

    async def get_message(self, channel: str, ts: str) -> dict[str, Any]:
        """Get single message details.

        Args:
            channel: Channel ID or name
            ts: Message timestamp

        Returns:
            Message object with full details

        Raises:
            SlackAPIError: On API errors
        """
        params = {
            "channel": str(channel).strip(),
            "latest": str(ts).strip(),
            "limit": 1,
            "inclusive": True,
        }
        result = await self._integration.execute("GET", "conversations.history", params=params)
        messages = result.get("messages", [])
        if messages:
            return messages[0]
        raise SlackAPIError(f"Message not found: {channel}/{ts}")

    async def search_messages(
        self,
        query: str,
        sort: str = "timestamp",
        sort_dir: str = "desc",
        count: int = 20,
    ) -> dict[str, Any]:
        """Search workspace messages.

        Args:
            query: Search query (supports Slack search syntax)
            sort: Sort field ('timestamp' or 'relevance')
            sort_dir: Sort direction ('asc' or 'desc')
            count: Number of results to return

        Returns:
            Search results with matches array

        Raises:
            SlackAPIError: On API errors
        """
        if not str(query).strip():
            raise ValueError("query cannot be empty")

        params = {
            "query": str(query).strip(),
            "sort": str(sort).strip(),
            "sort_dir": str(sort_dir).strip(),
            "count": max(1, min(100, int(count))),
        }

        result = await self._integration.execute("GET", "search.messages", params=params)
        log.debug(
            "Message search completed: %d results for query '%s'",
            len(result.get("messages", {}).get("matches", [])),
            query,
        )
        return result

    def parse_message_mentions(self, text: str) -> list[str]:
        """Extract user mentions from message text.

        Args:
            text: Message text

        Returns:
            List of user IDs mentioned (without angle brackets)
        """
        # Slack user mentions are <@USERID> or <@USERID|username>
        pattern = r"<@([A-Z0-9]+)(?:\|[^>]*)?"
        matches = re.findall(pattern, text)
        return matches

    def parse_channel_mentions(self, text: str) -> list[str]:
        """Extract channel mentions from message text.

        Args:
            text: Message text

        Returns:
            List of channel IDs mentioned (without angle brackets)
        """
        # Slack channel mentions are <#CHANNEL_ID> or <#CHANNEL_ID|channel_name>
        pattern = r"<#([A-Z0-9]+)(?:\|[^>]*)?"
        matches = re.findall(pattern, text)
        return matches

    def format_user_mention(self, user_id: str) -> str:
        """Format user mention for message text.

        Args:
            user_id: Slack user ID

        Returns:
            Formatted mention string
        """
        return f"<@{str(user_id).strip()}>"

    def format_channel_mention(self, channel_id: str) -> str:
        """Format channel mention for message text.

        Args:
            channel_id: Slack channel ID

        Returns:
            Formatted mention string
        """
        return f"<#{str(channel_id).strip()}>"

    def create_text_block(self, text: str, block_id: str | None = None) -> dict[str, Any]:
        """Create Block Kit text block.

        Args:
            text: Text content (markdown)
            block_id: Optional block ID for interactions

        Returns:
            Block Kit section block
        """
        block = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": str(text).strip(),
            },
        }
        if block_id:
            block["block_id"] = str(block_id).strip()
        return block

    def create_image_block(
        self,
        image_url: str,
        alt_text: str,
        title: str | None = None,
        block_id: str | None = None,
    ) -> dict[str, Any]:
        """Create Block Kit image block.

        Args:
            image_url: URL to image
            alt_text: Accessibility text
            title: Optional title text
            block_id: Optional block ID

        Returns:
            Block Kit image block
        """
        block = {
            "type": "image",
            "image_url": str(image_url).strip(),
            "alt_text": str(alt_text).strip(),
        }
        if title:
            block["title"] = {
                "type": "plain_text",
                "text": str(title).strip(),
            }
        if block_id:
            block["block_id"] = str(block_id).strip()
        return block

    def create_button_block(
        self,
        text: str,
        action_id: str,
        value: str,
        style: str | None = None,
    ) -> dict[str, Any]:
        """Create Block Kit button element (for use in actions block).

        Args:
            text: Button label
            action_id: Unique action identifier
            value: Value sent when clicked
            style: 'primary' or 'danger'

        Returns:
            Block Kit button element
        """
        button = {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": str(text).strip(),
            },
            "action_id": str(action_id).strip(),
            "value": str(value).strip(),
        }
        if style and style in ("primary", "danger"):
            button["style"] = style
        return button

    def create_actions_block(
        self,
        elements: list[dict[str, Any]],
        block_id: str | None = None,
    ) -> dict[str, Any]:
        """Create Block Kit actions block (container for buttons, etc).

        Args:
            elements: List of button/select elements
            block_id: Optional block ID

        Returns:
            Block Kit actions block
        """
        block = {
            "type": "actions",
            "elements": elements,
        }
        if block_id:
            block["block_id"] = str(block_id).strip()
        return block

    def create_divider_block(self, block_id: str | None = None) -> dict[str, Any]:
        """Create Block Kit divider block.

        Args:
            block_id: Optional block ID

        Returns:
            Block Kit divider block
        """
        block = {"type": "divider"}
        if block_id:
            block["block_id"] = str(block_id).strip()
        return block
