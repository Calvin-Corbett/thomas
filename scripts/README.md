# Scripts - Automation and Workboard Tools

This directory contains standalone scripts for workboard management, task automation, release processes, code quality checks, and system administration.

## What This Directory Does

Scripts provide **automation and manual maintenance** for Thomas:

```
Scheduled or manual invocation
        ↓
    scripts/script.py
        ↓
Perform specialized task (workboard management, release, checks, etc.)
        ↓
Report results or make changes
```

## Script Categories

### Workboard and Task Management

| Script | Purpose |
|---|---|
| `workboard_task_manager.py` | Poll WORKBOARD.md, claim tasks, assign sub-tasks |
| `workboard_worker.py` | Execute commands assigned on workboard |
| `workboard_message.py` | Send messages between workboard agents |
| `workboard_swarm.py` | Launch multi-agent swarm from workboard |
| `forge/gates/workboard_claims.py` | Verify agent claims on workboard |
| `forge/gates/workboard_agent_claim.py` | Validate a specific agent's claim |
| `forge/gates/workboard_changed_files.py` | What files did workboard change |
| `forge/gates/workboard_task_problems.py` | Identify task failures on workboard |
| `forge/gates/workboard_claim_freshness.py` | Are workboard claims still valid |

### Quality and Compliance Checks

| Script | Purpose |
|---|---|
| `auto_checks.py` | Run all quality checks |
| `forge/gates/monolith_guard.py` | Verify monolith files are valid (Python split parts) |
| `forge/gates/monolith_filename_guard.py` | Monolith naming rules |
| `forge/gates/monolith_baseline_approval_gate.py` | Baseline size checks |
| `forge/gates/precommit_skip_policy.py` | Pre-commit hook enforcement |
| `forge/gates/deletions.py` | Verify deleted files are safe to delete |
| `forge/gates/release_hygiene.py` | Release process validation |
| `forge/gates/release_update_gate.py` | Version and changelog checks |
| `forge/gates/repo_hygiene.py` | General repository health |
| `forge/gates/placeholder_completion_policy.py` | Find incomplete placeholders |

### Features and Catalog

| Script | Purpose |
|---|---|
| `forge/gates/feature_registry.py` | Feature tracking |
| `forge/gates/feature_catalog_gate.py` | Catalog validation |
| `forge/gates/competitive_scope_gate.py` | Competitive feature analysis |
| `forge/gates/model_onboarding_gate.py` | LLM model onboarding |
| `forge/gates/module_audit_gate.py` | Module audit trail |

### Release and Identity

| Script | Purpose |
|---|---|
| `forge/gates/repo_identity.py` | Repository identity validation |
| `apply_release_lanes.ps1` | PowerShell: Apply release lanes |
| `apply_branch_protection.ps1` | PowerShell: Branch protection setup |
| `forge/gates/release_lane_policy.py` | Release lane enforcement |
| `agent_bootstrap_claim.py` | Agent initialization claim |
| `forge/gates/claim_integrity.py` | Validate agent claims |

### Visualization and Verification

| Script | Purpose |
|---|---|
| `forge/gates/site_visual_proof.py` | Visual regression testing |
| `forge/gates/surface_parity.py` | UI surface consistency |
| `forge/gates/core_overhead_guard.py` | Core system overhead monitoring |

### Utilities

| Script | Purpose |
|---|---|
| `audit_secrets.py` | Find exposed secrets |
| `audit_tool_sizes.py` | Tool size analysis |
| `forge/gates/chat_control_protocol.py` | Chat control verification |
| `forge/gates/competitor_freshness_guard.py` | Competitive intelligence freshness |
| `forge/gates/repl_scope.py` | REPL scope checking |
| `agent_identity.py` | Agent identity utilities |
| `append_handoff.py` | Append handoff messages |
| `active_folders.py` | Track active development folders |

### Bootstrap and Setup

| Script | Purpose |
|---|---|
| ootdoctor.ps1 | PowerShell: System diagnostics |
| gent_startup_router.py | Classify a task into the right startup lane |

## The WORKBOARD.md System

Scripts interact heavily with `plans/thomas/WORKBOARD.md`:

```markdown
## WORKBOARD.md Structure

### Up For Grabs
- chat-fix-bug-a3f2c1
  - title: Fix database bug
  - status: waiting
  - assigned: none

### Active Tasks
- chat-fix-bug-a3f2c1
  - status: in_progress
  - assigned: task-manager-agent
  - workers: [worker-1, worker-2]

### Completed
- chat-fix-bug-a3f2c1
  - status: done
  - result: Fixed connection pooling
```

## Key Scripts Deep Dive

### workboard_task_manager.py

Manages task lifecycle on WORKBOARD.md:

