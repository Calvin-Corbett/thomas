"""Tests for the Thomas parser."""

import pytest

from ._types import (
    ArrayType,
    BinaryExpr,
    CallExpr,
    FloatType,
    FuncDecl,
    IfStmt,
    IntLit,
    IntType,
    Program,
    ReturnStmt,
    StringLit,
    TokenType,
    UnaryExpr,
    VarDecl,
    VoidType,
    WhileStmt,
)
from .lexer import Lexer
from .parser import Parser


class TestParserBasic:
    """Test basic parsing functionality."""

    def test_empty_program(self) -> None:
        """Test parsing an empty program."""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()
        assert isinstance(program, Program)
        assert len(program.declarations) == 0

    def test_parse_integer_literal(self) -> None:
        """Test parsing an integer literal."""
        lexer = Lexer("42")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, IntLit)
        assert expr.value == 42

    def test_parse_string_literal(self) -> None:
        """Test parsing a string literal."""
        lexer = Lexer('"hello"')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, StringLit)
        assert expr.value == "hello"


class TestParserTypes:
    """Test type annotation parsing."""

    def test_int_type(self) -> None:
        """Test parsing int type."""
        lexer = Lexer("int")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        type_anno = parser.parse_type()
        assert isinstance(type_anno, IntType)

    def test_float_type(self) -> None:
        """Test parsing float type."""
        lexer = Lexer("float")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        type_anno = parser.parse_type()
        assert isinstance(type_anno, FloatType)

    def test_array_type(self) -> None:
        """Test parsing array type."""
        lexer = Lexer("int[]")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        type_anno = parser.parse_type()
        assert isinstance(type_anno, ArrayType)
        assert isinstance(type_anno.element_type, IntType)

    def test_multidimensional_array_type(self) -> None:
        """Test parsing multidimensional array type."""
        lexer = Lexer("int[][]")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        type_anno = parser.parse_type()
        assert isinstance(type_anno, ArrayType)
        assert isinstance(type_anno.element_type, ArrayType)


class TestParserExpressions:
    """Test expression parsing."""

    def test_binary_addition(self) -> None:
        """Test parsing binary addition."""
        lexer = Lexer("1 + 2")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.PLUS

    def test_binary_subtraction(self) -> None:
        """Test parsing binary subtraction."""
        lexer = Lexer("5 - 3")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.MINUS

    def test_operator_precedence(self) -> None:
        """Test operator precedence."""
        lexer = Lexer("1 + 2 * 3")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        # Should be (1 + (2 * 3))
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.PLUS
        assert isinstance(expr.right, BinaryExpr)
        assert expr.right.op == TokenType.STAR

    def test_unary_negation(self) -> None:
        """Test parsing unary negation."""
        lexer = Lexer("-42")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, UnaryExpr)
        assert expr.op == TokenType.MINUS

    def test_unary_not(self) -> None:
        """Test parsing logical NOT."""
        lexer = Lexer("!true")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, UnaryExpr)
        assert expr.op == TokenType.NOT

    def test_parenthesized_expression(self) -> None:
        """Test parsing parenthesized expression."""
        lexer = Lexer("(1 + 2) * 3")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        # Should be ((1 + 2) * 3)
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.STAR
        assert isinstance(expr.left, BinaryExpr)
        assert expr.left.op == TokenType.PLUS


class TestParserFunctions:
    """Test function declaration parsing."""

    def test_simple_function(self) -> None:
        """Test parsing a simple function."""
        source = "fn add(x: int, y: int) -> int { return x + y; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        assert len(program.declarations) == 1
        func = program.declarations[0]
        assert isinstance(func, FuncDecl)
        assert func.name == "add"
        assert len(func.params) == 2
        assert func.params[0][0] == "x"
        assert isinstance(func.params[0][1], IntType)

    def test_function_no_return_type(self) -> None:
        """Test parsing function with no return type (void)."""
        source = "fn greet() { }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        assert isinstance(func, FuncDecl)
        assert isinstance(func.return_type, VoidType)


