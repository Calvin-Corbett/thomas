from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from typing import Any


class SafeExpressionError(ValueError):
    """Raised when an expression is invalid or uses unsupported syntax."""


_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def evaluate_safe_expression(
    expr: str,
    *,
    names: Mapping[str, Any] | None = None,
    functions: Mapping[str, Callable[..., Any]] | None = None,
) -> Any:
    """Evaluate a restricted expression AST with explicit names/functions."""

    try:
        tree = ast.parse(str(expr or "").strip(), mode="eval")
    except SyntaxError as exc:
        raise SafeExpressionError(f"invalid expression: {exc.msg}") from exc
    return _eval_node(tree.body, names=dict(names or {}), functions=dict(functions or {}))


def _eval_node(node: ast.AST, *, names: Mapping[str, Any], functions: Mapping[str, Callable[..., Any]]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise SafeExpressionError(f"unknown name: {node.id}")
    if isinstance(node, ast.List):
        return [_eval_node(item, names=names, functions=functions) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, names=names, functions=functions) for item in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_node(item, names=names, functions=functions) for item in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _eval_node(key, names=names, functions=functions): _eval_node(value, names=names, functions=functions)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if fn is None:
            raise SafeExpressionError(f"unsupported operator: {type(node.op).__name__}")
        return fn(
            _eval_node(node.left, names=names, functions=functions),
            _eval_node(node.right, names=names, functions=functions),
        )
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if fn is None:
            raise SafeExpressionError(f"unsupported unary operator: {type(node.op).__name__}")
        return fn(_eval_node(node.operand, names=names, functions=functions))
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(item, names=names, functions=functions) for item in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise SafeExpressionError(f"unsupported boolean operator: {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, names=names, functions=functions)
        for op, comparator in zip(node.ops, node.comparators):
            fn = _COMPARE_OPS.get(type(op))
            if fn is None:
                raise SafeExpressionError(f"unsupported comparison operator: {type(op).__name__}")
            right = _eval_node(comparator, names=names, functions=functions)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise SafeExpressionError("only direct function calls are allowed")
        fn = functions.get(node.func.id)
        if fn is None:
            raise SafeExpressionError(f"unknown function: {node.func.id}")
        if node.keywords:
            raise SafeExpressionError("keyword arguments are not supported")
        args = [_eval_node(arg, names=names, functions=functions) for arg in node.args]
        return fn(*args)
    raise SafeExpressionError(f"unsupported expression node: {type(node).__name__}")
