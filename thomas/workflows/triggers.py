"""
Workflow Triggers

Triggers that start workflow execution:
- CronTrigger: Schedule-based (via cron expressions)
- EventTrigger: Event bus based (on event type X, start workflow Y)
- WebhookTrigger: HTTP webhook endpoint
- FileTrigger: File system change (new file, modified file)
- ManualTrigger: User-initiated start

Each trigger type handles its own activation logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Base Trigger
# ============================================================


class WorkflowTrigger(ABC):
    """Base class for workflow triggers.

    A trigger determines when a workflow should be started.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
        config: dict[str, Any],
    ):
        """Initialize trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: ID of workflow to trigger
            config: Trigger-specific configuration
        """
        self.trigger_id = trigger_id
        self.workflow_id = workflow_id
        self.config = config
        self.enabled = True

    @abstractmethod
    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start the trigger.

        Args:
            callback: Async function to call with (workflow_id, inputs)
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the trigger."""
        pass

    async def activate(self) -> None:
        """Enable trigger activation."""
        self.enabled = True
        logger.info(f"Trigger activated: {self.trigger_id}")

    async def deactivate(self) -> None:
        """Disable trigger activation."""
        self.enabled = False
        logger.info(f"Trigger deactivated: {self.trigger_id}")


# ============================================================
# Cron Trigger
# ============================================================


class CronTrigger(WorkflowTrigger):
    """Schedule-based trigger using cron expressions.

    Starts a workflow on a cron schedule.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
        cron_expr: str,
        inputs: dict[str, Any] | None = None,
    ):
        """Initialize cron trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: Workflow to trigger
            cron_expr: Cron expression (5-field)
            inputs: Default inputs to pass to workflow
        """
        super().__init__(
            trigger_id,
            workflow_id,
            {"cron_expr": cron_expr, "inputs": inputs or {}},
        )
        self._task: asyncio.Task | None = None

    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start cron scheduling.

        Args:
            callback: Function to call on schedule
        """
        if self._task:
            return

        async def cron_loop():
            try:
                from datetime import datetime, timezone

                from croniter import croniter

                cron_expr = self.config["cron_expr"]
                inputs = self.config.get("inputs", {})

                # Validate cron expression
                if not croniter.is_valid(cron_expr):
                    logger.error(f"Invalid cron expression: {cron_expr}")
                    return

                base = datetime.now(timezone.utc)
                cron_iter = croniter(cron_expr, base)

                while self.enabled:
                    next_run = cron_iter.get_next(datetime)
                    now = datetime.now(timezone.utc)
                    wait_seconds = max(0, (next_run - now).total_seconds())

                    await asyncio.sleep(wait_seconds)

                    if self.enabled:
                        logger.info(f"Triggering workflow via cron: {self.workflow_id}")
                        try:
                            await callback(self.workflow_id, inputs)
                        except Exception as e:
                            logger.error(f"Cron trigger callback failed: {e}")

            except Exception as e:
                logger.error(f"Cron trigger error: {e}")

        self._task = asyncio.create_task(cron_loop())
        logger.info(f"Cron trigger started: {self.trigger_id} ({self.config['cron_expr']})")

    async def stop(self) -> None:
        """Stop cron scheduling."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info(f"Cron trigger stopped: {self.trigger_id}")


# ============================================================
# Event Trigger
# ============================================================


class EventTrigger(WorkflowTrigger):
    """Event bus trigger.

    Starts workflow when a specific event is published.
    Integrates with Thomas event bus.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
        event_type: str,
        input_mapping: dict[str, str] | None = None,
    ):
        """Initialize event trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: Workflow to trigger
            event_type: Event type to listen for
            input_mapping: Map event fields to workflow inputs
        """
        super().__init__(
            trigger_id,
            workflow_id,
            {
                "event_type": event_type,
                "input_mapping": input_mapping or {},
            },
        )
        self._subscription_id: str | None = None

    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start listening for events.

        Args:
            callback: Function to call when event occurs
        """
        try:
            # TODO: Integrate with thomas.event_bus
            event_type = self.config["event_type"]
            input_mapping = self.config.get("input_mapping", {})

            async def on_event(event: Any) -> None:
                if not self.enabled:
                    return

                # Map event fields to workflow inputs
                inputs = {}
                for input_key, event_field in input_mapping.items():
                    inputs[input_key] = getattr(event, event_field, None)

                logger.info(f"Triggering workflow via event {event_type}: {self.workflow_id}")
                try:
                    await callback(self.workflow_id, inputs)
                except Exception as e:
                    logger.error(f"Event trigger callback failed: {e}")

            # TODO: bus.subscribe(on_event, event_types={event_type})
            logger.info(f"Event trigger started: {self.trigger_id} ({event_type})")

        except Exception as e:
            logger.error(f"Event trigger startup failed: {e}")

    async def stop(self) -> None:
        """Stop listening for events."""
        # TODO: bus.unsubscribe(self._subscription_id)
        logger.info(f"Event trigger stopped: {self.trigger_id}")


# ============================================================
# Webhook Trigger
# ============================================================


