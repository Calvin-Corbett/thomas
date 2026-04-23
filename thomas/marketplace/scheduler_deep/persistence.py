"""
Job state persistence and history management.

Provides storage backends for jobs and execution history.
"""

import json
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.marketplace.scheduler_deep._exceptions import PersistenceError
from thomas.marketplace.scheduler_deep._types import Job, JobHistory

logger = logging.getLogger(__name__)


class JobStore(ABC):
    """Abstract base class for job storage."""

    @abstractmethod
    def save_job(self, job: Job) -> None:
        """Save job state.

        Args:
            job: Job to save
        """
        pass

    @abstractmethod
    def load_job(self, job_id: str) -> Job | None:
        """Load job by ID.

        Args:
            job_id: Job ID to load

        Returns:
            Job or None if not found
        """
        pass

    @abstractmethod
    def delete_job(self, job_id: str) -> None:
        """Delete job.

        Args:
            job_id: Job ID to delete
        """
        pass

    @abstractmethod
    def list_jobs(self) -> list[Job]:
        """List all jobs.

        Returns:
            List of all stored jobs
        """
        pass

    @abstractmethod
    def save_history(self, history: JobHistory) -> None:
        """Save execution history.

        Args:
            history: History record to save
        """
        pass

    @abstractmethod
    def get_history(
        self,
        job_id: str,
        limit: int = 100,
    ) -> list[JobHistory]:
        """Get job execution history.

        Args:
            job_id: Job ID
            limit: Maximum records to return

        Returns:
            List of history records
        """
        pass

    @abstractmethod
    def clear_history(self, job_id: str, before: datetime | None = None) -> None:
        """Clear job history.

        Args:
            job_id: Job ID
            before: Only clear records before this time
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close store connection."""
        pass


class MemoryJobStore(JobStore):
    """In-memory job storage."""

    def __init__(self) -> None:
        """Initialize memory store."""
        self._jobs: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def save_job(self, job: Job) -> None:
        """Save job to memory.

        Args:
            job: Job to save
        """
        with self._lock:
            self._jobs[job.id] = {
                "id": job.id,
                "name": job.name,
                "status": job.status.value,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "result": str(job.result) if job.result else None,
                "error": job.error,
                "created_at": job.created_at.isoformat(),
            }

    def load_job(self, job_id: str) -> Job | None:
        """Load job from memory.

        Args:
            job_id: Job ID to load

        Returns:
            Job or None
        """
        with self._lock:
            data = self._jobs.get(job_id)
            if data is None:
                return None
            # Note: Cannot fully reconstruct job without callable
            return None

    def delete_job(self, job_id: str) -> None:
        """Delete job from memory.

        Args:
            job_id: Job ID to delete
        """
        with self._lock:
            self._jobs.pop(job_id, None)
            self._history.pop(job_id, None)

    def list_jobs(self) -> list[Job]:
        """List all jobs.

        Returns:
            Empty list (cannot reconstruct jobs)
        """
        return []

    def save_history(self, history: JobHistory) -> None:
        """Save history record.

        Args:
            history: History record to save
        """
        with self._lock:
            if history.job_id not in self._history:
                self._history[history.job_id] = []
            self._history[history.job_id].append(history.to_dict())

    def get_history(
        self,
        job_id: str,
        limit: int = 100,
    ) -> list[JobHistory]:
        """Get job history.

        Args:
            job_id: Job ID
            limit: Max records

        Returns:
            List of history records
        """
        with self._lock:
            records = self._history.get(job_id, [])
            return [JobHistory.from_dict(r) for r in records[-limit:]]

    def clear_history(self, job_id: str, before: datetime | None = None) -> None:
        """Clear job history.

        Args:
            job_id: Job ID
            before: Clear before this time
        """
        with self._lock:
            if job_id not in self._history:
                return

            if before is None:
                self._history[job_id] = []
            else:
                self._history[job_id] = [
                    r for r in self._history[job_id] if datetime.fromisoformat(r["executed_at"]) > before
                ]

    def close(self) -> None:
        """Close store (no-op for memory store)."""
        pass


