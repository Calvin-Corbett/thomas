# scheduler_deep: Advanced Job Scheduling System

A production-ready Python job scheduling library with support for cron expressions, multiple trigger types, DAG-based job dependencies, distributed scheduling, and comprehensive monitoring.

## Features

### Core Scheduling
- **Cron Expressions**: Full 5-field cron syntax with ranges, steps, lists, and @shortcuts
- **Multiple Trigger Types**: Interval, Date, Calendar-based, Dependency, Compound, Adaptive, Random, Conditional, Exponential Backoff
- **Job Execution**: Thread/process pool execution with timeout enforcement and context passing
- **Concurrency Control**: Per-job limits, global concurrency management, rate control

### Advanced Capabilities
- **DAG Scheduling**: Define job dependencies as directed acyclic graphs with topological sorting
- **Distributed Scheduling**: Leader election, job locking, automatic failover across multiple nodes
- **Persistence**: File-based or in-memory job state and execution history storage
- **Monitoring**: Real-time metrics, health checks, job statistics, SLA tracking
- **Resilience**: Job retries with exponential backoff, failure recovery, graceful shutdown

### Business Features
- **Business Calendar**: Working day/hour calculations with holiday support
- **Rate Control**: Execution windows, blackout periods, per-job-type concurrency limits
- **Job History**: Complete execution history with results and error tracking
- **Event System**: Extensible callback system for job lifecycle events

## Architecture

### Core Components

```
scheduler_deep/
├── __init__.py              # Package exports
├── _types.py               # Data classes (Job, Trigger, Config, etc.)
├── _exceptions.py          # Custom exceptions
├── scheduler.py            # Main Scheduler class (~600 lines)
├── cron.py                 # Cron expression parser/evaluator (~500 lines)
├── triggers.py             # Trigger implementations (~400 lines)
├── executor.py             # Job execution engine (~400 lines)
├── dag.py                  # DAG scheduling (~500 lines)
├── calendar.py             # Business calendar (~350 lines)
├── persistence.py          # State persistence (~350 lines)
├── monitoring.py           # Metrics and monitoring (~300 lines)
├── distributed.py          # Distributed coordination (~350 lines)
└── rate_control.py         # Rate limiting (~250 lines)
```

## Usage Examples

### Basic Job Scheduling

```python
from thomas.scheduler_deep import Scheduler, IntervalTrigger
import time

# Create scheduler
scheduler = Scheduler()

# Define a job
def my_task():
    print("Task executed!")
    return "success"

# Add job with interval trigger (every 60 seconds)
trigger = IntervalTrigger(interval_seconds=60)
job = scheduler.add_job(my_task, trigger, name="my_job")

# Start scheduler
scheduler.start()

# Let it run...
time.sleep(120)

# Stop scheduler
scheduler.stop()
```

### Cron-Based Scheduling

```python
from thomas.scheduler_deep import Scheduler, CronTrigger

scheduler = Scheduler()

def scheduled_task():
    print("Running at 9 AM every weekday")

# Every weekday at 9 AM
trigger = CronTrigger("0 9 * * 1-5")
scheduler.add_job(scheduled_task, trigger, name="weekday_job")

scheduler.start()
```

### DAG-Based Job Dependencies

```python
from thomas.scheduler_deep import DAGScheduler, IntervalTrigger
from thomas.scheduler_deep._types import Job

dag = DAGScheduler()

def extract_data():
    return "raw_data"

def transform_data():
    return "transformed_data"

def load_data():
    return "loaded"

trigger = IntervalTrigger(3600)

# Create jobs
job_extract = Job(extract_data, trigger, job_id="extract")
job_transform = Job(transform_data, trigger, job_id="transform")
job_load = Job(load_data, trigger, job_id="load")

# Define dependencies: transform depends on extract, load depends on transform
dag.add_job(job_extract)
dag.add_job(job_transform, dependencies=["extract"])
dag.add_job(job_load, dependencies=["transform"])

# Get execution order
order = dag.get_topological_order()
print(order)  # ['extract', 'transform', 'load']
```

### Business Calendar Integration

```python
from thomas.scheduler_deep import Scheduler, CalendarTrigger
from thomas.scheduler_deep._types import Calendar
from datetime import date

# Create business calendar
calendar = Calendar(
    business_start_hour=9,
    business_end_hour=17,
    business_days={0, 1, 2, 3, 4},  # Monday-Friday
)

# Add holidays
calendar.add_holiday(date(2024, 12, 25))  # Christmas

scheduler = Scheduler()

def business_hours_task():
    print("Running during business hours")

trigger = CalendarTrigger(calendar)
scheduler.add_job(business_hours_task, trigger, name="business_task")

scheduler.start()
```

### Distributed Scheduling

```python
from thomas.scheduler_deep import Scheduler, DistributedScheduler, SchedulerConfig
import tempfile

# Create scheduler with distributed mode
config = SchedulerConfig(
    distributed_mode=True,
    max_concurrent_jobs=10,
)
scheduler = Scheduler(config)

# Distributed coordination uses file-based leader election
# Multiple nodes can share the same coordination directory
scheduler.start()

# Only the leader executes scheduled jobs
# Other nodes automatically failover if leader dies
```

### Monitoring and Metrics

