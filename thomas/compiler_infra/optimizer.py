"""IR optimization passes for the Thomas compiler."""

from __future__ import annotations

from .ir import IRBasicBlock, IRFunction, IRInstruction, IROpcode, IRProgram


class ConstantFolder:
    """Constant folding optimization pass."""

    def __init__(self) -> None:
        """Initialize the constant folder."""
        self.constants: dict[str, tuple[str, float]] = {}  # temp -> (type, value)

    def fold_operation(self, op: str, left: str, right: str) -> tuple[str, float] | None:
        """Try to fold a binary operation.

        Returns:
            (type, value) if successful, None otherwise.
        """
        try:
            if op == "+":
                return ("num", float(left) + float(right))
            elif op == "-":
                return ("num", float(left) - float(right))
            elif op == "*":
                return ("num", float(left) * float(right))
            elif op == "/":
                if float(right) != 0:
                    return ("num", float(left) / float(right))
            elif op == "%":
                return ("num", int(float(left)) % int(float(right)))
            elif op == "==":
                return ("bool", 1.0 if float(left) == float(right) else 0.0)
            elif op == "!=":
                return ("bool", 1.0 if float(left) != float(right) else 0.0)
            elif op == "<":
                return ("bool", 1.0 if float(left) < float(right) else 0.0)
            elif op == ">":
                return ("bool", 1.0 if float(left) > float(right) else 0.0)
            elif op == "<=":
                return ("bool", 1.0 if float(left) <= float(right) else 0.0)
            elif op == ">=":
                return ("bool", 1.0 if float(left) >= float(right) else 0.0)
            elif op == "&&":
                return ("bool", 1.0 if (float(left) and float(right)) else 0.0)
            elif op == "||":
                return ("bool", 1.0 if (float(left) or float(right)) else 0.0)
        except (ValueError, ZeroDivisionError):
            pass

        return None

    def is_constant(self, value: str) -> bool:
        """Check if a value is a constant."""
        try:
            float(value)
            return True
        except ValueError:
            return value in self.constants

    def get_constant_value(self, value: str) -> float | None:
        """Get the numeric value of a constant."""
        try:
            return float(value)
        except ValueError:
            if value in self.constants:
                return self.constants[value][1]
        return None

    def fold_block(self, block: IRBasicBlock) -> None:
        """Apply constant folding to a block."""
        i = 0
        while i < len(block.instructions):
            instr = block.instructions[i]

            if instr.opcode == IROpcode.COPY:
                if self.is_constant(instr.arg1):
                    self.constants[instr.result] = ("num", self.get_constant_value(instr.arg1))

            elif instr.opcode == IROpcode.BIN_OP:
                if self.is_constant(instr.arg1) and self.is_constant(instr.arg3):
                    left_val = self.get_constant_value(instr.arg1)
                    right_val = self.get_constant_value(instr.arg3)
                    folded = self.fold_operation(instr.arg2, str(left_val), str(right_val))
                    if folded:
                        fold_type, fold_val = folded
                        self.constants[instr.result] = (fold_type, fold_val)

            i += 1

    def optimize(self, program: IRProgram) -> IRProgram:
        """Apply constant folding to the entire program.

        Args:
            program: The IR program to optimize.

        Returns:
            The optimized program.
        """
        for func in program.functions:
            self.constants.clear()
            for block in func.blocks:
                self.fold_block(block)

        return program


class DeadCodeEliminator:
    """Dead code elimination optimization pass."""

    def reachable_blocks(self, func: IRFunction) -> set[str]:
        """Find all reachable blocks in a function."""
        reachable: set[str] = set()
        to_visit = [func.blocks[0].label]

        while to_visit:
            label = to_visit.pop()
            if label in reachable:
                continue
            reachable.add(label)

            # Find this block
            block = None
            for b in func.blocks:
                if b.label == label:
                    block = b
                    break

            if not block:
                continue

            # Find successors
            for instr in block.instructions:
                if instr.opcode == IROpcode.JUMP:
                    if instr.arg1 and instr.arg1 not in reachable:
                        to_visit.append(instr.arg1)
                elif instr.opcode == IROpcode.COND_JUMP:
                    if instr.arg2 and instr.arg2 not in reachable:
                        to_visit.append(instr.arg2)
                    # Conditional jump can also fall through
                    next_block_idx = func.blocks.index(block) + 1
                    if next_block_idx < len(func.blocks):
                        next_label = func.blocks[next_block_idx].label
                        if next_label not in reachable:
                            to_visit.append(next_label)

        return reachable

    def remove_unreachable_blocks(self, func: IRFunction) -> None:
        """Remove unreachable blocks from a function."""
        reachable = self.reachable_blocks(func)
        func.blocks = [b for b in func.blocks if b.label in reachable]

    def remove_dead_stores(self, block: IRBasicBlock, live_out: set[str]) -> None:
        """Remove stores to dead variables."""
        # Simple approach: remove instructions whose result is not used
        used_after: dict[int, set[str]] = {}
        live = live_out.copy()

        # Backward pass to compute what's live after each instruction
        for i in range(len(block.instructions) - 1, -1, -1):
            used_after[i] = live.copy()

            instr = block.instructions[i]

            # Add uses
            if instr.arg1 and isinstance(instr.arg1, str) and instr.arg1.startswith("$"):
                live.add(instr.arg1)
            if instr.arg3 and isinstance(instr.arg3, str) and instr.arg3.startswith("$"):
                live.add(instr.arg3)

            # Remove defs
            if instr.result:
                live.discard(instr.result)

    def optimize(self, program: IRProgram) -> IRProgram:
        """Apply dead code elimination to the entire program.

        Args:
            program: The IR program to optimize.

        Returns:
            The optimized program.
        """
        for func in program.functions:
            self.remove_unreachable_blocks(func)

        return program


