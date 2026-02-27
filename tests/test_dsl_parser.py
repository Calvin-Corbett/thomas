"""Tests for DSL parser."""

from thomas.dsl import (
    BinaryOp,
    Block,
    DictExpr,
    ForLoop,
    FunctionCall,
    Identifier,
    IfExpr,
    LambdaExpr,
    LetBinding,
    Lexer,
    ListExpr,
    Literal,
    Parser,
    UnaryOp,
    WhileLoop,
)


class TestParserBasics:
    """Test basic parser functionality."""

    def _parse(self, code: str):
        """Helper to parse code."""
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def test_parse_literal_int(self) -> None:
        """Test parsing integer literal."""
        ast = self._parse("42")
        assert isinstance(ast, Literal)
        assert ast.value == 42

    def test_parse_literal_float(self) -> None:
        """Test parsing float literal."""
        ast = self._parse("3.14")
        assert isinstance(ast, Literal)
        assert ast.value == 3.14

    def test_parse_literal_string(self) -> None:
        """Test parsing string literal."""
        ast = self._parse('"hello"')
        assert isinstance(ast, Literal)
        assert ast.value == "hello"

    def test_parse_identifier(self) -> None:
        """Test parsing identifier."""
        ast = self._parse("foo")
        assert isinstance(ast, Identifier)
        assert ast.name == "foo"

    def test_parse_boolean(self) -> None:
        """Test parsing boolean."""
        ast = self._parse("true")
        assert isinstance(ast, Literal)
        assert ast.value is True

    def test_parse_binary_operation(self) -> None:
        """Test parsing binary operation."""
        ast = self._parse("1 + 2")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"
        assert isinstance(ast.left, Literal)
        assert isinstance(ast.right, Literal)

    def test_parse_binary_operation_chain(self) -> None:
        """Test parsing chained operations."""
        ast = self._parse("1 + 2 + 3")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"
        assert isinstance(ast.right, Literal)
        assert ast.right.value == 3

    def test_parse_operator_precedence(self) -> None:
        """Test operator precedence."""
        ast = self._parse("1 + 2 * 3")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"
        assert isinstance(ast.right, BinaryOp)
        assert ast.right.operator == "*"

    def test_parse_parenthesized_expression(self) -> None:
        """Test parsing parenthesized expression."""
        ast = self._parse("(1 + 2) * 3")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "*"
        assert isinstance(ast.left, BinaryOp)

    def test_parse_unary_minus(self) -> None:
        """Test parsing unary minus."""
        ast = self._parse("-42")
        assert isinstance(ast, UnaryOp)
        assert ast.operator == "-"

    def test_parse_unary_not(self) -> None:
        """Test parsing logical not."""
        ast = self._parse("!true")
        assert isinstance(ast, UnaryOp)
        assert ast.operator == "!"

    def test_parse_function_call(self) -> None:
        """Test parsing function call."""
        ast = self._parse("foo()")
        assert isinstance(ast, FunctionCall)
        assert isinstance(ast.function, Identifier)

    def test_parse_function_call_with_args(self) -> None:
        """Test parsing function call with arguments."""
        ast = self._parse("foo(1, 2, 3)")
        assert isinstance(ast, FunctionCall)
        assert len(ast.arguments) == 3

    def test_parse_if_expression(self) -> None:
        """Test parsing if expression."""
        ast = self._parse("if x then 1 else 2")
        assert isinstance(ast, IfExpr)
        assert isinstance(ast.condition, Identifier)
        assert isinstance(ast.then_expr, Literal)

    def test_parse_if_without_else(self) -> None:
        """Test parsing if without else."""
        ast = self._parse("if x then 1")
        assert isinstance(ast, IfExpr)
        assert ast.else_expr is None

    def test_parse_list_literal(self) -> None:
        """Test parsing list literal."""
        ast = self._parse("[1, 2, 3]")
        assert isinstance(ast, ListExpr)
        assert len(ast.elements) == 3

    def test_parse_empty_list(self) -> None:
        """Test parsing empty list."""
        ast = self._parse("[]")
        assert isinstance(ast, ListExpr)
        assert len(ast.elements) == 0

    def test_parse_dict_literal(self) -> None:
        """Test parsing dict literal."""
        ast = self._parse("{a: 1, b: 2}")
        assert isinstance(ast, DictExpr)
        assert len(ast.pairs) == 2

    def test_parse_while_loop(self) -> None:
        """Test parsing while loop."""
        ast = self._parse("while x do x - 1")
        assert isinstance(ast, WhileLoop)
        assert isinstance(ast.condition, Identifier)

    def test_parse_for_loop(self) -> None:
        """Test parsing for loop."""
        ast = self._parse("for x in y do x + 1")
        assert isinstance(ast, ForLoop)
        assert ast.variable == "x"

    def test_parse_let_binding(self) -> None:
        """Test parsing let binding."""
        ast = self._parse("let x = 1 in x + 1")
        assert isinstance(ast, LetBinding)
        assert ast.name == "x"

    def test_parse_assignment(self) -> None:
        """Test parsing assignment."""
        ast = self._parse("x = 42")
        from thomas.dsl import Assignment

        assert isinstance(ast, Assignment)
        assert ast.target == "x"

    def test_parse_compound_assignment(self) -> None:
        """Test parsing compound assignment."""
        ast = self._parse("x += 1")
        from thomas.dsl import Assignment

        assert isinstance(ast, Assignment)
        assert ast.operator == "+="

    def test_parse_lambda(self) -> None:
        """Test parsing lambda."""
        ast = self._parse("fn |x| x + 1")
        assert isinstance(ast, LambdaExpr)
        assert "x" in ast.parameters

    def test_parse_lambda_named(self) -> None:
        """Test parsing named lambda."""
        ast = self._parse("fn add(x, y) { x + y }")
        from thomas.dsl import FunctionDef

        assert isinstance(ast, FunctionDef)
        assert ast.name == "add"

    def test_parse_block_statements(self) -> None:
        """Test parsing block with multiple statements."""
        ast = self._parse("1; 2; 3")
        assert isinstance(ast, Block)
        assert len(ast.statements) == 3

    def test_parse_comparison(self) -> None:
        """Test parsing comparison."""
        ast = self._parse("x < y")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "<"

    def test_parse_logical_and(self) -> None:
        """Test parsing logical and."""
        ast = self._parse("x && y")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "&&"

    def test_parse_logical_or(self) -> None:
        """Test parsing logical or."""
        ast = self._parse("x || y")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "||"

    def test_parse_index_expression(self) -> None:
        """Test parsing index expression."""
        ast = self._parse("x[0]")
        from thomas.dsl import IndexExpr

        assert isinstance(ast, IndexExpr)

    def test_parse_return_statement(self) -> None:
        """Test parsing return statement."""
        ast = self._parse("return 42")
        from thomas.dsl import ReturnExpr

        assert isinstance(ast, ReturnExpr)
        assert ast.value is not None

    def test_parse_break_statement(self) -> None:
        """Test parsing break statement."""
        ast = self._parse("break")
        from thomas.dsl import BreakExpr

        assert isinstance(ast, BreakExpr)

    def test_parse_continue_statement(self) -> None:
        """Test parsing continue statement."""
        ast = self._parse("continue")
        from thomas.dsl import ContinueExpr

        assert isinstance(ast, ContinueExpr)

    def test_parse_bitwise_operations(self) -> None:
        """Test parsing bitwise operations."""
        ast = self._parse("x & y")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "&"

    def test_parse_shift_operations(self) -> None:
        """Test parsing shift operations."""
        ast = self._parse("x << 2")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "<<"

    def test_parse_power_operation(self) -> None:
        """Test parsing power operation."""
        ast = self._parse("x ** 2")
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "**"


