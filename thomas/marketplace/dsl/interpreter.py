"""Tree-walking interpreter for DSL."""

import math
import operator
from dataclasses import dataclass
from typing import Any

from ._exceptions import (
    ArityError,
    BreakException,
    ContinueException,
    RecursionError,
    ReturnException,
    UndefinedVariable,
)
from ._exceptions import RuntimeError as DSLRuntimeError
from ._types import (
    Assignment,
    ASTNode,
    BinaryOp,
    Block,
    BreakExpr,
    ContinueExpr,
    DictExpr,
    DSLConfig,
    Environment,
    ForLoop,
    FunctionCall,
    FunctionDef,
    Identifier,
    IfExpr,
    IndexExpr,
    LambdaExpr,
    LetBinding,
    ListExpr,
    Literal,
    MatchExpr,
    ReturnExpr,
    UnaryOp,
    Value,
    WhileLoop,
)


@dataclass
class Closure:
    """Closure with captured environment."""

    params: list[str]
    body: ASTNode | None
    env: Environment

    def __call__(self, *args: Any) -> Value:
        """Call closure as function."""
        if len(args) != len(self.params):
            raise ArityError("<lambda>", len(self.params), len(args))
        # Call site will handle this via interpreter
        return self


class Interpreter:
    """Tree-walking interpreter with lexical scoping."""

    def __init__(self, config: DSLConfig | None = None) -> None:
        """Initialize interpreter.

        Args:
            config: DSL configuration
        """
        self.config = config or DSLConfig()
        self.global_env = Environment()
        self.current_env = self.global_env
        self.recursion_depth = 0
        self._setup_builtins()

    def _setup_builtins(self) -> None:
        """Setup built-in functions."""
        builtins = {
            "print": self._builtin_print,
            "len": self._builtin_len,
            "range": self._builtin_range,
            "map": self._builtin_map,
            "filter": self._builtin_filter,
            "reduce": self._builtin_reduce,
            "str": self._builtin_str,
            "int": self._builtin_int,
            "float": self._builtin_float,
            "bool": self._builtin_bool,
            "list": self._builtin_list,
            "dict": self._builtin_dict,
            "type": self._builtin_type,
            "abs": self._builtin_abs,
            "min": self._builtin_min,
            "max": self._builtin_max,
            "sum": self._builtin_sum,
            "sorted": self._builtin_sorted,
            "reverse": self._builtin_reverse,
            "zip": self._builtin_zip,
            "enumerate": self._builtin_enumerate,
            "sin": self._builtin_sin,
            "cos": self._builtin_cos,
            "sqrt": self._builtin_sqrt,
            "pow": self._builtin_pow,
            "log": self._builtin_log,
            "floor": self._builtin_floor,
            "ceil": self._builtin_ceil,
        }

        for name, func in builtins.items():
            self.global_env.define(name, func)

    def interpret(self, node: ASTNode) -> Value:
        """Interpret AST node.

        Args:
            node: Root AST node

        Returns:
            Result value

        Raises:
            RuntimeError: On execution errors
        """
        return self._eval(node, self.current_env)

    def _eval(self, node: ASTNode, env: Environment) -> Value:
        """Evaluate AST node.

        Args:
            node: Node to evaluate
            env: Environment

        Returns:
            Evaluated value
        """
        if isinstance(node, Literal):
            return node.value

        elif isinstance(node, Identifier):
            try:
                return env.get(node.name)
            except KeyError:
                raise UndefinedVariable(node.name)

        elif isinstance(node, BinaryOp):
            return self._eval_binary_op(node, env)

        elif isinstance(node, UnaryOp):
            return self._eval_unary_op(node, env)

        elif isinstance(node, FunctionCall):
            return self._eval_call(node, env)

        elif isinstance(node, Assignment):
            value = self._eval(node.value, env)
            if node.operator == "=":
                try:
                    env.set(node.target, value)
                except KeyError:
                    env.define(node.target, value)
            elif node.operator == "+=":
                current = env.get(node.target)
                env.set(node.target, current + value)
            elif node.operator == "-=":
                current = env.get(node.target)
                env.set(node.target, current - value)
            elif node.operator == "*=":
                current = env.get(node.target)
                env.set(node.target, current * value)
            elif node.operator == "/=":
                current = env.get(node.target)
                env.set(node.target, current / value)
            return value

        elif isinstance(node, IfExpr):
            cond = self._eval(node.condition, env)
            if self._is_truthy(cond):
                return self._eval(node.then_expr, env)
            elif node.else_expr:
                return self._eval(node.else_expr, env)
            return None

        elif isinstance(node, WhileLoop):
            result = None
            while self._is_truthy(self._eval(node.condition, env)):
                try:
                    result = self._eval(node.body, env)
                except BreakException:
                    break
                except ContinueException:
                    continue
            return result

        elif isinstance(node, ForLoop):
            iterable = self._eval(node.iterable, env)
            result = None
            for value in self._to_iterable(iterable):
                child_env = Environment(env)
                child_env.define(node.variable, value)
                try:
                    result = self._eval(node.body, child_env)
                except BreakException:
                    break
                except ContinueException:
                    continue
            return result

        elif isinstance(node, Block):
            result = None
            for stmt in node.statements:
                result = self._eval(stmt, env)
            return result

        elif isinstance(node, LetBinding):
            value = self._eval(node.value, env)
            child_env = Environment(env)
            child_env.define(node.name, value)
            return self._eval(node.body, child_env)

        elif isinstance(node, LambdaExpr):
            return Closure(node.parameters, node.body, env)

        elif isinstance(node, FunctionDef):
            closure = Closure(node.parameters, node.body, env)
            env.define(node.name, closure)
            return closure

        elif isinstance(node, MatchExpr):
            return self._eval_match(node, env)

        elif isinstance(node, IndexExpr):
            obj = self._eval(node.object, env)
            index = self._eval(node.index, env)
            if isinstance(obj, (list, str)):
                return obj[int(index)]
            elif isinstance(obj, dict):
                return obj[index]
            raise DSLRuntimeError(f"Cannot index {type(obj).__name__}")

        elif isinstance(node, ListExpr):
            return [self._eval(elem, env) for elem in node.elements]

        elif isinstance(node, DictExpr):
            result = {}
            for key_node, val_node in node.pairs:
                # Dict literals treat bare identifiers as string keys:
                # {a: 1} -> {"a": 1}
                if isinstance(key_node, Identifier):
                    key = key_node.name
                else:
                    key = self._eval(key_node, env)
                val = self._eval(val_node, env)
                result[key] = val
            return result

        elif isinstance(node, ReturnExpr):
            value = self._eval(node.value, env) if node.value else None
            raise ReturnException(value)

        elif isinstance(node, BreakExpr):
            raise BreakException()

        elif isinstance(node, ContinueExpr):
            raise ContinueException()

        return None

    def _eval_binary_op(self, node: BinaryOp, env: Environment) -> Value:
        """Evaluate binary operation.

        Args:
            node: Binary op node
            env: Environment

        Returns:
            Result value
        """
        left = self._eval(node.left, env)

        # Short-circuit evaluation for logical operators
        if node.operator == "&&":
            if not self._is_truthy(left):
                return left
            return self._eval(node.right, env)

        elif node.operator == "||":
            if self._is_truthy(left):
                return left
            return self._eval(node.right, env)

        right = self._eval(node.right, env)

        op_map = {
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv,
            "%": operator.mod,
            "**": operator.pow,
            "==": operator.eq,
            "!=": operator.ne,
            "<": operator.lt,
            "<=": operator.le,
            ">": operator.gt,
            ">=": operator.ge,
            "&": operator.and_,
            "|": operator.or_,
            "^": operator.xor,
            "<<": operator.lshift,
            ">>": operator.rshift,
        }

        if node.operator in op_map:
            return op_map[node.operator](left, right)

        raise DSLRuntimeError(f"Unknown operator: {node.operator}")

    def _eval_unary_op(self, node: UnaryOp, env: Environment) -> Value:
        """Evaluate unary operation.

        Args:
            node: Unary op node
            env: Environment

        Returns:
            Result value
        """
        operand = self._eval(node.operand, env)

        if node.operator == "-":
            return -operand
        elif node.operator == "!":
            return not self._is_truthy(operand)
        elif node.operator == "~":
            return ~int(operand)

        raise DSLRuntimeError(f"Unknown unary operator: {node.operator}")

    def _eval_call(self, node: FunctionCall, env: Environment) -> Value:
        """Evaluate function call.

        Args:
            node: Function call node
            env: Environment

        Returns:
            Return value of function
        """
        func = self._eval(node.function, env)
        args = [self._eval(arg, env) for arg in node.arguments]

        # Check recursion depth
        self.recursion_depth += 1
        if self.recursion_depth > self.config.max_recursion_depth:
            self.recursion_depth -= 1
            raise RecursionError()

        try:
            # Built-in function
            if callable(func) and not isinstance(func, Closure):
                result = func(*args)
            # Closure
            elif isinstance(func, Closure):
                if len(args) != len(func.params):
                    raise ArityError("<lambda>", len(func.params), len(args))
                # Create new environment with parameters
                call_env = Environment(func.env)
                for param, arg in zip(func.params, args):
                    call_env.define(param, arg)

                # Execute closure body
                try:
                    if func.body:
                        result = self._eval(func.body, call_env)
                    else:
                        result = None
                except ReturnException as e:
                    result = e.value

            else:
                raise DSLRuntimeError(f"Not callable: {type(func).__name__}")

        finally:
            self.recursion_depth -= 1

        return result

    def _eval_match(self, node: MatchExpr, env: Environment) -> Value:
        """Evaluate match expression.

        Args:
            node: Match node
            env: Environment

        Returns:
            Matched result
        """
        value = self._eval(node.expr, env)

        for pattern, result_expr in node.patterns:
            pattern_val = self._eval(pattern, env)
            if value == pattern_val:
                return self._eval(result_expr, env)

        if node.default:
            return self._eval(node.default, env)

        return None

    def _is_truthy(self, value: Value) -> bool:
        """Check if value is truthy.

        Args:
            value: Value to check

        Returns:
            True if truthy
        """
        if value is None or value is False:
            return False
        if value == 0 or value == "" or value == [] or value == {}:
            return False
        return True

    def _to_iterable(self, value: Value) -> list:
        """Convert value to iterable.

        Args:
            value: Value to convert

        Returns:
            List of values
        """
        if isinstance(value, (list, str)):
            return list(value)
        elif isinstance(value, dict):
            return list(value.keys())
        elif isinstance(value, range):
            return list(value)
        raise DSLRuntimeError(f"Not iterable: {type(value).__name__}")

    # Built-in functions
    def _builtin_print(self, *args: Any) -> None:
        """Print function."""
        print(*args)
        return None

    def _builtin_len(self, obj: Any) -> int:
        """Length function."""
        return len(obj)

    def _builtin_range(self, *args: Any) -> list:
        """Range function."""
        return list(range(*args))

    def _builtin_map(self, func: Closure, iterable: Any) -> list:
        """Map function."""
        result = []
        for item in self._to_iterable(iterable):
            result.append(self._eval_call(FunctionCall(Literal(func), [Literal(item)]), self.current_env))
        return result

    def _builtin_filter(self, func: Closure, iterable: Any) -> list:
        """Filter function."""
        result = []
        for item in self._to_iterable(iterable):
            cond = self._eval_call(FunctionCall(Literal(func), [Literal(item)]), self.current_env)
            if self._is_truthy(cond):
                result.append(item)
        return result

    def _builtin_reduce(self, func: Closure, iterable: Any, initial: Any = None) -> Any:
        """Reduce function."""
        items = self._to_iterable(iterable)
        if initial is None:
            if not items:
                raise DSLRuntimeError("Reduce of empty sequence")
            acc = items[0]
            items = items[1:]
        else:
            acc = initial

        for item in items:
            acc = self._eval_call(FunctionCall(Literal(func), [Literal(acc), Literal(item)]), self.current_env)
        return acc

    def _builtin_str(self, obj: Any) -> str:
        """String conversion."""
        return str(obj)

    def _builtin_int(self, obj: Any) -> int:
        """Integer conversion."""
        return int(obj)

    def _builtin_float(self, obj: Any) -> float:
        """Float conversion."""
        return float(obj)

    def _builtin_bool(self, obj: Any) -> bool:
        """Boolean conversion."""
        return self._is_truthy(obj)

    def _builtin_list(self, *args: Any) -> list:
        """List creation."""
        if args:
            return self._to_iterable(args[0])
        return []

    def _builtin_dict(self, *args: Any) -> dict:
        """Dict creation."""
        return {}

    def _builtin_type(self, obj: Any) -> str:
        """Type name."""
        return type(obj).__name__

    def _builtin_abs(self, obj: Any) -> Any:
        """Absolute value."""
        return abs(obj)

    def _builtin_min(self, *args: Any) -> Any:
        """Minimum value."""
        return min(args)

    def _builtin_max(self, *args: Any) -> Any:
        """Maximum value."""
        return max(args)

    def _builtin_sum(self, iterable: Any, start: Any = 0) -> Any:
        """Sum function."""
        return sum(self._to_iterable(iterable), start)

    def _builtin_sorted(self, iterable: Any) -> list:
        """Sorted function."""
        return sorted(self._to_iterable(iterable))

    def _builtin_reverse(self, iterable: Any) -> list:
        """Reverse function."""
        return list(reversed(self._to_iterable(iterable)))

    def _builtin_zip(self, *iterables: Any) -> list:
        """Zip function."""
        lists = [self._to_iterable(it) for it in iterables]
        return list(zip(*lists))

    def _builtin_enumerate(self, iterable: Any) -> list:
        """Enumerate function."""
        return list(enumerate(self._to_iterable(iterable)))

    def _builtin_sin(self, x: Any) -> float:
        """Sine function."""
        return math.sin(float(x))

    def _builtin_cos(self, x: Any) -> float:
        """Cosine function."""
        return math.cos(float(x))

    def _builtin_sqrt(self, x: Any) -> float:
        """Square root function."""
        return math.sqrt(float(x))

    def _builtin_pow(self, x: Any, y: Any) -> Any:
        """Power function."""
        return pow(x, y)

    def _builtin_log(self, x: Any, base: Any = math.e) -> float:
        """Logarithm function."""
        return math.log(float(x), float(base))

    def _builtin_floor(self, x: Any) -> int:
        """Floor function."""
        return math.floor(float(x))

    def _builtin_ceil(self, x: Any) -> int:
        """Ceiling function."""
        return math.ceil(float(x))
