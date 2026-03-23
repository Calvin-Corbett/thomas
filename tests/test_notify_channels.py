"""
Tests for notification channel implementations.
"""

import pytest

from thomas.notify._exceptions import ChannelException
from thomas.notify._types import (
    ChannelType,
    DeliveryStatus,
    Notification,
    Recipient,
    Template,
)
from thomas.notify.channels import (
    ChannelFactory,
    EmailChannel,
    InAppChannel,
    PushChannel,
    SlackChannel,
    SMSChannel,
    WebhookChannel,
)


class TestEmailChannel:
    """Tests for email channel."""

    def test_send_email_success(self) -> None:
        """Test successful email send."""
        channel = EmailChannel(
            smtp_host="localhost",
            smtp_port=587,
            smtp_user="test@example.com",
        )

        recipient = Recipient(
            user_id="user1",
            email="recipient@example.com",
        )

        template = Template(
            template_id="template1",
            name="Test Template",
            channel_type=ChannelType.EMAIL,
            subject="Test Subject",
            body="Test Body",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.EMAIL,
        )

        result = channel.send(notification, template)

        assert result.status == DeliveryStatus.DELIVERED
        assert result.notification_id == notification.notification_id
        assert result.channel_type == ChannelType.EMAIL

    def test_send_email_without_address(self) -> None:
        """Test email send fails without address."""
        channel = EmailChannel()

        recipient = Recipient(user_id="user1")

        template = Template(
            template_id="template1",
            name="Test Template",
            channel_type=ChannelType.EMAIL,
            subject="Subject",
            body="Body",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.EMAIL,
        )

        with pytest.raises(ChannelException):
            channel.send(notification, template)

    def test_generate_plain_text_fallback(self) -> None:
        """Test HTML to plain text conversion."""
        channel = EmailChannel()

        html = "<p>Hello <b>World</b></p>"
        text = channel.generate_plain_text_fallback(html)

        assert "Hello" in text
        assert "<" not in text


class TestSMSChannel:
    """Tests for SMS channel."""

    def test_send_sms_success(self) -> None:
        """Test successful SMS send."""
        channel = SMSChannel(api_key="test_key")

        recipient = Recipient(
            user_id="user1",
            phone_number="+1234567890",
        )

        template = Template(
            template_id="template1",
            name="SMS Template",
            channel_type=ChannelType.SMS,
            body="Test SMS message",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.SMS,
        )

        result = channel.send(notification, template)

        assert result.status == DeliveryStatus.DELIVERED

    def test_sms_message_splitting(self) -> None:
        """Test long SMS message splitting."""
        channel = SMSChannel()

        long_message = "a" * 200

        segments = channel._split_message(long_message)

        assert len(segments) > 1
        assert all(len(s) <= 153 for s in segments)

    def test_sms_short_message_no_split(self) -> None:
        """Test short SMS not split."""
        channel = SMSChannel()

        short_message = "Hello World"

        segments = channel._split_message(short_message)

        assert len(segments) == 1
        assert segments[0] == short_message


class TestPushChannel:
    """Tests for push notification channel."""

    def test_send_push_success(self) -> None:
        """Test successful push send."""
        channel = PushChannel(provider_key="test_key")

        recipient = Recipient(
            user_id="user1",
            slack_user_id="device_123",
        )

        template = Template(
            template_id="template1",
            name="Push Template",
            channel_type=ChannelType.PUSH,
            subject="Push Title",
            body="Push Body",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.PUSH,
            metadata={
                "icon": "notification_icon",
                "action_url": "https://example.com",
                "badge_count": 5,
            },
        )

        result = channel.send(notification, template)

        assert result.status == DeliveryStatus.DELIVERED

    def test_build_push_payload(self) -> None:
        """Test push payload construction."""
        channel = PushChannel()

        recipient = Recipient(user_id="user1")
        template = Template(
            template_id="t1",
            name="Test",
            channel_type=ChannelType.PUSH,
            subject="Title",
            body="Body",
        )
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.PUSH,
            metadata={"icon": "icon.png"},
        )

        payload = channel._build_push_payload(notification, template)

        assert "title" in payload
        assert "body" in payload
        assert payload["icon"] == "icon.png"


class TestInAppChannel:
    """Tests for in-app notification channel."""

    def test_send_in_app_success(self) -> None:
        """Test successful in-app send."""
        channel = InAppChannel()

        recipient = Recipient(user_id="user1")

        template = Template(
            template_id="template1",
            name="InApp Template",
            channel_type=ChannelType.IN_APP,
            body="In-app message",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.IN_APP,
            metadata={
                "in_app_type": "banner",
                "dismissable": True,
                "persistent": False,
            },
        )

        result = channel.send(notification, template)

        assert result.status == DeliveryStatus.DELIVERED
        assert result.metadata["dismissable"] is True


class TestSlackChannel:
    """Tests for Slack channel."""

    def test_build_slack_blocks(self) -> None:
        """Test Slack Block Kit generation."""
        channel = SlackChannel()

        recipient = Recipient(
            user_id="user1",
            slack_user_id="U123456",
        )

        template = Template(
            template_id="template1",
            name="Slack Template",
            channel_type=ChannelType.SLACK,
            subject="Slack Header",
            body="Slack Message",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.SLACK,
        )

        blocks = channel._build_slack_blocks(notification, template)

        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"


class TestWebhookChannel:
    """Tests for webhook channel."""

    def test_build_webhook_payload(self) -> None:
        """Test webhook payload construction."""
        channel = WebhookChannel()

        recipient = Recipient(
            user_id="user1",
            webhook_url="https://example.com/webhook",
        )

        template = Template(
            template_id="template1",
            name="Webhook Template",
            channel_type=ChannelType.WEBHOOK,
            subject="Subject",
            body="Body",
        )

        notification = Notification(
            recipient=recipient,
            template_id="template1",
            channel_type=ChannelType.WEBHOOK,
        )

        payload = channel._build_webhook_payload(notification, template)

        assert "notification_id" in payload
        assert "recipient_id" in payload
        assert "subject" in payload
        assert payload["body"] == "Body"


class TestChannelFactory:
    """Tests for channel factory."""

    def test_register_and_get_channel(self) -> None:
        """Test channel registration and retrieval."""
        factory = ChannelFactory()

        channel = EmailChannel()
        factory.register_channel(channel)

        retrieved = factory.get_channel(ChannelType.EMAIL)

        assert retrieved is channel

    def test_get_unregistered_channel_raises(self) -> None:
        """Test getting unregistered channel raises exception."""
        factory = ChannelFactory()

        with pytest.raises(ChannelException):
            factory.get_channel(ChannelType.SLACK)
