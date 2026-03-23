# scheduler_deep Module Index

## Module Overview
Advanced job scheduling system supporting cron, triggers, DAG dependencies, distributed coordination, and comprehensive monitoring.

## File Structure

### Core Files
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 88 | Package exports and initialization |
| `_types.py` | 383 | Core data structures (Job, Trigger, Config, etc.) |
| `_exceptions.py` | 173 | Custom exception hierarchy |

### Main Scheduler
| File | Lines | Purpose |
|------|-------|---------|
| `scheduler.py` | 497 | Main Scheduler class with lifecycle management |
| `cron.py` | 276 | Cron expression parser and evaluator |
| `triggers.py` | 308 | Advanced trigger implementations |

### Advanced Features
| File | Lines | Purpose |
|------|-------|---------|
| `dag.py` | 332 | DAG scheduling with topological sort |
| `calendar.py` | 310 | Business calendar and working hours |
| `executor.py` | 335 | Job execution with thread/process pools |
| `persistence.py` | 419 | Job state and history storage |
| `monitoring.py` | 308 | Metrics and health monitoring |
| `rate_control.py` | 282 | Rate limiting and concurrency control |
| `distributed.py` | 376 | Distributed coordination with leader election |

### Test Files
| File | Lines | Test Coverage |
|------|-------|----------------|
| `test_scheduler_cron.py` | 181 | Cron expression parsing (15 tests) |
| `test_scheduler_triggers.py` | 241 | All trigger types (7 test classes) |
| `test_scheduler_executor.py` | 248 | Job execution (12 tests) |
| `test_scheduler_dag.py` | 281 | DAG operations (15 tests) |
| `test_scheduler_distributed.py` | 247 | Distributed coordination (13 tests) |
| `test_scheduler_integration.py` | 423 | End-to-end scenarios (40+ tests) |

## Key Classes

### Scheduler Management
- `Scheduler` - Main scheduler class
- `SchedulerConfig` - Configuration object
- `SchedulerMonitor` - Metrics and health monitoring

### Job Definitions
- `Job` - Job dataclass with scheduling metadata
- `JobStatus` - Enum (IDLE, RUNNING, SUCCESS, FAILED, PAUSED, CANCELLED)
- `JobHistory` - Execution history record

### Triggers (10 types)
- `Trigger` - Base class
- `IntervalTrigger` - Fixed intervals
- `CronTrigger` - Cron expressions
- `DateTrigger` - One-shot execution
- `DependencyTrigger` - Job dependencies
- `CalendarTrigger` - Business hours
- `CompoundTrigger` - AND/OR combinations
- `ConditionalTrigger` - Custom conditions
- `AdaptiveTrigger` - Self-adapting
- `RandomTrigger` - Random windows
- `ExponentialBackoffTrigger` - Retry logic

### Cron Support
- `CronExpression` - Parser and evaluator
- `CronIterator` - Iterator over cron events

### Execution
- `JobExecutor` - Thread/process pool executor
- `ExecutionContext` - Execution context for jobs
- `PersistentExecutor` - Execution with persistence

### Advanced Features
- `DAGScheduler` - Dependency management
- `DAGNode` - Graph node
- `BusinessCalendar` - Working hours calculations
- `DistributedScheduler` - Multi-node coordination
- `NodeInfo` - Node state information
- `JobLock` - Distributed job locking
- `RateControl` - Concurrency management
- `ExecutionWindow` - Time-based execution windows
- `BlackoutPeriod` - Maintenance windows

### Storage
- `JobStore` - Abstract base class
- `MemoryJobStore` - In-memory storage
- `FileJobStore` - File-based (JSON) storage

### Monitoring
- `SchedulerMonitor` - Metrics collection
- `SchedulerMetrics` - Overall metrics
- `JobStats` - Per-job statistics
- `HealthStatus` - Health enum

## Exception Types
- `SchedulerException` - Base exception
- `JobNotFound` - Job lookup failed
- `JobAlreadyExists` - Duplicate job ID
- `InvalidTrigger` - Invalid trigger configuration
- `InvalidCronExpression` - Invalid cron syntax
- `JobExecutionError` - Job failed to execute
- `JobTimeout` - Job execution timeout
- `CycleDetected` - Circular dependency detected
- `InvalidDAG` - Invalid DAG configuration
- `PersistenceError` - Storage operation failed
- `DistributedSchedulingError` - Distributed coordination failed
- `LeaderElectionFailed` - Leader election failed
- `RateLimitExceeded` - Rate limit exceeded

## Quick Start

```python
from thomas.marketplace.scheduler_deep import Scheduler, CronTrigger

# Create scheduler
scheduler = Scheduler()

# Define job
def my_job():
    print("Job executed!")

# Schedule with cron (9 AM on weekdays)
trigger = CronTrigger("0 9 * * 1-5")
scheduler.add_job(my_job, trigger, name="weekday_job")

# Start scheduler
scheduler.start()

# Stop when done
scheduler.stop()
```

## Advanced Examples

### DAG Scheduling
```python
from thomas.marketplace.scheduler_deep.dag import DAGScheduler
from thomas.marketplace.scheduler_deep._types import Job, IntervalTrigger

dag = DAGScheduler()
trigger = IntervalTrigger(3600)

# Create jobs with dependencies
job1 = Job(extract_func, trigger, job_id="extract")
job2 = Job(transform_func, trigger, job_id="transform")
job3 = Job(load_func, trigger, job_id="load")

dag.add_job(job1)
dag.add_job(job2, dependencies=["extract"])
dag.add_job(job3, dependencies=["transform"])

# Get execution order
order = dag.get_topological_order()  # ['extract', 'transform', 'load']
```

### Business Calendar
```python
from thomas.marketplace.scheduler_deep import BusinessCalendar, CalendarTrigger
from datetime import date

calendar = BusinessCalendar(
    business_start_hour=9,
    business_end_hour=17,
    business_days={0, 1, 2, 3, 4},  # Monday-Friday
)
calendar.add_holiday(date(2024, 12, 25))

trigger = CalendarTrigger(calendar)
scheduler.add_job(business_task, trigger)
```

### Distributed Scheduling
```python
from thomas.marketplace.scheduler_deep import SchedulerConfig, Scheduler

config = SchedulerConfig(distributed_mode=True)
scheduler = Scheduler(config)
scheduler.start()

# Multiple instances can coordinate via shared directory
```

## Testing

Run all tests:
```bash
pytest thomas/scheduler_deep/test_*.py -v
```

Run specific test suite:
```bash
pytest thomas/scheduler_deep/test_scheduler_cron.py -v
```

## Module Statistics
- **Total Lines**: 5,708
- **Source Code**: 4,087 lines
- **Test Code**: 1,621 lines
- **Files**: 19 (13 source + 6 tests)
- **Classes**: 35+
- **Functions**: 150+
- **Exception Types**: 12
- **Test Methods**: 75+

## Performance
- Job lookup: O(1)
- Next occurrence: O(1440) worst case, O(1) average
- DAG operations: O(V + E)
- Rate control: O(1)
- Trigger matching: O(1)

## Thread Safety
- All components are thread-safe
- Fine-grained locking to minimize contention
- No race conditions in core operations
- Safe concurrent job execution

## Deployment
- Pure Python stdlib (no external dependencies)
- Configurable via SchedulerConfig
- State persistence for recovery
- Health monitoring included
- Rate control for resource management
- Graceful shutdown support

## Design Patterns
- Singleton (Scheduler)
- Strategy (Triggers, Executors)
- Observer (Events)
- Factory (Jobs)
- Template Method (Trigger base)
- Command (Job execution)
- Repository (JobStore)
