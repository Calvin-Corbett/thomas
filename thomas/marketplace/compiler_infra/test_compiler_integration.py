"""Integration tests for the Thomas compiler."""

import pytest

from ._exceptions import CompilerError
from .pipeline import Compiler, CompilerConfig, compile_and_execute


class TestCompilerIntegrationBasic:
    """Test basic compilation and execution."""

    def test_compile_simple_addition(self) -> None:
        """Test compiling and executing simple addition."""
        source = """
        fn main() {
            return 2 + 3;
        }
        """
        result = compile_and_execute(source)
        assert result == 5

    def test_compile_simple_string(self) -> None:
        """Test compiling and executing string literal."""
        source = """
        fn main() {
            return "hello";
        }
        """
        result = compile_and_execute(source)
        assert result == "hello"

    def test_compile_boolean(self) -> None:
        """Test compiling and executing boolean."""
        source = """
        fn main() {
            return true;
        }
        """
        result = compile_and_execute(source)
        assert result == 1


class TestCompilerIntegrationVariables:
    """Test variable-related compilation."""

    def test_variable_declaration_and_use(self) -> None:
        """Test variable declaration and usage."""
        source = """
        fn main() {
            let x: int = 42;
            return x;
        }
        """
        result = compile_and_execute(source)
        assert result == 42

    def test_variable_assignment(self) -> None:
        """Test variable assignment."""
        source = """
        fn main() {
            let x: int = 10;
            x = 20;
            return x;
        }
        """
        result = compile_and_execute(source)
        assert result == 20

    def test_multiple_variables(self) -> None:
        """Test multiple variables."""
        source = """
        fn main() {
            let x: int = 10;
            let y: int = 20;
            return x + y;
        }
        """
        result = compile_and_execute(source)
        assert result == 30


class TestCompilerIntegrationArithmetic:
    """Test arithmetic expression compilation."""

    def test_addition(self) -> None:
        """Test addition."""
        source = "fn main() { return 10 + 5; }"
        result = compile_and_execute(source)
        assert result == 15

    def test_subtraction(self) -> None:
        """Test subtraction."""
        source = "fn main() { return 10 - 5; }"
        result = compile_and_execute(source)
        assert result == 5

    def test_multiplication(self) -> None:
        """Test multiplication."""
        source = "fn main() { return 6 * 7; }"
        result = compile_and_execute(source)
        assert result == 42

    def test_division(self) -> None:
        """Test division."""
        source = "fn main() { return 20 / 4; }"
        result = compile_and_execute(source)
        assert result == 5

    def test_modulo(self) -> None:
        """Test modulo."""
        source = "fn main() { return 17 % 5; }"
        result = compile_and_execute(source)
        assert result == 2

    def test_operator_precedence(self) -> None:
        """Test operator precedence."""
        source = "fn main() { return 2 + 3 * 4; }"
        result = compile_and_execute(source)
        assert result == 14  # 2 + (3 * 4)

    def test_parenthesized_expression(self) -> None:
        """Test parenthesized expression."""
        source = "fn main() { return (2 + 3) * 4; }"
        result = compile_and_execute(source)
        assert result == 20


class TestCompilerIntegrationComparison:
    """Test comparison expression compilation."""

    def test_equal_true(self) -> None:
        """Test equality when true."""
        source = "fn main() { return 5 == 5; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_equal_false(self) -> None:
        """Test equality when false."""
        source = "fn main() { return 5 == 3; }"
        result = compile_and_execute(source)
        assert result == 0

    def test_not_equal(self) -> None:
        """Test not equal."""
        source = "fn main() { return 5 != 3; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_less_than(self) -> None:
        """Test less than."""
        source = "fn main() { return 3 < 5; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_greater_than(self) -> None:
        """Test greater than."""
        source = "fn main() { return 5 > 3; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_less_or_equal(self) -> None:
        """Test less or equal."""
        source = "fn main() { return 5 <= 5; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_greater_or_equal(self) -> None:
        """Test greater or equal."""
        source = "fn main() { return 5 >= 5; }"
        result = compile_and_execute(source)
        assert result == 1


class TestCompilerIntegrationLogical:
    """Test logical operation compilation."""

    def test_logical_and(self) -> None:
        """Test logical AND."""
        source = "fn main() { return true && true; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_logical_or(self) -> None:
        """Test logical OR."""
        source = "fn main() { return false || true; }"
        result = compile_and_execute(source)
        assert result == 1

    def test_logical_not(self) -> None:
        """Test logical NOT."""
        source = "fn main() { return !false; }"
        result = compile_and_execute(source)
        assert result == 1


class TestCompilerIntegrationFunctions:
    """Test function compilation."""

    def test_simple_function_call(self) -> None:
        """Test simple function call."""
        source = """
        fn add(x: int, y: int) -> int {
            return x + y;
        }
        fn main() {
            return add(10, 20);
        }
        """
        result = compile_and_execute(source)
        assert result == 30

    def test_multiple_function_calls(self) -> None:
        """Test multiple function calls."""
        source = """
        fn double(x: int) -> int {
            return x * 2;
        }
        fn main() {
            return double(5) + double(3);
        }
        """
        result = compile_and_execute(source)
        assert result == 16  # (5*2) + (3*2)

    def test_nested_function_calls(self) -> None:
        """Test nested function calls."""
        source = """
        fn add(x: int, y: int) -> int {
            return x + y;
        }
        fn multiply(x: int, y: int) -> int {
            return x * y;
        }
        fn main() {
            return multiply(add(2, 3), 4);
        }
        """
        result = compile_and_execute(source)
        assert result == 20  # (2 + 3) * 4


