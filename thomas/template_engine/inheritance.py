"""Template inheritance system."""

from __future__ import annotations

from typing import Any

from ._exceptions import InheritanceError
from ._types import Block, Extends, Template, TemplateNode


class BlockRegistry:
    """Registry for template blocks used in inheritance."""

    def __init__(self) -> None:
        """Initialize block registry."""
        self.blocks: dict[str, list[TemplateNode]] = {}
        self.parent_blocks: dict[str, list[TemplateNode]] = {}

    def register(self, name: str, nodes: list[TemplateNode]) -> None:
        """Register a block."""
        self.blocks[name] = nodes

    def register_parent(self, name: str, nodes: list[TemplateNode]) -> None:
        """Register parent block for super()."""
        self.parent_blocks[name] = nodes

    def get(self, name: str) -> list[TemplateNode]:
        """Get block nodes."""
        return self.blocks.get(name, [])

    def get_parent(self, name: str) -> list[TemplateNode]:
        """Get parent block nodes."""
        return self.parent_blocks.get(name, [])

    def has(self, name: str) -> bool:
        """Check if block exists."""
        return name in self.blocks


class InheritanceProcessor:
    """Process template inheritance chains."""

    def __init__(self, loader: Any) -> None:
        """
        Initialize processor.

        Args:
            loader: Template loader for loading parent templates
        """
        self.loader = loader
        self._processing: set[str] = set()

    def process(self, template: Template, registry: BlockRegistry) -> None:
        """
        Process template inheritance.

        Args:
            template: Template to process
            registry: Block registry to populate
        """
        self._extract_blocks(template.body, registry)

        # Find extends statement
        extends_node = self._find_extends(template.body)
        if extends_node:
            parent_template = self._load_parent(extends_node.parent)
            self._merge_inheritance(parent_template.body, template.body, registry)

    def _extract_blocks(self, body: list[TemplateNode], registry: BlockRegistry) -> None:
        """Extract block nodes from template body."""
        for node in body:
            if isinstance(node, Block):
                registry.register(node.name, node.body)
            elif hasattr(node, "body") and isinstance(node.body, list):
                self._extract_blocks(node.body, registry)

    def _find_extends(self, body: list[TemplateNode]) -> Extends | None:
        """Find extends node in template."""
        for node in body:
            if isinstance(node, Extends):
                return node
        return None

    def _load_parent(self, parent_name: str) -> Template:
        """Load parent template."""
        if parent_name in self._processing:
            raise InheritanceError(f"Circular inheritance: {parent_name}")

        self._processing.add(parent_name)
        try:
            source, filename = self.loader.get_source(parent_name)
            # Would need to parse the parent template
            # This is a simplified version
            return Template()
        finally:
            self._processing.discard(parent_name)

    def _merge_inheritance(
        self,
        parent_body: list[TemplateNode],
        child_body: list[TemplateNode],
        registry: BlockRegistry,
    ) -> None:
        """Merge child blocks into parent template."""
        # Extract child blocks
        child_blocks: dict[str, list[TemplateNode]] = {}
        for node in child_body:
            if isinstance(node, Block):
                child_blocks[node.name] = node.body

        # Register parent blocks
        for node in parent_body:
            if isinstance(node, Block) and node.name in child_blocks:
                registry.register_parent(node.name, node.body)

        # Override with child blocks
        for name, child_nodes in child_blocks.items():
            registry.register(name, child_nodes)


class BlockScope:
    """Scope for block-scoped variables."""

    def __init__(self, parent: BlockScope | None = None) -> None:
        """
        Initialize block scope.

        Args:
            parent: Parent scope
        """
        self.parent = parent
        self.variables: dict[str, Any] = {}

    def get(self, name: str, default: Any = None) -> Any:
        """Get variable from scope."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set variable in scope."""
        self.variables[name] = value

    def child(self) -> BlockScope:
        """Create child scope."""
        return BlockScope(parent=self)


class SuperBlock:
    """Represents the super() call in block overrides."""

    def __init__(self, parent_nodes: list[TemplateNode]) -> None:
        """
        Initialize super block.

        Args:
            parent_nodes: Parent block content
        """
        self.parent_nodes = parent_nodes

    def __call__(self) -> list[TemplateNode]:
        """Call to get parent nodes."""
        return self.parent_nodes


class BlockOverride:
    """Handles block override logic."""

    def __init__(self) -> None:
        """Initialize block override handler."""
        self.current_block: str | None = None
        self.override_stack: list[dict[str, list[TemplateNode]]] = []

    def push_override(self, overrides: dict[str, list[TemplateNode]]) -> None:
        """Push block overrides onto stack."""
        self.override_stack.append(overrides)

    def pop_override(self) -> dict[str, list[TemplateNode]]:
        """Pop block overrides from stack."""
        return self.override_stack.pop() if self.override_stack else {}

    def get_block(self, name: str) -> list[TemplateNode] | None:
        """Get block override."""
        if self.override_stack:
            return self.override_stack[-1].get(name)
        return None

    def has_override(self, name: str) -> bool:
        """Check if block is overridden."""
        return self.get_block(name) is not None


class InheritanceChain:
    """Represents a template inheritance chain."""

    def __init__(self, templates: list[str]) -> None:
        """
        Initialize inheritance chain.

        Args:
            templates: List of template names from child to parent
        """
        self.templates = templates
        self.length = len(templates)

    def get_parent(self, index: int) -> str | None:
        """Get parent template at index."""
        if 0 <= index < len(self.templates):
            return self.templates[index]
        return None

    def is_root(self, name: str) -> bool:
        """Check if template is root."""
        return self.templates[-1] == name if self.templates else False

    def resolve_mro(self) -> list[str]:
        """Resolve method resolution order."""
        # Simple MRO: just reverse the list (parent to child)
        return list(reversed(self.templates))