class WebhookTrigger(WorkflowTrigger):
    """HTTP webhook trigger.

    Provides an endpoint that triggers workflow execution.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
        path: str,
        secret: str | None = None,
    ):
        """Initialize webhook trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: Workflow to trigger
            path: HTTP path for webhook (e.g., /workflows/my-trigger)
            secret: Optional HMAC secret for verification
        """
        super().__init__(
            trigger_id,
            workflow_id,
            {
                "path": path,
                "secret": secret,
            },
        )

    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start webhook server.

        Args:
            callback: Function to call on webhook POST
        """
        # TODO: Register webhook endpoint with HTTP server
        logger.info(f"Webhook trigger started: {self.trigger_id} ({self.config['path']})")

    async def stop(self) -> None:
        """Stop webhook server."""
        # TODO: Unregister webhook endpoint
        logger.info(f"Webhook trigger stopped: {self.trigger_id}")

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle incoming webhook request.

        Args:
            payload: Request payload

        Returns:
            True if webhook was processed
        """
        if not self.enabled:
            return False

        # TODO: Verify HMAC signature if secret is configured
        logger.info(f"Webhook received: {self.trigger_id}")
        return True


# ============================================================
# File Trigger
# ============================================================


class FileTrigger(WorkflowTrigger):
    """File system watch trigger.

    Starts workflow when files in a directory change.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
        watch_path: str,
        pattern: str | None = None,
        events: list | None = None,
    ):
        """Initialize file trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: Workflow to trigger
            watch_path: Directory to watch
            pattern: File name pattern to match (glob)
            events: File events to watch ['created', 'modified', 'deleted']
        """
        super().__init__(
            trigger_id,
            workflow_id,
            {
                "watch_path": watch_path,
                "pattern": pattern or "*",
                "events": events or ["created", "modified"],
            },
        )
        self._observer: Any | None = None
        self._file_hashes: dict[str, str] = {}
        self._task: asyncio.Task | None = None

    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start watching directory.

        Args:
            callback: Function to call on file change
        """
        if self._task:
            return

        watch_path = self.config["watch_path"]
        pattern = self.config["pattern"]
        events = self.config["events"]

        async def watch_loop():
            try:
                import asyncio
                from pathlib import Path

                watch_dir = Path(watch_path)
                if not watch_dir.exists():
                    logger.warning(f"Watch directory does not exist: {watch_path}")
                    return

                while self.enabled:
                    try:
                        for file_path in watch_dir.glob(pattern):
                            if file_path.is_file():
                                await self._check_file(file_path, callback, events)
                    except Exception as e:
                        logger.error(f"File watch error: {e}")

                    await asyncio.sleep(1)  # Poll interval

            except Exception as e:
                logger.error(f"File trigger error: {e}")

        self._task = asyncio.create_task(watch_loop())
        logger.info(f"File trigger started: {self.trigger_id} ({watch_path}, {pattern})")

    async def stop(self) -> None:
        """Stop watching directory."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._file_hashes.clear()
        logger.info(f"File trigger stopped: {self.trigger_id}")

    async def _check_file(
        self,
        file_path: Path,
        callback: Callable,
        events: list,
    ) -> None:
        """Check if file has changed and trigger if needed.

        Args:
            file_path: Path to check
            callback: Callback to invoke
            events: Events to watch for
        """
        try:
            # Compute file hash
            file_hash = self._hash_file(file_path)
            path_str = str(file_path)
            old_hash = self._file_hashes.get(path_str)

            if old_hash is None and "created" in events:
                # File is new
                self._file_hashes[path_str] = file_hash
                logger.info(f"File created: {file_path}")
                await callback(
                    self.workflow_id,
                    {"file_path": path_str, "event": "created"},
                )

            elif old_hash and old_hash != file_hash and "modified" in events:
                # File was modified
                self._file_hashes[path_str] = file_hash
                logger.info(f"File modified: {file_path}")
                await callback(
                    self.workflow_id,
                    {"file_path": path_str, "event": "modified"},
                )

        except Exception as e:
            logger.warning(f"Error checking file {file_path}: {e}")

    def _hash_file(self, file_path: Path, chunk_size: int = 8192) -> str:
        """Compute SHA256 hash of file.

        Args:
            file_path: Path to file
            chunk_size: Chunk size for reading

        Returns:
            Hex hash string
        """
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
        except OSError:
            return ""
        return hasher.hexdigest()


# ============================================================
# Manual Trigger
# ============================================================


class ManualTrigger(WorkflowTrigger):
    """Manual user-initiated trigger.

    Workflow starts only when explicitly triggered by user.
    """

    def __init__(
        self,
        trigger_id: str,
        workflow_id: str,
    ):
        """Initialize manual trigger.

        Args:
            trigger_id: Unique trigger identifier
            workflow_id: Workflow to trigger
        """
        super().__init__(trigger_id, workflow_id, {})

    async def start(self, callback: Callable[[str, dict[str, Any]], Any]) -> None:
        """Start manual trigger (no-op).

        Args:
            callback: Function to call
        """
        self._callback = callback
        logger.info(f"Manual trigger started: {self.trigger_id}")

    async def stop(self) -> None:
        """Stop manual trigger."""
        logger.info(f"Manual trigger stopped: {self.trigger_id}")

    async def trigger(self, inputs: dict[str, Any] | None = None) -> None:
        """Manually trigger the workflow.

        Args:
            inputs: Input parameters for workflow
        """
        if not self.enabled:
            logger.warning(f"Manual trigger disabled: {self.trigger_id}")
            return

        if not hasattr(self, "_callback"):
            logger.warning(f"Callback not set for manual trigger: {self.trigger_id}")
            return

        logger.info(f"Manual trigger activated: {self.trigger_id}")
        try:
            await self._callback(self.workflow_id, inputs or {})
        except Exception as e:
            logger.error(f"Manual trigger callback failed: {e}")
