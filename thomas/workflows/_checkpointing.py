"""
Workflow checkpointing for crash recovery.

Saves workflow state after each step so that workflows can resume
from the last successful checkpoint if the server crashes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowCheckpoint:
    """Manages workflow checkpoints for crash recovery."""

    def __init__(self, db_path: Path):
        """Initialize checkpoint manager.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize checkpoint table."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL UNIQUE,
                        workflow_id TEXT NOT NULL,
                        current_step TEXT,
                        executed_steps TEXT,
                        step_results TEXT,
                        workflow_context TEXT,
                        checkpoint_time TEXT NOT NULL,
                        step_start_time TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_run_id " "ON workflow_checkpoints(run_id)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoint_workflow_id " "ON workflow_checkpoints(workflow_id)"
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize checkpoint database: {e}")
            raise

    async def save(
        self,
        run_id: str,
        workflow_id: str,
        current_step: str | None,
        executed_steps: list[str],
        step_results: dict[str, Any],
        workflow_context: dict[str, Any],
    ) -> None:
        """Save workflow checkpoint.

        Args:
            run_id: Workflow run ID
            workflow_id: Workflow ID
            current_step: Currently executing step ID
            executed_steps: List of completed step IDs
            step_results: Results from all completed steps
            workflow_context: Workflow execution context
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO workflow_checkpoints
                        (run_id, workflow_id, current_step, executed_steps,
                         step_results, workflow_context, checkpoint_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            workflow_id,
                            current_step,
                            json.dumps(executed_steps),
                            json.dumps(step_results),
                            json.dumps(workflow_context),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    conn.commit()

                logger.debug(f"Checkpoint saved for run {run_id} at step {current_step}")

            except Exception as e:
                logger.error(f"Failed to save checkpoint: {e}")
                raise

    async def load(self, run_id: str) -> dict[str, Any] | None:
        """Load checkpoint for a run.

        Args:
            run_id: Workflow run ID

        Returns:
            Checkpoint data or None if not found
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row

                    cursor = conn.execute(
                        "SELECT * FROM workflow_checkpoints WHERE run_id = ?",
                        (run_id,),
                    )
                    row = cursor.fetchone()

                    if not row:
                        return None

                    return {
                        "run_id": row["run_id"],
                        "workflow_id": row["workflow_id"],
                        "current_step": row["current_step"],
                        "executed_steps": json.loads(row["executed_steps"]),
                        "step_results": json.loads(row["step_results"]),
                        "workflow_context": json.loads(row["workflow_context"]),
                        "checkpoint_time": row["checkpoint_time"],
                    }

            except Exception as e:
                logger.error(f"Failed to load checkpoint: {e}")
                return None

    async def delete(self, run_id: str) -> None:
        """Delete checkpoint for a completed run.

        Args:
            run_id: Workflow run ID
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        "DELETE FROM workflow_checkpoints WHERE run_id = ?",
                        (run_id,),
                    )
                    conn.commit()

                logger.debug(f"Checkpoint deleted for run {run_id}")

            except Exception as e:
                logger.error(f"Failed to delete checkpoint: {e}")
                raise

    async def list_incomplete(self) -> list[dict[str, Any]]:
        """List checkpoints for incomplete workflows.

        Returns:
            List of incomplete workflow checkpoints
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row

                    cursor = conn.execute(
                        """
                        SELECT * FROM workflow_checkpoints
                        ORDER BY checkpoint_time DESC
                        """
                    )

                    return [
                        {
                            "run_id": row["run_id"],
                            "workflow_id": row["workflow_id"],
                            "current_step": row["current_step"],
                            "executed_steps": json.loads(row["executed_steps"]),
                            "step_results": json.loads(row["step_results"]),
                            "workflow_context": json.loads(row["workflow_context"]),
                            "checkpoint_time": row["checkpoint_time"],
                        }
                        for row in cursor.fetchall()
                    ]

            except Exception as e:
                logger.error(f"Failed to list incomplete checkpoints: {e}")
                return []
