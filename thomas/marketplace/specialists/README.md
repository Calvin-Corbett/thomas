# Specialists - Sub-Agent Implementations

Specialists are sub-agents that handle specific types of work. The orchestrator delegates to them based on intent. Each has a narrow responsibility and a clear interface.

## What This Directory Does

When the orchestrator routes an intent, it looks up which specialist(s) can handle it and delegates via a binding contract. Specialists don't make routing decisions—they just execute their specialty. Think of them as task-specific workers with guardrails.

## The Five Core Specialists

| File | What It Does |
|---|---|
| `base.py` | BaseSpecialist interface—all specialists inherit from this |
| `reasoning.py` | Reasoning specialist—complex analysis, planning, deliberation |
| `coding.py` | Coding specialist—code generation, modification, debugging |
| `research.py` | Research specialist—web search, fact-finding, synthesis |
| `synthesis.py` | Synthesis specialist—combining outputs, summarization |
| `tools.py` | Tools specialist—executing built-in tools (file ops, database, shell, etc.) |

## Base Specialist Interface (base.py)

All specialists must implement this:

```python
class BaseSpecialist:
    """Base class for all specialists."""

    async def can_handle(self, route_decision: RouteDecision) -> bool:
        """Can this specialist handle this intent?"""
        pass

    async def execute(
        self,
        contract: DelegationContract,
        context: MemoryContext
    ) -> DelegationResult:
        """Execute the work. Must return DelegationResult."""
        pass

    def get_capability_tokens(self) -> list[CapabilityToken]:
        """What tools is this specialist allowed to use?"""
        pass
```

## How Specialists Work

1. **Receive a DelegationContract** from orchestrator
2. **Check constraints** (what tools are allowed, token budget)
3. **Execute the work** (call LLM, run tools, process data)
4. **Return a DelegationResult** (status, output, tokens used, errors)

Example:

```python
class ReasoningSpecialist(BaseSpecialist):
    async def execute(self, contract, context):
        # 1. Validate contract
        if contract.token_budget < 1000:
            return DelegationResult(
                status=SpecialistStatus.FAILED,
                errors=["Token budget too low"]
            )

        # 2. Do the work
        result = await self.llm_client.complete(
            prompt=...,
            max_tokens=contract.token_budget,
            thinking=True
        )

        # 3. Return result
        return DelegationResult(
            status=SpecialistStatus.DONE,
            output=result.text,
            tokens_used=result.usage.total_tokens
        )
```

## Current Specialist Capabilities

### reasoning.py
- Analyzes user intent
- Plans complex workflows
- Breaks down ambiguous requests
- Uses extended thinking for hard problems

### coding.py
- Generates code
- Fixes bugs
- Refactors code
- Reviews code quality

### research.py
- Searches the web
- Finds references
- Synthesizes research findings
- Fact-checks claims

### synthesis.py
- Combines outputs from multiple specialists
- Summarizes findings
- Creates final responses
- Formats output for user

### tools.py
- Executes built-in tools (file ops, database, shell, email, etc.)
- Checks capability tokens before execution
- Handles tool errors gracefully
- Reports tool results back

## Important: Capability Tokens

Each specialist declares what tools it's allowed to use:

```python
def get_capability_tokens(self) -> list[CapabilityToken]:
    return [
        CapabilityToken(
            tool_name="shell",
            allowed=True,
            constraints={"max_commands": 10}
        ),
        CapabilityToken(
            tool_name="database",
            allowed=True,
            constraints={"max_queries": 20, "read_only": True}
        ),
    ]
```

The orchestrator enforces these constraints. If a specialist tries to exceed them, execution fails.

## Common Mistakes

### ✗ Don't do this:

1. **Call other specialists directly** — Go through orchestrator delegation.
2. **Ignore the DelegationContract** — Token budgets and deadlines matter.
3. **Make routing decisions** — That's the orchestrator's job.
4. **Assume tools are available** — Check capability tokens first.
5. **Use unbounded loops** — Respect token budgets.

### ✓ Do this:

1. Inherit from `BaseSpecialist`
2. Implement `can_handle()`, `execute()`, `get_capability_tokens()`
3. Validate the contract at the start of `execute()`
4. Return a properly formed `DelegationResult`
5. Register in `orchestrator/registry.py`

## Adding a New Specialist

1. Create `thomas/specialists/my_specialist.py`:

```python
from thomas.marketplace.specialists.base import BaseSpecialist
from thomas.marketplace.orchestrator.protocol import DelegationContract, DelegationResult, SpecialistStatus

class MySpecialist(BaseSpecialist):
    async def can_handle(self, route_decision):
        return "my_keyword" in route_decision.intent.lower()

    async def execute(self, contract, context):
        # Do work here
        return DelegationResult(
            status=SpecialistStatus.DONE,
            output="result",
            tokens_used=100
        )

    def get_capability_tokens(self):
        return [...]
```

2. Register in `thomas/orchestrator/registry.py`:

```python
registry.register('my_task', MySpecialist)
```

3. Restart the server.

## Debugging Specialists

- Add logging to `execute()`:
  ```python
  import logging
  log = logging.getLogger(__name__)
  log.debug(f"Executing {contract.specialist_id}")
  ```

- Check `token_budget` constraints:
  ```python
  if tokens_used > contract.token_budget:
      log.warning("Exceeded token budget")
  ```

- Return detailed errors:
  ```python
  return DelegationResult(
      status=SpecialistStatus.FAILED,
      errors=[str(e) for e in exceptions]
  )
  ```

## For AI Agents

### To fix a broken specialist:
→ Check `can_handle()` (maybe it's not routing correctly)
→ Check `execute()` (maybe token budget is exceeded)
→ Check capability tokens (maybe a tool is disabled)

### To add a new tool to a specialist:
→ Add to `get_capability_tokens()` in that specialist
→ Check that `thomas/core/tool_factory.py` has the tool registered

### To adjust specialist priorities:
→ Edit the order in `orchestrator/registry.py`
→ Specialists are tried in order—first match wins

## See Also

- `thomas/orchestrator/protocol.py` — Contract types
- `thomas/orchestrator/registry.py` — Specialist registration
- `thomas/core/llm_client.py` — LLM access (call `LLMClient()`)
- `thomas/tools/*.py` — Available tools
