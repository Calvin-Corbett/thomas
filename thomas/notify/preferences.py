"""
User notification preference management system.
Manages per-user preferences for categories and channels.
"""

from datetime import datetime

from thomas.notify._exceptions import PreferenceException
from thomas.notify._types import (
    Category,
    ChannelType,
    NotificationPreference,
)


class PreferenceManager:
    """Manages user notification preferences."""

    # Channels required for transactional notifications
    REQUIRED_TRANSACTIONAL_CHANNELS: set[ChannelType] = {
        ChannelType.EMAIL,
        ChannelType.SMS,
        ChannelType.PUSH,
    }

    # Default preference matrix: category -> channels enabled
    DEFAULT_PREFERENCES: dict[Category, dict[ChannelType, bool]] = {
        Category.MARKETING: {
            ChannelType.EMAIL: True,
            ChannelType.SMS: False,
            ChannelType.PUSH: True,
        },
        Category.TRANSACTIONAL: {
            ChannelType.EMAIL: True,
            ChannelType.SMS: True,
            ChannelType.PUSH: True,
        },
        Category.SYSTEM: {
            ChannelType.EMAIL: True,
            ChannelType.PUSH: True,
        },
        Category.SOCIAL: {
            ChannelType.PUSH: True,
            ChannelType.IN_APP: True,
        },
        Category.SECURITY: {
            ChannelType.EMAIL: True,
            ChannelType.SMS: True,
        },
        Category.UPDATES: {
            ChannelType.EMAIL: True,
            ChannelType.IN_APP: True,
        },
    }

    def __init__(self) -> None:
        """Initialize preference manager."""
        self.preferences: dict[str, NotificationPreference] = {}

    def get_user_preference(self, user_id: str) -> NotificationPreference:
        """Get user preference, creating default if needed.

        Args:
            user_id: User identifier

        Returns:
            User's notification preference
        """
        if user_id not in self.preferences:
            self.preferences[user_id] = self._create_default_preference(user_id)

        return self.preferences[user_id]

    def create_preference(
        self,
        user_id: str,
        preferences: dict[Category, dict[ChannelType, bool]] | None = None,
        preferred_channels: list[ChannelType] | None = None,
    ) -> NotificationPreference:
        """Create user preference.

        Args:
            user_id: User identifier
            preferences: Category/channel preferences
            preferred_channels: Preferred channel order

        Returns:
            Created preference

        Raises:
            PreferenceException: If preference already exists or invalid
        """
        if user_id in self.preferences:
            raise PreferenceException(
                f"Preference for user {user_id} already exists",
                user_id=user_id,
            )

        if preferences is None:
            preferences = self.DEFAULT_PREFERENCES.copy()

        # Validate transactional preferences
        if Category.TRANSACTIONAL in preferences:
            self._validate_transactional_preference(preferences[Category.TRANSACTIONAL])

        pref = NotificationPreference(
            user_id=user_id,
            preferences=preferences,
            preferred_channels=preferred_channels
            or [
                ChannelType.PUSH,
                ChannelType.EMAIL,
                ChannelType.SMS,
            ],
        )

        self.preferences[user_id] = pref
        return pref

    def update_category_preference(
        self,
        user_id: str,
        category: Category,
        channel_preferences: dict[ChannelType, bool],
    ) -> NotificationPreference:
        """Update preference for a category.

        Args:
            user_id: User identifier
            category: Category to update
            channel_preferences: Channel enable/disable settings

        Returns:
            Updated preference

        Raises:
            PreferenceException: If preference invalid
        """
        preference = self.get_user_preference(user_id)

        # Validate transactional
        if category == Category.TRANSACTIONAL:
            self._validate_transactional_preference(channel_preferences)

        preference.preferences[category] = channel_preferences
        preference.updated_at = datetime.utcnow()

        return preference

    def enable_channel_for_category(
        self,
        user_id: str,
        category: Category,
        channel: ChannelType,
    ) -> None:
        """Enable channel for a category.

        Args:
            user_id: User identifier
            category: Category
            channel: Channel to enable
        """
        preference = self.get_user_preference(user_id)

        if category not in preference.preferences:
            preference.preferences[category] = {}

        preference.preferences[category][channel] = True
        preference.updated_at = datetime.utcnow()

    def disable_channel_for_category(
        self,
        user_id: str,
        category: Category,
        channel: ChannelType,
    ) -> None:
        """Disable channel for a category.

        Args:
            user_id: User identifier
            category: Category
            channel: Channel to disable

        Raises:
            PreferenceException: If would violate transactional requirement
        """
        preference = self.get_user_preference(user_id)

        if category not in preference.preferences:
            preference.preferences[category] = {}

        # Validate transactional
        if category == Category.TRANSACTIONAL:
            updated = preference.preferences[category].copy()
            updated[channel] = False
            self._validate_transactional_preference(updated)

        preference.preferences[category][channel] = False
        preference.updated_at = datetime.utcnow()

    def set_global_opt_out(self, user_id: str, opt_out: bool) -> NotificationPreference:
        """Set global opt-out status.

        Args:
            user_id: User identifier
            opt_out: True to opt out globally

        Returns:
            Updated preference
        """
        preference = self.get_user_preference(user_id)
        preference.global_opt_out = opt_out
        preference.updated_at = datetime.utcnow()
        return preference

    def set_preferred_channels(
        self,
        user_id: str,
        channels: list[ChannelType],
    ) -> NotificationPreference:
        """Set preferred channel order.

        Args:
            user_id: User identifier
            channels: Ordered list of channels

        Returns:
            Updated preference
        """
        preference = self.get_user_preference(user_id)
        preference.preferred_channels = channels
        preference.updated_at = datetime.utcnow()
        return preference

    def enable_quiet_hours(
        self,
        user_id: str,
        start_time: str = "22:00",
        end_time: str = "08:00",
    ) -> NotificationPreference:
        """Enable quiet hours for user.

        Args:
            user_id: User identifier
            start_time: Start time (HH:MM)
            end_time: End time (HH:MM)

        Returns:
            Updated preference

        Raises:
            PreferenceException: If invalid time format
        """
        self._validate_time_format(start_time)
        self._validate_time_format(end_time)

        preference = self.get_user_preference(user_id)
        preference.quiet_hours_enabled = True
        preference.quiet_hours_start = start_time
        preference.quiet_hours_end = end_time
        preference.updated_at = datetime.utcnow()
        return preference

    def disable_quiet_hours(self, user_id: str) -> NotificationPreference:
        """Disable quiet hours for user.

        Args:
            user_id: User identifier

        Returns:
            Updated preference
        """
        preference = self.get_user_preference(user_id)
        preference.quiet_hours_enabled = False
        preference.updated_at = datetime.utcnow()
        return preference

    def set_frequency_cap(
        self,
        user_id: str,
        channel: ChannelType,
        max_per_day: int,
    ) -> NotificationPreference:
        """Set frequency cap for channel.

        Args:
            user_id: User identifier
            channel: Channel type
            max_per_day: Maximum notifications per day

        Returns:
            Updated preference

        Raises:
            PreferenceException: If max_per_day invalid
        """
        if max_per_day < 1:
            raise PreferenceException(
                "max_per_day must be at least 1",
                user_id=user_id,
            )

        preference = self.get_user_preference(user_id)
        preference.max_per_channel_per_day[channel] = max_per_day
        preference.updated_at = datetime.utcnow()
        return preference

    def migrate_preferences(
        self,
        user_id: str,
        new_categories: list[Category],
    ) -> NotificationPreference:
        """Migrate preferences when new categories added.

        Args:
            user_id: User identifier
            new_categories: New categories to add

        Returns:
            Updated preference
        """
        preference = self.get_user_preference(user_id)

        for category in new_categories:
            if category not in preference.preferences:
                preference.preferences[category] = self.DEFAULT_PREFERENCES.get(category, {}).copy()

        preference.updated_at = datetime.utcnow()
        return preference

    def validate_preference(self, preference: NotificationPreference) -> bool:
        """Validate preference configuration.

        Args:
            preference: Preference to validate

        Returns:
            True if valid

        Raises:
            PreferenceException: If invalid
        """
        if Category.TRANSACTIONAL in preference.preferences:
            self._validate_transactional_preference(preference.preferences[Category.TRANSACTIONAL])

        return True

    def get_preference_summary(self, user_id: str) -> dict[str, str]:
        """Get human-readable preference summary.

        Args:
            user_id: User identifier

        Returns:
            Preference summary
        """
        preference = self.get_user_preference(user_id)

        summary = {
            "global_opt_out": str(preference.global_opt_out),
            "quiet_hours_enabled": str(preference.quiet_hours_enabled),
            "quiet_hours": (f"{preference.quiet_hours_start}-{preference.quiet_hours_end}"),
        }

        for category, channels in preference.preferences.items():
            enabled = [ch.value for ch, enabled in channels.items() if enabled]
            summary[f"{category.value}_channels"] = ", ".join(enabled) if enabled else "none"

        return summary

    def _create_default_preference(self, user_id: str) -> NotificationPreference:
        """Create default preference for user.

        Args:
            user_id: User identifier

        Returns:
            Default preference
        """
        return NotificationPreference(
            user_id=user_id,
            preferences=self.DEFAULT_PREFERENCES.copy(),
            preferred_channels=[
                ChannelType.PUSH,
                ChannelType.EMAIL,
                ChannelType.SMS,
            ],
        )

    def _validate_transactional_preference(self, channel_preferences: dict[ChannelType, bool]) -> None:
        """Validate that transactional has at least one channel.

        Args:
            channel_preferences: Channel preferences

        Raises:
            PreferenceException: If no channels enabled
        """
        enabled_channels = [ch for ch, enabled in channel_preferences.items() if enabled]

        if not enabled_channels:
            raise PreferenceException(
                "Transactional notifications must have at least one enabled channel",
                code="TRANSACTIONAL_CHANNEL_REQUIRED",
            )

    def _validate_time_format(self, time_str: str) -> None:
        """Validate time format HH:MM.

        Args:
            time_str: Time string

        Raises:
            PreferenceException: If invalid format
        """
        try:
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError()

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError()

        except (ValueError, AttributeError):
            raise PreferenceException(f"Invalid time format: {time_str}. Expected HH:MM (24-hour format)")
