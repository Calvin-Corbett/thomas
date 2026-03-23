"""Behavior Tree AI system with selector, sequence, and decorator nodes.

Implements a hierarchical behavior tree system for AI decision-making and planning.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeStatus(str, Enum):
    """Node execution status."""

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ExecutionContext:
    """Context for behavior tree execution."""

    tree_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    variables: dict[str, Any] = field(default_factory=dict)
    call_stack: list[str] = field(default_factory=list)
    execution_log: list[dict[str, Any]] = field(default_factory=list)
    max_depth: int = 100

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a context variable."""
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a context variable."""
        self.variables[name] = value

    def push_call(self, node_id: str) -> None:
        """Push a node onto the call stack."""
        if len(self.call_stack) >= self.max_depth:
            raise RuntimeError("Max recursion depth exceeded")
        self.call_stack.append(node_id)

    def pop_call(self) -> str | None:
        """Pop a node from the call stack."""
        if self.call_stack:
            return self.call_stack.pop()
        return None

    def log_event(self, node_id: str, status: NodeStatus, data: dict | None = None) -> None:
        """Log an execution event."""
        self.execution_log.append({"node_id": node_id, "status": status.value, "data": data or {}})


class BehaviorNode(ABC):
    """Base class for behavior tree nodes."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.parent: BehaviorNode | None = None
        self.children: list[BehaviorNode] = []

    @abstractmethod
    async def execute(self, context: ExecutionContext) -> NodeStatus:
        """Execute the node."""
        pass

    def add_child(self, child: "BehaviorNode") -> None:
        """Add a child node."""
        self.children.append(child)
        child.parent = self

    def remove_child(self, child: "BehaviorNode") -> bool:
        """Remove a child node."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return True
        return False

    def get_path(self) -> str:
        """Get the node's path in the tree."""
        if self.parent:
            return f"{self.parent.get_path()}/{self.name}"
        return f"/{self.name}"


class Selector(BehaviorNode):
    """Selector node - returns success if any child succeeds."""

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            for child in self.children:
                status = await child.execute(context)
                context.log_event(self.id, status, {"child": child.name})

                if status in (NodeStatus.SUCCESS, NodeStatus.RUNNING):
                    return status

            context.log_event(self.id, NodeStatus.FAILURE)
            return NodeStatus.FAILURE
        finally:
            context.pop_call()


class Sequence(BehaviorNode):
    """Sequence node - returns success only if all children succeed."""

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            for child in self.children:
                status = await child.execute(context)
                context.log_event(self.id, status, {"child": child.name})

                if status in (NodeStatus.FAILURE, NodeStatus.ERROR):
                    return status

                if status == NodeStatus.RUNNING:
                    return NodeStatus.RUNNING

            context.log_event(self.id, NodeStatus.SUCCESS)
            return NodeStatus.SUCCESS
        finally:
            context.pop_call()


class Parallel(BehaviorNode):
    """Parallel node - executes all children concurrently."""

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            import asyncio

            tasks = [child.execute(context) for child in self.children]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            statuses = []
            for result in results:
                if isinstance(result, Exception):
                    statuses.append(NodeStatus.ERROR)
                else:
                    statuses.append(result)

            context.log_event(self.id, NodeStatus.SUCCESS, {"statuses": [s.value for s in statuses]})

            if NodeStatus.ERROR in statuses:
                return NodeStatus.ERROR
            if all(s == NodeStatus.SUCCESS for s in statuses):
                return NodeStatus.SUCCESS
            if any(s == NodeStatus.RUNNING for s in statuses):
                return NodeStatus.RUNNING

            return NodeStatus.FAILURE
        finally:
            context.pop_call()


class Decorator(BehaviorNode):
    """Decorator node - wraps a child and modifies its behavior."""

    def __init__(self, name: str, child: BehaviorNode | None = None):
        super().__init__(name)
        if child:
            self.add_child(child)

    @abstractmethod
    async def _decorate(self, status: NodeStatus, context: ExecutionContext) -> NodeStatus:
        """Decorate the child's status."""
        pass

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            if not self.children:
                return NodeStatus.FAILURE

            child_status = await self.children[0].execute(context)
            result = await self._decorate(child_status, context)
            context.log_event(self.id, result)
            return result
        finally:
            context.pop_call()


