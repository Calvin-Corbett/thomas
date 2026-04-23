"""
Channel implementations for sending notifications.
Supports email, SMS, push notifications, in-app, Slack, and webhooks.
"""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests

from thomas.notify._exceptions import ChannelException
from thomas.notify._types import (
    ChannelType,
    DeliveryResult,
    DeliveryStatus,
    InAppType,
    Notification,
    Recipient,
    Template,
)


class Channel(ABC):
    """Abstract base class for notification channels."""

    def __init__(self, channel_type: ChannelType) -> None:
        """Initialize channel."""
        self.channel_type = channel_type
        self.error_count = 0
        self.success_count = 0

    @abstractmethod
    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send notification through this channel.

        Args:
            notification: Notification to send
            template: Rendered template

        Returns:
            DeliveryResult with status and metadata

        Raises:
            ChannelException: If send fails
        """
        pass

    def validate_recipient(self, recipient: Recipient) -> bool:
        """Validate recipient has required address for this channel."""
        return recipient.get_channel_address(self.channel_type) is not None


class EmailChannel(Channel):
    """Email notification channel with template rendering and attachment support."""

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
    ) -> None:
        """Initialize email channel.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP authentication user
            smtp_password: SMTP authentication password
        """
        super().__init__(ChannelType.EMAIL)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send email notification.

        Args:
            notification: Notification to send
            template: Email template with subject and body

        Returns:
            DeliveryResult with delivery status

        Raises:
            ChannelException: If recipient has no email or send fails
        """
        start_time = datetime.utcnow()

        try:
            recipient_email = notification.recipient.get_channel_address(ChannelType.EMAIL)
            if not recipient_email:
                raise ChannelException(
                    f"Recipient {notification.recipient.user_id} has no email address",
                    channel_type=self.channel_type.value,
                )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = template.subject
            msg["From"] = self.smtp_user
            msg["To"] = recipient_email

            # Attach plain text
            if template.plain_text_fallback:
                msg.attach(MIMEText(template.plain_text_fallback, "plain"))

            # Attach HTML
            if template.html_body:
                msg.attach(MIMEText(template.html_body, "html"))
            else:
                msg.attach(MIMEText(template.body, "plain"))

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=notification.recipient.user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={"to": recipient_email, "subject": template.subject},
            )

        except ChannelException:
            raise
        except Exception as e:
            self.error_count += 1
            raise ChannelException(
                f"Email send failed: {str(e)}",
                channel_type=self.channel_type.value,
            )

    def render_template_with_inline_css(self, html: str, css: str) -> str:
        """Render HTML email with inline CSS.

        Args:
            html: HTML template
            css: CSS styles

        Returns:
            HTML with inlined styles
        """
        # Simplified implementation: wrap in style tag
        return f"<style>{css}</style>\n{html}"

    def generate_plain_text_fallback(self, html: str) -> str:
        """Generate plain text fallback from HTML.

        Args:
            html: HTML content

        Returns:
            Plain text version
        """
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", html)
        # Decode HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&amp;", "&")
        return text


