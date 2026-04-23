"""Gmail API operations for Google Workspace integration.

Provides functions to list, read, send, and manage emails through Gmail API v1.
"""

from __future__ import annotations

import base64
import logging
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

log = logging.getLogger(__name__)


class GmailError(Exception):
    """Raised when Gmail API operations fail."""

    pass


class GmailAPI:
    """Wrapper for Gmail API v1 operations using raw REST endpoints."""

    BASE_URL = "https://www.googleapis.com/gmail/v1/users/me"

    def __init__(self, access_token: str) -> None:
        """Initialize Gmail API client.

        Args:
            access_token: OAuth2 access token with Gmail scope
        """
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _build_headers(self) -> dict[str, str]:
        """Get headers for message build requests (multipart)."""
        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    async def list_messages(
        self,
        session: Any,
        query: str = "",
        max_results: int = 10,
        label_ids: list[str] | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List messages matching query.

        Args:
            session: aiohttp ClientSession
            query: Gmail search query (e.g., "from:user@example.com is:unread")
            max_results: Maximum messages to return (1-500)
            label_ids: List of label IDs to filter by
            page_token: Token for paginated results

        Returns:
            Dict with messages list and next page token
        """
        max_results = min(500, max(1, max_results))
        params = {
            "q": query,
            "maxResults": max_results,
        }
        if page_token:
            params["pageToken"] = page_token
        if label_ids:
            params["labelIds"] = label_ids

        url = f"{self.BASE_URL}/messages"
        try:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"List messages failed: {resp.status} - {error}")
                data = await resp.json()
                return {
                    "messages": data.get("messages", []),
                    "resultSizeEstimate": data.get("resultSizeEstimate", 0),
                    "nextPageToken": data.get("nextPageToken"),
                }
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to list messages: {e}") from e

    async def get_message(
        self,
        session: Any,
        message_id: str,
        format: str = "full",
    ) -> dict[str, Any]:
        """Get full message details including body and attachments.

        Args:
            session: aiohttp ClientSession
            message_id: Gmail message ID
            format: Message format - "minimal", "full", or "raw"

        Returns:
            Message object with headers, body, and attachment metadata
        """
        params = {"format": format}
        url = f"{self.BASE_URL}/messages/{message_id}"
        try:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"Get message failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_message(data)
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to get message {message_id}: {e}") from e

    async def send_message(
        self,
        session: Any,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        """Send an email message.

        Args:
            session: aiohttp ClientSession
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            cc: List of CC recipient addresses
            bcc: List of BCC recipient addresses
            attachments: List of (filename, content_bytes) tuples

        Returns:
            Dict with sent message ID and threadId
        """
        if attachments:
            # Use multipart/mixed for attachments
            msg = MIMEMultipart("mixed")
            msg_body = MIMEMultipart("alternative")
            msg.attach(msg_body)
            msg_body.attach(MIMEText(body, "plain"))
        else:
            msg = MIMEText(body, "plain")

        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = ", ".join(cc)
        if bcc:
            msg["bcc"] = ", ".join(bcc)

        # Add attachments if provided
        if attachments:
            for filename, content in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(content)
                part.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(part)

        # Encode message
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        payload = {"raw": raw_message}
        url = f"{self.BASE_URL}/messages/send"
        try:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"Send message failed: {resp.status} - {error}")
                data = await resp.json()
                return {
                    "messageId": data.get("id"),
                    "threadId": data.get("threadId"),
                }
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to send message: {e}") from e

    async def reply_to_message(
        self,
        session: Any,
        message_id: str,
        body: str,
    ) -> dict[str, Any]:
        """Reply to a message in its thread.

        Args:
            session: aiohttp ClientSession
            message_id: Original message ID to reply to
            body: Reply body text

        Returns:
            Dict with sent reply message ID and threadId
        """
        # Get original message to extract thread info and recipient
        original = await self.get_message(session, message_id, format="minimal")
        headers = original.get("headers", {})

        # Extract sender and subject from original message
        from_header = headers.get("from", "")
        subject = headers.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Reply in thread
        reply_result = await self.send_message(
            session,
            to=from_header,
            subject=subject,
            body=body,
        )

        # Move to thread (we need thread ID)
        thread_id = original.get("threadId")
        if thread_id:
            reply_result["threadId"] = thread_id

        return reply_result

    async def create_draft(
        self,
        session: Any,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a draft message (not sent).

        Args:
            session: aiohttp ClientSession
            to: Recipient email address
            subject: Email subject
            body: Email body text
            cc: List of CC recipient addresses
            bcc: List of BCC recipient addresses

        Returns:
            Dict with draft message ID
        """
        msg = MIMEText(body, "plain")
        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = ", ".join(cc)
        if bcc:
            msg["bcc"] = ", ".join(bcc)

        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        payload = {
            "message": {
                "raw": raw_message,
            }
        }

        url = f"{self.BASE_URL}/drafts"
        try:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"Create draft failed: {resp.status} - {error}")
                data = await resp.json()
                draft = data.get("draft", {})
                return {
                    "draftId": draft.get("id"),
                    "messageId": draft.get("message", {}).get("id"),
                }
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to create draft: {e}") from e

    async def list_labels(self, session: Any) -> dict[str, Any]:
        """Get all labels in user's mailbox.

        Args:
            session: aiohttp ClientSession

        Returns:
            Dict with labels list
        """
        url = f"{self.BASE_URL}/labels"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"List labels failed: {resp.status} - {error}")
                data = await resp.json()
                labels = data.get("labels", [])
                return {
                    "labels": [
                        {
                            "id": label.get("id"),
                            "name": label.get("name"),
                            "type": label.get("type"),
                            "messageListVisibility": label.get("messageListVisibility"),
                            "labelListVisibility": label.get("labelListVisibility"),
                        }
                        for label in labels
                    ]
                }
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to list labels: {e}") from e

    async def modify_labels(
        self,
        session: Any,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add or remove labels from a message.

        Args:
            session: aiohttp ClientSession
            message_id: Message ID to modify
            add_labels: List of label IDs to add
            remove_labels: List of label IDs to remove

        Returns:
            Updated message object
        """
        payload = {}
        if add_labels:
            payload["addLabelIds"] = add_labels
        if remove_labels:
            payload["removeLabelIds"] = remove_labels

        if not payload:
            raise GmailError("Must specify at least one label to add or remove")

        url = f"{self.BASE_URL}/messages/{message_id}/modify"
        try:
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise GmailError(f"Modify labels failed: {resp.status} - {error}")
                data = await resp.json()
                return self._normalize_message(data)
        except GmailError:
            raise
        except Exception as e:
            raise GmailError(f"Failed to modify labels for {message_id}: {e}") from e

    @staticmethod
    def _normalize_message(raw_message: dict[str, Any]) -> dict[str, Any]:
        """Normalize Gmail API message response."""
        headers = {}
        header_list = raw_message.get("payload", {}).get("headers", [])
        for h in header_list:
            headers[h.get("name", "").lower()] = h.get("value", "")

        # Extract body
        body_text = ""
        payload = raw_message.get("payload", {})
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        else:
            # Handle multipart
            parts = payload.get("parts", [])
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        break

        # Extract attachments
        attachments = []
        for part in payload.get("parts", []):
            if part.get("filename"):
                attachments.append(
                    {
                        "filename": part.get("filename"),
                        "mimeType": part.get("mimeType"),
                        "size": part.get("size"),
                        "partId": part.get("partId"),
                    }
                )

        return {
            "messageId": raw_message.get("id"),
            "threadId": raw_message.get("threadId"),
            "labels": raw_message.get("labelIds", []),
            "snippet": raw_message.get("snippet", ""),
            "headers": headers,
            "body": body_text[:2000] if body_text else "",  # Limit body size
            "internalDate": raw_message.get("internalDate"),
            "attachmentCount": len(attachments),
            "attachments": attachments,
        }
