# Orchestrator - Thomas's Decision Brain

This is the **core delegation engine**. When Thomas receives a classified user intent, it routes to here. The orchestrator decides which specialist(s) to use, creates a binding contract with them, and validates their output.

## What This Directory Does

The orchestrator is Thomas's brain. It:
1. Receives a classified **RouteDecision** (from dispatch.py)
2. Looks up specialists that can handle it (from registry)
3. Creates a **DelegationContract** binding Thomas to the specialist
4. Delegates the work with token budgets and capability constraints
5. Validates the specialist's output
6. Synthesizes a final response

## Key Files

| File | Role |
|---|---|
| `brain.py` | **MAIN ENTRY POINT**. OrchestratorBrain class. Receives intent, delegates, validates. 30KB. |
| `protocol.py` | Contract types: DelegationContract, CapabilityToken, RouteDecision, SpecialistStatus |
| `registry.py` | Specialist registry. Maps capabilities to specialist classes. |
| `core.py` | Core structures and enums (token budgets, modes, priorities) |
| `tools.py` | Tool registration and capability binding for specialists |

## How It Works (The Contract Model)

```
dispatch.py classifies user intent
              ↓
          brain.py receives RouteDecision
              ↓
    registry.get_specialists(capability)
              ↓
    for each specialist:
        create DelegationContract {
            specialist_id: str
            capability: str
            token_budget: int
            constraints: CapabilityToken[]
            deadline: float
        }
              ↓
        specialist.execute(contract)
              ↓
        validate DelegationResult {
            status: SpecialistStatus
            output: str
            tokens_used: int
            errors: str[]
        }
              ↓
    synthesize final response
```

## Critical Types (protocol.py)

```python
class RouteDecision:
    """What dispatch.py sends to brain."""
    is_actionable: bool
    intent: str
    confidence: float

class DelegationContract:
    """Binding agreement between brain and specialist."""
    specialist_id: str
    capability: str
    token_budget: int  # Max tokens specialist can use
    constraints: list[CapabilityToken]  # What tools are allowed
    deadline: float  # Unix timestamp—must finish by then

class DelegationResult:
    """What specialist returns."""
    status: SpecialistStatus  # EXECUTING, DONE, FAILED, TIMEOUT
    output: str
    tokens_used: int
    errors: list[str]
    metadata: dict

class CapabilityToken:
    """Permission to use a tool."""
    tool_name: str
    allowed: bool
    constraints: dict  # Tool-specific limits
```

## Important: Monolith Loader

`brain.py` may be split into multiple `_part*.py` files. The loader uses `monolith_source_loader.py` to dynamically load them:

```python
# Inside brain.py stub:
from thomas.core.monolith_source_loader import load_source
exec(load_source('thomas.orchestrator.brain'))
```

**When you edit brain.py:**
1. Check if file is a stub or the full code
2. If stub, find and edit the `brain_part01.py`, `brain_part02.py` etc
3. Always clear `.pyc` files after editing
4. Restart the server

## Specialist Registry

The registry maps capabilities to specialist classes:

```python
registry = SpecialistRegistry()
registry.register('reasoning', ReasoningSpecialist)
registry.register('coding', CodingSpecialist)
registry.register('research', ResearchSpecialist)
registry.register('synthesis', SynthesisSpecialist)
registry.register('tools', ToolsSpecialist)
```

When you add a new specialist:
1. Implement `BaseSpecialist` interface (in `specialists/base.py`)
2. Add to registry in `registry.py`
3. Update `orchestrator/protocol.py` if you need new contract fields

## Token Budgets (core.py)

Thomas allocates tokens to specialists based on mode:

| Mode | Budget | Use Case |
|---|---|---|
| `fast` | 1,500 | Quick replies, no thinking |
| `auto` | 4,000 | Normal operation |
| `thinking` | 8,000 | Complex reasoning |
| `max` | 16,000 | Research, synthesis, max quality |

Set via `OrchestratorBrain(mode='thinking')`.

## Common Mistakes

### ✗ Don't do this:

1. **Calling specialist directly** — Always go through the contract model.
2. **Ignoring token budgets** — Specialists MUST respect the budget or face timeout.
3. **Assuming all routes are implemented** — Check `registry.py` first.
4. **Forgetting capability tokens** — If you add a new tool, update the token system.

### ✓ Do this:

1. Create a specialist that implements `BaseSpecialist`
2. Register it in `registry.py`
3. Update `protocol.py` if contract structure changes
4. Test with a unit test that verifies the contract is valid

## Execution Flow (in brain.py)

```python
async def delegate(self, route_decision: RouteDecision) -> str:
    """Main delegation flow."""
    # 1. Find matching specialists
    specialists = self.registry.get_specialists(route_decision.intent)

    # 2. For each specialist, create contract
    for specialist_cls in specialists:
        contract = DelegationContract(
            specialist_id=specialist_cls.__name__,
            capability=route_decision.intent,
            token_budget=self.mode_budgets[self.mode],
            constraints=self.get_capability_tokens(),
            deadline=time.time() + self.deadline_seconds
        )

        # 3. Execute specialist
        result = await specialist_cls.execute(contract)

        # 4. Validate result
        if result.status == SpecialistStatus.DONE:
            return result.output
        elif result.status == SpecialistStatus.FAILED:
            log.error(f"Specialist failed: {result.errors}")

    # 5. Fallback if all fail
    return self.synthesize_fallback_response()
```

## For AI Agents

### To change specialist routing:
→ Edit `registry.py` and `brain.py`'s delegation logic

### To add constraints to specialists:
→ Create new `CapabilityToken` in `protocol.py` and bind in `tools.py`

### To adjust token budgets:
→ Edit `_MODE_BUDGETS` in `core.py`

### To debug a specialist:
→ Add logging in `brain.py`'s `delegate()` method to trace execution

## See Also

- `thomas/specialists/base.py` — Base specialist interface
- `thomas/specialists/*.py` — Actual specialist implementations
- `docs/CHAT_EXECUTION_MODEL.md` — How this fits into overall chat architecture