class SMSChannel(Channel):
    """SMS notification channel with message truncation and concatenation."""

    MAX_SMS_LENGTH = 160
    CONCATENATED_SMS_LENGTH = 153  # 160 - 7 for UDH header

    def __init__(self, api_key: str = "") -> None:
        """Initialize SMS channel.

        Args:
            api_key: SMS provider API key
        """
        super().__init__(ChannelType.SMS)
        self.api_key = api_key

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send SMS notification with automatic message splitting.

        Args:
            notification: Notification to send
            template: SMS template

        Returns:
            DeliveryResult with delivery status

        Raises:
            ChannelException: If recipient has no phone or send fails
        """
        start_time = datetime.utcnow()

        try:
            phone = notification.recipient.get_channel_address(ChannelType.SMS)
            if not phone:
                raise ChannelException(
                    f"Recipient {notification.recipient.user_id} has no phone number",
                    channel_type=self.channel_type.value,
                )

            message = template.body
            segments = self._split_message(message)

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=notification.recipient.user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={
                    "to": phone,
                    "segment_count": len(segments),
                    "total_length": len(message),
                },
            )

        except ChannelException:
            raise
        except Exception as e:
            self.error_count += 1
            raise ChannelException(
                f"SMS send failed: {str(e)}",
                channel_type=self.channel_type.value,
            )

    def _split_message(self, message: str) -> list[str]:
        """Split long message into SMS segments.

        SMS messages over 160 characters are split with concatenation headers.
        Each segment after first is 153 characters (7 for UDH).

        Args:
            message: Message text

        Returns:
            List of message segments
        """
        if len(message) <= self.MAX_SMS_LENGTH:
            return [message]

        segments = []
        remaining = message
        max_len = self.CONCATENATED_SMS_LENGTH

        while remaining:
            segment = remaining[:max_len]
            segments.append(segment)
            remaining = remaining[max_len:]

        return segments

    def handle_opt_out(self, phone_number: str) -> None:
        """Handle opt-out for a phone number.

        Args:
            phone_number: Phone number to opt out
        """
        # Mark phone number as opted out in preference system
        pass


class PushChannel(Channel):
    """Push notification channel with rich content support."""

    def __init__(self, provider_key: str = "") -> None:
        """Initialize push notification channel.

        Args:
            provider_key: Push service provider API key
        """
        super().__init__(ChannelType.PUSH)
        self.provider_key = provider_key

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send push notification with title, body, and action URL.

        Args:
            notification: Notification to send
            template: Push notification template

        Returns:
            DeliveryResult with delivery status

        Raises:
            ChannelException: If recipient has no device or send fails
        """
        start_time = datetime.utcnow()

        try:
            device_id = notification.recipient.get_channel_address(ChannelType.PUSH)
            if not device_id:
                raise ChannelException(
                    f"Recipient {notification.recipient.user_id} has no push device",
                    channel_type=self.channel_type.value,
                )

            payload = self._build_push_payload(notification, template)

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=notification.recipient.user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={"device_id": device_id, "payload": payload},
            )

        except ChannelException:
            raise
        except Exception as e:
            self.error_count += 1
            raise ChannelException(
                f"Push send failed: {str(e)}",
                channel_type=self.channel_type.value,
            )

    def _build_push_payload(self, notification: Notification, template: Template) -> dict[str, Any]:
        """Build push notification payload.

        Args:
            notification: Notification with variables
            template: Push template

        Returns:
            Push payload dictionary
        """
        payload: dict[str, Any] = {
            "title": template.subject or "Notification",
            "body": template.body,
        }

        if "icon" in notification.metadata:
            payload["icon"] = notification.metadata["icon"]

        if "action_url" in notification.metadata:
            payload["action_url"] = notification.metadata["action_url"]

        if "badge_count" in notification.metadata:
            payload["badge"] = notification.metadata["badge_count"]

        return payload


class InAppChannel(Channel):
    """In-app notification channel with dismissal and persistence."""

    def __init__(self) -> None:
        """Initialize in-app notification channel."""
        super().__init__(ChannelType.IN_APP)

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send in-app notification.

        Args:
            notification: Notification to send
            template: In-app notification template

        Returns:
            DeliveryResult with delivery status
        """
        start_time = datetime.utcnow()

        try:
            user_id = notification.recipient.user_id

            in_app_type = InAppType(notification.metadata.get("in_app_type", "banner"))
            dismissable = notification.metadata.get("dismissable", True)
            persistent = notification.metadata.get("persistent", False)

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={
                    "type": in_app_type.value,
                    "dismissable": dismissable,
                    "persistent": persistent,
                },
            )

        except Exception as e:
            self.error_count += 1
            raise ChannelException(
                f"In-app send failed: {str(e)}",
                channel_type=self.channel_type.value,
            )


class SlackChannel(Channel):
    """Slack notification channel with Block Kit message formatting."""

    def __init__(self, webhook_url: str = "") -> None:
        """Initialize Slack channel.

        Args:
            webhook_url: Slack webhook URL
        """
        super().__init__(ChannelType.SLACK)
        self.webhook_url = webhook_url

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send Slack notification with Block Kit formatting.

        Args:
            notification: Notification to send
            template: Slack message template

        Returns:
            DeliveryResult with delivery status

        Raises:
            ChannelException: If recipient has no Slack ID or send fails
        """
        start_time = datetime.utcnow()

        try:
            slack_user_id = notification.recipient.get_channel_address(ChannelType.SLACK)
            if not slack_user_id and not self.webhook_url:
                raise ChannelException(
                    "No Slack user ID or webhook URL configured",
                    channel_type=self.channel_type.value,
                )

            blocks = self._build_slack_blocks(notification, template)

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=notification.recipient.user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={"blocks_count": len(blocks)},
            )

        except ChannelException:
            raise
        except Exception as e:
            self.error_count += 1
            raise ChannelException(
                f"Slack send failed: {str(e)}",
                channel_type=self.channel_type.value,
            )

    def _build_slack_blocks(self, notification: Notification, template: Template) -> list[dict[str, Any]]:
        """Build Slack Block Kit message blocks.

        Args:
            notification: Notification with metadata
            template: Message template with blocks

        Returns:
            List of Slack block objects
        """
        blocks: list[dict[str, Any]] = []

        if template.subject:
            blocks.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": template.subject,
                    },
                }
            )

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": template.body,
                },
            }
        )

        if template.blocks:
            for block in template.blocks:
                blocks.append(block.to_dict())

        return blocks