```python
# Load workboard
workboard = load_workboard()

# Find unclaimed tasks
unclaimed = workboard.find_tasks(status='waiting')

for task in unclaimed:
    # Claim it
    task.claim('task-manager-agent')

    # Break into sub-tasks if needed
    subtasks = analyze_task(task)
    for subtask in subtasks:
        task.add_subtask(subtask)

    # Assign to workers
    workers = assign_workers(subtasks)
    task.assign(workers)

    # Update status
    task.status = 'in_progress'

# Save workboard
save_workboard(workboard)
```

### workboard_worker.py

Executes commands assigned to it on workboard:

```python
# Poll for assigned tasks
while True:
    tasks = workboard.find_tasks(assigned_to=WORKER_ID)

    for task in tasks:
        try:
            # Execute the task
            result = execute(task.command)

            # Report back
            task.report_progress(50)
            task.report_progress(100)
            task.status = 'done'
            task.result = result

        except Exception as e:
            task.status = 'failed'
            task.error = str(e)

        # Save workboard
        save_workboard(workboard)
```

### check_monolith_guard.py

Verifies Python monolith files (split _partXX.py files) are valid:

```python
# Find all monolith stubs
stubs = find_monolith_stubs()

for stub in stubs:
    # Check corresponding parts exist
    parts = find_monolith_parts(stub)

    if not parts:
        raise ValidityError(f"{stub} has no parts!")

    # Verify parts load correctly
    try:
        code = load_monolith_source(stub)
        compile(code, stub, 'exec')
    except SyntaxError as e:
        raise ValidityError(f"{stub} parts have syntax error: {e}")

    print(f"✓ {stub}")
```

## Common Script Patterns

### Loading WORKBOARD.md

```python
import yaml

def load_workboard():
    with open('plans/thomas/WORKBOARD.md', 'r') as f:
        content = f.read()

    # Parse markdown + YAML frontmatter
    workboard = parse_workboard_md(content)
    return workboard
```

### Finding Files

```python
from pathlib import Path

# Find all Python files
python_files = Path('thomas').glob('**/*.py')

# Find monolith parts
monolith_parts = Path('thomas').glob('**/*_part[0-9]*.py')

# Find specific pattern
files = Path('thomas').glob('**/dispatch*.py')
```

### Running Checks

```python
def run_check(name, validator):
    try:
        issues = validator()
        if issues:
            for issue in issues:
                print(f"❌ {name}: {issue}")
            return False
        else:
            print(f"✓ {name}")
            return True
    except Exception as e:
        print(f"ERROR {name}: {e}")
        return False
```

## Common Mistakes

### ✗ Don't do this:

1. **Run scripts without understanding WORKBOARD** — It's the task queue.
2. **Edit WORKBOARD.md directly** — Let scripts manage it.
3. **Assume scripts are always up-to-date** — Check the script before running.
4. **Run release scripts locally** — They're for CI/CD.
5. **Ignore script output** — It tells you what happened.

### ✓ Do this:

1. Read the script docstring first
2. Understand what WORKBOARD changes it makes
3. Run in test mode first if available (`--dry-run`)
4. Check the output for errors
5. Save any important output (logs, reports)

## Running Scripts

### From command line:

```bash
python scripts/workboard_task_manager.py
python scripts/auto_checks.py --verbose
python scripts/forge/gates/monolith_guard.py --fix
```

### With options:

```bash
# Dry run (don't make changes)
python scripts/workboard_task_manager.py --dry-run

# Verbose output
python scripts/auto_checks.py -v

# Fix issues automatically
python scripts/forge/gates/monolith_guard.py --fix

# Specific checks only
python scripts/auto_checks.py --checks monolith,release
```

## Integration with CI/CD

Scripts are typically run in CI/CD pipelines:

1. Pre-commit hooks: `check_*.py` validators
2. Pull request checks: `auto_checks.py`
3. Release process: `check_release_*.py` and `apply_release_*.ps1`
4. Scheduled tasks: `workboard_task_manager.py` runs periodically

## For AI Agents

### To check system health:
```bash
python scripts/auto_checks.py
```

### To verify monolith integrity:
```bash
python scripts/forge/gates/monolith_guard.py
```

### To interact with workboard:
```python
from scripts.workboard_message import post_message

# Post status to workboard
post_message(
    task_id='chat-fix-bug-a3f2c1',
    message='Working on database connection pooling'
)
```

### To run all checks before commit:
```bash
python scripts/auto_checks.py --verbose
```

### To validate a release:
```bash
python scripts/forge/gates/release_hygiene.py
```

## Important Files Referenced

- `plans/thomas/WORKBOARD.md` — The task queue and agent coordination board
- `plans/thomas/worker_command_catalog.json` — Commands workers can execute
- `.pre-commit-config.yaml` — Pre-commit hooks (some scripts run here)

## See Also

- `docs/CHAT_EXECUTION_MODEL.md` — How workboard fits into chat flow
- `thomas/server/routes/task_events.py` — Watches workboard for UI updates
- `thomas/agent/chat_dispatcher.py` — Posts tasks to workboard from chat
