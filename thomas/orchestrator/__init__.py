"""Service orchestrator with saga pattern and distributed transactions.

Provides saga execution, compensation strategies, and 2PC
distributed transaction coordination.
"""

from .core import (
    CompensationManager,
    DistributedTransactionCoordinator,
    Saga,
    SagaExecutor,
    SagaStatus,
    Step,
    StepStatus,
    TransactionManager,
)

__all__ = [
    "SagaStatus",
    "StepStatus",
    "Step",
    "Saga",
    "TransactionManager",
    "SagaExecutor",
    "CompensationManager",
    "DistributedTransactionCoordinator",
]

__version__ = "1.0.0"
