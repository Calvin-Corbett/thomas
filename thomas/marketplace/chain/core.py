"""LLM chain/pipeline system with prompt chains, memory, and tools.

Implements a system for chaining LLM calls together with state management.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ChainType(str, Enum):
    """Types of chains."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    LOOP = "loop"


@dataclass
class PromptTemplate:
    """A prompt template for LLM calls."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    template: str = ""
    variables: list[str] = field(default_factory=list)
    system_prompt: str | None = None

    def render(self, values: dict[str, str]) -> str:
        """Render the template with values."""
        result = self.template
        for var in self.variables:
            placeholder = "{" + var + "}"
            if var in values:
                result = result.replace(placeholder, str(values[var]))
        return result

    def validate(self, values: dict[str, Any]) -> list[str]:
        """Validate that all required variables are provided."""
        errors = []
        for var in self.variables:
            if var not in values:
                errors.append(f"Missing required variable: {var}")
        return errors


@dataclass
class ChainMemory:
    """Memory for chain execution."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list[dict[str, str]] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    max_messages: int = 100

    def add_message(self, role: str, content: str) -> None:
        """Add a message to memory."""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def get_messages(self) -> list[dict[str, str]]:
        """Get all messages."""
        return self.messages

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a variable."""
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable."""
        self.variables[name] = value

    def clear(self) -> None:
        """Clear all memory."""
        self.messages.clear()
        self.variables.clear()


class ChainStep:
    """A step in a chain."""

    def __init__(self, name: str, step_type: str = "llm"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.step_type = step_type
        self.inputs: list[str] = []
        self.outputs: list[str] = []
        self.config: dict[str, Any] = {}
        self.executed = False
        self.result: Any | None = None

    async def execute(self, memory: ChainMemory, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the step."""
        # Simulate LLM call
        output = {
            "step_id": self.id,
            "step_name": self.name,
            "status": "success",
            "result": f"Processed: {str(inputs)}",
        }
        self.result = output
        self.executed = True
        return output

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.step_type,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "executed": self.executed,
        }


class LLMChain:
    """A chain of LLM calls with memory and tools."""

    def __init__(self, name: str, chain_type: ChainType = ChainType.SEQUENTIAL):
        self.id = str(uuid.uuid4())
        self.name = name
        self.chain_type = chain_type
        self.steps: list[ChainStep] = []
        self.memory = ChainMemory()
        self.tools: dict[str, Callable] = {}
        self.execution_log: list[dict[str, Any]] = []

    def add_step(self, step: ChainStep) -> None:
        """Add a step to the chain."""
        self.steps.append(step)

    def register_tool(self, name: str, tool: Callable) -> None:
        """Register a tool for the chain."""
        self.tools[name] = tool

    def add_prompt_template(self, template: PromptTemplate) -> None:
        """Add a prompt template."""
        self.memory.set_variable(f"template_{template.id}", template)

    async def execute(self, initial_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute the chain."""
        inputs = initial_inputs or {}
        results = []

        if self.chain_type == ChainType.SEQUENTIAL:
            for step in self.steps:
                step_result = await step.execute(self.memory, inputs)
                results.append(step_result)
                inputs = step_result  # Use output as next input

        elif self.chain_type == ChainType.PARALLEL:
            import asyncio

            tasks = [step.execute(self.memory, inputs) for step in self.steps]
            results = await asyncio.gather(*tasks)

        self.execution_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "chain_type": self.chain_type.value,
                "steps_executed": len(self.steps),
                "results": results,
            }
        )

        return {"chain_id": self.id, "chain_name": self.name, "status": "success", "results": results}

    def get_execution_history(self) -> list[dict[str, Any]]:
        """Get execution history."""
        return self.execution_log

    def get_chain_structure(self) -> dict[str, Any]:
        """Get chain structure."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.chain_type.value,
            "steps": [step.to_dict() for step in self.steps],
            "tools": list(self.tools.keys()),
        }


class ChainRegistry:
    """Registry for managing chains."""

    def __init__(self):
        self.chains: dict[str, LLMChain] = {}
        self.templates: dict[str, PromptTemplate] = {}

    def register_chain(self, chain: LLMChain) -> None:
        """Register a chain."""
        self.chains[chain.id] = chain

    def get_chain(self, chain_id: str) -> LLMChain | None:
        """Get a chain by ID."""
        return self.chains.get(chain_id)

    def register_template(self, template: PromptTemplate) -> None:
        """Register a prompt template."""
        self.templates[template.id] = template

    def get_template(self, template_id: str) -> PromptTemplate | None:
        """Get a template by ID."""
        return self.templates.get(template_id)

    def list_chains(self) -> list[dict[str, Any]]:
        """List all chains."""
        return [
            {"id": chain.id, "name": chain.name, "type": chain.chain_type.value, "steps": len(chain.steps)}
            for chain in self.chains.values()
        ]

    def list_templates(self) -> list[dict[str, Any]]:
        """List all templates."""
        return [
            {"id": template.id, "name": template.name, "variables": template.variables}
            for template in self.templates.values()
        ]