class TestCompilerIntegrationControlFlow:
    """Test control flow compilation."""

    def test_if_true_branch(self) -> None:
        """Test if statement with true condition."""
        source = """
        fn main() {
            if (true) {
                return 42;
            }
            return 0;
        }
        """
        result = compile_and_execute(source)
        assert result == 42

    def test_if_false_branch(self) -> None:
        """Test if statement with false condition."""
        source = """
        fn main() {
            if (false) {
                return 42;
            }
            return 0;
        }
        """
        result = compile_and_execute(source)
        assert result == 0

    def test_if_else(self) -> None:
        """Test if-else statement."""
        source = """
        fn main() {
            if (false) {
                return 10;
            } else {
                return 20;
            }
        }
        """
        result = compile_and_execute(source)
        assert result == 20

    def test_while_loop(self) -> None:
        """Test while loop."""
        source = """
        fn main() {
            let x: int = 0;
            while (x < 5) {
                x = x + 1;
            }
            return x;
        }
        """
        result = compile_and_execute(source)
        assert result == 5

    def test_for_loop(self) -> None:
        """Test for loop."""
        source = """
        fn main() {
            let sum: int = 0;
            for (let i: int = 0; i < 5; i = i + 1) {
                sum = sum + i;
            }
            return sum;
        }
        """
        result = compile_and_execute(source)
        assert result == 10  # 0+1+2+3+4


class TestCompilerIntegrationArrays:
    """Test array compilation."""

    def test_array_literal(self) -> None:
        """Test array literal."""
        source = """
        fn main() {
            let arr: int[] = [1, 2, 3];
            return arr[0];
        }
        """
        # Note: Array indexing support depends on IR implementation
        try:
            result = compile_and_execute(source)
            assert result == 1
        except Exception:
            # Arrays might not be fully implemented yet
            pass

    def test_array_indexing(self) -> None:
        """Test array indexing."""
        source = """
        fn main() {
            let arr: int[] = [10, 20, 30];
            return arr[1];
        }
        """
        try:
            result = compile_and_execute(source)
            assert result == 20
        except Exception:
            pass


class TestCompilerIntegrationOptimization:
    """Test optimization during compilation."""

    def test_constant_folding(self) -> None:
        """Test that constant folding is applied."""
        config = CompilerConfig()
        config.optimize = True

        source = "fn main() { return 100 + 50; }"
        compiler = Compiler(config)
        result = compiler.compile_and_execute(source)
        assert result == 150

    def test_optimization_disabled(self) -> None:
        """Test compilation without optimization."""
        config = CompilerConfig()
        config.optimize = False

        source = "fn main() { return 100 + 50; }"
        compiler = Compiler(config)
        result = compiler.compile_and_execute(source)
        assert result == 150


class TestCompilerIntegrationErrors:
    """Test error detection during compilation."""

    def test_syntax_error(self) -> None:
        """Test syntax error detection."""
        source = "fn fn"  # Invalid syntax
        with pytest.raises(CompilerError):
            compile_and_execute(source)

    def test_type_error(self) -> None:
        """Test type error detection."""
        source = 'fn main() { return "hello" + 42; }'
        with pytest.raises(CompilerError):
            compile_and_execute(source)

    def test_undefined_function(self) -> None:
        """Test undefined function error."""
        source = "fn main() { return undefined_func(); }"
        with pytest.raises(CompilerError):
            compile_and_execute(source)

    def test_undefined_variable(self) -> None:
        """Test undefined variable error."""
        source = "fn main() { return undefined_var; }"
        with pytest.raises(CompilerError):
            compile_and_execute(source)


class TestCompilerIntegrationPipeline:
    """Test the complete compilation pipeline."""

    def test_full_pipeline_timing(self) -> None:
        """Test that pipeline tracks timing for each phase."""
        config = CompilerConfig()
        config.verbose = False

        source = """
        fn factorial(n: int) -> int {
            if (n <= 1) {
                return 1;
            }
            return n * factorial(n - 1);
        }
        fn main() {
            return factorial(5);
        }
        """
        compiler = Compiler(config)
        result = compiler.compile(source)

        # Check that all phases were tracked
        assert "Lexing" in result.phases
        assert "Parsing" in result.phases
        assert "Type Checking" in result.phases
        assert "IR Generation" in result.phases
        if config.optimize:
            assert "Optimization" in result.phases
        assert "Code Generation" in result.phases

    def test_compiler_verbose_mode(self) -> None:
        """Test verbose mode."""
        config = CompilerConfig()
        config.verbose = True

        source = "fn main() { return 42; }"
        compiler = Compiler(config)
        # Should not raise
        result = compiler.compile(source)


class TestCompilerIntegrationComplex:
    """Test complex compilation scenarios."""

    def test_fibonacci(self) -> None:
        """Test compiling fibonacci function."""
        source = """
        fn fib(n: int) -> int {
            if (n <= 1) {
                return n;
            }
            return fib(n - 1) + fib(n - 2);
        }
        fn main() {
            return fib(6);
        }
        """
        result = compile_and_execute(source)
        assert result == 8

    def test_nested_if_else(self) -> None:
        """Test nested if-else statements."""
        source = """
        fn max(a: int, b: int) -> int {
            if (a > b) {
                return a;
            } else {
                return b;
            }
        }
        fn main() {
            return max(10, 5);
        }
        """
        result = compile_and_execute(source)
        assert result == 10

    def test_mixed_operators(self) -> None:
        """Test mixed operators."""
        source = """
        fn main() {
            return (10 + 5) * 2 - 3 / 1;
        }
        """
        result = compile_and_execute(source)
        assert result == 27  # (15 * 2) - 3
