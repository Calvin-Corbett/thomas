"""
Device command management and execution.

Handles command queuing, status tracking, execution, timeouts,
batch operations, and command history.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from uuid import UUID, uuid4

from thomas.iot_platform._exceptions import CommandError
from thomas.iot_platform._types import Command, CommandStatus


class CommandManager:
    """
    Manages device command lifecycle and execution.

    Provides command queuing, status tracking, timeout handling,
    batch operations, and execution history.
    """

    def __init__(self, default_timeout_seconds: int = 60) -> None:
        """
        Initialize command manager.

        Args:
            default_timeout_seconds: Default command timeout.
        """
        self._commands: dict[UUID, Command] = {}
        self._device_queues: dict[UUID, deque] = {}
        self._command_history: list[Command] = []
        self._default_timeout = default_timeout_seconds
        self._lock = threading.RLock()

    def send_command(
        self,
        target_device_id: UUID,
        action: str,
        parameters: dict[str, any] | None = None,
        timeout_seconds: int | None = None,
    ) -> Command:
        """
        Send a command to a device.

        Args:
            target_device_id: ID of target device.
            action: Command action name.
            parameters: Command parameters.
            timeout_seconds: Command timeout override.

        Returns:
            Created Command instance.

        Raises:
            CommandError: If parameters are invalid.
        """
        if not action or len(action.strip()) == 0:
            raise CommandError("Action name cannot be empty")

        with self._lock:
            command_id = uuid4()
            timeout = timeout_seconds or self._default_timeout

            command = Command(
                command_id=command_id,
                target_device_id=target_device_id,
                action=action,
                parameters=parameters or {},
                status=CommandStatus.PENDING,
                created_at=datetime.utcnow(),
                timeout_seconds=timeout,
            )

            self._commands[command_id] = command

            # Add to device queue
            if target_device_id not in self._device_queues:
                self._device_queues[target_device_id] = deque()

            self._device_queues[target_device_id].append(command_id)

            return command

    def get_command(self, command_id: UUID) -> Command:
        """
        Get a command by ID.

        Args:
            command_id: ID of command to retrieve.

        Returns:
            Command instance.

        Raises:
            CommandError: If command not found.
        """
        with self._lock:
            if command_id not in self._commands:
                raise CommandError(f"Command {command_id} not found")
            return self._commands[command_id]

    def update_command_status(
        self,
        command_id: UUID,
        status: CommandStatus,
        result: dict[str, any] | None = None,
    ) -> Command:
        """
        Update command execution status.

        Args:
            command_id: ID of command to update.
            status: New status.
            result: Optional execution result.

        Returns:
            Updated Command instance.

        Raises:
            CommandError: If command not found.
        """
        with self._lock:
            if command_id not in self._commands:
                raise CommandError(f"Command {command_id} not found")

            command = self._commands[command_id]

            if status == CommandStatus.SENT:
                command.sent_at = datetime.utcnow()

            elif status in (CommandStatus.COMPLETED, CommandStatus.FAILED):
                command.completed_at = datetime.utcnow()
                if result:
                    command.result = result

            command.status = status
            return command

    def get_device_queue(self, device_id: UUID) -> list[UUID]:
        """
        Get pending command queue for a device.

        Args:
            device_id: Device to get queue for.

        Returns:
            List of command IDs in queue order.
        """
        with self._lock:
            if device_id not in self._device_queues:
                return []

            return list(self._device_queues[device_id])

    def dequeue_command(self, device_id: UUID) -> Command | None:
        """
        Get next pending command for device.

        Args:
            device_id: Device to get command for.

        Returns:
            Next pending Command or None if queue empty.
        """
        with self._lock:
            if device_id not in self._device_queues:
                return None

            queue = self._device_queues[device_id]

            while queue:
                command_id = queue[0]
                command = self._commands.get(command_id)

                if command and command.status == CommandStatus.PENDING:
                    return command

                queue.popleft()

            return None

    def acknowledge_command(self, command_id: UUID) -> Command:
        """
        Mark command as acknowledged by device.

        Args:
            command_id: ID of command to acknowledge.

        Returns:
            Updated Command instance.

        Raises:
            CommandError: If command not found.
        """
        return self.update_command_status(command_id, CommandStatus.ACKNOWLEDGED)

    def complete_command(self, command_id: UUID, result: dict[str, any] | None = None) -> Command:
        """
        Mark command as completed.

        Args:
            command_id: ID of command to complete.
            result: Optional completion result.

        Returns:
            Updated Command instance.

        Raises:
            CommandError: If command not found.
        """
        return self.update_command_status(command_id, CommandStatus.COMPLETED, result)

    def fail_command(self, command_id: UUID, error_message: str, retry: bool = True) -> Command:
        """
        Mark command as failed.

        Args:
            command_id: ID of command that failed.
            error_message: Failure error message.
            retry: Whether to retry the command.

        Returns:
            Updated Command instance.

        Raises:
            CommandError: If command not found.
        """
        with self._lock:
            if command_id not in self._commands:
                raise CommandError(f"Command {command_id} not found")

            command = self._commands[command_id]

            if retry and command.retry_count < command.max_retries:
                command.retry_count += 1
                command.status = CommandStatus.PENDING
                command.sent_at = None
            else:
                command.status = CommandStatus.FAILED
                command.completed_at = datetime.utcnow()
                command.result = {"error": error_message}

            return command

    def check_timeouts(self) -> list[Command]:
        """
        Check for expired commands and mark as timeout.

        Returns:
            List of commands that timed out.
        """
        timed_out: list[Command] = []

        with self._lock:
            for command in self._commands.values():
                if command.status == CommandStatus.SENT and command.is_expired():
                    command.status = CommandStatus.TIMEOUT
                    command.completed_at = datetime.utcnow()
                    timed_out.append(command)

        return timed_out

    def send_batch_commands(
        self,
        device_ids: list[UUID],
        action: str,
        parameters: dict[str, any] | None = None,
    ) -> list[Command]:
        """
        Send same command to multiple devices.

        Args:
            device_ids: List of target device IDs.
            action: Command action.
            parameters: Command parameters.

        Returns:
            List of created commands.
        """
        commands: list[Command] = []

        for device_id in device_ids:
            try:
                cmd = self.send_command(device_id, action, parameters)
                commands.append(cmd)
            except CommandError:
                pass  # Skip failed commands

        return commands

    def get_command_history(
        self,
        device_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Command]:
        """
        Get command execution history.

        Args:
            device_id: Optional filter by device.
            limit: Maximum results to return.

        Returns:
            List of historical commands.
        """
        with self._lock:
            history = [
                c
                for c in self._commands.values()
                if c.status in (CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.TIMEOUT)
            ]

            if device_id:
                history = [c for c in history if c.target_device_id == device_id]

            history.sort(key=lambda c: c.created_at, reverse=True)
            return history[:limit]

    def get_device_command_stats(self, device_id: UUID) -> dict[str, int]:
        """
        Get command statistics for a device.

        Args:
            device_id: Device to get stats for.

        Returns:
            Dictionary with command status counts.
        """
        with self._lock:
            device_commands = [c for c in self._commands.values() if c.target_device_id == device_id]

            stats: dict[str, int] = {
                "pending": 0,
                "sent": 0,
                "acknowledged": 0,
                "completed": 0,
                "failed": 0,
                "timeout": 0,
            }

            for cmd in device_commands:
                key = cmd.status.value
                if key in stats:
                    stats[key] += 1

            return stats

    def clear_device_queue(self, device_id: UUID) -> int:
        """
        Clear all pending commands for a device.

        Args:
            device_id: Device to clear queue for.

        Returns:
            Number of commands cleared.
        """
        with self._lock:
            if device_id not in self._device_queues:
                return 0

            queue = self._device_queues[device_id]
            cleared = 0

            while queue:
                command_id = queue.popleft()
                command = self._commands.get(command_id)

                if command and command.status == CommandStatus.PENDING:
                    command.status = CommandStatus.FAILED
                    command.completed_at = datetime.utcnow()
                    cleared += 1

            return cleared

    def get_total_command_count(self) -> int:
        """Get total number of commands."""
        with self._lock:
            return len(self._commands)

    def get_pending_command_count(self) -> int:
        """Get number of pending commands."""
        with self._lock:
            return sum(1 for c in self._commands.values() if c.status == CommandStatus.PENDING)
