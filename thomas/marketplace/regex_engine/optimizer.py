"""
Regex optimization passes.

Applies various optimizations to reduce matching time and improve efficiency.
"""

from __future__ import annotations

from ._types import (
    Alternation,
    Anchor,
    ASTNode,
    CharClass,
    Concatenation,
    Group,
    Literal,
    Quantifier,
)


class RegexOptimizer:
    """Optimizes regex AST."""

    def __init__(self) -> None:
        """Initialize optimizer."""
        self.optimizations_applied = 0

    def optimize(self, ast: ASTNode) -> ASTNode:
        """Apply all optimization passes."""
        ast = self._optimize_node(ast)
        ast = self._simplify_quantifiers(ast)
        ast = self._remove_unnecessary_groups(ast)
        ast = self._simplify_alternation(ast)
        return ast

    def _optimize_node(self, node: ASTNode) -> ASTNode:
        """Recursively optimize a node."""
        if isinstance(node, Literal):
            return node

        elif isinstance(node, CharClass):
            return self._optimize_char_class(node)

        elif isinstance(node, Concatenation) or isinstance(node, Alternation):
            # Optimize children
            optimized_nodes = [self._optimize_node(child) for child in node.nodes]
            node.nodes = optimized_nodes
            return node

        elif isinstance(node, Quantifier) or isinstance(node, Group):
            node.node = self._optimize_node(node.node)
            return node

        else:
            return node

    def _optimize_char_class(self, node: CharClass) -> ASTNode:
        """Optimize character class."""
        # If negated character class is just [^...], keep as is
        # Could add more optimizations like simplifying ranges
        return node

    def _simplify_quantifiers(self, ast: ASTNode) -> ASTNode:
        """Simplify quantifier expressions."""
        if isinstance(ast, Quantifier):
            # Optimize the child first
            ast.node = self._simplify_quantifiers(ast.node)

            # {1,1} -> no quantifier
            if ast.min_count == 1 and ast.max_count == 1:
                self.optimizations_applied += 1
                return ast.node

            # {n,n} -> {n}
            if ast.min_count == ast.max_count:
                pass  # Already in simplified form

            return ast

        elif isinstance(ast, Concatenation) or isinstance(ast, Alternation):
            ast.nodes = [self._simplify_quantifiers(node) for node in ast.nodes]
            return ast

        elif isinstance(ast, Group):
            ast.node = self._simplify_quantifiers(ast.node)
            return ast

        else:
            return ast

    def _remove_unnecessary_groups(self, ast: ASTNode) -> ASTNode:
        """Remove non-capturing groups wrapping single elements."""
        if isinstance(ast, Group):
            if not ast.is_capturing:
                # Non-capturing group can sometimes be removed
                # But we need to be careful with precedence
                ast.node = self._remove_unnecessary_groups(ast.node)

            return ast

        elif isinstance(ast, Concatenation) or isinstance(ast, Alternation):
            ast.nodes = [self._remove_unnecessary_groups(node) for node in ast.nodes]
            return ast

        elif isinstance(ast, Quantifier):
            ast.node = self._remove_unnecessary_groups(ast.node)
            return ast

        else:
            return ast

    def _simplify_alternation(self, ast: ASTNode) -> ASTNode:
        """Simplify alternation expressions."""
        if isinstance(ast, Alternation):
            # Flatten nested alternations
            flattened = []
            for node in ast.nodes:
                if isinstance(node, Alternation):
                    flattened.extend(node.nodes)
                else:
                    flattened.append(node)

            if len(flattened) != len(ast.nodes):
                self.optimizations_applied += 1

            ast.nodes = flattened

            # Recursively optimize children
            ast.nodes = [self._simplify_alternation(node) for node in ast.nodes]

            return ast

        elif isinstance(ast, Concatenation):
            ast.nodes = [self._simplify_alternation(node) for node in ast.nodes]
            return ast

        elif isinstance(ast, Quantifier) or isinstance(ast, Group):
            ast.node = self._simplify_alternation(ast.node)
            return ast

        else:
            return ast

    def extract_literal_prefix(self, ast: ASTNode) -> str | None:
        """
        Extract common literal prefix for fast rejection.

        Returns the literal prefix that all matches must start with.
        """
        if isinstance(ast, Literal):
            return ast.char

        elif isinstance(ast, Concatenation):
            prefix = ""
            for node in ast.nodes:
                if isinstance(node, Literal):
                    prefix += node.char
                elif isinstance(node, Anchor) and node.anchor_type == "start":
                    continue
                else:
                    break
            return prefix if prefix else None

        elif isinstance(ast, Group):
            return self.extract_literal_prefix(ast.node)

        elif isinstance(ast, Alternation):
            # For alternation, find common prefix
            prefixes = [self.extract_literal_prefix(node) for node in ast.nodes]
            if not prefixes or any(p is None for p in prefixes):
                return None

            # Find longest common prefix
            if not prefixes:
                return None

            common = prefixes[0]
            for prefix in prefixes[1:]:
                if prefix is None:
                    return None
                # Find common prefix
                i = 0
                while i < len(common) and i < len(prefix) and common[i] == prefix[i]:
                    i += 1
                common = common[:i]

            return common if common else None

        else:
            return None

    def is_anchored_start(self, ast: ASTNode) -> bool:
        """Check if regex is anchored to start."""
        if isinstance(ast, Anchor):
            return ast.anchor_type == "start"

        elif isinstance(ast, Concatenation):
            if not ast.nodes:
                return False
            return self.is_anchored_start(ast.nodes[0])

        elif isinstance(ast, Group):
            return self.is_anchored_start(ast.node)

        else:
            return False

    def is_anchored_end(self, ast: ASTNode) -> bool:
        """Check if regex is anchored to end."""
        if isinstance(ast, Anchor):
            return ast.anchor_type == "end"

        elif isinstance(ast, Concatenation):
            if not ast.nodes:
                return False
            return self.is_anchored_end(ast.nodes[-1])

        elif isinstance(ast, Group):
            return self.is_anchored_end(ast.node)

        else:
            return False


def optimize(ast: ASTNode) -> ASTNode:
    """Apply regex optimizations."""
    optimizer = RegexOptimizer()
    return optimizer.optimize(ast)
