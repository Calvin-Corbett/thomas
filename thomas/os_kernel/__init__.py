"""OS kernel abstractions for processes, memory, filesystem, and scheduling.

Provides cross-platform abstractions for system-level operations
with support for Unix/Linux, Windows, and macOS.
"""

from .core import (
    FileSystemAbstraction,
    MemoryBlock,
    MemoryManager,
    MemoryType,
    PriorityTaskScheduler,
    ProcessInfo,
    ProcessManager,
    ProcessState,
    SimpleMemoryManager,
    TaskScheduler,
    UnixFileSystem,
    UnixProcessManager,
)

__all__ = [
    "ProcessState",
    "MemoryType",
    "ProcessInfo",
    "MemoryBlock",
    "FileSystemEntry",
    "ProcessManager",
    "MemoryManager",
    "FileSystemAbstraction",
    "TaskScheduler",
    "UnixProcessManager",
    "SimpleMemoryManager",
    "UnixFileSystem",
    "PriorityTaskScheduler",
]

__version__ = "1.0.0"