class FileJobStore(JobStore):
    """File-based job storage."""

    def __init__(self, store_dir: str) -> None:
        """Initialize file store.

        Args:
            store_dir: Directory for storing files
        """
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs_file = self.store_dir / "jobs.json"
        self._history_dir = self.store_dir / "history"
        self._history_dir.mkdir(exist_ok=True)

    def save_job(self, job: Job) -> None:
        """Save job to file.

        Args:
            job: Job to save
        """
        try:
            with self._lock:
                # Load existing jobs
                jobs = {}
                if self._jobs_file.exists():
                    with open(self._jobs_file) as f:
                        jobs = json.load(f)

                # Update job
                jobs[job.id] = job.to_dict()

                # Save back
                with open(self._jobs_file, "w") as f:
                    json.dump(jobs, f, indent=2)

        except Exception as e:
            raise PersistenceError("save_job", str(e))

    def load_job(self, job_id: str) -> Job | None:
        """Load job from file.

        Args:
            job_id: Job ID to load

        Returns:
            Job or None
        """
        try:
            with self._lock:
                if not self._jobs_file.exists():
                    return None

                with open(self._jobs_file) as f:
                    jobs = json.load(f)

                return jobs.get(job_id)

        except Exception as e:
            raise PersistenceError("load_job", str(e))

    def delete_job(self, job_id: str) -> None:
        """Delete job from file.

        Args:
            job_id: Job ID to delete
        """
        try:
            with self._lock:
                if not self._jobs_file.exists():
                    return

                with open(self._jobs_file) as f:
                    jobs = json.load(f)

                jobs.pop(job_id, None)

                with open(self._jobs_file, "w") as f:
                    json.dump(jobs, f, indent=2)

                # Delete history
                history_file = self._history_dir / f"{job_id}.json"
                history_file.unlink(missing_ok=True)

        except Exception as e:
            raise PersistenceError("delete_job", str(e))

    def list_jobs(self) -> list[Job]:
        """List all jobs.

        Returns:
            List of jobs
        """
        try:
            with self._lock:
                if not self._jobs_file.exists():
                    return []

                with open(self._jobs_file) as f:
                    jobs = json.load(f)

                return list(jobs.values())

        except Exception as e:
            raise PersistenceError("list_jobs", str(e))

    def save_history(self, history: JobHistory) -> None:
        """Save history record.

        Args:
            history: History to save
        """
        try:
            with self._lock:
                history_file = self._history_dir / f"{history.job_id}.json"
                records = []

                if history_file.exists():
                    with open(history_file) as f:
                        records = json.load(f)

                records.append(history.to_dict())
                records = records[-10000:]  # Keep last 10000

                with open(history_file, "w") as f:
                    json.dump(records, f, indent=2)

        except Exception as e:
            raise PersistenceError("save_history", str(e))

    def get_history(
        self,
        job_id: str,
        limit: int = 100,
    ) -> list[JobHistory]:
        """Get job history.

        Args:
            job_id: Job ID
            limit: Max records

        Returns:
            List of history records
        """
        try:
            with self._lock:
                history_file = self._history_dir / f"{job_id}.json"

                if not history_file.exists():
                    return []

                with open(history_file) as f:
                    records = json.load(f)

                return [JobHistory.from_dict(r) for r in records[-limit:]]

        except Exception as e:
            raise PersistenceError("get_history", str(e))

    def clear_history(self, job_id: str, before: datetime | None = None) -> None:
        """Clear job history.

        Args:
            job_id: Job ID
            before: Clear before this time
        """
        try:
            with self._lock:
                history_file = self._history_dir / f"{job_id}.json"

                if not history_file.exists():
                    return

                with open(history_file) as f:
                    records = json.load(f)

                if before is None:
                    records = []
                else:
                    records = [r for r in records if datetime.fromisoformat(r["executed_at"]) > before]

                with open(history_file, "w") as f:
                    json.dump(records, f, indent=2)

        except Exception as e:
            raise PersistenceError("clear_history", str(e))

    def close(self) -> None:
        """Close store (no-op for file store)."""
        pass
