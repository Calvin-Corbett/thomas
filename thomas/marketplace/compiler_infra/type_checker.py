"""Type checker for the Thomas language."""

from __future__ import annotations

from ._exceptions import CompilerErrorCollector, TypeError
from ._types import (
    ArrayLit,
    ArrayType,
    AssignStmt,
    ASTVisitor,
    BinaryExpr,
    Block,
    BoolLit,
    BoolType,
    CallExpr,
    ExprStmt,
    FloatLit,
    FloatType,
    ForStmt,
    FuncDecl,
    FuncType,
    Identifier,
    IfStmt,
    IndexAssignStmt,
    IndexExpr,
    IntLit,
    IntType,
    NullLit,
    Program,
    ReturnStmt,
    StringLit,
    StringType,
    TokenType,
    Type,
    UnaryExpr,
    VarDecl,
    VoidType,
    WhileStmt,
)


class SymbolTable:
    """Symbol table with scope management."""

    def __init__(self) -> None:
        """Initialize the symbol table."""
        self.scopes: list[dict[str, Type]] = [{}]  # Global scope

    def push_scope(self) -> None:
        """Enter a new scope."""
        self.scopes.append({})

    def pop_scope(self) -> None:
        """Exit the current scope."""
        if len(self.scopes) > 1:
            self.scopes.pop()

    def define(self, name: str, var_type: Type) -> None:
        """Define a variable in the current scope."""
        self.scopes[-1][name] = var_type

    def lookup(self, name: str) -> Type | None:
        """Look up a variable in all scopes (from innermost to outermost)."""
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def is_defined_in_current_scope(self, name: str) -> bool:
        """Check if a variable is defined in the current scope only."""
        return name in self.scopes[-1]


