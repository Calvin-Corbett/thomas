"""Type system with Hindley-Milner type inference."""

from typing import Optional

from ._exceptions import SourceLocation, TypeError, UnificationError
from ._types import (
    ASTNode,
    BinaryOp,
    Block,
    DSLType,
    ForLoop,
    FunctionCall,
    FunctionType,
    Identifier,
    IfExpr,
    LambdaExpr,
    LetBinding,
    ListExpr,
    ListType,
    Literal,
    SimpleType,
    TypeVariable,
    UnaryOp,
    WhileLoop,
)


class TypeEnvironment:
    """Type environment for type checking and inference."""

    def __init__(self, parent: Optional["TypeEnvironment"] = None) -> None:
        """Initialize type environment.

        Args:
            parent: Parent environment for lexical scoping
        """
        self.parent = parent
        self.bindings: dict[str, DSLType] = {}
        self.var_counter = 0

    def define(self, name: str, type_: DSLType) -> None:
        """Define variable type.

        Args:
            name: Variable name
            type_: Type annotation
        """
        self.bindings[name] = type_

    def lookup(self, name: str) -> DSLType | None:
        """Look up variable type.

        Args:
            name: Variable name

        Returns:
            Type or None if not found
        """
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def fresh_var(self) -> TypeVariable:
        """Generate fresh type variable.

        Returns:
            New type variable
        """
        var = TypeVariable(f"t{self.var_counter}")
        self.var_counter += 1
        return var

    def child(self) -> "TypeEnvironment":
        """Create child environment.

        Returns:
            New child environment
        """
        return TypeEnvironment(self)


class Unifier:
    """Unification algorithm for type checking."""

    def __init__(self) -> None:
        """Initialize unifier."""
        self.substitution: dict[str, DSLType] = {}

    def unify(self, type1: DSLType, type2: DSLType, location: tuple[int, int] | None = None) -> None:
        """Unify two types.

        Args:
            type1: First type
            type2: Second type
            location: Optional source location

        Raises:
            UnificationError: If types cannot unify
        """
        t1 = self._deref(type1)
        t2 = self._deref(type2)

        # Same type
        if t1 == t2:
            return

        # Type variable cases
        if isinstance(t1, TypeVariable):
            if self._occurs_check(t1.name, t2):
                raise UnificationError(
                    str(t1),
                    str(t2),
                    SourceLocation("<input>", location[0] if location else 0, location[1] if location else 0)
                    if location
                    else None,
                )
            self.substitution[t1.name] = t2
            return

        if isinstance(t2, TypeVariable):
            if self._occurs_check(t2.name, t1):
                raise UnificationError(
                    str(t1),
                    str(t2),
                    SourceLocation("<input>", location[0] if location else 0, location[1] if location else 0)
                    if location
                    else None,
                )
            self.substitution[t2.name] = t1
            return

        # Function type
        if isinstance(t1, FunctionType) and isinstance(t2, FunctionType):
            if len(t1.arg_types) != len(t2.arg_types):
                raise UnificationError(
                    str(t1),
                    str(t2),
                    SourceLocation("<input>", location[0] if location else 0, location[1] if location else 0)
                    if location
                    else None,
                )
            for a1, a2 in zip(t1.arg_types, t2.arg_types):
                self.unify(a1, a2, location)
            if t1.return_type and t2.return_type:
                self.unify(t1.return_type, t2.return_type, location)
            return

        # List type
        if isinstance(t1, ListType) and isinstance(t2, ListType):
            self.unify(t1.element_type, t2.element_type, location)
            return

        # Cannot unify
        raise UnificationError(
            str(t1),
            str(t2),
            SourceLocation("<input>", location[0] if location else 0, location[1] if location else 0)
            if location
            else None,
        )

    def _deref(self, type_: DSLType) -> DSLType:
        """Dereference type variable.

        Args:
            type_: Type to dereference

        Returns:
            Dereferenced type
        """
        if isinstance(type_, TypeVariable):
            if type_.name in self.substitution:
                return self._deref(self.substitution[type_.name])
        return type_

    def _occurs_check(self, var_name: str, type_: DSLType) -> bool:
        """Check if variable occurs in type (prevent infinite types).

        Args:
            var_name: Variable name
            type_: Type to check

        Returns:
            True if variable occurs in type
        """
        type_ = self._deref(type_)

        if isinstance(type_, TypeVariable):
            return type_.name == var_name
        elif isinstance(type_, FunctionType):
            return any(self._occurs_check(var_name, arg) for arg in type_.arg_types) or (
                type_.return_type and self._occurs_check(var_name, type_.return_type)
            )
        elif isinstance(type_, ListType):
            return self._occurs_check(var_name, type_.element_type)
        return False

    def apply(self, type_: DSLType) -> DSLType:
        """Apply substitution to type.

        Args:
            type_: Type to apply substitution to

        Returns:
            Type with substitution applied
        """
        type_ = self._deref(type_)

        if isinstance(type_, TypeVariable):
            return type_
        elif isinstance(type_, FunctionType):
            new_args = [self.apply(arg) for arg in type_.arg_types]
            new_return = self.apply(type_.return_type) if type_.return_type else None
            return FunctionType(new_args, new_return)
        elif isinstance(type_, ListType):
            return ListType(self.apply(type_.element_type))
        return type_


