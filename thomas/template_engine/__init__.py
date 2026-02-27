"""Template engine package."""

from ._exceptions import (
    CircularIncludeError,
    FilterNotFoundError,
    InheritanceError,
    LoopContextError,
    MacroError,
    TemplateError,
    TemplateRuntimeError,
    TemplateSyntaxError,
    TestNotFoundError,
    UndefinedError,
)
from ._types import (
    Block,
    Call,
    Context,
    Extends,
    FilterBlock,
    ForLoop,
    IfBlock,
    Include,
    Macro,
    RawBlock,
    Set,
    TemplateConfig,
    Token,
    TokenType,
    UndefinedBehavior,
    Variable,
)
from ._types import (
    Template as TemplateNode,
)
from .environment import (
    DictLoader,
    Environment,
    FileSystemLoader,
    PackageLoader,
    PrefixLoader,
    Template,
)
from .extensions import (
    AssetsExtension,
    CacheExtension,
    DebugExtension,
    ExtensionRegistry,
    I18nExtension,
    SafetyExtension,
)
from .filters import BUILTIN_FILTERS
from .inheritance import (
    BlockOverride,
    BlockRegistry,
    BlockScope,
    InheritanceChain,
    InheritanceProcessor,
    SuperBlock,
)
from .lexer import Lexer
from .parser import Parser
from .renderer import Renderer
from .tests_builtin import BUILTIN_TESTS

__version__ = "0.1.0"

__all__ = [
    # Exceptions
    "TemplateSyntaxError",
    "TemplateRuntimeError",
    "UndefinedError",
    "FilterNotFoundError",
    "TestNotFoundError",
    "LoopContextError",
    "InheritanceError",
    "MacroError",
    "CircularIncludeError",
    "TemplateError",
    # Types
    "Token",
    "TokenType",
    "TemplateNode",
    "Variable",
    "Block",
    "ForLoop",
    "IfBlock",
    "Include",
    "Macro",
    "Call",
    "FilterBlock",
    "Set",
    "Extends",
    "RawBlock",
    "Context",
    "TemplateConfig",
    "UndefinedBehavior",
    # Core
    "Lexer",
    "Parser",
    "Renderer",
    "Environment",
    "Template",
    # Loaders
    "FileSystemLoader",
    "DictLoader",
    "PackageLoader",
    "PrefixLoader",
    # Inheritance
    "BlockRegistry",
    "BlockScope",
    "BlockOverride",
    "InheritanceProcessor",
    "InheritanceChain",
    "SuperBlock",
    # Extensions
    "ExtensionRegistry",
    "I18nExtension",
    "DebugExtension",
    "CacheExtension",
    "AssetsExtension",
    "SafetyExtension",
    # Built-ins
    "BUILTIN_FILTERS",
    "BUILTIN_TESTS",
]
