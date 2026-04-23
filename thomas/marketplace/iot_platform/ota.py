"""
Over-the-air firmware update management.

Handles firmware updates, rollout strategies, version management,
update validation, device status tracking, and rollback.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime
from uuid import UUID, uuid4

from thomas.marketplace.iot_platform._exceptions import OTAError
from thomas.marketplace.iot_platform._types import (
    OTAUpdate,
    RolloutStrategy,
    UpdateStatus,
)


class OTAManager:
    """
    Manages firmware over-the-air update campaigns.

    Provides update creation, rollout strategies, validation,
    device tracking, and rollback capability.
    """

    def __init__(self) -> None:
        """Initialize the OTA manager."""
        self._updates: dict[UUID, OTAUpdate] = {}
        self._device_update_state: dict[UUID, dict[str, any]] = {}
        self._update_history: list[OTAUpdate] = []
        self._lock = threading.RLock()

    def create_update(
        self,
        firmware_version: str,
        firmware_url: str,
        checksum: str,
        file_size: int,
        rollout_strategy: RolloutStrategy,
        target_groups: list[str] | None = None,
        target_device_ids: list[UUID] | None = None,
    ) -> OTAUpdate:
        """
        Create a firmware update campaign.

        Args:
            firmware_version: Target firmware version.
            firmware_url: URL to download firmware from.
            checksum: SHA256 checksum for validation.
            file_size: Firmware file size in bytes.
            rollout_strategy: Update rollout strategy.
            target_groups: Device groups to target.
            target_device_ids: Specific device IDs to target.

        Returns:
            Created OTAUpdate instance.

        Raises:
            OTAError: If parameters are invalid.
        """
        if not firmware_version or len(firmware_version.strip()) == 0:
            raise OTAError("Firmware version cannot be empty")

        if not firmware_url or len(firmware_url.strip()) == 0:
            raise OTAError("Firmware URL cannot be empty")

        if not checksum or len(checksum) != 64:  # SHA256 hex length
            raise OTAError("Invalid checksum format")

        if file_size <= 0:
            raise OTAError("File size must be positive")

        with self._lock:
            update_id = uuid4()
            update = OTAUpdate(
                update_id=update_id,
                firmware_version=firmware_version,
                firmware_url=firmware_url,
                checksum=checksum,
                file_size=file_size,
                rollout_strategy=rollout_strategy,
                target_groups=target_groups or [],
                target_device_ids=target_device_ids or [],
            )

            self._updates[update_id] = update
            return update

    def get_update(self, update_id: UUID) -> OTAUpdate:
        """
        Get an update campaign by ID.

        Args:
            update_id: ID of update to retrieve.

        Returns:
            OTAUpdate instance.

        Raises:
            OTAError: If update not found.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")
            return self._updates[update_id]

    def start_update(self, update_id: UUID, target_devices: list[UUID]) -> OTAUpdate:
        """
        Start an update campaign with specific target devices.

        Args:
            update_id: ID of update to start.
            target_devices: Devices to update.

        Returns:
            Updated OTAUpdate instance.

        Raises:
            OTAError: If update not found or invalid.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")

            update = self._updates[update_id]

            if update.current_status != UpdateStatus.PENDING:
                raise OTAError("Update already started")

            update.current_status = UpdateStatus.IN_PROGRESS
            update.target_device_ids = target_devices

            # Initialize device tracking
            for device_id in target_devices:
                if device_id not in self._device_update_state:
                    self._device_update_state[device_id] = {}

                self._device_update_state[device_id][str(update_id)] = {
                    "status": UpdateStatus.PENDING,
                    "started_at": datetime.utcnow(),
                    "completed_at": None,
                }
                update.device_statuses[str(device_id)] = UpdateStatus.PENDING

            return update

    def _get_rollout_phase_targets(self, update: OTAUpdate, total_devices: int) -> list[UUID]:
        """Determine which devices to update in current rollout phase."""
        if update.rollout_strategy == RolloutStrategy.IMMEDIATE:
            return update.target_device_ids

        elif update.rollout_strategy == RolloutStrategy.CANARY:
            # 10% canary rollout
            canary_count = max(1, total_devices // 10)
            return update.target_device_ids[:canary_count]

        elif update.rollout_strategy == RolloutStrategy.STAGED:
            # Staged 25% at a time
            staged_count = max(1, total_devices // 4)
            return update.target_device_ids[:staged_count]

        return update.target_device_ids

    def update_device_status(
        self,
        update_id: UUID,
        device_id: UUID,
        status: UpdateStatus,
        completion_message: str | None = None,
    ) -> OTAUpdate:
        """
        Update firmware status for a specific device.

        Args:
            update_id: ID of update campaign.
            device_id: Device being updated.
            status: New update status.
            completion_message: Optional status message.

        Returns:
            Updated OTAUpdate instance.

        Raises:
            OTAError: If update or device not found.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")

            update = self._updates[update_id]

            if device_id not in [d for d in update.target_device_ids]:
                raise OTAError(f"Device {device_id} not in update targets")

            device_key = str(device_id)
            update.device_statuses[device_key] = status

            if device_id in self._device_update_state:
                if device_id not in self._device_update_state:
                    self._device_update_state[device_id] = {}

                self._device_update_state[device_id][str(update_id)] = {
                    "status": status,
                    "started_at": datetime.utcnow(),
                    "completed_at": datetime.utcnow()
                    if status in (UpdateStatus.COMPLETED, UpdateStatus.FAILED, UpdateStatus.ROLLED_BACK)
                    else None,
                    "message": completion_message,
                }

            # Update overall progress
            self._update_progress(update)

            return update

    def _update_progress(self, update: OTAUpdate) -> None:
        """Calculate and update overall update progress."""
        if not update.target_device_ids:
            update.progress_percentage = 0
            return

        completed = sum(
            1 for status in update.device_statuses.values() if status in (UpdateStatus.COMPLETED, UpdateStatus.FAILED)
        )

        update.progress_percentage = completed * 100 // len(update.target_device_ids)

        # Mark as completed if all devices finished
        if completed == len(update.target_device_ids):
            failed = sum(1 for status in update.device_statuses.values() if status == UpdateStatus.FAILED)

            if failed == 0:
                update.current_status = UpdateStatus.COMPLETED
            else:
                # Partial success is still considered in progress
                update.current_status = UpdateStatus.IN_PROGRESS

    def validate_firmware(self, firmware_data: bytes, expected_checksum: str) -> bool:
        """
        Validate firmware file integrity.

        Args:
            firmware_data: Firmware file content.
            expected_checksum: Expected SHA256 checksum.

        Returns:
            True if firmware is valid.
        """
        calculated = hashlib.sha256(firmware_data).hexdigest()
        return calculated.lower() == expected_checksum.lower()

    def check_compatibility(
        self,
        device_current_version: str,
        target_version: str,
        device_type: str,
    ) -> bool:
        """
        Check firmware compatibility for device.

        Args:
            device_current_version: Current device firmware version.
            target_version: Target firmware version.
            device_type: Type of device.

        Returns:
            True if update is compatible.
        """
        # Simple version compatibility check
        # In production, would use more sophisticated version scheme
        current_parts = device_current_version.split(".")
        target_parts = target_version.split(".")

        try:
            current_major = int(current_parts[0])
            target_major = int(target_parts[0])

            # Major version must match or be incrementing
            return target_major >= current_major
        except (ValueError, IndexError):
            return True  # Default to compatible

    def rollback_update(self, update_id: UUID, device_id: UUID, previous_version: str) -> OTAUpdate:
        """
        Rollback firmware update for a device.

        Args:
            update_id: ID of update campaign.
            device_id: Device to rollback.
            previous_version: Version to rollback to.

        Returns:
            Updated OTAUpdate instance.

        Raises:
            OTAError: If update not found.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")

            update = self._updates[update_id]
            device_key = str(device_id)

            if device_key in update.device_statuses:
                update.device_statuses[device_key] = UpdateStatus.ROLLED_BACK

            self._update_progress(update)
            return update

    def list_updates(self) -> list[OTAUpdate]:
        """List all update campaigns."""
        with self._lock:
            return list(self._updates.values())

    def get_update_history(self, device_id: UUID) -> list[dict[str, any]]:
        """
        Get firmware update history for a device.

        Args:
            device_id: Device to get history for.

        Returns:
            List of update history entries.
        """
        with self._lock:
            if device_id not in self._device_update_state:
                return []

            return list(self._device_update_state[device_id].values())

    def get_device_update_status(self, update_id: UUID, device_id: UUID) -> UpdateStatus | None:
        """
        Get update status for a specific device.

        Args:
            update_id: Update campaign ID.
            device_id: Device ID.

        Returns:
            UpdateStatus or None if not found.
        """
        with self._lock:
            if update_id not in self._updates:
                return None

            update = self._updates[update_id]
            device_key = str(device_id)
            return update.device_statuses.get(device_key)

    def cancel_update(self, update_id: UUID) -> OTAUpdate:
        """
        Cancel an update campaign.

        Args:
            update_id: Update to cancel.

        Returns:
            Updated OTAUpdate instance.

        Raises:
            OTAError: If update not found.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")

            update = self._updates[update_id]

            if update.current_status == UpdateStatus.PENDING:
                update.current_status = UpdateStatus.FAILED
            elif update.current_status == UpdateStatus.IN_PROGRESS:
                # Mark incomplete devices as failed
                for device_key, status in update.device_statuses.items():
                    if status == UpdateStatus.PENDING:
                        update.device_statuses[device_key] = UpdateStatus.FAILED

            return update

    def get_rollout_status(self, update_id: UUID) -> dict[str, any]:
        """
        Get detailed rollout status for an update.

        Args:
            update_id: Update ID.

        Returns:
            Dictionary with rollout statistics.

        Raises:
            OTAError: If update not found.
        """
        with self._lock:
            if update_id not in self._updates:
                raise OTAError(f"Update {update_id} not found")

            update = self._updates[update_id]

            pending = sum(1 for s in update.device_statuses.values() if s == UpdateStatus.PENDING)
            in_progress = sum(1 for s in update.device_statuses.values() if s == UpdateStatus.IN_PROGRESS)
            completed = sum(1 for s in update.device_statuses.values() if s == UpdateStatus.COMPLETED)
            failed = sum(1 for s in update.device_statuses.values() if s == UpdateStatus.FAILED)

            return {
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
                "failed": failed,
                "progress_percentage": update.progress_percentage,
                "total_devices": len(update.target_device_ids),
            }
