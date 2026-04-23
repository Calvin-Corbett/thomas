"""AST optimizer for DSL."""

from dataclasses import replace
from typing import Any

from ._types import ASTNode, BinaryOp, Block, DictExpr, FunctionCall, IfExpr, ListExpr, Literal, UnaryOp


class ConstantFolder:
    """Constant folding optimization."""

    def fold(self, node: ASTNode) -> ASTNode:
        """Fold constants in AST.

        Args:
            node: AST node to fold

        Returns:
            Optimized node
        """
        if isinstance(node, BinaryOp):
            return self._fold_binary(node)
        elif isinstance(node, UnaryOp):
            return self._fold_unary(node)
        elif isinstance(node, IfExpr):
            return self._fold_if(node)
        elif isinstance(node, Block):
            stmts = [self.fold(stmt) for stmt in node.statements]
            return replace(node, statements=stmts)
        elif isinstance(node, ListExpr):
            elems = [self.fold(elem) for elem in node.elements]
            return replace(node, elements=elems)
        elif isinstance(node, DictExpr):
            pairs = [(self.fold(k), self.fold(v)) for k, v in node.pairs]
            return replace(node, pairs=pairs)
        elif isinstance(node, FunctionCall):
            func = self.fold(node.function)
            args = [self.fold(arg) for arg in node.arguments]
            return replace(node, function=func, arguments=args)
        return node

    def _fold_binary(self, node: BinaryOp) -> ASTNode:
        """Fold binary operation.

        Args:
            node: Binary op node

        Returns:
            Folded node or original
        """
        left = self.fold(node.left)
        right = self.fold(node.right)

        if isinstance(left, Literal) and isinstance(right, Literal):
            try:
                result = self._eval_binary(left.value, node.operator, right.value)
                return Literal(result, line=node.line, column=node.column)
            except Exception:
                pass

        return replace(node, left=left, right=right)

    def _fold_unary(self, node: UnaryOp) -> ASTNode:
        """Fold unary operation.

        Args:
            node: Unary op node

        Returns:
            Folded node or original
        """
        operand = self.fold(node.operand)

        if isinstance(operand, Literal):
            try:
                result = self._eval_unary(node.operator, operand.value)
                return Literal(result, line=node.line, column=node.column)
            except Exception:
                pass

        return replace(node, operand=operand)

    def _fold_if(self, node: IfExpr) -> ASTNode:
        """Fold if expression.

        Args:
            node: If expression

        Returns:
            Simplified node
        """
        cond = self.fold(node.condition)

        if isinstance(cond, Literal):
            if self._is_truthy(cond.value):
                return self.fold(node.then_expr)
            elif node.else_expr:
                return self.fold(node.else_expr)
            else:
                return Literal(None)

        then_expr = self.fold(node.then_expr)
        else_expr = self.fold(node.else_expr) if node.else_expr else None

        return replace(node, condition=cond, then_expr=then_expr, else_expr=else_expr)

    def _eval_binary(self, left: Any, op: str, right: Any) -> Any:
        """Evaluate binary operation on constants.

        Args:
            left: Left value
            op: Operator
            right: Right value

        Returns:
            Result
        """
        ops = {
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: a / b,
            "%": lambda a, b: a % b,
            "**": lambda a, b: a**b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "&": lambda a, b: a & b,
            "|": lambda a, b: a | b,
            "^": lambda a, b: a ^ b,
            "<<": lambda a, b: a << b,
            ">>": lambda a, b: a >> b,
        }

        if op in ops:
            return ops[op](left, right)
        raise ValueError(f"Unknown operator: {op}")

    def _eval_unary(self, op: str, value: Any) -> Any:
        """Evaluate unary operation on constant.

        Args:
            op: Operator
            value: Operand value

        Returns:
            Result
        """
        if op == "-":
            return -value
        elif op == "!":
            return not self._is_truthy(value)
        elif op == "~":
            return ~int(value)
        raise ValueError(f"Unknown operator: {op}")

    def _is_truthy(self, value: Any) -> bool:
        """Check if value is truthy.

        Args:
            value: Value

        Returns:
            True if truthy
        """
        if value is None or value is False:
            return False
        if value == 0 or value == "" or value == [] or value == {}:
            return False
        return True


