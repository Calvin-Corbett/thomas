"""Template renderer for executing compiled templates."""

from __future__ import annotations

import html
from typing import Any

from ._exceptions import TemplateRuntimeError, UndefinedError
from ._types import (
    Block,
    Call,
    Context,
    Extends,
    FilterBlock,
    ForLoop,
    IfBlock,
    Include,
    RawBlock,
    Set,
    Template,
    TemplateConfig,
    TemplateNode,
    Text,
    UndefinedBehavior,
    Variable,
)


class LoopContext:
    """Context information for for-loops."""

    def __init__(self, iterable: list[Any]) -> None:
        """Initialize loop context."""
        self.iterable = iterable
        self.index = 0
        self.index0 = 0

    @property
    def first(self) -> bool:
        """Check if first iteration."""
        return self.index == 1

    @property
    def last(self) -> bool:
        """Check if last iteration."""
        return self.index == len(self.iterable)

    @property
    def length(self) -> int:
        """Get length of iterable."""
        return len(self.iterable)

    @property
    def index1(self) -> int:
        """Get 1-based index."""
        return self.index

    @property
    def revindex(self) -> int:
        """Get reverse index (1-based)."""
        return len(self.iterable) - self.index + 1

    @property
    def revindex0(self) -> int:
        """Get reverse index (0-based)."""
        return len(self.iterable) - self.index

    @property
    def depth(self) -> int:
        """Get nesting depth."""
        return len(self._depth_stack) if hasattr(self, "_depth_stack") else 1


