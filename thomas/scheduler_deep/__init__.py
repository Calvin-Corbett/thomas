"""
Advanced job scheduling system with cron, triggers, DAG support, and distributed scheduling.

A production-ready scheduler library supporting:
- Cron-based scheduling with timezone support
- Multiple trigger types (interval, date, calendar-based, dependencies)
- Directed acyclic graph (DAG) scheduling with parallel execution
- Distributed scheduling with leader election and failover
- Job persistence and monitoring
- Rate control and resource management
"""

from thomas.scheduler_deep._exceptions import (
    CycleDetected,
    InvalidTrigger,
    JobAlreadyExists,
    JobNotFound,
    SchedulerException,
)
from thomas.scheduler_deep._types import (
    Calendar,
    CronTrigger,
    DateTrigger,
    DependencyTrigger,
    IntervalTrigger,
    Job,
    JobHistory,
    JobStatus,
    SchedulerConfig,
    Trigger,
)
from thomas.scheduler_deep.calendar import BusinessCalendar
from thomas.scheduler_deep.cron import CronExpression
from thomas.scheduler_deep.dag import DAGScheduler
from thomas.scheduler_deep.distributed import DistributedScheduler
from thomas.scheduler_deep.executor import ExecutionContext, JobExecutor
from thomas.scheduler_deep.monitoring import SchedulerMonitor
from thomas.scheduler_deep.persistence import FileJobStore, JobStore, MemoryJobStore
from thomas.scheduler_deep.rate_control import RateControl
from thomas.scheduler_deep.scheduler import Scheduler
from thomas.scheduler_deep.triggers import (
    AdaptiveTrigger,
    CalendarTrigger,
    CompoundTrigger,
    ConditionalTrigger,
    ExponentialBackoffTrigger,
    MissedFirePolicy,
    RandomTrigger,
    Trigger,
)

__version__ = "1.0.0"
__all__ = [
    "Job",
    "JobStatus",
    "JobHistory",
    "SchedulerConfig",
    "Trigger",
    "CronTrigger",
    "IntervalTrigger",
    "DateTrigger",
    "DependencyTrigger",
    "Calendar",
    "Scheduler",
    "CronExpression",
    "CompoundTrigger",
    "ConditionalTrigger",
    "ExponentialBackoffTrigger",
    "AdaptiveTrigger",
    "RandomTrigger",
    "MissedFirePolicy",
    "CalendarTrigger",
    "DAGScheduler",
    "BusinessCalendar",
    "JobExecutor",
    "ExecutionContext",
    "JobStore",
    "FileJobStore",
    "MemoryJobStore",
    "SchedulerMonitor",
    "DistributedScheduler",
    "RateControl",
    "SchedulerException",
    "JobNotFound",
    "InvalidTrigger",
    "JobAlreadyExists",
    "CycleDetected",
]
