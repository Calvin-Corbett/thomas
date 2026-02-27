"""
Dead letter queue for failed workflows.

Stores workflows that have exhausted all retries for later analysis
and manual recovery.
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


class DeadLetterQueue:
    """Manages dead letter queue for failed workflows.

    Stores workflow execution data for workflows that have failed
    after exhausting all retry attempts.
    """

    def __init__(self, db_path: Path):
        """Initialize dead letter queue.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize DLQ table."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_dead_letters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        workflow_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        step_id TEXT NOT NULL,
                        error TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        original_input TEXT,
                        last_result TEXT,
                        resolved INTEGER DEFAULT 0,
                        resolved_at TEXT,
                        resolution_notes TEXT,
                        UNIQUE(run_id, step_id)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_workflow_id " "ON workflow_dead_letters(workflow_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_run_id " "ON workflow_dead_letters(run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_resolved " "ON workflow_dead_letters(resolved)")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize DLQ database: {e}")
            raise

    async def enqueue(
        self,
        workflow_id: str,
        run_id: str,
        step_id: str,
        error: str,
        retry_count: int = 0,
        original_input: dict[str, Any] | None = None,
        last_result: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a failed workflow to dead letter queue.

        Args:
            workflow_id: Workflow ID
            run_id: Run ID
            step_id: Step ID
            error: Error message
            retry_count: Number of retry attempts made
            original_input: Original step input
            last_result: Last step result before failure
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO workflow_dead_letters
                        (workflow_id, run_id, step_id, error, timestamp,
                         retry_count, original_input, last_result)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            workflow_id,
                            run_id,
                            step_id,
                            error,
                            datetime.now(timezone.utc).isoformat(),
                            retry_count,
                            json.dumps(original_input) if original_input else None,
                            json.dumps(last_result) if last_result else None,
                        ),
                    )
                    conn.commit()

                logger.error(
                    f"Enqueued to DLQ: workflow={workflow_id}, " f"run={run_id}, step={step_id}, retries={retry_count}"
                )

            except Exception as e:
                logger.error(f"Failed to enqueue to DLQ: {e}")
                raise

    async def list_pending(
        self,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List pending (unresolved) dead letters.

        Args:
            workflow_id: Filter by workflow ID
            limit: Maximum results

        Returns:
            List of dead letter records
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row

                    if workflow_id:
                        cursor = conn.execute(
                            """
                            SELECT * FROM workflow_dead_letters
                            WHERE resolved = 0 AND workflow_id = ?
                            ORDER BY timestamp DESC
                            LIMIT ?
                            """,
                            (workflow_id, limit),
                        )
                    else:
                        cursor = conn.execute(
                            """
                            SELECT * FROM workflow_dead_letters
                            WHERE resolved = 0
                            ORDER BY timestamp DESC
                            LIMIT ?
                            """,
                            (limit,),
                        )

                    return [
                        {
                            "id": row["id"],
                            "workflow_id": row["workflow_id"],
                            "run_id": row["run_id"],
                            "step_id": row["step_id"],
                            "error": row["error"],
                            "timestamp": row["timestamp"],
                            "retry_count": row["retry_count"],
                            "original_input": (json.loads(row["original_input"]) if row["original_input"] else None),
                            "last_result": (json.loads(row["last_result"]) if row["last_result"] else None),
                        }
                        for row in cursor.fetchall()
                    ]

            except Exception as e:
                logger.error(f"Failed to list pending DLQ items: {e}")
                return []

    async def resolve(
        self,
        record_id: int,
        notes: str = "",
    ) -> None:
        """Mark a dead letter as resolved.

        Args:
            record_id: Record ID
            notes: Resolution notes
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        """
                        UPDATE workflow_dead_letters
                        SET resolved = 1, resolved_at = ?, resolution_notes = ?
                        WHERE id = ?
                        """,
                        (datetime.now(timezone.utc).isoformat(), notes, record_id),
                    )
                    conn.commit()

                logger.info(f"Resolved DLQ record: {record_id}")

            except Exception as e:
                logger.error(f"Failed to resolve DLQ record: {e}")
                raise

    async def count_pending(self) -> int:
        """Get count of pending dead letters.

        Returns:
            Number of unresolved records
        """
        async with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM workflow_dead_letters WHERE resolved = 0")
                    return cursor.fetchone()[0]

            except Exception as e:
                logger.error(f"Failed to count pending DLQ items: {e}")
                return 0
