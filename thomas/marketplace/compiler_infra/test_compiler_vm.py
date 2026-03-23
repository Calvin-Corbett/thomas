"""Tests for the Thomas virtual machine."""

import pytest

from ._exceptions import RuntimeError as Thomas_RuntimeError
from .codegen import Bytecode, BytecodeFunction, BytecodeInstruction, BytecodeProgram
from .vm import CallFrame, VirtualMachine


class TestVMStack:
    """Test stack operations."""

    def test_push_and_pop(self) -> None:
        """Test push and pop operations."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 42),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 42

    def test_stack_underflow(self) -> None:
        """Test stack underflow error."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.POP),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func

        vm = VirtualMachine(program)
        with pytest.raises(Thomas_RuntimeError):
            vm.execute()


class TestVMArithmetic:
    """Test arithmetic operations."""

    def test_addition(self) -> None:
        """Test addition operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 2),  # Push 2
            BytecodeInstruction(Bytecode.PUSH, 3),  # Push 3
            BytecodeInstruction(Bytecode.ADD),  # Add: 2 + 3 = 5
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 5

    def test_subtraction(self) -> None:
        """Test subtraction operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 10),
            BytecodeInstruction(Bytecode.PUSH, 3),
            BytecodeInstruction(Bytecode.SUB),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 7

    def test_multiplication(self) -> None:
        """Test multiplication operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 6),
            BytecodeInstruction(Bytecode.PUSH, 7),
            BytecodeInstruction(Bytecode.MUL),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 42

    def test_division(self) -> None:
        """Test division operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 20),
            BytecodeInstruction(Bytecode.PUSH, 4),
            BytecodeInstruction(Bytecode.DIV),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 5

    def test_division_by_zero(self) -> None:
        """Test division by zero error."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 10),
            BytecodeInstruction(Bytecode.PUSH, 0),
            BytecodeInstruction(Bytecode.DIV),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        with pytest.raises(Thomas_RuntimeError):
            vm.execute()

    def test_modulo(self) -> None:
        """Test modulo operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 17),
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.MOD),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 2

    def test_negation(self) -> None:
        """Test negation operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 42),
            BytecodeInstruction(Bytecode.NEG),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == -42


class TestVMComparison:
    """Test comparison operations."""

    def test_equal_true(self) -> None:
        """Test equality when values are equal."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.EQ),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1  # True

    def test_equal_false(self) -> None:
        """Test equality when values are not equal."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.PUSH, 3),
            BytecodeInstruction(Bytecode.EQ),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 0  # False

    def test_not_equal(self) -> None:
        """Test not equal operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.PUSH, 3),
            BytecodeInstruction(Bytecode.NE),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1  # True

    def test_less_than(self) -> None:
        """Test less than operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 3),
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.LT),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1  # True (3 < 5)

    def test_greater_than(self) -> None:
        """Test greater than operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 5),
            BytecodeInstruction(Bytecode.PUSH, 3),
            BytecodeInstruction(Bytecode.GT),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1  # True (5 > 3)


class TestVMLogical:
    """Test logical operations."""

    def test_logical_and_true(self) -> None:
        """Test logical AND with both true."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 1),
            BytecodeInstruction(Bytecode.PUSH, 1),
            BytecodeInstruction(Bytecode.AND),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1

    def test_logical_and_false(self) -> None:
        """Test logical AND with one false."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 1),
            BytecodeInstruction(Bytecode.PUSH, 0),
            BytecodeInstruction(Bytecode.AND),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 0

    def test_logical_or(self) -> None:
        """Test logical OR operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 0),
            BytecodeInstruction(Bytecode.PUSH, 1),
            BytecodeInstruction(Bytecode.OR),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1

    def test_logical_not(self) -> None:
        """Test logical NOT operation."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 0),
            BytecodeInstruction(Bytecode.NOT),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 1


class TestVMVariables:
    """Test variable operations."""

    def test_store_and_load(self) -> None:
        """Test storing and loading variables."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 42),
            BytecodeInstruction(Bytecode.STORE, 0),  # Store in local 0
            BytecodeInstruction(Bytecode.LOAD, 0),  # Load from local 0
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        assert result == 42


class TestVMJumps:
    """Test jump operations."""

    def test_unconditional_jump(self) -> None:
        """Test unconditional jump."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 1),
            BytecodeInstruction(Bytecode.JMP, 3),  # Jump to instruction 3
            BytecodeInstruction(Bytecode.PUSH, 2),  # Skipped
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        result = vm.execute()

        # Stack should only have 1 (the 2 is skipped)
        assert result == 1

    def test_conditional_jump_true(self) -> None:
        """Test conditional jump when condition is true."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 1),  # True condition
            BytecodeInstruction(Bytecode.JMP_IF_FALSE, 4),  # Jump if false (but it's true, so don't jump)
            BytecodeInstruction(Bytecode.PUSH, 100),
            BytecodeInstruction(Bytecode.JMP, 5),
            BytecodeInstruction(Bytecode.PUSH, 200),  # This would execute if we jumped
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        # Pop the condition before halt
        vm.stack = []
        vm.call_stack = [CallFrame(func, 0, {})]
        vm.execute()


class TestVMBuiltins:
    """Test built-in functions."""

    def test_print_builtin(self) -> None:
        """Test print built-in function."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 42),
            BytecodeInstruction(Bytecode.CALL, "print"),
            BytecodeInstruction(Bytecode.HALT),
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program)
        # Should not raise
        vm.execute()


class TestVMStepLimit:
    """Test step limit to prevent infinite loops."""

    def test_step_limit_exceeded(self) -> None:
        """Test that step limit prevents infinite loops."""
        program = BytecodeProgram()
        func = BytecodeFunction("main", 0)
        func.instructions = [
            BytecodeInstruction(Bytecode.PUSH, 0),
            BytecodeInstruction(Bytecode.JMP, 0),  # Jump to self (infinite loop)
        ]
        program.functions["main"] = func
        program.constant_pool = {}

        vm = VirtualMachine(program, step_limit=100)
        with pytest.raises(Thomas_RuntimeError):
            vm.execute()