class DeadCodeEliminator:
    """Remove unreachable code."""

    def eliminate(self, node: ASTNode) -> ASTNode:
        """Eliminate dead code.

        Args:
            node: AST node

        Returns:
            Optimized node
        """
        if isinstance(node, Block):
            return self._eliminate_block(node)
        elif isinstance(node, IfExpr):
            return self._eliminate_if(node)
        return node

    def _eliminate_block(self, node: Block) -> ASTNode:
        """Eliminate dead code in block.

        Args:
            node: Block node

        Returns:
            Optimized node
        """
        stmts = []
        for stmt in node.statements:
            stmts.append(self.eliminate(stmt))
            # Stop after return statements
            if isinstance(stmt, Literal) and stmt is node.statements[-1]:
                break

        return replace(node, statements=stmts)

    def _eliminate_if(self, node: IfExpr) -> ASTNode:
        """Eliminate dead code in if.

        Args:
            node: If expression

        Returns:
            Optimized node
        """
        cond = self.eliminate(node.condition)
        then_expr = self.eliminate(node.then_expr)
        else_expr = self.eliminate(node.else_expr) if node.else_expr else None

        return replace(node, condition=cond, then_expr=then_expr, else_expr=else_expr)


class StrengthReducer:
    """Strength reduction optimization."""

    def reduce(self, node: ASTNode) -> ASTNode:
        """Reduce operation strength.

        Args:
            node: AST node

        Returns:
            Optimized node
        """
        if isinstance(node, BinaryOp):
            return self._reduce_binary(node)
        elif isinstance(node, UnaryOp):
            return self._reduce_unary(node)
        return node

    def _reduce_binary(self, node: BinaryOp) -> ASTNode:
        """Reduce binary operation strength.

        Args:
            node: Binary op

        Returns:
            Optimized node
        """
        left = self.reduce(node.left)
        right = self.reduce(node.right)

        # x + 0 -> x
        if node.operator == "+" and isinstance(right, Literal) and right.value == 0:
            return left

        # 0 + x -> x
        if node.operator == "+" and isinstance(left, Literal) and left.value == 0:
            return right

        # x * 0 -> 0
        if node.operator == "*" and isinstance(right, Literal) and right.value == 0:
            return right

        # 0 * x -> 0
        if node.operator == "*" and isinstance(left, Literal) and left.value == 0:
            return left

        # x * 1 -> x
        if node.operator == "*" and isinstance(right, Literal) and right.value == 1:
            return left

        # 1 * x -> x
        if node.operator == "*" and isinstance(left, Literal) and left.value == 1:
            return right

        # x * 2 -> x + x (or x << 1)
        if node.operator == "*" and isinstance(right, Literal) and right.value == 2:
            return BinaryOp(left, "+", left, node.line, node.column)

        # x / 1 -> x
        if node.operator == "/" and isinstance(right, Literal) and right.value == 1:
            return left

        return replace(node, left=left, right=right)

    def _reduce_unary(self, node: UnaryOp) -> ASTNode:
        """Reduce unary operation strength.

        Args:
            node: Unary op

        Returns:
            Optimized node
        """
        operand = self.reduce(node.operand)

        # Double negation: -(-x) -> x
        if node.operator == "-" and isinstance(operand, UnaryOp) and operand.operator == "-":
            return operand.operand

        # Double negation: !(!x) -> x
        if node.operator == "!" and isinstance(operand, UnaryOp) and operand.operator == "!":
            return operand.operand

        return replace(node, operand=operand)


class Optimizer:
    """Main optimizer combining multiple passes."""

    def __init__(self) -> None:
        """Initialize optimizer."""
        self.folder = ConstantFolder()
        self.eliminator = DeadCodeEliminator()
        self.reducer = StrengthReducer()

    def optimize(self, node: ASTNode, passes: int = 3) -> ASTNode:
        """Run optimization passes.

        Args:
            node: AST node
            passes: Number of optimization passes

        Returns:
            Optimized node
        """
        current = node
        for _ in range(passes):
            prev = current
            current = self.folder.fold(current)
            current = self.eliminator.eliminate(current)
            current = self.reducer.reduce(current)

            if current == prev:
                break

        return current