class TestParserEdgeCases:
    """Test parser edge cases."""

    def _parse(self, code: str):
        """Helper to parse code."""
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def test_parse_nested_function_calls(self) -> None:
        """Test parsing nested function calls."""
        ast = self._parse("f(g(h()))")
        assert isinstance(ast, FunctionCall)
        assert isinstance(ast.function, FunctionCall)

    def test_parse_nested_list(self) -> None:
        """Test parsing nested lists."""
        ast = self._parse("[[1, 2], [3, 4]]")
        assert isinstance(ast, ListExpr)
        assert isinstance(ast.elements[0], ListExpr)

    def test_parse_mixed_operators(self) -> None:
        """Test parsing mixed operators."""
        ast = self._parse("1 + 2 * 3 - 4 / 2")
        assert isinstance(ast, BinaryOp)

    def test_parse_complex_condition(self) -> None:
        """Test parsing complex condition."""
        ast = self._parse("if x > 0 && y < 10 then 1 else 0")
        assert isinstance(ast, IfExpr)
        assert isinstance(ast.condition, BinaryOp)

    def test_parse_multiple_statements(self) -> None:
        """Test parsing multiple statements."""
        code = """
        x = 1
        y = 2
        z = x + y
        """
        ast = self._parse(code)
        assert isinstance(ast, Block)

    def test_parse_function_with_block(self) -> None:
        """Test parsing function with block body."""
        code = """
        fn test(x) {
            x + 1
        }
        """
        ast = self._parse(code)
        from thomas.dsl import FunctionDef

        assert isinstance(ast, FunctionDef)

    def test_parse_nested_if(self) -> None:
        """Test parsing nested if."""
        ast = self._parse("if x then if y then 1 else 2 else 3")
        assert isinstance(ast, IfExpr)
        assert isinstance(ast.then_expr, IfExpr)

    def test_parse_trailing_comma(self) -> None:
        """Test parsing trailing comma in list."""
        ast = self._parse("[1, 2, 3,]")
        # Should still work
        assert isinstance(ast, ListExpr)

    def test_parse_empty_dict(self) -> None:
        """Test parsing empty dict."""
        ast = self._parse("{}")
        assert isinstance(ast, DictExpr)
        assert len(ast.pairs) == 0

    def test_parse_single_element_list(self) -> None:
        """Test parsing single element list."""
        ast = self._parse("[42]")
        assert isinstance(ast, ListExpr)
        assert len(ast.elements) == 1

    def test_parse_string_concatenation(self) -> None:
        """Test string with plus operator."""
        ast = self._parse('"hello" + "world"')
        assert isinstance(ast, BinaryOp)
        assert ast.operator == "+"

    def test_parse_negative_numbers(self) -> None:
        """Test parsing negative numbers."""
        ast = self._parse("-42")
        assert isinstance(ast, UnaryOp)
        assert ast.operator == "-"

    def test_parse_float_operations(self) -> None:
        """Test parsing float operations."""
        ast = self._parse("3.14 * 2.0")
        assert isinstance(ast, BinaryOp)

    def test_parse_complex_let(self) -> None:
        """Test complex let binding."""
        ast = self._parse("let x = 1 in let y = 2 in x + y")
        assert isinstance(ast, LetBinding)
        assert isinstance(ast.body, LetBinding)

    def test_parse_lambda_multiple_params(self) -> None:
        """Test lambda with multiple parameters."""
        ast = self._parse("fn |x, y, z| x + y + z")
        assert isinstance(ast, LambdaExpr)
        assert len(ast.parameters) == 3
