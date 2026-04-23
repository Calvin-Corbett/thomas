"""
Workflow Persistence Layer

Stores workflow definitions and execution state to SQLite.
Enables resumption of workflows across server restarts.

Uses Thomas's migration system for schema management.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    Workflow,
    WorkflowPersistenceError,
    WorkflowRun,
)

logger = logging.getLogger(__name__)


class WorkflowStore:
    """Persistent storage for workflows and runs.

    Uses SQLite with schema management via migrations.
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize workflow store.

        Args:
            db_path: Path to SQLite database (defaults to ~/.thomas/thomas.db)
        """
        if db_path is None:
            try:
                from thomas.preferences.store import get_db_path

                db_path = get_db_path()
            except ImportError:
                db_path = Path.home() / ".thomas" / "thomas.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            # Create tables if they don't exist
            with self._get_conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflows (
                        workflow_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        version INTEGER NOT NULL DEFAULT 1,
                        definition TEXT NOT NULL,
                        metadata TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_runs (
                        run_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        inputs TEXT NOT NULL,
                        variables TEXT,
                        current_step TEXT,
                        executed_steps TEXT,
                        step_results TEXT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        paused_at TEXT,
                        error TEXT,
                        metadata TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                    )
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_runs_workflow
                    ON workflow_runs(workflow_id)
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_runs_status
                    ON workflow_runs(status)
                    """
                )

                conn.commit()

            logger.info(f"Workflow database initialized: {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize workflow database: {e}")
            raise WorkflowPersistenceError(f"Database initialization failed: {e}")

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def save_workflow(self, workflow: Workflow) -> None:
        """Save workflow definition.

        Args:
            workflow: Workflow to save

        Raises:
            WorkflowPersistenceError: If save fails
        """
        try:
            definition = json.dumps(workflow.to_dict())
            metadata = json.dumps(workflow.metadata)

            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO workflows
                    (workflow_id, name, description, version, definition, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow.workflow_id,
                        workflow.name,
                        workflow.description,
                        workflow.version,
                        definition,
                        metadata,
                        workflow.created_at,
                        workflow.updated_at,
                    ),
                )
                conn.commit()

            logger.debug(f"Saved workflow: {workflow.workflow_id}")

        except Exception as e:
            raise WorkflowPersistenceError(f"Failed to save workflow: {e}")

    async def load_workflow(self, workflow_id: str) -> Workflow | None:
        """Load workflow definition.

        Args:
            workflow_id: Workflow ID to load

        Returns:
            Workflow if found, None otherwise
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT definition FROM workflows WHERE workflow_id = ?",
                    (workflow_id,),
                )
                row = cursor.fetchone()

            if not row:
                return None

            data = json.loads(row[0])
            return Workflow.from_dict(data)

        except Exception as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None

    async def list_workflows(self) -> list[Workflow]:
        """List all workflows.

        Returns:
            List of workflows
        """
        try:
            workflows = []
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT definition FROM workflows ORDER BY created_at DESC")
                for row in cursor:
                    data = json.loads(row[0])
                    workflows.append(Workflow.from_dict(data))

            return workflows

        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            return []

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete workflow definition.

        Args:
            workflow_id: Workflow ID to delete

        Raises:
            WorkflowPersistenceError: If delete fails
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM workflows WHERE workflow_id = ?",
                    (workflow_id,),
                )
                conn.commit()

            logger.info(f"Deleted workflow: {workflow_id}")

        except Exception as e:
            raise WorkflowPersistenceError(f"Failed to delete workflow: {e}")

    async def save_run(self, run: WorkflowRun) -> None:
        """Save workflow run state.

        Args:
            run: Workflow run to save

        Raises:
            WorkflowPersistenceError: If save fails
        """
        try:
            data = run.to_dict()
            inputs = json.dumps(data["inputs"])
            variables = json.dumps(data["variables"])
            executed_steps = json.dumps(data["executed_steps"])
            step_results = json.dumps(data["step_results"])
            metadata = json.dumps(data["metadata"])

            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO workflow_runs
                    (run_id, workflow_id, status, inputs, variables, current_step,
                     executed_steps, step_results, started_at, finished_at, paused_at,
                     error, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.workflow_id,
                        run.status.value,
                        inputs,
                        variables,
                        run.current_step,
                        executed_steps,
                        step_results,
                        run.started_at,
                        run.finished_at,
                        run.paused_at,
                        run.error,
                        metadata,
                    ),
                )
                conn.commit()

            logger.debug(f"Saved workflow run: {run.run_id}")

        except Exception as e:
            raise WorkflowPersistenceError(f"Failed to save workflow run: {e}")

    async def load_run(self, run_id: str) -> WorkflowRun | None:
        """Load workflow run state.

        Args:
            run_id: Run ID to load

        Returns:
            WorkflowRun if found, None otherwise
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        run_id, workflow_id, status, inputs, variables, current_step,
                        executed_steps, step_results, started_at, finished_at, paused_at,
                        error, metadata
                    FROM workflow_runs
                    WHERE run_id = ?
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()

            if not row:
                return None

            data = {
                "run_id": row[0],
                "workflow_id": row[1],
                "status": row[2],
                "inputs": json.loads(row[3]),
                "variables": json.loads(row[4]),
                "current_step": row[5],
                "executed_steps": json.loads(row[6]),
                "step_results": json.loads(row[7]),
                "started_at": row[8],
                "finished_at": row[9],
                "paused_at": row[10],
                "error": row[11],
                "metadata": json.loads(row[12]),
            }

            return WorkflowRun.from_dict(data)

        except Exception as e:
            logger.error(f"Failed to load workflow run {run_id}: {e}")
            return None

    async def list_runs(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowRun]:
        """List workflow runs.

        Args:
            workflow_id: Filter by workflow ID
            status: Filter by status
            limit: Maximum results

        Returns:
            List of workflow runs
        """
        try:
            query = "SELECT * FROM workflow_runs WHERE 1=1"
            params: list[Any] = []

            if workflow_id:
                query += " AND workflow_id = ?"
                params.append(workflow_id)

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)

            runs = []
            with self._get_conn() as conn:
                cursor = conn.execute(query, params)
                for row in cursor:
                    data = {
                        "run_id": row[0],
                        "workflow_id": row[1],
                        "status": row[2],
                        "inputs": json.loads(row[3]),
                        "variables": json.loads(row[4]),
                        "current_step": row[5],
                        "executed_steps": json.loads(row[6]),
                        "step_results": json.loads(row[7]),
                        "started_at": row[8],
                        "finished_at": row[9],
                        "paused_at": row[10],
                        "error": row[11],
                        "metadata": json.loads(row[12]),
                    }
                    runs.append(WorkflowRun.from_dict(data))

            return runs

        except Exception as e:
            logger.error(f"Failed to list workflow runs: {e}")
            return []

    async def delete_run(self, run_id: str) -> None:
        """Delete workflow run state.

        Args:
            run_id: Run ID to delete

        Raises:
            WorkflowPersistenceError: If delete fails
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM workflow_runs WHERE run_id = ?",
                    (run_id,),
                )
                conn.commit()

            logger.info(f"Deleted workflow run: {run_id}")

        except Exception as e:
            raise WorkflowPersistenceError(f"Failed to delete workflow run: {e}")

    async def cleanup_old_runs(self, days: int = 30) -> int:
        """Delete runs older than specified days.

        Args:
            days: Age threshold in days

        Returns:
            Number of runs deleted
        """
        try:
            cutoff_date = datetime.now(timezone.utc)
            cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)

            with self._get_conn() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM workflow_runs
                    WHERE status IN ('completed', 'failed', 'cancelled')
                    AND finished_at < ?
                    """,
                    (cutoff_date.isoformat(),),
                )
                deleted = cursor.rowcount
                conn.commit()

            logger.info(f"Cleaned up {deleted} old workflow runs")
            return deleted

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return 0
