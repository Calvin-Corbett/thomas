"""Tests for DSL interpreter."""

import pytest

from thomas.dsl import Interpreter, Lexer, Parser


class TestInterpreter:
    """Test interpreter functionality."""

    def _eval(self, code: str):
        """Helper to evaluate code."""
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        interpreter = Interpreter()
        return interpreter.interpret(ast)

    def test_eval_integer_literal(self) -> None:
        """Test evaluating integer literal."""
        result = self._eval("42")
        assert result == 42

    def test_eval_float_literal(self) -> None:
        """Test evaluating float literal."""
        result = self._eval("3.14")
        assert result == 3.14

    def test_eval_string_literal(self) -> None:
        """Test evaluating string literal."""
        result = self._eval('"hello"')
        assert result == "hello"

    def test_eval_boolean_literal(self) -> None:
        """Test evaluating boolean literal."""
        assert self._eval("true") is True
        assert self._eval("false") is False

    def test_eval_none_literal(self) -> None:
        """Test evaluating none literal."""
        assert self._eval("none") is None

    def test_eval_addition(self) -> None:
        """Test evaluating addition."""
        result = self._eval("1 + 2")
        assert result == 3

    def test_eval_subtraction(self) -> None:
        """Test evaluating subtraction."""
        result = self._eval("10 - 3")
        assert result == 7

    def test_eval_multiplication(self) -> None:
        """Test evaluating multiplication."""
        result = self._eval("4 * 5")
        assert result == 20

    def test_eval_division(self) -> None:
        """Test evaluating division."""
        result = self._eval("10 / 2")
        assert result == 5

    def test_eval_modulo(self) -> None:
        """Test evaluating modulo."""
        result = self._eval("10 % 3")
        assert result == 1

    def test_eval_power(self) -> None:
        """Test evaluating power."""
        result = self._eval("2 ** 3")
        assert result == 8

    def test_eval_comparison_equal(self) -> None:
        """Test equality comparison."""
        assert self._eval("5 == 5") is True
        assert self._eval("5 == 3") is False

    def test_eval_comparison_not_equal(self) -> None:
        """Test inequality comparison."""
        assert self._eval("5 != 3") is True
        assert self._eval("5 != 5") is False

    def test_eval_comparison_less(self) -> None:
        """Test less than comparison."""
        assert self._eval("3 < 5") is True
        assert self._eval("5 < 3") is False

    def test_eval_comparison_greater(self) -> None:
        """Test greater than comparison."""
        assert self._eval("5 > 3") is True
        assert self._eval("3 > 5") is False

    def test_eval_logical_and(self) -> None:
        """Test logical and."""
        assert self._eval("true && true") is True
        assert self._eval("true && false") is False
        assert self._eval("false && true") is False

    def test_eval_logical_or(self) -> None:
        """Test logical or."""
        assert self._eval("true || false") is True
        assert self._eval("false || false") is False

    def test_eval_logical_not(self) -> None:
        """Test logical not."""
        assert self._eval("!true") is False
        assert self._eval("!false") is True

    def test_eval_if_then_else(self) -> None:
        """Test if-then-else."""
        assert self._eval("if true then 1 else 2") == 1
        assert self._eval("if false then 1 else 2") == 2

    def test_eval_if_without_else(self) -> None:
        """Test if without else."""
        assert self._eval("if true then 42") == 42
        assert self._eval("if false then 42") is None

    def test_eval_list_literal(self) -> None:
        """Test list literal."""
        result = self._eval("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_eval_list_indexing(self) -> None:
        """Test list indexing."""
        result = self._eval("[1, 2, 3][1]")
        assert result == 2

    def test_eval_string_indexing(self) -> None:
        """Test string indexing."""
        result = self._eval('"hello"[0]')
        assert result == "h"

    def test_eval_dict_literal(self) -> None:
        """Test dict literal."""
        result = self._eval("{a: 1, b: 2}")
        assert isinstance(result, dict)
        assert len(result) == 2

    def test_eval_negative_number(self) -> None:
        """Test unary negation."""
        assert self._eval("-42") == -42
        assert self._eval("-(5 + 3)") == -8

    def test_eval_bitwise_and(self) -> None:
        """Test bitwise and."""
        assert self._eval("5 & 3") == 1

    def test_eval_bitwise_or(self) -> None:
        """Test bitwise or."""
        assert self._eval("5 | 3") == 7

    def test_eval_bitwise_xor(self) -> None:
        """Test bitwise xor."""
        assert self._eval("5 ^ 3") == 6

    def test_eval_bitwise_not(self) -> None:
        """Test bitwise not."""
        assert self._eval("~0") == -1

    def test_eval_shift_left(self) -> None:
        """Test left shift."""
        assert self._eval("1 << 3") == 8

    def test_eval_shift_right(self) -> None:
        """Test right shift."""
        assert self._eval("8 >> 2") == 2

    def test_eval_string_concatenation(self) -> None:
        """Test string concatenation."""
        result = self._eval('"hello" + " " + "world"')
        assert result == "hello world"

    def test_eval_list_concatenation(self) -> None:
        """Test list concatenation."""
        result = self._eval("[1, 2] + [3, 4]")
        assert result == [1, 2, 3, 4]

    def test_eval_builtin_len(self) -> None:
        """Test built-in len function."""
        assert self._eval("len([1, 2, 3])") == 3
        assert self._eval('len("hello")') == 5

    def test_eval_builtin_min(self) -> None:
        """Test built-in min function."""
        assert self._eval("min(3, 1, 2)") == 1

    def test_eval_builtin_max(self) -> None:
        """Test built-in max function."""
        assert self._eval("max(3, 1, 2)") == 3

    def test_eval_builtin_abs(self) -> None:
        """Test built-in abs function."""
        assert self._eval("abs(-42)") == 42

    def test_eval_let_binding(self) -> None:
        """Test let binding."""
        result = self._eval("let x = 10 in x + 5")
        assert result == 15

    def test_eval_nested_let(self) -> None:
        """Test nested let bindings."""
        result = self._eval("let x = 1 in let y = 2 in x + y")
        assert result == 3

    def test_eval_lambda(self) -> None:
        """Test lambda function."""
        result = self._eval("(fn |x| x + 1)(41)")
        assert result == 42

    def test_eval_lambda_multiple_params(self) -> None:
        """Test lambda with multiple parameters."""
        result = self._eval("(fn |x, y| x + y)(3, 4)")
        assert result == 7

    def test_eval_function_definition(self) -> None:
        """Test function definition and call."""
        code = """
        fn add(x, y) { x + y };
        add(3, 4)
        """
        result = self._eval(code)
        assert result == 7

    def test_eval_assignment(self) -> None:
        """Test variable assignment."""
        code = """
        x = 42;
        x
        """
        result = self._eval(code)
        assert result == 42

    def test_eval_compound_assignment(self) -> None:
        """Test compound assignment."""
        code = """
        x = 10;
        x += 5;
        x
        """
        result = self._eval(code)
        assert result == 15

    def test_eval_while_loop(self) -> None:
        """Test while loop."""
        code = """
        x = 0;
        while x < 5 do x = x + 1;
        x
        """
        result = self._eval(code)
        assert result == 5

    def test_eval_for_loop(self) -> None:
        """Test for loop."""
        code = """
        sum = 0;
        for i in [1, 2, 3, 4, 5] do sum = sum + i;
        sum
        """
        result = self._eval(code)
        assert result == 15

    def test_eval_break(self) -> None:
        """Test break statement."""
        code = """
        x = 0;
        while true do {
            x = x + 1;
            if x == 3 then break
        };
        x
        """
        result = self._eval(code)
        assert result == 3

    def test_eval_continue(self) -> None:
        """Test continue statement."""
        code = """
        sum = 0;
        for i in [1, 2, 3, 4, 5] do {
            if i == 3 then continue;
            sum = sum + i
        };
        sum
        """
        result = self._eval(code)
        assert result == 12

    def test_eval_operator_precedence(self) -> None:
        """Test operator precedence."""
        assert self._eval("2 + 3 * 4") == 14
        assert self._eval("(2 + 3) * 4") == 20

    def test_eval_short_circuit_and(self) -> None:
        """Test short-circuit evaluation for and."""
        # If first operand is false, second shouldn't be evaluated
        result = self._eval("false && (1 / 0)")
        assert result is False

    def test_eval_short_circuit_or(self) -> None:
        """Test short-circuit evaluation for or."""
        # If first operand is true, second shouldn't be evaluated
        result = self._eval("true || (1 / 0)")
        assert result is True

    def test_eval_closure(self) -> None:
        """Test closure capturing environment."""
        code = """
        let x = 10 in
        (fn |y| x + y)(5)
        """
        result = self._eval(code)
        assert result == 15

    def test_eval_recursion(self) -> None:
        """Test recursive function."""
        code = """
        fn fact(n) {
            if n <= 1 then 1 else n * fact(n - 1)
        };
        fact(5)
        """
        result = self._eval(code)
        assert result == 120


class TestInterpreterEdgeCases:
    """Test interpreter edge cases."""

    def _eval(self, code: str):
        """Helper to evaluate code."""
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        interpreter = Interpreter()
        return interpreter.interpret(ast)

    def test_eval_empty_list(self) -> None:
        """Test empty list."""
        result = self._eval("[]")
        assert result == []

    def test_eval_empty_dict(self) -> None:
        """Test empty dict."""
        result = self._eval("{}")
        assert result == {}

    def test_eval_zero_division(self) -> None:
        """Test division by zero."""
        with pytest.raises(ZeroDivisionError):
            self._eval("1 / 0")

    def test_eval_undefined_variable(self) -> None:
        """Test undefined variable."""
        from thomas.dsl import UndefinedVariable

        with pytest.raises(UndefinedVariable):
            self._eval("undefined_var")

    def test_eval_list_out_of_bounds(self) -> None:
        """Test list index out of bounds."""
        with pytest.raises(IndexError):
            self._eval("[1, 2, 3][10]")

    def test_eval_truthy_values(self) -> None:
        """Test truthy value evaluation."""
        # Non-zero numbers are truthy
        assert self._eval("if 42 then true else false") is True
        assert self._eval("if 0 then true else false") is False
        assert self._eval("if 1 then true else false") is True

    def test_eval_string_multiplication(self) -> None:
        """Test string multiplication."""
        result = self._eval('"ab" * 3')
        assert result == "ababab"