class TypeChecker(ASTVisitor):
    """Type checking visitor for the AST."""

    def __init__(self) -> None:
        """Initialize the type checker."""
        self.symbol_table = SymbolTable()
        self.errors = CompilerErrorCollector()
        self.current_function: FuncDecl | None = None
        self.current_return_type: Type | None = None

    def check(self, program: Program) -> None:
        """Check types in the program.

        Args:
            program: The AST to check.

        Raises:
            CompilerError: If type errors are found.
        """
        program.accept(self)
        self.errors.raise_if_errors()

    def type_error(self, message: str, location) -> None:
        """Record a type error."""
        self.errors.add(TypeError(message, location))

    def visit_program(self, node: Program) -> Type | None:
        """Visit a program node."""
        # First pass: collect all function signatures
        for decl in node.declarations:
            if isinstance(decl, FuncDecl):
                params = tuple(ptype for _, ptype in decl.params)
                func_type = FuncType(params, decl.return_type)
                self.symbol_table.define(decl.name, func_type)

        # Second pass: check function bodies
        for decl in node.declarations:
            if isinstance(decl, FuncDecl) or isinstance(decl, VarDecl):
                decl.accept(self)

        return None

    def visit_func_decl(self, node: FuncDecl) -> Type | None:
        """Visit a function declaration."""
        old_func = self.current_function
        old_return_type = self.current_return_type

        self.current_function = node
        self.current_return_type = node.return_type

        self.symbol_table.push_scope()

        # Define parameters
        for param_name, param_type in node.params:
            self.symbol_table.define(param_name, param_type)

        # Check body
        node.body.accept(self)

        self.symbol_table.pop_scope()

        self.current_function = old_func
        self.current_return_type = old_return_type

        return None

    def visit_var_decl(self, node: VarDecl) -> Type | None:
        """Visit a variable declaration."""
        if self.symbol_table.is_defined_in_current_scope(node.name):
            self.type_error(f"Variable {node.name} already defined", node.location)

        if node.init_expr:
            init_type = node.init_expr.accept(self)
            if init_type and not self.is_assignable(node.var_type, init_type):
                self.type_error(f"Cannot assign {init_type} to {node.var_type}", node.init_expr.location)

        self.symbol_table.define(node.name, node.var_type)
        return None

    def visit_block(self, node: Block) -> Type | None:
        """Visit a block."""
        for stmt in node.statements:
            stmt.accept(self)
        return None

    def visit_if_stmt(self, node: IfStmt) -> Type | None:
        """Visit an if statement."""
        cond_type = node.condition.accept(self)
        if cond_type and not isinstance(cond_type, BoolType):
            self.type_error(f"Condition must be bool, got {cond_type}", node.condition.location)

        node.then_branch.accept(self)
        if node.else_branch:
            node.else_branch.accept(self)

        return None

    def visit_while_stmt(self, node: WhileStmt) -> Type | None:
        """Visit a while statement."""
        cond_type = node.condition.accept(self)
        if cond_type and not isinstance(cond_type, BoolType):
            self.type_error(f"Condition must be bool, got {cond_type}", node.condition.location)

        node.body.accept(self)
        return None

    def visit_for_stmt(self, node: ForStmt) -> Type | None:
        """Visit a for statement."""
        self.symbol_table.push_scope()

        if node.init:
            node.init.accept(self)

        if node.condition:
            cond_type = node.condition.accept(self)
            if cond_type and not isinstance(cond_type, BoolType):
                self.type_error(f"Condition must be bool, got {cond_type}", node.condition.location)

        if node.update:
            node.update.accept(self)

        node.body.accept(self)

        self.symbol_table.pop_scope()
        return None

    def visit_return_stmt(self, node: ReturnStmt) -> Type | None:
        """Visit a return statement."""
        if node.value:
            value_type = node.value.accept(self)
            if value_type and self.current_return_type:
                if not self.is_assignable(self.current_return_type, value_type):
                    self.type_error(
                        f"Cannot return {value_type}, expected {self.current_return_type}", node.value.location
                    )
        elif self.current_return_type and not isinstance(self.current_return_type, VoidType):
            self.type_error(f"Expected return value of type {self.current_return_type}", node.location)

        return None

    def visit_assign_stmt(self, node: AssignStmt) -> Type | None:
        """Visit an assignment statement."""
        var_type = self.symbol_table.lookup(node.target)
        if var_type is None:
            self.type_error(f"Undefined variable: {node.target}", node.location)
            return None

        value_type = node.value.accept(self)
        if value_type and not self.is_assignable(var_type, value_type):
            self.type_error(f"Cannot assign {value_type} to {var_type}", node.value.location)

        return None

    def visit_index_assign_stmt(self, node: IndexAssignStmt) -> Type | None:
        """Visit an array index assignment."""
        var_type = self.symbol_table.lookup(node.target)
        if var_type is None:
            self.type_error(f"Undefined variable: {node.target}", node.location)
            return None

        if not isinstance(var_type, ArrayType):
            self.type_error(f"Cannot index non-array type {var_type}", node.location)
            return None

        index_type = node.index.accept(self)
        if index_type and not isinstance(index_type, IntType):
            self.type_error(f"Array index must be int, got {index_type}", node.index.location)

        value_type = node.value.accept(self)
        if value_type and not self.is_assignable(var_type.element_type, value_type):
            self.type_error(f"Cannot assign {value_type} to {var_type.element_type}", node.value.location)

        return None

    def visit_expr_stmt(self, node: ExprStmt) -> Type | None:
        """Visit an expression statement."""
        node.expr.accept(self)
        return None

    def visit_binary_expr(self, node: BinaryExpr) -> Type | None:
        """Visit a binary expression."""
        left_type = node.left.accept(self)
        right_type = node.right.accept(self)

        if left_type is None or right_type is None:
            return None

        # Arithmetic operators
        if node.op in (TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            if isinstance(left_type, IntType) and isinstance(right_type, IntType):
                return IntType()
            elif isinstance(left_type, (IntType, FloatType)) and isinstance(right_type, (IntType, FloatType)):
                return FloatType()
            elif node.op == TokenType.PLUS and isinstance(left_type, StringType) and isinstance(right_type, StringType):
                return StringType()
            else:
                self.type_error(f"Cannot apply {node.op.name} to {left_type} and {right_type}", node.location)
                return None

        # Comparison operators
        if node.op in (TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE, TokenType.EQ, TokenType.NE):
            if (
                isinstance(left_type, (IntType, FloatType))
                and isinstance(right_type, (IntType, FloatType))
                or left_type == right_type
            ):
                return BoolType()
            else:
                self.type_error(f"Cannot compare {left_type} and {right_type}", node.location)
                return None

        # Logical operators
        if node.op in (TokenType.LOGICAL_AND, TokenType.LOGICAL_OR, TokenType.AND, TokenType.OR):
            if isinstance(left_type, BoolType) and isinstance(right_type, BoolType):
                return BoolType()
            else:
                self.type_error(
                    f"Logical operators require bool operands, got {left_type} and {right_type}", node.location
                )
                return None

        self.type_error(f"Unknown operator: {node.op.name}", node.location)
        return None

    def visit_unary_expr(self, node: UnaryExpr) -> Type | None:
        """Visit a unary expression."""
        operand_type = node.operand.accept(self)

        if operand_type is None:
            return None

        if node.op == TokenType.MINUS:
            if isinstance(operand_type, (IntType, FloatType)):
                return operand_type
            else:
                self.type_error(f"Cannot negate {operand_type}", node.location)
                return None

        if node.op in (TokenType.NOT,):
            if isinstance(operand_type, BoolType):
                return BoolType()
            else:
                self.type_error(f"Cannot apply NOT to {operand_type}", node.location)
                return None

        self.type_error(f"Unknown unary operator: {node.op.name}", node.location)
        return None

    def visit_call_expr(self, node: CallExpr) -> Type | None:
        """Visit a function call."""
        func_type = self.symbol_table.lookup(node.name)

        if func_type is None:
            self.type_error(f"Undefined function: {node.name}", node.location)
            return None

        if not isinstance(func_type, FuncType):
            self.type_error(f"{node.name} is not a function", node.location)
            return None

        if len(node.args) != len(func_type.param_types):
            self.type_error(
                f"{node.name} expects {len(func_type.param_types)} arguments, got {len(node.args)}", node.location
            )
            return None

        for i, arg in enumerate(node.args):
            arg_type = arg.accept(self)
            expected_type = func_type.param_types[i]
            if arg_type and not self.is_assignable(expected_type, arg_type):
                self.type_error(f"Argument {i+1} type {arg_type} cannot be assigned to {expected_type}", arg.location)

        return func_type.return_type

    def visit_index_expr(self, node: IndexExpr) -> Type | None:
        """Visit an array index expression."""
        var_type = self.symbol_table.lookup(node.target)

        if var_type is None:
            self.type_error(f"Undefined variable: {node.target}", node.location)
            return None

        if not isinstance(var_type, ArrayType):
            self.type_error(f"Cannot index non-array type {var_type}", node.location)
            return None

        index_type = node.index.accept(self)
        if index_type and not isinstance(index_type, IntType):
            self.type_error(f"Array index must be int, got {index_type}", node.index.location)

        return var_type.element_type

    def visit_array_lit(self, node: ArrayLit) -> Type | None:
        """Visit an array literal."""
        if not node.elements:
            return None  # Empty array type is ambiguous

        element_type = None
        for elem in node.elements:
            elem_type = elem.accept(self)
            if elem_type:
                if element_type is None:
                    element_type = elem_type
                elif element_type != elem_type:
                    # Try to find common type
                    if self.is_assignable(element_type, elem_type):
                        element_type = element_type
                    elif self.is_assignable(elem_type, element_type):
                        element_type = elem_type
                    else:
                        self.type_error(
                            f"Array elements must have consistent type, got {element_type} and {elem_type}",
                            elem.location,
                        )

        if element_type:
            return ArrayType(element_type)
        return None

    def visit_identifier(self, node: Identifier) -> Type | None:
        """Visit an identifier."""
        var_type = self.symbol_table.lookup(node.name)
        if var_type is None:
            self.type_error(f"Undefined variable: {node.name}", node.location)
            return None
        return var_type

    def visit_int_lit(self, node: IntLit) -> Type | None:
        """Visit an integer literal."""
        return IntType()

    def visit_float_lit(self, node: FloatLit) -> Type | None:
        """Visit a float literal."""
        return FloatType()

    def visit_string_lit(self, node: StringLit) -> Type | None:
        """Visit a string literal."""
        return StringType()

    def visit_bool_lit(self, node: BoolLit) -> Type | None:
        """Visit a boolean literal."""
        return BoolType()

    def visit_null_lit(self, node: NullLit) -> Type | None:
        """Visit a null literal."""
        return None  # null type

    def is_assignable(self, target_type: Type, source_type: Type) -> bool:
        """Check if source_type can be assigned to target_type."""
        if target_type == source_type:
            return True

        # Allow int to float conversion
        if isinstance(target_type, FloatType) and isinstance(source_type, IntType):
            return True

        # Allow null to any type
        if source_type is None:
            return True

        return False
