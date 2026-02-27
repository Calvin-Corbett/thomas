"""
Tests for command manager module.

Tests command creation, queuing, status tracking, timeouts,
batch operations, and execution history.
"""

from uuid import uuid4

import pytest

from thomas.iot_platform._exceptions import CommandError
from thomas.iot_platform._types import CommandStatus
from thomas.iot_platform.commands import CommandManager


class TestCommandManager:
    """Test command manager functionality."""

    @pytest.fixture
    def manager(self) -> CommandManager:
        """Create a command manager instance."""
        return CommandManager(default_timeout_seconds=60)

    @pytest.fixture
    def device_id(self) -> str:
        """Get a test device ID."""
        return uuid4()

    def test_send_command(self, manager: CommandManager, device_id) -> None:
        """Test sending a command."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
            parameters={"value": 25.0},
        )

        assert cmd.action == "set_temperature"
        assert cmd.status == CommandStatus.PENDING
        assert cmd.parameters["value"] == 25.0

    def test_send_command_empty_action(self, manager: CommandManager, device_id) -> None:
        """Test sending command with empty action fails."""
        with pytest.raises(CommandError):
            manager.send_command(
                target_device_id=device_id,
                action="",
            )

    def test_get_command(self, manager: CommandManager, device_id) -> None:
        """Test retrieving a command."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="query",
        )

        retrieved = manager.get_command(cmd.command_id)

        assert retrieved.command_id == cmd.command_id
        assert retrieved.action == "query"

    def test_get_nonexistent_command(self, manager: CommandManager) -> None:
        """Test retrieving nonexistent command fails."""
        fake_id = uuid4()

        with pytest.raises(CommandError):
            manager.get_command(fake_id)

    def test_update_command_status(self, manager: CommandManager, device_id) -> None:
        """Test updating command status."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )

        updated = manager.update_command_status(
            cmd.command_id,
            CommandStatus.SENT,
        )

        assert updated.status == CommandStatus.SENT
        assert updated.sent_at is not None

    def test_acknowledge_command(self, manager: CommandManager, device_id) -> None:
        """Test acknowledging a command."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )

        acked = manager.acknowledge_command(cmd.command_id)

        assert acked.status == CommandStatus.ACKNOWLEDGED

    def test_complete_command(self, manager: CommandManager, device_id) -> None:
        """Test completing a command."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="query",
        )

        result = {"temperature": 22.5, "humidity": 65.0}
        completed = manager.complete_command(cmd.command_id, result)

        assert completed.status == CommandStatus.COMPLETED
        assert completed.result == result
        assert completed.completed_at is not None

    def test_fail_command_with_retry(self, manager: CommandManager, device_id) -> None:
        """Test failing command with retry."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )

        manager.update_command_status(cmd.command_id, CommandStatus.SENT)

        failed = manager.fail_command(
            cmd.command_id,
            error_message="Device unreachable",
            retry=True,
        )

        assert failed.status == CommandStatus.PENDING
        assert failed.retry_count == 1

    def test_fail_command_max_retries(self, manager: CommandManager, device_id) -> None:
        """Test failing command after max retries."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )

        # Exhaust retries
        for _ in range(4):
            manager.update_command_status(cmd.command_id, CommandStatus.SENT)
            cmd = manager.fail_command(
                cmd.command_id,
                error_message="Device unreachable",
                retry=True,
            )

        assert cmd.status == CommandStatus.FAILED
        assert cmd.retry_count == 3

    def test_get_device_queue(self, manager: CommandManager, device_id) -> None:
        """Test getting device command queue."""
        cmd1 = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )
        cmd2 = manager.send_command(
            target_device_id=device_id,
            action="query",
        )

        queue = manager.get_device_queue(device_id)

        assert len(queue) == 2
        assert cmd1.command_id in queue
        assert cmd2.command_id in queue

    def test_dequeue_command(self, manager: CommandManager, device_id) -> None:
        """Test dequeueing next pending command."""
        cmd1 = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )
        cmd2 = manager.send_command(
            target_device_id=device_id,
            action="query",
        )

        next_cmd = manager.dequeue_command(device_id)

        assert next_cmd is not None
        assert next_cmd.command_id == cmd1.command_id

    def test_send_batch_commands(self, manager: CommandManager) -> None:
        """Test sending batch commands."""
        device_ids = [uuid4() for _ in range(3)]

        commands = manager.send_batch_commands(
            device_ids=device_ids,
            action="set_parameter",
            parameters={"param": "value"},
        )

        assert len(commands) == 3

    def test_check_timeouts(self, manager_short) -> None:
        """Test timeout detection."""
        manager = CommandManager(default_timeout_seconds=1)
        device_id = uuid4()

        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )

        manager.update_command_status(cmd.command_id, CommandStatus.SENT)

        import time

        time.sleep(1.1)

        timed_out = manager.check_timeouts()

        assert len(timed_out) > 0
        assert timed_out[0].status == CommandStatus.TIMEOUT

    def test_get_command_history(self, manager: CommandManager, device_id) -> None:
        """Test getting command history."""
        cmd1 = manager.send_command(
            target_device_id=device_id,
            action="set_temperature",
        )
        manager.complete_command(cmd1.command_id, {"success": True})

        cmd2 = manager.send_command(
            target_device_id=device_id,
            action="query",
        )

        history = manager.get_command_history(device_id)

        assert len(history) == 1
        assert history[0].command_id == cmd1.command_id

    def test_get_device_command_stats(self, manager: CommandManager, device_id) -> None:
        """Test getting device command statistics."""
        cmd1 = manager.send_command(
            target_device_id=device_id,
            action="action1",
        )
        cmd2 = manager.send_command(
            target_device_id=device_id,
            action="action2",
        )

        manager.update_command_status(cmd1.command_id, CommandStatus.SENT)
        manager.complete_command(cmd2.command_id)

        stats = manager.get_device_command_stats(device_id)

        assert stats["sent"] == 1
        assert stats["completed"] == 1

    def test_clear_device_queue(self, manager: CommandManager, device_id) -> None:
        """Test clearing device queue."""
        manager.send_command(
            target_device_id=device_id,
            action="action1",
        )
        manager.send_command(
            target_device_id=device_id,
            action="action2",
        )

        cleared = manager.clear_device_queue(device_id)

        assert cleared == 2

        queue = manager.get_device_queue(device_id)
        assert len(queue) == 0

    def test_get_total_command_count(self, manager: CommandManager, device_id) -> None:
        """Test getting total command count."""
        manager.send_command(
            target_device_id=device_id,
            action="action1",
        )
        manager.send_command(
            target_device_id=device_id,
            action="action2",
        )

        count = manager.get_total_command_count()

        assert count == 2

    def test_get_pending_command_count(self, manager: CommandManager, device_id) -> None:
        """Test getting pending command count."""
        cmd1 = manager.send_command(
            target_device_id=device_id,
            action="action1",
        )
        cmd2 = manager.send_command(
            target_device_id=device_id,
            action="action2",
        )

        manager.complete_command(cmd1.command_id)

        pending = manager.get_pending_command_count()

        assert pending == 1

    def test_command_parameters(self, manager: CommandManager, device_id) -> None:
        """Test command with complex parameters."""
        params = {
            "target_temp": 25.0,
            "schedule": [
                {"time": "08:00", "temp": 20.0},
                {"time": "22:00", "temp": 18.0},
            ],
            "enabled": True,
        }

        cmd = manager.send_command(
            target_device_id=device_id,
            action="set_schedule",
            parameters=params,
        )

        assert cmd.parameters == params

    def test_command_custom_timeout(self, manager: CommandManager, device_id) -> None:
        """Test command with custom timeout."""
        cmd = manager.send_command(
            target_device_id=device_id,
            action="long_operation",
            timeout_seconds=300,
        )

        assert cmd.timeout_seconds == 300
