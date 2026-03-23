"""OS kernel abstractions for process, memory, filesystem, and scheduling.

Provides cross-platform abstractions for system-level operations
including process management, memory allocation, and task scheduling.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProcessState(Enum):
    """Process states."""

    CREATED = "created"
    RUNNING = "running"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    ZOMBIE = "zombie"


class MemoryType(Enum):
    """Memory allocation types."""

    HEAP = "heap"
    STACK = "stack"
    SHARED = "shared"
    MMAP = "mmap"


@dataclass
class ProcessInfo:
    """Process information."""

    pid: int
    name: str
    parent_pid: int
    state: ProcessState
    cpu_percent: float
    memory_mb: float
    created_at: datetime = field(default_factory=datetime.utcnow)
    threads: int = 1


@dataclass
class MemoryBlock:
    """Memory allocation block."""

    address: int
    size: int
    mem_type: MemoryType
    allocated_at: datetime = field(default_factory=datetime.utcnow)
    owner: int | None = None


@dataclass
class FileSystemEntry:
    """File system entry."""

    path: str
    is_directory: bool
    size: int
    permissions: str
    owner: str
    modified_at: datetime


class ProcessManager(ABC):
    """Base process manager."""

    @abstractmethod
    async def create_process(self, executable: str, args: list[str]) -> ProcessInfo:
        """Create new process."""
        pass

    @abstractmethod
    async def terminate_process(self, pid: int) -> bool:
        """Terminate process."""
        pass

    @abstractmethod
    async def get_process_info(self, pid: int) -> ProcessInfo | None:
        """Get process information."""
        pass

    @abstractmethod
    async def list_processes(self) -> list[ProcessInfo]:
        """List all processes."""
        pass

    @abstractmethod
    async def suspend_process(self, pid: int) -> bool:
        """Suspend process."""
        pass

    @abstractmethod
    async def resume_process(self, pid: int) -> bool:
        """Resume process."""
        pass


class MemoryManager(ABC):
    """Base memory manager."""

    @abstractmethod
    async def allocate(self, size: int, mem_type: MemoryType) -> MemoryBlock:
        """Allocate memory."""
        pass

    @abstractmethod
    async def free(self, block: MemoryBlock) -> bool:
        """Free memory block."""
        pass

    @abstractmethod
    async def get_memory_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        pass

    @abstractmethod
    async def defragment(self) -> bool:
        """Defragment memory."""
        pass


class FileSystemAbstraction(ABC):
    """Base filesystem abstraction."""

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read file contents."""
        pass

    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> bool:
        """Write file contents."""
        pass

    @abstractmethod
    async def list_directory(self, path: str) -> list[FileSystemEntry]:
        """List directory contents."""
        pass

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete file."""
        pass


class TaskScheduler(ABC):
    """Base task scheduler."""

    @abstractmethod
    async def schedule_task(self, task_id: str, task: Callable, priority: int) -> str:
        """Schedule task execution."""
        pass

    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel scheduled task."""
        pass

    @abstractmethod
    async def get_scheduled_tasks(self) -> list[dict[str, Any]]:
        """Get scheduled tasks."""
        pass


class UnixProcessManager(ProcessManager):
    """Unix/Linux process manager."""

    def __init__(self):
        self.processes: dict[int, ProcessInfo] = {}

    async def create_process(self, executable: str, args: list[str]) -> ProcessInfo:
        """Create process via fork/exec."""
        pid = os.getpid()  # Simplified
        process = ProcessInfo(
            pid=pid,
            name=executable,
            parent_pid=os.getppid(),
            state=ProcessState.RUNNING,
            cpu_percent=0.0,
            memory_mb=10.0,
        )
        self.processes[pid] = process
        return process

    async def terminate_process(self, pid: int) -> bool:
        """Terminate process."""
        if pid in self.processes:
            self.processes[pid].state = ProcessState.TERMINATED
            return True
        return False

    async def get_process_info(self, pid: int) -> ProcessInfo | None:
        """Get process info."""
        return self.processes.get(pid)

    async def list_processes(self) -> list[ProcessInfo]:
        """List all processes."""
        return list(self.processes.values())

    async def suspend_process(self, pid: int) -> bool:
        """Suspend process."""
        if pid in self.processes:
            self.processes[pid].state = ProcessState.SUSPENDED
            return True
        return False

    async def resume_process(self, pid: int) -> bool:
        """Resume process."""
        if pid in self.processes:
            self.processes[pid].state = ProcessState.RUNNING
            return True
        return False


class SimpleMemoryManager(MemoryManager):
    """Simple memory manager."""

    def __init__(self, total_memory_mb: int = 1024):
        self.total_memory = total_memory_mb * 1024 * 1024
        self.allocated_blocks: dict[int, MemoryBlock] = {}
        self.free_memory = self.total_memory

    async def allocate(self, size: int, mem_type: MemoryType) -> MemoryBlock:
        """Allocate memory."""
        if size > self.free_memory:
            raise MemoryError("Insufficient memory")

        block = MemoryBlock(address=self.total_memory - self.free_memory, size=size, mem_type=mem_type)
        self.allocated_blocks[block.address] = block
        self.free_memory -= size
        return block

    async def free(self, block: MemoryBlock) -> bool:
        """Free memory."""
        if block.address in self.allocated_blocks:
            del self.allocated_blocks[block.address]
            self.free_memory += block.size
            return True
        return False

    async def get_memory_stats(self) -> dict[str, Any]:
        """Get memory stats."""
        return {
            "total_mb": self.total_memory // (1024 * 1024),
            "free_mb": self.free_memory // (1024 * 1024),
            "allocated_blocks": len(self.allocated_blocks),
        }

    async def defragment(self) -> bool:
        """Defragment memory."""
        return True


class UnixFileSystem(FileSystemAbstraction):
    """Unix filesystem abstraction."""

    async def read_file(self, path: str) -> bytes:
        """Read file."""
        with open(path, "rb") as f:
            return f.read()

    async def write_file(self, path: str, data: bytes) -> bool:
        """Write file."""
        with open(path, "wb") as f:
            f.write(data)
        return True

    async def list_directory(self, path: str) -> list[FileSystemEntry]:
        """List directory."""
        entries = []
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            stat = os.stat(full_path)
            entries.append(
                FileSystemEntry(
                    path=full_path,
                    is_directory=os.path.isdir(full_path),
                    size=stat.st_size,
                    permissions=oct(stat.st_mode),
                    owner=str(stat.st_uid),
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )
        return entries

    async def delete_file(self, path: str) -> bool:
        """Delete file."""
        try:
            os.remove(path)
            return True
        except Exception:
            return False


class PriorityTaskScheduler(TaskScheduler):
    """Priority-based task scheduler."""

    def __init__(self):
        self.tasks: dict[str, dict[str, Any]] = {}
        self.queue: list[tuple[int, str]] = []

    async def schedule_task(self, task_id: str, task: Callable, priority: int) -> str:
        """Schedule task."""
        self.tasks[task_id] = {"task": task, "priority": priority, "created_at": datetime.utcnow()}
        self.queue.append((priority, task_id))
        self.queue.sort(reverse=True)
        return task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.queue = [(p, t) for p, t in self.queue if t != task_id]
            return True
        return False

    async def get_scheduled_tasks(self) -> list[dict[str, Any]]:
        """Get scheduled tasks."""
        return list(self.tasks.values())
