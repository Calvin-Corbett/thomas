"""Service orchestrator with saga pattern and distributed transactions.

Provides saga pattern implementation, compensation strategies,
and distributed transaction coordination.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SagaStatus(Enum):
    """Saga execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"


class StepStatus(Enum):
    """Individual step status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class Step:
    """Single saga step."""

    name: str
    action: Callable
    compensation: Callable | None = None
    timeout_seconds: int = 30
    retry_count: int = 0
    status: StepStatus = StepStatus.PENDING
    error: str | None = None
    result: Any | None = None


@dataclass
class Saga:
    """Distributed saga execution."""

    saga_id: str
    name: str
    steps: list[Step] = field(default_factory=list)
    status: SagaStatus = SagaStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    error: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: Step) -> None:
        """Add step to saga."""
        self.steps.append(step)


class TransactionManager(ABC):
    """Base transaction manager."""

    @abstractmethod
    async def begin(self) -> str:
        """Begin transaction."""
        pass

    @abstractmethod
    async def commit(self, transaction_id: str) -> bool:
        """Commit transaction."""
        pass

    @abstractmethod
    async def rollback(self, transaction_id: str) -> bool:
        """Rollback transaction."""
        pass


class SagaExecutor:
    """Executes sagas with compensation support."""

    def __init__(self):
        self.sagas: dict[str, Saga] = {}
        self.compensation_history: dict[str, list[str]] = {}

    async def execute_saga(self, saga: Saga) -> Saga:
        """Execute saga with all steps."""
        saga.saga_id = str(uuid.uuid4())
        saga.status = SagaStatus.RUNNING
        self.sagas[saga.saga_id] = saga
        self.compensation_history[saga.saga_id] = []

        try:
            for step in saga.steps:
                step.status = StepStatus.RUNNING
                try:
                    step.result = await step.action()
                    step.status = StepStatus.SUCCESS
                    self.compensation_history[saga.saga_id].append(step.name)
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    saga.error = str(e)
                    saga.status = SagaStatus.FAILED

                    # Compensate
                    await self._compensate(saga)
                    saga.status = SagaStatus.FAILED
                    return saga

            saga.status = SagaStatus.COMPLETED
            saga.completed_at = datetime.utcnow()
            return saga

        except Exception as e:
            saga.status = SagaStatus.FAILED
            saga.error = str(e)
            return saga

    async def _compensate(self, saga: Saga) -> None:
        """Execute compensation for failed saga."""
        saga.status = SagaStatus.COMPENSATING

        # Compensate in reverse order
        completed_steps = self.compensation_history[saga.saga_id]

        for step_name in reversed(completed_steps):
            for step in saga.steps:
                if step.name == step_name and step.compensation:
                    try:
                        await step.compensation()
                        step.status = StepStatus.COMPENSATED
                    except Exception:
                        pass

    def get_saga(self, saga_id: str) -> Saga | None:
        """Retrieve saga by ID."""
        return self.sagas.get(saga_id)

    def get_saga_history(self, saga_id: str) -> list[str]:
        """Get compensation history for saga."""
        return self.compensation_history.get(saga_id, [])


class CompensationManager:
    """Manages compensation strategies."""

    def __init__(self):
        self.strategies: dict[str, Callable] = {}

    def register_strategy(self, name: str, handler: Callable) -> None:
        """Register compensation strategy."""
        self.strategies[name] = handler

    async def execute_compensation(self, strategy: str, context: dict[str, Any]) -> bool:
        """Execute compensation strategy."""
        if strategy not in self.strategies:
            return False

        try:
            await self.strategies[strategy](context)
            return True
        except Exception:
            return False

    def get_available_strategies(self) -> list[str]:
        """List available compensation strategies."""
        return list(self.strategies.keys())


class DistributedTransactionCoordinator:
    """Coordinates distributed transactions."""

    def __init__(self):
        self.transactions: dict[str, dict[str, Any]] = {}
        self.participants: dict[str, list[str]] = {}

    async def start_transaction(self, transaction_id: str, participants: list[str]) -> str:
        """Start distributed transaction."""
        self.transactions[transaction_id] = {
            "status": "active",
            "participants": participants,
            "created_at": datetime.utcnow(),
        }
        self.participants[transaction_id] = []
        return transaction_id

    async def prepare(self, transaction_id: str, participant: str) -> bool:
        """Prepare participant for commit."""
        if transaction_id not in self.transactions:
            return False

        self.participants[transaction_id].append(participant)
        return True

    async def commit_distributed(self, transaction_id: str) -> bool:
        """Commit distributed transaction."""
        if transaction_id not in self.transactions:
            return False

        self.transactions[transaction_id]["status"] = "committed"
        return True

    async def abort_distributed(self, transaction_id: str) -> bool:
        """Abort distributed transaction."""
        if transaction_id not in self.transactions:
            return False

        self.transactions[transaction_id]["status"] = "aborted"
        return True

    def get_transaction_status(self, transaction_id: str) -> str | None:
        """Get transaction status."""
        trans = self.transactions.get(transaction_id)
        return trans["status"] if trans else None
