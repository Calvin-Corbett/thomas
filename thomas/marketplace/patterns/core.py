"""Design patterns library (Factory, Observer, Strategy, Command, State Machine).

Provides common design pattern implementations for software architecture.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Optional


class Factory(ABC):
    """Base factory pattern."""

    @abstractmethod
    def create(self, product_type: str) -> Any:
        """Create product."""
        pass


class ConcreteFactory(Factory):
    """Concrete factory implementation."""

    def __init__(self):
        self.creators: dict[str, Callable] = {}

    def register(self, product_type: str, creator: Callable) -> None:
        """Register creator function."""
        self.creators[product_type] = creator

    def create(self, product_type: str) -> Any:
        """Create product by type."""
        creator = self.creators.get(product_type)
        if not creator:
            raise ValueError(f"Unknown product type: {product_type}")
        return creator()


class Observer(ABC):
    """Observer interface."""

    @abstractmethod
    def update(self, subject: "Subject", **kwargs) -> None:
        """Receive update from subject."""
        pass


class Subject:
    """Subject being observed."""

    def __init__(self):
        self._observers: list[Observer] = []

    def attach(self, observer: Observer) -> None:
        """Attach observer."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: Observer) -> None:
        """Detach observer."""
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, **kwargs) -> None:
        """Notify all observers."""
        for observer in self._observers:
            observer.update(self, **kwargs)


class Strategy(ABC):
    """Strategy interface."""

    @abstractmethod
    def execute(self, data: Any) -> Any:
        """Execute strategy."""
        pass


class Context:
    """Context for strategy execution."""

    def __init__(self, strategy: Strategy):
        self.strategy = strategy

    def set_strategy(self, strategy: Strategy) -> None:
        """Change strategy."""
        self.strategy = strategy

    def execute(self, data: Any) -> Any:
        """Execute current strategy."""
        return self.strategy.execute(data)


class Command(ABC):
    """Command interface."""

    @abstractmethod
    async def execute(self) -> Any:
        """Execute command."""
        pass

    @abstractmethod
    async def undo(self) -> Any:
        """Undo command."""
        pass


class CommandInvoker:
    """Command invoker."""

    def __init__(self):
        self.history: list[Command] = []

    async def execute_command(self, command: Command) -> Any:
        """Execute command and record."""
        result = await command.execute()
        self.history.append(command)
        return result

    async def undo_last(self) -> bool:
        """Undo last command."""
        if not self.history:
            return False
        command = self.history.pop()
        await command.undo()
        return True

    async def undo_all(self) -> int:
        """Undo all commands."""
        count = 0
        while self.history:
            command = self.history.pop()
            await command.undo()
            count += 1
        return count


class State(ABC):
    """State interface."""

    @abstractmethod
    def handle(self, context: "StateMachine") -> None:
        """Handle state."""
        pass


class StateMachine:
    """State machine implementation."""

    def __init__(self, initial_state: State):
        self.current_state = initial_state
        self.state_history: list[State] = []

    def transition_to(self, state: State) -> None:
        """Transition to new state."""
        self.state_history.append(self.current_state)
        self.current_state = state

    def handle_event(self) -> None:
        """Handle event in current state."""
        self.current_state.handle(self)

    def get_history(self) -> list[State]:
        """Get state history."""
        return self.state_history.copy()


class Builder(ABC):
    """Builder pattern."""

    @abstractmethod
    def build(self) -> Any:
        """Build product."""
        pass


class ConcreteBuilder(Builder):
    """Concrete builder."""

    def __init__(self):
        self.product = {}

    def add_component(self, name: str, value: Any) -> "ConcreteBuilder":
        """Add component."""
        self.product[name] = value
        return self

    def build(self) -> dict[str, Any]:
        """Build product."""
        return self.product.copy()


class Singleton:
    """Singleton pattern."""

    _instance: Optional["Singleton"] = None

    def __new__(cls) -> "Singleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


class Adapter:
    """Adapter pattern for interface compatibility."""

    def __init__(self, adaptee: Any, interface_methods: dict[str, str]):
        self.adaptee = adaptee
        self.interface_methods = interface_methods

    def __getattr__(self, name: str) -> Callable:
        """Adapt method calls."""
        if name in self.interface_methods:
            method_name = self.interface_methods[name]
            return getattr(self.adaptee, method_name)
        return getattr(self.adaptee, name)


class Decorator(ABC):
    """Decorator pattern."""

    def __init__(self, component: Any):
        self.component = component

    @abstractmethod
    def operation(self) -> Any:
        """Perform operation."""
        pass


class DecoratorImpl(Decorator):
    """Concrete decorator."""

    def operation(self) -> Any:
        """Add behavior before delegating."""
        return self.component.operation()


class ChainOfResponsibility:
    """Chain of responsibility pattern."""

    def __init__(self):
        self.handlers: list[Callable] = []

    def add_handler(self, handler: Callable) -> None:
        """Add handler."""
        self.handlers.append(handler)

    async def process(self, request: Any) -> Any | None:
        """Process request through chain."""
        for handler in self.handlers:
            result = await handler(request)
            if result is not None:
                return result
        return None