class CopyPropagation:
    """Copy propagation optimization pass."""

    def propagate_block(self, block: IRBasicBlock) -> None:
        """Apply copy propagation to a block."""
        copies: dict[str, str] = {}  # src -> dst

        for instr in block.instructions:
            # Replace uses with the original value
            if instr.arg1 and isinstance(instr.arg1, str) and instr.arg1 in copies:
                instr.arg1 = copies[instr.arg1]
            if instr.arg3 and isinstance(instr.arg3, str) and instr.arg3 in copies:
                instr.arg3 = copies[instr.arg3]

            # Track new copies
            if instr.opcode == IROpcode.COPY:
                if instr.arg1 and isinstance(instr.arg1, str):
                    copies[instr.result] = instr.arg1

    def optimize(self, program: IRProgram) -> IRProgram:
        """Apply copy propagation to the entire program.

        Args:
            program: The IR program to optimize.

        Returns:
            The optimized program.
        """
        for func in program.functions:
            for block in func.blocks:
                self.propagate_block(block)

        return program


class StrengthReducer:
    """Strength reduction optimization pass."""

    def is_power_of_two(self, n: int) -> bool:
        """Check if n is a power of 2."""
        return n > 0 and (n & (n - 1)) == 0

    def log2(self, n: int) -> int:
        """Compute log2(n) for power of 2."""
        return (n - 1).bit_length()

    def reduce_block(self, block: IRBasicBlock) -> None:
        """Apply strength reduction to a block."""
        for instr in block.instructions:
            if instr.opcode == IROpcode.BIN_OP:
                try:
                    if instr.arg2 == "*" and isinstance(instr.arg3, str):
                        right_val = int(instr.arg3)
                        if self.is_power_of_two(right_val):
                            # Replace * with <<
                            shift = self.log2(right_val)
                            instr.arg2 = "<<"
                            instr.arg3 = str(shift)

                    elif instr.arg2 == "/" and isinstance(instr.arg3, str):
                        right_val = int(instr.arg3)
                        if self.is_power_of_two(right_val):
                            # Replace / with >>
                            shift = self.log2(right_val)
                            instr.arg2 = ">>"
                            instr.arg3 = str(shift)
                except (ValueError, TypeError):
                    pass

    def optimize(self, program: IRProgram) -> IRProgram:
        """Apply strength reduction to the entire program.

        Args:
            program: The IR program to optimize.

        Returns:
            The optimized program.
        """
        for func in program.functions:
            for block in func.blocks:
                self.reduce_block(block)

        return program


class CommonSubexpressionEliminator:
    """Common subexpression elimination optimization pass."""

    def eliminate_block(self, block: IRBasicBlock) -> None:
        """Apply CSE to a block."""
        expr_cache: dict[tuple, str] = {}  # (op, arg1, arg2) -> result

        i = 0
        while i < len(block.instructions):
            instr = block.instructions[i]

            if instr.opcode == IROpcode.BIN_OP:
                key = (instr.arg2, instr.arg1, instr.arg3)
                if key in expr_cache:
                    # Replace with cached result
                    new_instr = IRInstruction(IROpcode.COPY, result=instr.result, arg1=expr_cache[key])
                    block.instructions[i] = new_instr
                else:
                    expr_cache[key] = instr.result

            i += 1

    def optimize(self, program: IRProgram) -> IRProgram:
        """Apply CSE to the entire program.

        Args:
            program: The IR program to optimize.

        Returns:
            The optimized program.
        """
        for func in program.functions:
            for block in func.blocks:
                self.eliminate_block(block)

        return program


class IROptimizer:
    """Main optimizer that applies all optimization passes."""

    def __init__(self) -> None:
        """Initialize the optimizer."""
        self.const_folder = ConstantFolder()
        self.dead_code_elim = DeadCodeEliminator()
        self.copy_prop = CopyPropagation()
        self.strength_reducer = StrengthReducer()
        self.cse = CommonSubexpressionEliminator()

    def optimize(self, program: IRProgram, passes: list[str] | None = None) -> IRProgram:
        """Apply optimization passes to the IR.

        Args:
            program: The IR program to optimize.
            passes: List of passes to apply. If None, applies all passes.

        Returns:
            The optimized program.
        """
        if passes is None:
            passes = ["constant_fold", "dead_code", "copy_prop", "strength_reduce", "cse"]

        for pass_name in passes:
            if pass_name == "constant_fold":
                program = self.const_folder.optimize(program)
            elif pass_name == "dead_code":
                program = self.dead_code_elim.optimize(program)
            elif pass_name == "copy_prop":
                program = self.copy_prop.optimize(program)
            elif pass_name == "strength_reduce":
                program = self.strength_reducer.optimize(program)
            elif pass_name == "cse":
                program = self.cse.optimize(program)

        return program
