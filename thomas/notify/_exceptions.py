"""
Exception classes for the notification system.
"""


class NotifyException(Exception):
    """Base exception for notification system."""

    def __init__(self, message: str, code: str = "NOTIFY_ERROR") -> None:
        """Initialize exception with message and error code."""
        self.message = message
        self.code = code
        super().__init__(message)


class ChannelException(NotifyException):
    """Raised when channel operation fails."""

    def __init__(self, message: str, channel_type: str = "", code: str = "CHANNEL_ERROR") -> None:
        """Initialize with channel type information."""
        self.channel_type = channel_type
        super().__init__(message, code)


class TemplateException(NotifyException):
    """Raised when template operation fails."""

    def __init__(self, message: str, template_id: str = "", code: str = "TEMPLATE_ERROR") -> None:
        """Initialize with template information."""
        self.template_id = template_id
        super().__init__(message, code)


class RoutingException(NotifyException):
    """Raised when routing decision fails."""

    def __init__(self, message: str, code: str = "ROUTING_ERROR") -> None:
        """Initialize routing exception."""
        super().__init__(message, code)


class PreferenceException(NotifyException):
    """Raised when preference operation fails."""

    def __init__(self, message: str, user_id: str = "", code: str = "PREFERENCE_ERROR") -> None:
        """Initialize with user information."""
        self.user_id = user_id
        super().__init__(message, code)


class DeliveryException(NotifyException):
    """Raised when delivery operation fails."""

    def __init__(self, message: str, notification_id: str = "", code: str = "DELIVERY_ERROR") -> None:
        """Initialize with notification information."""
        self.notification_id = notification_id
        super().__init__(message, code)