```python
from thomas.scheduler_deep import Scheduler, IntervalTrigger

scheduler = Scheduler()

def task():
    return "result"

trigger = IntervalTrigger(10)
scheduler.add_job(task, trigger, name="monitored_job")

scheduler.start()

# Get metrics after some execution
metrics = scheduler.monitor.get_metrics()
print(f"Total executions: {metrics.total_executions}")
print(f"Success rate: {metrics.successful_executions / metrics.total_executions}")
print(f"Health: {metrics.health_status}")

# Get job-specific stats
stats = scheduler.monitor.get_job_stats("monitored_job")
if stats:
    print(f"Avg duration: {stats.avg_duration_seconds}s")
    print(f"Error rate: {stats.error_rate}")
```

### Rate Control and Throttling

```python
from thomas.scheduler_deep import RateControl, ExecutionWindow
from datetime import time

rate_control = RateControl(max_concurrent_jobs=5)

# Limit specific job type to 2 concurrent instances
rate_control.set_job_type_limit("import_jobs", 2)

# Define execution window (business hours)
window = ExecutionWindow(
    start_time=time(9, 0),
    end_time=time(17, 0),
    days_of_week={0, 1, 2, 3, 4}
)
rate_control.set_execution_window("background_task", window)

# Query status
print(f"Running: {rate_control.get_running_count()}")
print(f"Queued: {rate_control.get_queued_count()}")
```

### Job Retries with Exponential Backoff

```python
from thomas.scheduler_deep import Scheduler
from thomas.scheduler_deep.triggers import ExponentialBackoffTrigger

scheduler = Scheduler()

def unreliable_task():
    # Task that might fail
    raise Exception("Temporary failure")

# Exponential backoff: 1s, 2s, 4s, ... (max 60s)
trigger = ExponentialBackoffTrigger(
    initial_interval_seconds=1,
    multiplier=2.0,
    max_interval_seconds=60,
)

job = scheduler.add_job(
    unreliable_task,
    trigger,
    name="retry_job",
    max_retries=5,
)

scheduler.start()
```

## Job Types

### Trigger Types

1. **IntervalTrigger**: Fixed intervals with optional jitter
2. **CronTrigger**: Cron expression-based scheduling
3. **DateTrigger**: One-shot execution at specific datetime
4. **DependencyTrigger**: Execution after dependent jobs complete
5. **CalendarTrigger**: Business day/hour-based execution
6. **CompoundTrigger**: AND/OR combination of triggers
7. **ConditionalTrigger**: Condition function-based execution
8. **AdaptiveTrigger**: Adapts based on execution history
9. **RandomTrigger**: Random execution within window
10. **ExponentialBackoffTrigger**: Retry with exponential backoff

### Job Status

- `IDLE`: Ready to run
- `RUNNING`: Currently executing
- `SUCCESS`: Last execution succeeded
- `FAILED`: Last execution failed
- `PAUSED`: Execution paused by user
- `CANCELLED`: Job was cancelled

## Configuration

```python
from thomas.scheduler_deep import SchedulerConfig, Scheduler

config = SchedulerConfig(
    max_concurrent_jobs=10,           # Concurrent job limit
    job_timeout_seconds=3600,         # Job execution timeout
    persistence_enabled=True,         # Enable state persistence
    persistence_path="/var/lib/scheduler",
    max_history_records=10000,        # Keep last N execution records
    timezone="UTC",
    graceful_shutdown_timeout=30,     # Graceful shutdown timeout
    enable_monitoring=True,           # Enable metrics collection
    distributed_mode=False,           # Enable distributed scheduling
    leader_election_interval=10,      # Leader election frequency
    heartbeat_interval=5,             # Node heartbeat interval
    heartbeat_timeout=15,             # Heartbeat timeout
)

scheduler = Scheduler(config)
```

## Testing

The module includes 6 comprehensive test suites:

- `test_scheduler_cron.py`: Cron expression parsing and evaluation (181 lines)
- `test_scheduler_triggers.py`: All trigger types (241 lines)
- `test_scheduler_executor.py`: Job execution engine (248 lines)
- `test_scheduler_dag.py`: DAG scheduling and dependencies (281 lines)
- `test_scheduler_distributed.py`: Distributed coordination (247 lines)
- `test_scheduler_integration.py`: End-to-end integration (423 lines)

Run tests:
```bash
pytest thomas/scheduler_deep/test_*.py -v
```

## Implementation Details

### Cron Expression Parser
- Supports 5-field syntax: minute hour day month weekday
- Handles ranges (9-17), steps (*/15), lists (1,3,5)
- Includes @shortcuts: @yearly, @monthly, @daily, @hourly
- Proper timezone handling

### DAG Execution
- Topological sorting for execution order
- Cycle detection with detailed cycle path reporting
- Critical path calculation for SLA planning
- Parallel execution of independent jobs

### Distributed Scheduling
- File-based leader election for simplicity
- Job locking with expiration to prevent double execution
- Automatic node heartbeat monitoring
- Failover when leader becomes unavailable

### Job Persistence
- File-based or in-memory storage
- Complete job state serialization
- Execution history with results and errors
- Automatic cleanup of old history records

### Performance
- Thread pool executor for I/O-bound tasks
- Process pool executor for CPU-bound tasks
- Minimal lock contention with fine-grained locking
- Efficient scheduling with sleep-until-next calculation
- Configurable history limits to control memory usage

## Error Handling

- Comprehensive exception hierarchy
- Job execution errors don't crash scheduler
- Automatic retry with configurable limits
- Error tracking and reporting
- Health status monitoring

## Thread Safety

All components are thread-safe with:
- Fine-grained locking on shared data
- Safe concurrent job execution
- Thread-safe event callbacks
- No race conditions in job state updates

## Limitations & Future Work

- File-based distributed coordination doesn't scale to many nodes
- No built-in support for timezone conversion
- Limited support for complex time patterns
- No built-in monitoring dashboard
