"""Custom exceptions for the social platform."""


class SocialPlatformException(Exception):
    """Base exception for social platform errors."""

    pass


class UserNotFoundError(SocialPlatformException):
    """Raised when a user is not found."""

    pass


class UserAlreadyExistsError(SocialPlatformException):
    """Raised when attempting to create a user that already exists."""

    pass


class InvalidUsernameError(SocialPlatformException):
    """Raised when username is invalid."""

    pass


class InvalidEmailError(SocialPlatformException):
    """Raised when email is invalid."""

    pass


class InvalidPasswordError(SocialPlatformException):
    """Raised when password doesn't meet requirements."""

    pass


class AuthenticationError(SocialPlatformException):
    """Raised when authentication fails."""

    pass


class AuthorizationError(SocialPlatformException):
    """Raised when user lacks required permissions."""

    pass


class PostNotFoundError(SocialPlatformException):
    """Raised when a post is not found."""

    pass


class CommentNotFoundError(SocialPlatformException):
    """Raised when a comment is not found."""

    pass


class ConversationNotFoundError(SocialPlatformException):
    """Raised when a conversation is not found."""

    pass


class MessageNotFoundError(SocialPlatformException):
    """Raised when a message is not found."""

    pass


class NotificationNotFoundError(SocialPlatformException):
    """Raised when a notification is not found."""

    pass


class InvalidOperationError(SocialPlatformException):
    """Raised when operation is invalid."""

    pass


class BlockedUserError(SocialPlatformException):
    """Raised when attempting to interact with a blocked user."""

    pass


class PrivacyViolationError(SocialPlatformException):
    """Raised when privacy settings prevent the operation."""

    pass


class AccountDeactivatedError(SocialPlatformException):
    """Raised when attempting to use a deactivated account."""

    pass


class AccountSuspendedError(SocialPlatformException):
    """Raised when account is suspended."""

    pass


class RateLimitExceededError(SocialPlatformException):
    """Raised when rate limit is exceeded."""

    pass


class ContentTooLongError(SocialPlatformException):
    """Raised when content exceeds length limits."""

    pass


class InvalidMediaError(SocialPlatformException):
    """Raised when media is invalid."""

    pass


class ModerationError(SocialPlatformException):
    """Raised when content violates moderation policies."""

    pass


class SpamDetectedError(SocialPlatformException):
    """Raised when spam is detected."""

    pass


class ToxicContentError(SocialPlatformException):
    """Raised when toxic content is detected."""

    pass


class DuplicateActionError(SocialPlatformException):
    """Raised when attempting duplicate action."""

    pass


class InvalidReactionError(SocialPlatformException):
    """Raised when reaction type is invalid."""

    pass


class MaxRetryError(SocialPlatformException):
    """Raised when max retries exceeded."""

    pass
