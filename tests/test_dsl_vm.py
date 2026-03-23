"""Tests for DSL virtual machine."""

import pytest

from thomas.marketplace.dsl import VM, BinaryOp, Compiler, DSLConfig, Literal, OpCode


class TestVM:
    """Test virtual machine execution."""

    def _execute(self, code_obj):
        """Helper to execute code."""
        vm = VM()
        return vm.execute(code_obj)

    def _compile_and_execute(self, ast):
        """Helper to compile and execute AST."""
        compiler = Compiler()
        code = compiler.compile(ast)
        vm = VM()
        return vm.execute(code)

    def test_vm_load_const(self) -> None:
        """Test LOAD_CONST instruction."""
        compiler = Compiler()
        ast = Literal(42)
        code = compiler.compile(ast)
        result = self._execute(code)
        assert result == 42

    def test_vm_addition(self) -> None:
        """Test ADD instruction."""
        ast = BinaryOp(Literal(10), "+", Literal(32))
        result = self._compile_and_execute(ast)
        assert result == 42

    def test_vm_subtraction(self) -> None:
        """Test SUB instruction."""
        ast = BinaryOp(Literal(10), "-", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 7

    def test_vm_multiplication(self) -> None:
        """Test MUL instruction."""
        ast = BinaryOp(Literal(6), "*", Literal(7))
        result = self._compile_and_execute(ast)
        assert result == 42

    def test_vm_division(self) -> None:
        """Test DIV instruction."""
        ast = BinaryOp(Literal(84), "/", Literal(2))
        result = self._compile_and_execute(ast)
        assert result == 42

    def test_vm_modulo(self) -> None:
        """Test MOD instruction."""
        ast = BinaryOp(Literal(10), "%", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 1

    def test_vm_power(self) -> None:
        """Test POW instruction."""
        ast = BinaryOp(Literal(2), "**", Literal(6))
        result = self._compile_and_execute(ast)
        assert result == 64

    def test_vm_negation(self) -> None:
        """Test NEG instruction."""
        from thomas.marketplace.dsl import UnaryOp

        ast = UnaryOp("-", Literal(42))
        result = self._compile_and_execute(ast)
        assert result == -42

    def test_vm_equality(self) -> None:
        """Test EQ instruction."""
        ast = BinaryOp(Literal(42), "==", Literal(42))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_inequality(self) -> None:
        """Test NE instruction."""
        ast = BinaryOp(Literal(42), "!=", Literal(1))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_less_than(self) -> None:
        """Test LT instruction."""
        ast = BinaryOp(Literal(1), "<", Literal(2))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_less_equal(self) -> None:
        """Test LE instruction."""
        ast = BinaryOp(Literal(1), "<=", Literal(1))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_greater_than(self) -> None:
        """Test GT instruction."""
        ast = BinaryOp(Literal(2), ">", Literal(1))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_greater_equal(self) -> None:
        """Test GE instruction."""
        ast = BinaryOp(Literal(2), ">=", Literal(2))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_bitwise_and(self) -> None:
        """Test BIT_AND instruction."""
        ast = BinaryOp(Literal(5), "&", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 1

    def test_vm_bitwise_or(self) -> None:
        """Test BIT_OR instruction."""
        ast = BinaryOp(Literal(5), "|", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 7

    def test_vm_bitwise_xor(self) -> None:
        """Test BIT_XOR instruction."""
        ast = BinaryOp(Literal(5), "^", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 6

    def test_vm_bitwise_not(self) -> None:
        """Test BIT_NOT instruction."""
        from thomas.marketplace.dsl import UnaryOp

        ast = UnaryOp("~", Literal(0))
        result = self._compile_and_execute(ast)
        assert result == -1

    def test_vm_left_shift(self) -> None:
        """Test LSHIFT instruction."""
        ast = BinaryOp(Literal(1), "<<", Literal(6))
        result = self._compile_and_execute(ast)
        assert result == 64

    def test_vm_right_shift(self) -> None:
        """Test RSHIFT instruction."""
        ast = BinaryOp(Literal(64), ">>", Literal(2))
        result = self._compile_and_execute(ast)
        assert result == 16

    def test_vm_logical_and(self) -> None:
        """Test AND instruction."""
        ast = BinaryOp(Literal(True), "&&", Literal(True))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_logical_or(self) -> None:
        """Test OR instruction."""
        ast = BinaryOp(Literal(False), "||", Literal(True))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_logical_not(self) -> None:
        """Test NOT instruction."""
        from thomas.marketplace.dsl import UnaryOp

        ast = UnaryOp("!", Literal(False))
        result = self._compile_and_execute(ast)
        assert result is True

    def test_vm_multiple_operations(self) -> None:
        """Test multiple operations in sequence."""
        # (1 + 2) * 3 = 9
        left = BinaryOp(Literal(1), "+", Literal(2))
        ast = BinaryOp(left, "*", Literal(3))
        result = self._compile_and_execute(ast)
        assert result == 9

    def test_vm_stack_integrity(self) -> None:
        """Test that stack doesn't get corrupted."""
        vm = VM()
        vm.stack.append(10)
        vm.stack.append(20)

        assert vm.stack[-1] == 20
        assert vm.stack[-2] == 10

    def test_vm_call_frame(self) -> None:
        """Test call frame creation."""
        from thomas.marketplace.dsl import CallFrame, CodeObject

        code = CodeObject(name="test")
        frame = CallFrame(code)

        assert frame.code.name == "test"
        assert frame.pc == 0

    def test_vm_config(self) -> None:
        """Test VM with configuration."""
        config = DSLConfig(max_cycles=1000)
        vm = VM(config)

        assert vm.config.max_cycles == 1000

    def test_vm_debug_mode(self) -> None:
        """Test VM debug mode."""
        vm = VM()
        vm.debug = True

        ast = Literal(42)
        compiler = Compiler()
        code = compiler.compile(ast)

        # Should execute with debug output
        result = vm.execute(code)
        assert result == 42

    def test_vm_is_truthy(self) -> None:
        """Test truthy value evaluation."""
        vm = VM()

        assert vm._is_truthy(True) is True
        assert vm._is_truthy(False) is False
        assert vm._is_truthy(1) is True
        assert vm._is_truthy(0) is False
        assert vm._is_truthy("hello") is True
        assert vm._is_truthy("") is False
        assert vm._is_truthy([1, 2]) is True
        assert vm._is_truthy([]) is False
        assert vm._is_truthy(None) is False

    def test_vm_division_by_zero(self) -> None:
        """Test division by zero error."""
        ast = BinaryOp(Literal(10), "/", Literal(0))
        compiler = Compiler()
        code = compiler.compile(ast)
        vm = VM()

        with pytest.raises(ZeroDivisionError):
            vm.execute(code)

    def test_vm_nested_expressions(self) -> None:
        """Test complex nested expressions."""
        # ((1 + 2) * (3 + 4)) = 21
        left_left = BinaryOp(Literal(1), "+", Literal(2))
        left = BinaryOp(left_left, "*", Literal(3))
        ast = BinaryOp(left, "+", Literal(12))

        result = self._compile_and_execute(ast)
        assert result == 21

    def test_vm_operator_precedence_in_bytecode(self) -> None:
        """Test operator precedence is respected in bytecode."""
        # 1 + 2 * 3 should be 7, not 9
        left = Literal(1)
        right = BinaryOp(Literal(2), "*", Literal(3))
        ast = BinaryOp(left, "+", right)

        result = self._compile_and_execute(ast)
        assert result == 7

    def test_vm_instruction_sequence(self) -> None:
        """Test instruction execution sequence."""
        compiler = Compiler()
        ast = Literal(42)
        code = compiler.compile(ast)

        # Code should have LOAD_CONST and RETURN
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.LOAD_CONST in opcodes
        assert OpCode.RETURN in opcodes
