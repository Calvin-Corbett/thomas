"""Exception types for webhook management system."""


class WebhookException(Exception):
    """Base exception for webhook-related errors."""

    pass


class InvalidWebhookURL(WebhookException):
    """Raised when a webhook URL is invalid or unreachable."""

    def __init__(self, url: str, reason: str = ""):
        """Initialize with URL and optional reason."""
        msg = f"Invalid webhook URL: {url}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)
        self.url = url
        self.reason = reason


class DeliveryError(WebhookException):
    """Raised when webhook delivery fails."""

    def __init__(self, delivery_id: str, message: str, status_code: int = None):
        """Initialize delivery error."""
        super().__init__(f"Delivery {delivery_id} failed: {message}")
        self.delivery_id = delivery_id
        self.message = message
        self.status_code = status_code


class RetryExhausted(WebhookException):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, delivery_id: str, attempts: int):
        """Initialize retry exhausted error."""
        super().__init__(f"Delivery {delivery_id} exhausted after {attempts} attempts")
        self.delivery_id = delivery_id
        self.attempts = attempts


class SubscriptionNotFound(WebhookException):
    """Raised when a subscription cannot be found."""

    def __init__(self, subscription_id: str):
        """Initialize subscription not found error."""
        super().__init__(f"Subscription not found: {subscription_id}")
        self.subscription_id = subscription_id


class EndpointNotFound(WebhookException):
    """Raised when an endpoint cannot be found."""

    def __init__(self, endpoint_id: str):
        """Initialize endpoint not found error."""
        super().__init__(f"Endpoint not found: {endpoint_id}")
        self.endpoint_id = endpoint_id


class SignatureVerificationError(WebhookException):
    """Raised when webhook signature verification fails."""

    def __init__(self, reason: str = ""):
        """Initialize signature verification error."""
        msg = "Signature verification failed"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.reason = reason


class FilterExpressionError(WebhookException):
    """Raised when filter expression is invalid."""

    def __init__(self, expression: str, reason: str = ""):
        """Initialize filter expression error."""
        msg = f"Invalid filter expression: {expression}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)
        self.expression = expression
        self.reason = reason


class RateLimitExceeded(WebhookException):
    """Raised when rate limit is exceeded."""

    def __init__(self, endpoint_id: str, retry_after: int = None):
        """Initialize rate limit exceeded error."""
        msg = f"Rate limit exceeded for endpoint: {endpoint_id}"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg)
        self.endpoint_id = endpoint_id
        self.retry_after = retry_after
