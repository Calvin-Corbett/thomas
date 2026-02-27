# Thomas CLI Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

CLI is the command-line interface and entry point for Thomas. It depends on nearly everything, making it the "hub" module. This creates pressure to add code to existing files instead of creating structured subcommands.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Core
- **Depends On**: core, agent, server, tools, memory, models, plugins, browser, companion, integrations, channels, nodes, messages, gateway, system, investigation, vision, security, codex, upgrade
- **Health**: Yellow
- **Architecture Burden**: Hub (depends on too much)

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `main.py` | Exceeds 1600 lines | Split to ~800 lines | Entry point, command registration |
| `parity_compat.py` | Exceeds 2100 lines | MUST SPLIT to ~700 lines | Legacy CLI compatibility layer |
| `parity_commands.py` | Exceeds 1000 lines | Split to ~700 lines | Parity command implementations |
| `commands/p###_*.py` | Numbered files | DO NOT CREATE | Legacy pattern, banned going forward |

## Rule 1: parity_compat.py Is CRITICAL

**parity_compat.py is 2100+ lines and MUST be split or eliminated.**

This file exists to provide backward compatibility with a legacy CLI. Before spending effort on it:

1. **Ask the user**: Should we keep parity compatibility at all?
2. If yes: Plan a split to ~700 lines per file
3. If no: Stub it to call the new CLI and deprecate it

If keeping it, suggested split:
1. `parity_compat_core.py` — Compatibility layer, command mapping (target: 600 lines)
2. `parity_compat_formatters.py` — Output formatting, legacy output structures (target: 700 lines)
3. `parity_compat_handlers.py` — Command handlers and dispatching (target: 800 lines)

**DO NOT extend parity_compat.py without explicit user approval.**

## Rule 2: main.py Must Be Split

**main.py is 1600+ lines and must not grow beyond 1200.**

Current structure (typical for Click CLI):
- Command registration
- Group initialization
- Global options
- Entry point setup
- Version handling

Suggested split strategy:
1. `main_entry.py` — Main entry point, boot logic, configuration (target: 400 lines)
2. `main_commands.py` — Command registration, Click groups (target: 600 lines)
3. `main_middleware.py` — Global options, logging, error handling (target: 300 lines)

## Rule 3: parity_commands.py Must Not Grow

**parity_commands.py is 1000+ lines.**

If you're adding to parity_commands.py, STOP and:
1. Check if this is actually a new command or a parity fix
2. If new command: Create it in `commands/<name>.py` with a descriptive name
3. If parity fix: Plan a split first

Suggested split:
1. `parity_commands_data.py` — Data commands (db, config, etc.) (target: 350 lines)
2. `parity_commands_agent.py` — Agent commands (run, serve, etc.) (target: 350 lines)
3. `parity_commands_tools.py` — Tool commands (execute, test, etc.) (target: 300 lines)

## Rule 4: No New Numbered Stub Files (p###_*.py)

**This is banned. Do not create files like:**
- `commands/p001_foo.py`
- `commands/p123_bar.py`
- Any `p\d{3}_*` pattern

This legacy pattern created chaos. Modern approach:

**Use descriptive names:**
- `commands/agent.py` — Agent control
- `commands/mission.py` — Mission management
- `commands/sandbox.py` — Sandbox execution
- `commands/project.py` — Project management

**If you see numbered files:**
1. Read the code to understand what it does
2. Rename it with a descriptive name
3. Update imports
4. Verify tests pass

## Rule 5: Click Command Structure

Every command must follow this pattern:

```python
@cli.group("mission")
def mission_group():
    """Mission management commands."""
    pass

@mission_group.command("create")
@click.argument("name")
@click.option("--param", help="Description", required=False)
def create_mission(name, param):
    """Create a new mission."""
    try:
        # Implementation
        click.echo(f"Created mission: {name}")
    except ClickException:
        raise  # Let Click handle it
    except Exception as e:
        logger.exception("Mission creation failed")
        raise click.ClickException(str(e))
```

## Rule 6: Exception Handling in CLI

All exception handlers must be specific. Follow the master guardrails Rule 3.

CLI-specific patterns:
- `except click.BadParameter:` — Argument/option validation
- `except click.ClickException:` — Click-managed errors (let it propagate)
- `except FileNotFoundError:` — File operations
- `except <DomainError>:` — Domain-specific failures

**Never use bare `except:` or silent failures:**
```python
# WRONG:
try:
    result = run_command()
except:
    pass  # Silent failure!

# RIGHT:
try:
    result = run_command()
except click.ClickException:
    raise  # Let Click handle
except Exception as e:
    logger.exception("Command failed")
    raise click.ClickException(f"Failed: {e}")
```

## Rule 7: Module-Specific Import Rules

**cli MAY import:**
- core, agent, server, tools, memory, models, plugins, browser, companion
- integrations, channels, nodes, messages, gateway, system, investigation, vision
- security, codex, upgrade
- (all listed in `depends_on`)

**cli MAY NOT import:**
- extensions not in `depends_on`
- domain-specific support modules (agriculture, climate, etc.)

## Rule 8: Dependency Inversion Issues

**Known problematic imports (tech debt):**
- cli → browser (`p015_browser_command_registry_scaffold.py`)
- cli → nodes (`p049` nodes module)

**When working in browser/nodes integration:**
- Check if the import is truly necessary
- If so, verify it's documented as tech debt in `_architecture.py`
- Plan to invert the dependency when possible

## Verification Checklist

Before committing any cli/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/cli/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check: did you extend main.py, parity_compat.py, or parity_commands.py? Plan a split first
- [ ] No new numbered stub files (p###_*.py)
- [ ] All exception handlers are specific and proper
- [ ] All Click commands use descriptive names
- [ ] Run `python -m thomas <command> --help` and verify output
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with cli/ changes. Format:

```markdown
### [Added] or [Changed] or [Fixed]
- cli: <brief description of what changed and why>
```

Example:
```markdown
### Added
- cli: New 'mission create' command for quick mission startup

### Fixed
- cli: 'serve' command now properly forwards SIGTERM to graceful shutdown
```