class Renderer:
    """Renders template AST to string output."""

    def __init__(
        self,
        config: TemplateConfig,
        filters: dict[str, Any] | None = None,
        tests: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize renderer.

        Args:
            config: Template configuration
            filters: Available filters
            tests: Available test functions
        """
        self.config = config
        self.filters = filters or {}
        self.tests = tests or {}
        self.output = ""
        self.context: Context | None = None

    def render(
        self, ast: Template, context_vars: dict[str, Any], block_overrides: dict[str, list[TemplateNode]] | None = None
    ) -> str:
        """
        Render template AST with given context variables.

        Args:
            ast: Template AST to render
            context_vars: Variables for rendering

        Returns:
            Rendered template string
        """
        self.output = ""
        self.context = Context(variables=context_vars)
        if block_overrides:
            self.context.blocks.update(block_overrides)

        try:
            self._render_node(ast)
        except Exception as e:
            if isinstance(e, (UndefinedError, TemplateRuntimeError)):
                raise
            raise TemplateRuntimeError(str(e)) from e

        return self.output

    def _render_node(self, node: TemplateNode) -> None:
        """Render a single node."""
        if isinstance(node, Text):
            self._render_text(node)
        elif isinstance(node, Variable):
            self._render_variable(node)
        elif isinstance(node, ForLoop):
            self._render_for(node)
        elif isinstance(node, IfBlock):
            self._render_if(node)
        elif isinstance(node, Block):
            self._render_block(node)
        elif isinstance(node, Set):
            self._render_set(node)
        elif isinstance(node, Include):
            self._render_include(node)
        elif isinstance(node, FilterBlock):
            self._render_filter_block(node)
        elif isinstance(node, Template):
            self._render_template(node)
        elif isinstance(node, Call):
            self._render_call(node)
        elif isinstance(node, RawBlock):
            self._render_raw(node)
        elif isinstance(node, Extends):
            return
        else:
            raise TemplateRuntimeError(f"Unknown node type: {type(node)}")

    def _render_text(self, node: Text) -> None:
        """Render text node."""
        self.output += node.value

    def _render_variable(self, node: Variable) -> None:
        """Render variable expression."""
        value = self._resolve_variable(node.name)

        # Apply filters
        for filter_name, args in node.filters:
            if filter_name not in self.filters:
                raise TemplateRuntimeError(f"Filter not found: {filter_name}")

            filter_func = self.filters[filter_name]
            try:
                value = filter_func(value, *args)
            except Exception as e:
                raise TemplateRuntimeError(f"Filter error in {filter_name}: {e}") from e

        # Convert to string and handle escaping
        output = self._to_string(value)
        if self.config.autoescape and not self._is_safe(value):
            output = html.escape(output)

        self.output += output

    def _render_for(self, node: ForLoop) -> None:
        """Render for loop."""
        # Evaluate iterable expression
        iterable = self._evaluate_expression(node.iter)

        if not isinstance(iterable, (list, tuple, dict)):
            iterable = list(iterable) if hasattr(iterable, "__iter__") else [iterable]

        items = iterable if isinstance(iterable, list) else list(iterable)

        # Render loop body for each item
        for index, item in enumerate(items, 1):
            # Set loop variable
            self.context.set(node.target, item)

            # Set loop special variables
            loop_ctx = {
                "index": index,
                "index0": index - 1,
                "first": index == 1,
                "last": index == len(items),
                "length": len(items),
                "revindex": len(items) - index + 1,
                "revindex0": len(items) - index,
            }
            self.context.loop_stack.append(loop_ctx)
            self.context.set("loop", loop_ctx)

            for body_node in node.body:
                self._render_node(body_node)

            self.context.loop_stack.pop()

        # Render else clause if provided and iterable was empty
        if not items and node.orelse:
            for orelse_node in node.orelse:
                self._render_node(orelse_node)

    def _render_if(self, node: IfBlock) -> None:
        """Render if/elif/else block."""
        for condition, body in node.tests:
            if condition is None:
                # Else block - always render
                for body_node in body:
                    self._render_node(body_node)
                break
            elif self._evaluate_condition(condition):
                for body_node in body:
                    self._render_node(body_node)
                break

    def _render_block(self, node: Block) -> None:
        """Render named block."""
        # Store or use block override if available
        if self.context and node.name in self.context.blocks:
            for body_node in self.context.blocks[node.name]:
                self._render_node(body_node)
        else:
            for body_node in node.body:
                self._render_node(body_node)

    def _render_set(self, node: Set) -> None:
        """Render set statement (variable assignment)."""
        value = self._evaluate_expression(node.value)
        self.context.set(node.target, value)

    def _render_include(self, node: Include) -> None:
        """Render include (template include)."""
        # In a full implementation, this would load and render another template
        # For now, just a stub
        pass

    def _render_filter_block(self, node: FilterBlock) -> None:
        """Render filter block."""
        # Render body to buffer
        saved_output = self.output
        self.output = ""

        for body_node in node.body:
            self._render_node(body_node)

        buffered = self.output
        self.output = saved_output

        # Apply filter to buffer
        if node.name not in self.filters:
            raise TemplateRuntimeError(f"Filter not found: {node.name}")

        filter_func = self.filters[node.name]
        try:
            result = filter_func(buffered, *node.args)
        except Exception as e:
            raise TemplateRuntimeError(f"Filter error in {node.name}: {e}") from e

        self.output += self._to_string(result)

    def _render_call(self, node: Call) -> None:
        """Render macro call."""
        if node.name not in self.context.macros:
            raise TemplateRuntimeError(f"Macro not found: {node.name}")

        macro = self.context.macros[node.name]
        # Build arguments
        args = {}
        for i, arg in enumerate(node.args):
            if i < len(macro.args):
                args[macro.args[i]] = arg
        args.update(node.kwargs)

        # Add defaults
        for arg, default in macro.defaults.items():
            if arg not in args:
                args[arg] = default

        # Create new context for macro
        macro_ctx = self.context.push()
        macro_ctx.variables.update(args)

        saved_ctx = self.context
        self.context = macro_ctx

        for body_node in macro.body:
            self._render_node(body_node)

        self.context = saved_ctx

    def _render_template(self, node: Template) -> None:
        """Render template root node."""
        for body_node in node.body:
            self._render_node(body_node)

    def _render_raw(self, node: RawBlock) -> None:
        """Render raw block."""
        self.output += node.content

    def _resolve_variable(self, name: str) -> Any:
        """
        Resolve variable name with dot/bracket notation.

        Args:
            name: Variable name (e.g., 'a.b.c' or 'a["x"]')

        Returns:
            Resolved value
        """
        # Parse name into parts
        parts = self._parse_variable_name(name)
        obj = self.context.get(parts[0])

        if obj is None and self.config.undefined == UndefinedBehavior.STRICT:
            raise UndefinedError(f"Undefined variable: {parts[0]}")

        # Navigate through parts
        for part in parts[1:]:
            if obj is None:
                break

            if isinstance(part, str):
                # Attribute or dict key
                if isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    obj = getattr(obj, part, None)
            else:
                # Index
                try:
                    obj = obj[part]
                except (KeyError, IndexError, TypeError):
                    obj = None

        if obj is None:
            if self.config.undefined == UndefinedBehavior.STRICT:
                raise UndefinedError(f"Undefined: {name}")
            elif self.config.undefined == UndefinedBehavior.DEBUG:
                return f"{{{{ {name} }}}}"

        return obj

    def _evaluate_expression(self, expr: str) -> Any:
        """Evaluate an expression string."""
        # Simple expression evaluation
        expr = expr.strip()

        # Boolean literals
        if expr == "True":
            return True
        if expr == "False":
            return False
        if expr == "None":
            return None

        # String literals
        if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        # Number literals
        try:
            if "." in expr:
                return float(expr)
            return int(expr)
        except ValueError:
            pass

        # Variable reference
        return self._resolve_variable(expr)

    def _evaluate_test_call(self, value_expr: str, test_expr: str) -> bool:
        """Evaluate a registered template test expression."""
        value = self._evaluate_expression(value_expr)
        test_expr = test_expr.strip()
        test_name = test_expr
        test_args: list[Any] = []

        if test_expr.endswith(")") and "(" in test_expr:
            test_name, raw_args = test_expr.split("(", 1)
            raw_args = raw_args[:-1].strip()
            if raw_args:
                test_args = [self._evaluate_expression(part.strip()) for part in raw_args.split(",") if part.strip()]

        test_name = test_name.strip()
        if test_name not in self.tests:
            raise TemplateRuntimeError(f"Test not found: {test_name}")
        try:
            return bool(self.tests[test_name](value, *test_args))
        except Exception as e:
            raise TemplateRuntimeError(f"Test error in {test_name}: {e}") from e

    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a condition expression."""
        condition = condition.strip()

        if " is not " in condition:
            value_expr, test_expr = condition.split(" is not ", 1)
            return not self._evaluate_test_call(value_expr.strip(), test_expr.strip())

        if " is " in condition:
            value_expr, test_expr = condition.split(" is ", 1)
            return self._evaluate_test_call(value_expr.strip(), test_expr.strip())

        # Handle comparisons
        for op, op_name in [
            ("==", "eq"),
            ("!=", "ne"),
            ("<=", "le"),
            (">=", "ge"),
            ("<", "lt"),
            (">", "gt"),
        ]:
            if op in condition:
                left, right = condition.split(op, 1)
                left_val = self._evaluate_expression(left.strip())
                right_val = self._evaluate_expression(right.strip())

                if op == "==":
                    return left_val == right_val
                elif op == "!=":
                    return left_val != right_val
                elif op == "<":
                    return left_val < right_val
                elif op == "<=":
                    return left_val <= right_val
                elif op == ">":
                    return left_val > right_val
                elif op == ">=":
                    return left_val >= right_val

        # Handle 'in' operator
        if " in " in condition:
            item, container = condition.split(" in ", 1)
            item_val = self._evaluate_expression(item.strip())
            container_val = self._evaluate_expression(container.strip())
            return item_val in container_val

        # Handle 'and' operator
        if " and " in condition:
            parts = condition.split(" and ")
            return all(self._evaluate_condition(p.strip()) for p in parts)

        # Handle 'or' operator
        if " or " in condition:
            parts = condition.split(" or ")
            return any(self._evaluate_condition(p.strip()) for p in parts)

        # Handle 'not' operator
        if condition.startswith("not "):
            return not self._evaluate_condition(condition[4:].strip())

        # Single variable condition
        value = self._evaluate_expression(condition)
        return bool(value)

    def _parse_variable_name(self, name: str) -> list[str | int]:
        """Parse variable name into parts."""
        parts = []
        current = ""
        i = 0

        while i < len(name):
            if name[i] == ".":
                if current:
                    parts.append(current)
                current = ""
                i += 1
            elif name[i] == "[":
                if current:
                    parts.append(current)
                    current = ""
                # Extract bracket content
                j = i + 1
                while j < len(name) and name[j] != "]":
                    j += 1
                bracket_content = name[i + 1 : j]
                # Check if it's string or number
                if (
                    bracket_content.startswith('"')
                    and bracket_content.endswith('"')
                    or bracket_content.startswith("'")
                    and bracket_content.endswith("'")
                ):
                    parts.append(bracket_content[1:-1])
                else:
                    try:
                        parts.append(int(bracket_content))
                    except ValueError:
                        parts.append(bracket_content)
                i = j + 1
            else:
                current += name[i]
                i += 1

        if current:
            parts.append(current)

        return parts if parts else [""]

    def _to_string(self, value: Any) -> str:
        """Convert value to string."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            return str(value)
        return str(value)

    def _is_safe(self, value: Any) -> bool:
        """Check if value is marked as safe (should not be escaped)."""
        return hasattr(value, "__html__") or (isinstance(value, str) and hasattr(value, "_safe"))
