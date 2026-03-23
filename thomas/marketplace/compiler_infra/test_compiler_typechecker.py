"""Tests for the Thomas type checker."""

import pytest

from ._exceptions import CompilerError
from ._types import FloatType, IntType, StringType
from .lexer import Lexer
from .parser import Parser
from .type_checker import SymbolTable, TypeChecker


class TestSymbolTable:
    """Test symbol table operations."""

    def test_define_and_lookup(self) -> None:
        """Test defining and looking up variables."""
        table = SymbolTable()
        table.define("x", IntType())
        assert table.lookup("x") == IntType()

    def test_undefined_variable(self) -> None:
        """Test looking up undefined variable."""
        table = SymbolTable()
        assert table.lookup("undefined") is None

    def test_scoping(self) -> None:
        """Test variable scoping."""
        table = SymbolTable()
        table.define("x", IntType())

        table.push_scope()
        table.define("x", StringType())
        assert isinstance(table.lookup("x"), StringType)

        table.pop_scope()
        assert isinstance(table.lookup("x"), IntType)

    def test_shadow_outer_scope(self) -> None:
        """Test shadowing variables from outer scope."""
        table = SymbolTable()
        table.define("x", IntType())

        table.push_scope()
        table.define("x", FloatType())
        assert isinstance(table.lookup("x"), FloatType)

        table.pop_scope()
        assert isinstance(table.lookup("x"), IntType)


class TestTypeCheckerBasic:
    """Test basic type checking."""

    def test_integer_literal(self) -> None:
        """Test type checking integer literal."""
        source = "fn test() -> int { return 42; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        # Should not raise
        checker.check(program)

    def test_type_mismatch_return(self) -> None:
        """Test type mismatch in return statement."""
        source = 'fn test() -> int { return "hello"; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_undefined_variable_use(self) -> None:
        """Test using undefined variable."""
        source = "fn test() { return undefined_var; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerArithmetic:
    """Test arithmetic type checking."""

    def test_int_addition(self) -> None:
        """Test int + int = int."""
        source = "fn test() -> int { return 1 + 2; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_float_arithmetic(self) -> None:
        """Test float arithmetic."""
        source = "fn test() -> float { return 1.5 + 2.5; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_mixed_int_float(self) -> None:
        """Test int + float = float."""
        source = "fn test() -> float { return 1 + 2.5; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_string_concatenation(self) -> None:
        """Test string concatenation."""
        source = 'fn test() -> string { return "hello" + "world"; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_invalid_addition(self) -> None:
        """Test invalid addition."""
        source = 'fn test() { return 1 + "hello"; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerComparison:
    """Test comparison type checking."""

    def test_int_comparison(self) -> None:
        """Test comparing integers."""
        source = "fn test() -> bool { return 1 < 2; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_equality_check(self) -> None:
        """Test equality comparison."""
        source = "fn test() -> bool { return 1 == 1; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_invalid_comparison(self) -> None:
        """Test invalid comparison type."""
        source = 'fn test() { return 1 < "hello"; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerLogical:
    """Test logical operation type checking."""

    def test_logical_and(self) -> None:
        """Test logical AND."""
        source = "fn test() -> bool { return true && false; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_logical_or(self) -> None:
        """Test logical OR."""
        source = "fn test() -> bool { return true || false; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_logical_not(self) -> None:
        """Test logical NOT."""
        source = "fn test() -> bool { return !true; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_invalid_logical_operand(self) -> None:
        """Test invalid logical operand type."""
        source = "fn test() { return 1 && 2; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerFunctions:
    """Test function type checking."""

    def test_function_definition(self) -> None:
        """Test function definition type checking."""
        source = "fn add(x: int, y: int) -> int { return x + y; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_function_call_correct_args(self) -> None:
        """Test function call with correct argument types."""
        source = """
        fn add(x: int, y: int) -> int { return x + y; }
        fn test() -> int { return add(1, 2); }
        """
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_function_call_wrong_arg_count(self) -> None:
        """Test function call with wrong argument count."""
        source = """
        fn add(x: int, y: int) -> int { return x + y; }
        fn test() { return add(1); }
        """
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_function_call_wrong_arg_type(self) -> None:
        """Test function call with wrong argument type."""
        source = """
        fn add(x: int, y: int) -> int { return x + y; }
        fn test() { return add(1, "hello"); }
        """
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerVariables:
    """Test variable type checking."""

    def test_variable_declaration(self) -> None:
        """Test variable declaration."""
        source = "fn test() { let x: int = 42; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_variable_type_mismatch(self) -> None:
        """Test variable declaration with type mismatch."""
        source = 'fn test() { let x: int = "hello"; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_int_to_float_conversion(self) -> None:
        """Test implicit int to float conversion."""
        source = "fn test() { let x: float = 42; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        # Should allow implicit int -> float conversion
        checker.check(program)


class TestTypeCheckerArrays:
    """Test array type checking."""

    def test_array_declaration(self) -> None:
        """Test array variable declaration."""
        source = "fn test() { let arr: int[] = [1, 2, 3]; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_array_indexing(self) -> None:
        """Test array indexing type checking."""
        source = "fn test() -> int { let arr: int[] = [1, 2, 3]; return arr[0]; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        checker.check(program)

    def test_invalid_array_index_type(self) -> None:
        """Test invalid array index type."""
        source = 'fn test() { let arr: int[] = [1, 2, 3]; let x: int = arr["zero"]; }'
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_index_non_array(self) -> None:
        """Test indexing non-array type."""
        source = "fn test() { let x: int = 42; let y: int = x[0]; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)


class TestTypeCheckerControlFlow:
    """Test control flow type checking."""

    def test_if_condition_must_be_bool(self) -> None:
        """Test that if condition must be bool."""
        source = "fn test() { if (42) { } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_while_condition_must_be_bool(self) -> None:
        """Test that while condition must be bool."""
        source = "fn test() { while (42) { } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)

    def test_for_condition_must_be_bool(self) -> None:
        """Test that for condition must be bool."""
        source = "fn test() { for (let i: int = 0; 42; i = i + 1) { } }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        program = parser.parse_program()

        checker = TypeChecker()
        with pytest.raises(CompilerError):
            checker.check(program)
