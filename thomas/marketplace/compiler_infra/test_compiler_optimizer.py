"""Tests for IR optimization passes."""

from ._types import IntType
from .ir import IRBasicBlock, IRFunction, IRInstruction, IROpcode, IRProgram
from .optimizer import (
    CommonSubexpressionEliminator,
    ConstantFolder,
    CopyPropagation,
    DeadCodeEliminator,
    IROptimizer,
    StrengthReducer,
)


class TestConstantFolder:
    """Test constant folding optimization."""

    def test_constant_addition(self) -> None:
        """Test constant folding of addition."""
        folder = ConstantFolder()

        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "2", "+", "3"))

        folder.fold_block(block)
        assert "$t0" in folder.constants
        assert folder.constants["$t0"][1] == 5.0

    def test_constant_multiplication(self) -> None:
        """Test constant folding of multiplication."""
        folder = ConstantFolder()

        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "4", "*", "5"))

        folder.fold_block(block)
        assert "$t0" in folder.constants
        assert folder.constants["$t0"][1] == 20.0

    def test_constant_comparison(self) -> None:
        """Test constant folding of comparisons."""
        folder = ConstantFolder()

        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "5", ">", "3"))

        folder.fold_block(block)
        assert "$t0" in folder.constants
        assert folder.constants["$t0"][1] == 1.0

    def test_division_by_zero_not_folded(self) -> None:
        """Test that division by zero is not folded."""
        folder = ConstantFolder()

        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "5", "/", "0"))

        folder.fold_block(block)
        # Should not be in constants
        assert "$t0" not in folder.constants


class TestDeadCodeEliminator:
    """Test dead code elimination."""

    def test_unreachable_block_detection(self) -> None:
        """Test detection of unreachable blocks."""
        func = IRFunction("test", [], IntType())

        # Create two blocks: entry and unreachable
        entry_block = IRBasicBlock("entry")
        entry_block.add_instruction(IRInstruction(IROpcode.RETURN))

        unreachable_block = IRBasicBlock("unreachable")
        unreachable_block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "42"))

        func.add_block(entry_block)
        func.add_block(unreachable_block)

        program = IRProgram()
        program.add_function(func)

        eliminator = DeadCodeEliminator()
        reachable = eliminator.reachable_blocks(func)

        assert "entry" in reachable
        assert "unreachable" not in reachable

    def test_remove_unreachable_blocks(self) -> None:
        """Test removal of unreachable blocks."""
        func = IRFunction("test", [], IntType())

        entry_block = IRBasicBlock("entry")
        entry_block.add_instruction(IRInstruction(IROpcode.RETURN))

        unreachable_block = IRBasicBlock("unreachable")
        unreachable_block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "42"))

        func.add_block(entry_block)
        func.add_block(unreachable_block)

        program = IRProgram()
        program.add_function(func)

        eliminator = DeadCodeEliminator()
        result = eliminator.optimize(program)

        # After optimization, function should have only 1 block
        assert len(result.functions[0].blocks) == 1


class TestCopyPropagation:
    """Test copy propagation optimization."""

    def test_simple_copy_propagation(self) -> None:
        """Test simple copy propagation."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "42"))
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t1", "$t0"))
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t2", "$t1", "+", "1"))

        prop = CopyPropagation()
        prop.propagate_block(block)

        # After propagation, $t1 reference should be replaced with 42
        # The last instruction should reference 42 instead of $t1
        last_instr = block.instructions[-1]
        assert last_instr.arg1 == "42"

    def test_no_propagation_of_overwritten(self) -> None:
        """Test that overwritten copies are not propagated."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "42"))
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "100"))  # Overwrite
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t1", "$t0", "+", "1"))

        prop = CopyPropagation()
        prop.propagate_block(block)

        # After propagation, $t0 should be 100 (the overwritten value)
        last_instr = block.instructions[-1]
        assert last_instr.arg1 == "100"


class TestStrengthReducer:
    """Test strength reduction optimization."""

    def test_multiply_by_power_of_two(self) -> None:
        """Test multiplication by power of 2 becomes shift."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "$t1", "*", "4"))

        reducer = StrengthReducer()
        reducer.reduce_block(block)

        instr = block.instructions[0]
        assert instr.arg2 == "<<"
        assert instr.arg3 == "2"  # log2(4) = 2

    def test_multiply_by_8_becomes_shift_3(self) -> None:
        """Test multiplication by 8 becomes shift by 3."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "$t1", "*", "8"))

        reducer = StrengthReducer()
        reducer.reduce_block(block)

        instr = block.instructions[0]
        assert instr.arg2 == "<<"
        assert instr.arg3 == "3"

    def test_divide_by_power_of_two(self) -> None:
        """Test division by power of 2 becomes shift."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "$t1", "/", "4"))

        reducer = StrengthReducer()
        reducer.reduce_block(block)

        instr = block.instructions[0]
        assert instr.arg2 == ">>"
        assert instr.arg3 == "2"

    def test_multiply_by_non_power_of_two_unchanged(self) -> None:
        """Test that multiplication by non-power of 2 is not reduced."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "$t1", "*", "3"))

        original_op = block.instructions[0].arg2
        reducer = StrengthReducer()
        reducer.reduce_block(block)

        instr = block.instructions[0]
        assert instr.arg2 == original_op  # Should not change


class TestCommonSubexpressionElimination:
    """Test common subexpression elimination."""

    def test_eliminate_duplicate_expression(self) -> None:
        """Test elimination of duplicate expressions."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "a", "+", "b"))
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t1", "a", "+", "b"))

        cse = CommonSubexpressionEliminator()
        cse.eliminate_block(block)

        # Second instruction should be a copy of first result
        second_instr = block.instructions[1]
        assert second_instr.opcode == IROpcode.COPY
        assert second_instr.arg1 == "$t0"

    def test_no_elimination_different_expressions(self) -> None:
        """Test that different expressions are not eliminated."""
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "a", "+", "b"))
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t1", "a", "+", "c"))

        cse = CommonSubexpressionEliminator()
        cse.eliminate_block(block)

        # Both should be BinOp
        assert block.instructions[0].opcode == IROpcode.BIN_OP
        assert block.instructions[1].opcode == IROpcode.BIN_OP


class TestIROptimizer:
    """Test the complete optimizer."""

    def test_optimize_single_pass(self) -> None:
        """Test running a single optimization pass."""
        func = IRFunction("test", [], IntType())
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "2", "+", "3"))
        func.add_block(block)

        program = IRProgram()
        program.add_function(func)

        optimizer = IROptimizer()
        result = optimizer.optimize(program, ["constant_fold"])

        # Program should be optimized
        assert len(result.functions) == 1

    def test_optimize_multiple_passes(self) -> None:
        """Test running multiple optimization passes."""
        func = IRFunction("test", [], IntType())
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t0", "42"))
        block.add_instruction(IRInstruction(IROpcode.COPY, "$t1", "$t0"))
        func.add_block(block)

        program = IRProgram()
        program.add_function(func)

        optimizer = IROptimizer()
        result = optimizer.optimize(program, ["copy_prop", "constant_fold"])

        assert len(result.functions) == 1

    def test_optimize_all_passes(self) -> None:
        """Test running all optimization passes."""
        func = IRFunction("test", [], IntType())
        block = IRBasicBlock("test")
        block.add_instruction(IRInstruction(IROpcode.BIN_OP, "$t0", "4", "*", "2"))
        func.add_block(block)

        program = IRProgram()
        program.add_function(func)

        optimizer = IROptimizer()
        result = optimizer.optimize(program)  # All passes

        assert len(result.functions) == 1