class TypeInference:
    """Type inference using Hindley-Milner Algorithm W."""

    BUILTIN_TYPES = {
        "int": SimpleType("int"),
        "float": SimpleType("float"),
        "string": SimpleType("string"),
        "bool": SimpleType("bool"),
        "list": SimpleType("list"),
        "dict": SimpleType("dict"),
        "none": SimpleType("none"),
    }

    def __init__(self) -> None:
        """Initialize type inferencer."""
        self.unifier = Unifier()
        self.type_env = TypeEnvironment()

        # Define built-in types
        for name, type_ in self.BUILTIN_TYPES.items():
            self.type_env.define(name, type_)

    def infer(self, node: ASTNode) -> DSLType:
        """Infer type of AST node.

        Args:
            node: AST node

        Returns:
            Inferred type

        Raises:
            TypeError: If type checking fails
        """
        return self._infer_expr(node, self.type_env)

    def _infer_expr(self, node: ASTNode, env: TypeEnvironment) -> DSLType:
        """Infer type of expression.

        Args:
            node: Expression node
            env: Type environment

        Returns:
            Type of expression
        """
        if isinstance(node, Literal):
            return self._infer_literal(node)

        elif isinstance(node, Identifier):
            type_ = env.lookup(node.name)
            if type_ is None:
                type_ = env.fresh_var()
            return type_

        elif isinstance(node, BinaryOp):
            return self._infer_binary_op(node, env)

        elif isinstance(node, UnaryOp):
            return self._infer_unary_op(node, env)

        elif isinstance(node, FunctionCall):
            return self._infer_call(node, env)

        elif isinstance(node, IfExpr):
            cond_type = self._infer_expr(node.condition, env)
            self.unifier.unify(cond_type, SimpleType("bool"))

            then_type = self._infer_expr(node.then_expr, env)
            if node.else_expr:
                else_type = self._infer_expr(node.else_expr, env)
                self.unifier.unify(then_type, else_type)
            return then_type

        elif isinstance(node, ListExpr):
            if not node.elements:
                return ListType(env.fresh_var())

            elem_types = [self._infer_expr(elem, env) for elem in node.elements]
            for elem_type in elem_types[1:]:
                self.unifier.unify(elem_types[0], elem_type)

            return ListType(elem_types[0])

        elif isinstance(node, LambdaExpr):
            return self._infer_lambda(node, env)

        elif isinstance(node, LetBinding):
            val_type = self._infer_expr(node.value, env)
            child_env = env.child()
            child_env.define(node.name, val_type)
            return self._infer_expr(node.body, child_env)

        elif isinstance(node, Block):
            type_ = SimpleType("none")
            for stmt in node.statements:
                type_ = self._infer_expr(stmt, env)
            return type_

        elif isinstance(node, (WhileLoop, ForLoop)):
            return SimpleType("none")

        else:
            # Default to fresh type variable
            return env.fresh_var()

    def _infer_literal(self, node: Literal) -> DSLType:
        """Infer type of literal.

        Args:
            node: Literal node

        Returns:
            Type of literal
        """
        if node.value is None:
            return SimpleType("none")
        elif isinstance(node.value, bool):
            return SimpleType("bool")
        elif isinstance(node.value, int):
            return SimpleType("int")
        elif isinstance(node.value, float):
            return SimpleType("float")
        elif isinstance(node.value, str):
            return SimpleType("string")
        elif isinstance(node.value, list):
            return ListType(SimpleType("any"))
        else:
            return SimpleType("any")

    def _infer_binary_op(self, node: BinaryOp, env: TypeEnvironment) -> DSLType:
        """Infer type of binary operation.

        Args:
            node: Binary op node
            env: Type environment

        Returns:
            Type of operation
        """
        left_type = self._infer_expr(node.left, env)
        right_type = self._infer_expr(node.right, env)

        # Arithmetic operations
        if node.operator in ("+", "-", "*", "/", "%", "**"):
            self.unifier.unify(left_type, right_type)
            return left_type

        # Comparison operations
        elif node.operator in ("<", "<=", ">", ">=", "==", "!="):
            self.unifier.unify(left_type, right_type)
            return SimpleType("bool")

        # Logical operations
        elif node.operator in ("&&", "||"):
            self.unifier.unify(left_type, SimpleType("bool"))
            self.unifier.unify(right_type, SimpleType("bool"))
            return SimpleType("bool")

        # Bitwise operations
        elif node.operator in ("&", "|", "^", "<<", ">>"):
            self.unifier.unify(left_type, SimpleType("int"))
            self.unifier.unify(right_type, SimpleType("int"))
            return SimpleType("int")

        return env.fresh_var()

    def _infer_unary_op(self, node: UnaryOp, env: TypeEnvironment) -> DSLType:
        """Infer type of unary operation.

        Args:
            node: Unary op node
            env: Type environment

        Returns:
            Type of operation
        """
        operand_type = self._infer_expr(node.operand, env)

        if node.operator == "-":
            return operand_type
        elif node.operator == "!":
            self.unifier.unify(operand_type, SimpleType("bool"))
            return SimpleType("bool")
        elif node.operator == "~":
            self.unifier.unify(operand_type, SimpleType("int"))
            return SimpleType("int")

        return operand_type

    def _infer_call(self, node: FunctionCall, env: TypeEnvironment) -> DSLType:
        """Infer type of function call.

        Args:
            node: Function call node
            env: Type environment

        Returns:
            Return type of function
        """
        func_type = self._infer_expr(node.function, env)
        arg_types = [self._infer_expr(arg, env) for arg in node.arguments]

        return_var = env.fresh_var()

        if isinstance(func_type, FunctionType):
            if len(func_type.arg_types) != len(arg_types):
                raise TypeError(f"Function expects {len(func_type.arg_types)} args, got {len(arg_types)}")
            for param_type, arg_type in zip(func_type.arg_types, arg_types):
                self.unifier.unify(param_type, arg_type)

            return func_type.return_type if func_type.return_type else return_var

        # Assume it's a function
        return return_var

    def _infer_lambda(self, node: LambdaExpr, env: TypeEnvironment) -> DSLType:
        """Infer type of lambda expression.

        Args:
            node: Lambda node
            env: Type environment

        Returns:
            Function type
        """
        child_env = env.child()
        param_types = [env.fresh_var() for _ in node.parameters]

        for param_name, param_type in zip(node.parameters, param_types):
            child_env.define(param_name, param_type)

        if node.body:
            return_type = self._infer_expr(node.body, child_env)
        else:
            return_type = env.fresh_var()

        return FunctionType(param_types, return_type)