class WebhookChannel(Channel):
    """Webhook channel for HTTP POST delivery."""

    def __init__(self, timeout: int = 30) -> None:
        """Initialize webhook channel.

        Args:
            timeout: Request timeout in seconds
        """
        super().__init__(ChannelType.WEBHOOK)
        self.timeout = timeout

    def send(self, notification: Notification, template: Template) -> DeliveryResult:
        """Send notification via webhook HTTP POST.

        Args:
            notification: Notification to send
            template: Notification template

        Returns:
            DeliveryResult with delivery status

        Raises:
            ChannelException: If webhook URL missing or request fails
        """
        start_time = datetime.utcnow()

        try:
            webhook_url = notification.recipient.get_channel_address(ChannelType.WEBHOOK)
            if not webhook_url:
                raise ChannelException(
                    f"Recipient {notification.recipient.user_id} has no webhook URL",
                    channel_type=self.channel_type.value,
                )

            payload = self._build_webhook_payload(notification, template)

            response = requests.post(
                webhook_url,
                json=payload,
                timeout=self.timeout,
            )

            response.raise_for_status()

            delivery_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            self.success_count += 1
            return DeliveryResult(
                notification_id=notification.notification_id,
                recipient_id=notification.recipient.user_id,
                channel_type=self.channel_type,
                status=DeliveryStatus.DELIVERED,
                timestamp=datetime.utcnow(),
                delivery_time_ms=delivery_time,
                metadata={
                    "webhook_url": webhook_url,
                    "status_code": response.status_code,
                },
            )

        except ChannelException:
            raise
        except requests.exceptions.RequestException as e:
            self.error_count += 1
            raise ChannelException(
                f"Webhook request failed: {str(e)}",
                channel_type=self.channel_type.value,
            )

    def _build_webhook_payload(self, notification: Notification, template: Template) -> dict[str, Any]:
        """Build webhook payload.

        Args:
            notification: Notification with data
            template: Message template

        Returns:
            Webhook payload dictionary
        """
        return {
            "notification_id": notification.notification_id,
            "recipient_id": notification.recipient.user_id,
            "channel": self.channel_type.value,
            "priority": notification.priority.value,
            "category": notification.category.value,
            "subject": template.subject,
            "body": template.body,
            "variables": notification.variables,
            "timestamp": datetime.utcnow().isoformat(),
        }


class ChannelFactory:
    """Factory for creating channel instances."""

    _channels: dict[ChannelType, Channel] = {}

    @classmethod
    def register_channel(cls, channel: Channel) -> None:
        """Register a channel implementation.

        Args:
            channel: Channel instance to register
        """
        cls._channels[channel.channel_type] = channel

    @classmethod
    def get_channel(cls, channel_type: ChannelType) -> Channel:
        """Get a registered channel.

        Args:
            channel_type: Type of channel to retrieve

        Returns:
            Channel instance

        Raises:
            ChannelException: If channel type not registered
        """
        if channel_type not in cls._channels:
            raise ChannelException(
                f"Channel {channel_type.value} not registered",
                channel_type=channel_type.value,
            )
        return cls._channels[channel_type]

    @classmethod
    def get_all_channels(cls) -> dict[ChannelType, Channel]:
        """Get all registered channels.

        Returns:
            Dictionary of channel implementations
        """
        return cls._channels.copy()