class Inverter(Decorator):
    """Inverter decorator - flips success/failure."""

    async def _decorate(self, status: NodeStatus, context: ExecutionContext) -> NodeStatus:
        if status == NodeStatus.SUCCESS:
            return NodeStatus.FAILURE
        elif status == NodeStatus.FAILURE:
            return NodeStatus.SUCCESS
        return status


class Repeater(Decorator):
    """Repeater decorator - repeats child execution."""

    def __init__(self, name: str, child: BehaviorNode | None = None, times: int = 3):
        super().__init__(name, child)
        self.times = times
        self.count = 0

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            if not self.children:
                return NodeStatus.FAILURE

            self.count = 0
            for _ in range(self.times):
                status = await self.children[0].execute(context)
                self.count += 1
                if status == NodeStatus.FAILURE:
                    return NodeStatus.FAILURE

            return NodeStatus.SUCCESS
        finally:
            context.pop_call()


class Condition(BehaviorNode):
    """Condition node - checks a boolean condition."""

    def __init__(self, name: str, condition: Callable[[ExecutionContext], bool]):
        super().__init__(name)
        self.condition = condition

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            try:
                result = self.condition(context)
                status = NodeStatus.SUCCESS if result else NodeStatus.FAILURE
                context.log_event(self.id, status, {"condition_result": result})
                return status
            except Exception as e:
                context.log_event(self.id, NodeStatus.ERROR, {"error": str(e)})
                return NodeStatus.ERROR
        finally:
            context.pop_call()


class Action(BehaviorNode):
    """Action node - executes an async action."""

    def __init__(self, name: str, action: Callable[[ExecutionContext], Coroutine]):
        super().__init__(name)
        self.action = action

    async def execute(self, context: ExecutionContext) -> NodeStatus:
        context.push_call(self.id)
        try:
            try:
                result = await self.action(context)
                status = NodeStatus.SUCCESS if result else NodeStatus.FAILURE
                context.log_event(self.id, status, {"result": result})
                return status
            except Exception as e:
                context.log_event(self.id, NodeStatus.ERROR, {"error": str(e)})
                return NodeStatus.ERROR
        finally:
            context.pop_call()


class BehaviorTree:
    """Main behavior tree class."""

    def __init__(self, root: BehaviorNode, name: str = "tree"):
        self.root = root
        self.name = name
        self.id = str(uuid.uuid4())
        self.executions: list[ExecutionContext] = []

    async def execute(self, context: ExecutionContext | None = None) -> NodeStatus:
        """Execute the tree."""
        if context is None:
            context = ExecutionContext(tree_id=self.id)

        status = await self.root.execute(context)
        self.executions.append(context)
        return status

    def get_tree_structure(self) -> dict[str, Any]:
        """Get the tree structure as a dictionary."""
        return self._node_to_dict(self.root)

    def _node_to_dict(self, node: BehaviorNode) -> dict[str, Any]:
        """Convert a node to a dictionary."""
        return {
            "id": node.id,
            "name": node.name,
            "type": node.__class__.__name__,
            "children": [self._node_to_dict(child) for child in node.children],
        }

    def get_execution_log(self, execution_id: int = -1) -> list[dict[str, Any]]:
        """Get the execution log."""
        if execution_id < 0:
            execution_id = len(self.executions) + execution_id
        if 0 <= execution_id < len(self.executions):
            return self.executions[execution_id].execution_log
        return []

    def validate(self) -> list[str]:
        """Validate the tree structure."""
        errors = []
        visited = set()

        def visit(node: BehaviorNode, depth: int = 0) -> None:
            if node.id in visited:
                errors.append(f"Circular reference detected at node {node.name}")
                return
            visited.add(node.id)

            if depth > 100:
                errors.append(f"Tree depth exceeds maximum at node {node.name}")
                return

            for child in node.children:
                visit(child, depth + 1)

        visit(self.root)
        return errors
