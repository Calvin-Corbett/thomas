# Thomas Agent Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

This module contains the core agent loop and tool execution logic. It is mission-critical and highly unstable — agents have a track record of making loop.py larger instead of splitting it.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Core
- **Depends On**: core, tools, memory, policy, learning
- **Health**: Yellow
- **Architecture Tier**: Must not import from extensions directly (except tools)

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size |
|------|-------|------------|
| `loop.py` | Exceeds 2500 lines | MUST SPLIT — approx 600-700 lines per file |
| `response_tone.py` | Exceeds 827 lines | MUST SPLIT — approx 400-500 lines per file |
| `swarm.py` | Exceeds 930 lines | MUST SPLIT — approx 500-600 lines per file |

## Rule 1: loop.py Is the Most Critical Split

**loop.py is 2500+ lines and MUST be split before any new features are added.**

Current structure (from architecture):
- Agent execution loop
- Tool handling
- Streaming and response generation
- Guidance logic

Suggested split strategy:
1. `loop_core.py` — Main AgentLoop class, init, boot (target: 600 lines)
2. `loop_execute.py` — Tool execution, handling, formatting (target: 700 lines)
3. `loop_guidance.py` — Guidance rules, policy enforcement, safety checks (target: 600 lines)
4. `loop_streaming.py` — Response streaming, token handling, output (target: 500 lines)

**YOU MAY NOT:**
- Add new functions to loop.py
- Extend existing functions without first planning the split
- Create "temporary" additions expecting the split later
- Modify tests to make them pass with the monolith

## Rule 2: response_tone.py Must Be Split

**response_tone.py exceeds 827 lines and must not grow.**

Suggested strategy:
1. `tone_definitions.py` — Tone constants, voice profiles, style definitions (target: 300 lines)
2. `tone_encoder.py` — Encoding logic, serialization, format conversion (target: 400 lines)
3. `tone_decoder.py` — Decoding, interpretation, matching (target: 130 lines)

## Rule 3: swarm.py Must Be Split

**swarm.py exceeds 930 lines and must not grow.**

Suggested strategy:
1. `swarm_core.py` — SwarmConfig, agent pool, coordination primitives (target: 400 lines)
2. `swarm_execution.py` — Parallel execution, synchronization, fan-out/fan-in (target: 350 lines)
3. `swarm_aggregation.py` — Response merging, conflict resolution, quorum logic (target: 180 lines)

## Rule 4: Swarm Mode Is Opt-In

- **Do NOT enable swarm mode by default.** Swarm mode is experimental and only enabled when explicitly requested.
- Verify the user actually requested swarm behavior before activating it.
- Document in code comments when swarm mode logic is activated.

## Rule 5: Exception Handling

All exception handlers must be specific. Follow the master guardrails Rule 3.

Common patterns in agent/:
- `except asyncio.CancelledError:` — Task cancellation
- `except ToolError:` — Tool execution failures (from tools module)
- `except PolicyViolation:` — Policy enforcement blocks

**Never use bare `except:` or `except Exception:`**

## Rule 6: No New Circular Dependencies

Current known cycles in agent → core/tools/memory are acceptable. Do NOT add new cycles:
- ~~agent → browser~~ (banned)
- ~~agent → server~~ (banned, except via tools)
- ~~agent → cli~~ (banned)

## Rule 7: Module-Specific Import Rules

**agent MAY import:**
- core, tools, memory, policy, learning
- (tools may include browser, but agent must not import browser directly)

**agent MAY NOT import:**
- server (except through async middleware in tools)
- cli
- browser directly
- extensions except via tools

## Verification Checklist

Before committing any agent/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/agent/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Verify loop.py didn't grow
- [ ] Check: is this change a step toward splitting the monoliths, or adding to them?
- [ ] If extending loop.py, response_tone.py, or swarm.py: STOP and plan the split first
- [ ] All exception handlers are specific (no bare except)
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with agent/ changes. Format:

```markdown
### [Fixed] or [Changed] or [Added]
- agent: <brief description of what changed and why>
```

Example:
```markdown
### Fixed
- agent: Response tone encoder now handles whitespace in style definitions (fixes #1234)
```
