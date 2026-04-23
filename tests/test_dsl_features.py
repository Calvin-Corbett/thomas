"""Tests for DSL features: for loops, function calls, and pattern matching."""

from thomas.marketplace.dsl import VM, Compiler, Lexer, Parser


class TestForLoops:
    """Test for loop compilation and execution."""

    def test_for_loop_over_list(self) -> None:
        """Test for loop iterating over a list."""
        code = "for i in [1, 2, 3] do i + 1"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None

    def test_for_loop_with_variable_binding(self) -> None:
        """Test for loop binds loop variable."""
        code = "let x = 0 in for i in [10, 20, 30] do x"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None

    def test_for_loop_nested(self) -> None:
        """Test nested for loops."""
        code = "for i in [1, 2] do (for j in [3, 4] do j)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None

    def test_for_loop_empty_list(self) -> None:
        """Test for loop over empty list."""
        code = "for i in [] do i + 1"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None


class TestFunctionCalls:
    """Test function definition and calling."""

    def test_function_definition_and_call(self) -> None:
        """Test defining and calling a function."""
        code = "fn add(x, y) { x + y } add(2, 3)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 5

    def test_function_no_arguments(self) -> None:
        """Test function with no arguments."""
        code = "fn get_five() { 5 } get_five()"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 5

    def test_function_recursion(self) -> None:
        """Test recursive function calls."""
        code = "fn fib(n) { if n <= 1 then n else fib(n-1) + fib(n-2) } fib(5)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 5

    def test_function_multiple_calls(self) -> None:
        """Test calling a function multiple times."""
        code = "fn double(x) { x * 2 } double(3) + double(4)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 14

    def test_function_nested_calls(self) -> None:
        """Test nested function calls."""
        code = "fn add(x, y) { x + y } fn mul(x, y) { x * y } mul(add(2, 3), 4)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 20

    def test_function_factorial(self) -> None:
        """Test factorial function (recursion)."""
        code = "fn fact(n) { if n <= 1 then 1 else n * fact(n - 1) } fact(5)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 120


class TestPatternMatching:
    """Test pattern matching expressions."""

    def test_match_literal_pattern(self) -> None:
        """Test matching literal pattern."""
        code = "match 2 with case 1 => 10 case 2 => 20 default => 30"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 20

    def test_match_default_case(self) -> None:
        """Test match expression with default case."""
        code = "match 99 with case 1 => 10 default => 999"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 999

    def test_match_multiple_cases(self) -> None:
        """Test match with multiple cases."""
        code = "match 3 with case 1 => 10 case 2 => 20 case 3 => 30"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 30

    def test_match_string_pattern(self) -> None:
        """Test matching string patterns."""
        code = 'match "hello" with case "hello" => 1 case "world" => 2'
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 1

    def test_match_boolean_pattern(self) -> None:
        """Test matching boolean patterns."""
        code = "match true with case true => 100 case false => 200"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 100

    def test_match_no_patterns(self) -> None:
        """Test match with no patterns (default only)."""
        code = "match 42 with default => 99"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 99


class TestIntegration:
    """Test integration of features."""

    def test_function_with_for_loop(self) -> None:
        """Test function containing for loop."""
        code = "fn process_list(lst) { for x in lst do (x + 1) } process_list([1, 2, 3])"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None

    def test_match_with_function_call(self) -> None:
        """Test match expression with function calls."""
        code = "fn double(x) { x * 2 } match 5 with case 5 => double(10) default => 0"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result == 20

    def test_for_loop_with_match(self) -> None:
        """Test for loop with pattern matching in body."""
        code = "for i in [1, 2, 3] do (match i with case 2 => 20 default => i)"
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        compiler = Compiler()
        bytecode = compiler.compile(ast)
        vm = VM()
        result = vm.execute(bytecode)
        assert result is None
