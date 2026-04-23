"""Code generation utilities and tools for Thomas."""

from thomas.marketplace.codegen._types import CRUDOutput, GeneratedCode, GeneratedFile, ProjectScaffold
from thomas.marketplace.codegen.generator import CodeGenerator, CodeGeneratorError
from thomas.marketplace.codegen.templates import (
    CodeTemplate,
    TemplateRegistry,
    get_registry,
    get_template,
    list_templates,
)

__all__ = [
    "CodeGenerator",
    "CodeGeneratorError",
    "CodeTemplate",
    "TemplateRegistry",
    "GeneratedCode",
    "GeneratedFile",
    "ProjectScaffold",
    "CRUDOutput",
    "get_registry",
    "get_template",
    "list_templates",
]
