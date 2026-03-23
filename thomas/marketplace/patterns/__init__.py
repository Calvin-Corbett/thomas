"""Design patterns library.

Provides factory, observer, strategy, command, state machine,
builder, singleton, adapter, decorator, and chain of responsibility patterns.
"""

from .core import (
    Adapter,
    Builder,
    ChainOfResponsibility,
    Command,
    CommandInvoker,
    ConcreteBuilder,
    ConcreteFactory,
    Context,
    Decorator,
    DecoratorImpl,
    Factory,
    Observer,
    Singleton,
    State,
    StateMachine,
    Strategy,
    Subject,
)

__all__ = [
    "Factory",
    "ConcreteFactory",
    "Observer",
    "Subject",
    "Strategy",
    "Context",
    "Command",
    "CommandInvoker",
    "State",
    "StateMachine",
    "Builder",
    "ConcreteBuilder",
    "Singleton",
    "Adapter",
    "Decorator",
    "DecoratorImpl",
    "ChainOfResponsibility",
]

__version__ = "1.0.0"