class TestParserStatements:
    """Test statement parsing."""

    def test_variable_declaration(self) -> None:
        """Test parsing variable declaration."""
        source = "let x: int = 42;"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        assert len(program.declarations) == 1
        var_decl = program.declarations[0]
        assert isinstance(var_decl, VarDecl)
        assert var_decl.name == "x"
        assert isinstance(var_decl.var_type, IntType)

    def test_if_statement(self) -> None:
        """Test parsing if statement."""
        source = "fn test() { if (x > 5) { return 1; } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        if_stmt = func.body.statements[0]
        assert isinstance(if_stmt, IfStmt)

    def test_if_else_statement(self) -> None:
        """Test parsing if-else statement."""
        source = "fn test() { if (x > 5) { return 1; } else { return 0; } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        if_stmt = func.body.statements[0]
        assert isinstance(if_stmt, IfStmt)
        assert if_stmt.else_branch is not None

    def test_while_statement(self) -> None:
        """Test parsing while statement."""
        source = "fn test() { while (x > 0) { x = x - 1; } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        while_stmt = func.body.statements[0]
        assert isinstance(while_stmt, WhileStmt)

    def test_for_statement(self) -> None:
        """Test parsing for statement."""
        source = "fn test() { for (let i: int = 0; i < 10; i = i + 1) { } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        for_stmt = func.body.statements[0]
        assert isinstance(for_stmt, WhileStmt) or hasattr(for_stmt, "condition")

    def test_return_statement(self) -> None:
        """Test parsing return statement."""
        source = "fn test() { return 42; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        return_stmt = func.body.statements[0]
        assert isinstance(return_stmt, ReturnStmt)


class TestParserFunctionCalls:
    """Test function call parsing."""

    def test_function_call_no_args(self) -> None:
        """Test parsing function call with no arguments."""
        lexer = Lexer("foo()")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, CallExpr)
        assert expr.name == "foo"
        assert len(expr.args) == 0

    def test_function_call_one_arg(self) -> None:
        """Test parsing function call with one argument."""
        lexer = Lexer("foo(42)")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, CallExpr)
        assert expr.name == "foo"
        assert len(expr.args) == 1

    def test_function_call_multiple_args(self) -> None:
        """Test parsing function call with multiple arguments."""
        lexer = Lexer("foo(1, 2, 3)")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, CallExpr)
        assert expr.name == "foo"
        assert len(expr.args) == 3


class TestParserArrays:
    """Test array-related parsing."""

    def test_array_literal(self) -> None:
        """Test parsing array literal."""
        lexer = Lexer("[1, 2, 3]")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        from ._types import ArrayLit

        assert isinstance(expr, ArrayLit)
        assert len(expr.elements) == 3

    def test_array_index(self) -> None:
        """Test parsing array indexing."""
        lexer = Lexer("arr[0]")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        from ._types import IndexExpr

        assert isinstance(expr, IndexExpr)
        assert expr.target == "arr"


class TestParserErrors:
    """Test error handling."""

    def test_unexpected_token(self) -> None:
        """Test error on unexpected token."""
        lexer = Lexer("fn fn")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        with pytest.raises(Exception):
            parser.parse_program()

    def test_missing_closing_paren(self) -> None:
        """Test error on missing closing parenthesis."""
        lexer = Lexer("foo(")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        with pytest.raises(Exception):
            parser.parse_expression()

    def test_missing_type_annotation(self) -> None:
        """Test error on missing type annotation."""
        lexer = Lexer("let x = 42;")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        with pytest.raises(Exception):
            parser.parse_program()


class TestParserPrecedence:
    """Test operator precedence."""

    def test_multiplication_before_addition(self) -> None:
        """Test that * has higher precedence than +."""
        lexer = Lexer("1 + 2 * 3")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.PLUS
        # Right side should be multiplication
        assert isinstance(expr.right, BinaryExpr)
        assert expr.right.op == TokenType.STAR

    def test_comparison_lower_than_arithmetic(self) -> None:
        """Test that comparison has lower precedence than arithmetic."""
        lexer = Lexer("1 + 2 < 5")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.LT

    def test_logical_and_precedence(self) -> None:
        """Test logical AND precedence."""
        lexer = Lexer("true || false && true")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)
        assert expr.op == TokenType.LOGICAL_OR
        # Right side should have && since it binds tighter
        assert isinstance(expr.right, BinaryExpr)
        assert expr.right.op == TokenType.LOGICAL_AND or expr.right.op == TokenType.AND


class TestParserComplex:
    """Test complex parsing scenarios."""

    def test_complex_expression(self) -> None:
        """Test parsing complex expression."""
        lexer = Lexer("(a + b) * (c - d) / e")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, BinaryExpr)

    def test_nested_function_calls(self) -> None:
        """Test parsing nested function calls."""
        lexer = Lexer("foo(bar(baz()))")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        expr = parser.parse_expression()
        assert isinstance(expr, CallExpr)
        assert isinstance(expr.args[0], CallExpr)
        assert isinstance(expr.args[0].args[0], CallExpr)

    def test_multiple_statements_in_block(self) -> None:
        """Test parsing multiple statements in a block."""
        source = """
        fn test() {
            let x: int = 1;
            let y: int = 2;
            return x + y;
        }
        """
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        func = program.declarations[0]
        assert len(func.body.statements) == 3
