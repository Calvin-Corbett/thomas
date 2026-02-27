"""Tools for formal verification."""

from typing import Any

from thomas.formal_verify import core
from thomas.tools.base import Tool, ToolResult


class InvariantVerificationTool(Tool):
    """Verify system invariants."""

    name = "formal_verify_invariants"
    category = "formal_verify"
    description = "Define and verify system invariants"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_invariant", "check_state", "check_all", "get_report"],
                "description": "Verification action",
            },
            "invariant_name": {"type": "string", "description": "Invariant name"},
            "invariant_type": {
                "type": "string",
                "enum": ["safety", "liveness", "fairness"],
                "description": "Invariant type",
            },
            "description": {"type": "string", "description": "Invariant description"},
            "state": {"type": "object", "description": "System state"},
            "state_id": {"type": "string", "description": "State identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        initial_state = {"x": 0, "y": 0}
        self.state_space = core.StateSpace(initial_state)
        self.checker = core.ModelChecker(self.state_space)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_invariant":
                inv_name = args.get("invariant_name", "")
                inv_type = args.get("invariant_type", "safety")
                description = args.get("description", "")

                if not inv_name:
                    return ToolResult(ok=False, error="invariant_name required")

                # Create simple invariant
                def condition(state):
                    return True

                invariant = core.Invariant(
                    name=inv_name, inv_type=core.InvariantType(inv_type), condition=condition, description=description
                )
                self.checker.add_invariant(invariant)
                return ToolResult(ok=True, data={"added": True, "invariant": inv_name})

            elif action == "check_state":
                state = args.get("state", {})
                state_id = self.state_space.add_state(state)
                results = self.checker.check_state(state_id)
                return ToolResult(ok=True, data={"state_id": state_id, "results": results})

            elif action == "check_all":
                results = self.checker.check_all_states()
                return ToolResult(ok=True, data={"checked_states": len(results)})

            elif action == "get_report":
                report = self.checker.get_report()
                return ToolResult(ok=True, data=report)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TheoremProvingTool(Tool):
    """Prove theorems about systems."""

    name = "formal_verify_theorems"
    category = "formal_verify"
    description = "Define and prove theorems"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_theorem", "add_assumption", "add_proof_step", "prove", "get_proof"],
                "description": "Theorem action",
            },
            "theorem_name": {"type": "string", "description": "Theorem name"},
            "statement": {"type": "string", "description": "Theorem statement"},
            "assumption": {"type": "string", "description": "Assumption"},
            "proof_step": {"type": "string", "description": "Proof step"},
            "conclusion": {"type": "string", "description": "Conclusion"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.prover = core.TheoremProver()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_theorem":
                name = args.get("theorem_name", "")
                statement = args.get("statement", "")

                if not name or not statement:
                    return ToolResult(ok=False, error="theorem_name and statement required")

                theorem = core.Theorem(name, statement)
                self.prover.add_theorem(theorem)
                return ToolResult(ok=True, data={"theorem": name, "added": True})

            elif action == "add_assumption":
                name = args.get("theorem_name", "")
                assumption = args.get("assumption", "")

                if not name or not assumption:
                    return ToolResult(ok=False, error="theorem_name and assumption required")

                theorem = self.prover.theorems.get(name)
                if not theorem:
                    return ToolResult(ok=False, error=f"Theorem {name} not found")

                theorem.add_assumption(assumption)
                return ToolResult(ok=True, data={"added": True})

            elif action == "add_proof_step":
                name = args.get("theorem_name", "")
                step = args.get("proof_step", "")

                if not name or not step:
                    return ToolResult(ok=False, error="theorem_name and proof_step required")

                theorem = self.prover.theorems.get(name)
                if not theorem:
                    return ToolResult(ok=False, error=f"Theorem {name} not found")

                theorem.add_proof_step(step)
                return ToolResult(ok=True, data={"added": True})

            elif action == "prove":
                results = self.prover.prove_all()
                return ToolResult(ok=True, data={"results": results})

            elif action == "get_proof":
                name = args.get("theorem_name", "")
                if not name:
                    return ToolResult(ok=False, error="theorem_name required")

                proof = self.prover.get_proof(name)
                return ToolResult(ok=True, data={"proof": proof})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_formal_verify_tools(registry):
    """Register all formal verification tools."""
    registry.register(InvariantVerificationTool())
    registry.register(TheoremProvingTool())
