"""Code generation for the Thomas compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from ._exceptions import CodegenError
from .ir import IRBasicBlock, IRFunction, IRInstruction, IROpcode, IRProgram


class Bytecode(Enum):
    """Bytecode instruction types."""

    PUSH = auto()
    POP = auto()
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    NEG = auto()
    NOT = auto()
    EQ = auto()
    NE = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    AND = auto()
    OR = auto()
    LOAD = auto()
    STORE = auto()
    CALL = auto()
    RET = auto()
    JMP = auto()
    JMP_IF_FALSE = auto()
    LABEL = auto()
    PRINT = auto()
    HALT = auto()


@dataclass
class BytecodeInstruction:
    """A bytecode instruction."""

    opcode: Bytecode
    arg: Any | None = None

    def __str__(self) -> str:
        if self.arg is not None:
            return f"{self.opcode.name} {self.arg}"
        return self.opcode.name


@dataclass
class BytecodeFunction:
    """A compiled function."""

    name: str
    param_count: int
    instructions: list[BytecodeInstruction] = field(default_factory=list)


@dataclass
class BytecodeProgram:
    """A compiled program."""

    functions: dict[str, BytecodeFunction] = field(default_factory=dict)
    main_instructions: list[BytecodeInstruction] = field(default_factory=list)
    constant_pool: dict[Any, int] = field(default_factory=dict)


class CodeGenerator:
    """Generates bytecode from IR."""

    def __init__(self) -> None:
        """Initialize the code generator."""
        self.program = BytecodeProgram()
        self.current_instructions: list[BytecodeInstruction] = []
        self.label_positions: dict[str, int] = {}
        self.label_jumps: list[tuple[int, str]] = []  # (instruction_idx, label)
        self.stack_depth = 0

    def emit(self, opcode: Bytecode, arg: Any | None = None) -> int:
        """Emit a bytecode instruction.

        Returns:
            The index of the emitted instruction.
        """
        idx = len(self.current_instructions)
        self.current_instructions.append(BytecodeInstruction(opcode, arg))
        return idx

    def emit_label(self, label: str) -> None:
        """Emit a label marker."""
        self.label_positions[label] = len(self.current_instructions)

    def emit_jump(self, label: str) -> int:
        """Emit a jump instruction, to be patched later."""
        idx = len(self.current_instructions)
        self.label_jumps.append((idx, label))
        return self.emit(Bytecode.JMP, None)

    def emit_cond_jump(self, label: str) -> int:
        """Emit a conditional jump instruction, to be patched later."""
        idx = len(self.current_instructions)
        self.label_jumps.append((idx, label))
        return self.emit(Bytecode.JMP_IF_FALSE, None)

    def patch_jumps(self) -> None:
        """Patch all jump targets."""
        for instr_idx, label in self.label_jumps:
            if label not in self.label_positions:
                raise CodegenError(f"Undefined label: {label}")
            target = self.label_positions[label]
            self.current_instructions[instr_idx].arg = target

    def add_constant(self, value: Any) -> int:
        """Add a constant to the constant pool.

        Returns:
            The index of the constant.
        """
        if value not in self.program.constant_pool:
            self.program.constant_pool[value] = len(self.program.constant_pool)
        return self.program.constant_pool[value]

    def codegen_ir_instruction(self, instr: IRInstruction) -> None:
        """Generate bytecode for an IR instruction."""
        if instr.opcode == IROpcode.BIN_OP:
            # Binary operations: push operands, apply operation
            self.emit_value(instr.arg1)  # Push left
            self.emit_value(instr.arg3)  # Push right

            op = instr.arg2
            if op == "+":
                self.emit(Bytecode.ADD)
            elif op == "-":
                self.emit(Bytecode.SUB)
            elif op == "*":
                self.emit(Bytecode.MUL)
            elif op == "/":
                self.emit(Bytecode.DIV)
            elif op == "%":
                self.emit(Bytecode.MOD)
            elif op == "==":
                self.emit(Bytecode.EQ)
            elif op == "!=":
                self.emit(Bytecode.NE)
            elif op == "<":
                self.emit(Bytecode.LT)
            elif op == ">":
                self.emit(Bytecode.GT)
            elif op == "<=":
                self.emit(Bytecode.LE)
            elif op == ">=":
                self.emit(Bytecode.GE)
            elif op == "&&":
                self.emit(Bytecode.AND)
            elif op == "||":
                self.emit(Bytecode.OR)

            # Store result
            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.UNARY_OP:
            # Unary operations
            self.emit_value(instr.arg2)

            op = instr.arg1
            if op == "-":
                self.emit(Bytecode.NEG)
            elif op == "!":
                self.emit(Bytecode.NOT)

            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.COPY:
            # Copy value
            self.emit_value(instr.arg1)
            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.LABEL:
            self.emit_label(instr.arg1)

        elif instr.opcode == IROpcode.JUMP:
            self.emit_jump(instr.arg1)

        elif instr.opcode == IROpcode.COND_JUMP:
            self.emit_value(instr.arg1)
            self.emit_cond_jump(instr.arg2)

        elif instr.opcode == IROpcode.CALL:
            # Function call
            args = instr.arg2 if isinstance(instr.arg2, list) else []
            for arg in args:
                self.emit_value(arg)
            self.emit(Bytecode.CALL, instr.arg1)
            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.RETURN:
            if instr.arg1:
                self.emit_value(instr.arg1)
            self.emit(Bytecode.RET)

        elif instr.opcode == IROpcode.LOAD_ARRAY:
            # Load from array: arr[index]
            self.emit_value(instr.arg1)  # array
            self.emit_value(instr.arg2)  # index
            self.emit(Bytecode.LOAD)
            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.STORE_ARRAY:
            # Store to array: arr[index] = value
            self.emit_value(instr.arg1)  # array
            self.emit_value(instr.arg2)  # index
            self.emit_value(instr.arg3)  # value
            self.emit(Bytecode.STORE)

        elif instr.opcode == IROpcode.ALLOC:
            # Allocate array
            self.emit_value(instr.arg1)  # size
            self.emit(Bytecode.PUSH, None)  # Allocate
            if instr.result:
                self.emit(Bytecode.STORE, self.variable_index(instr.result))

        elif instr.opcode == IROpcode.PARAM:
            # Parameter (handled in function setup)
            pass

    def emit_value(self, value: Any) -> None:
        """Emit code to push a value onto the stack."""
        if isinstance(value, str):
            if value.startswith("$"):  # Temporary variable
                self.emit(Bytecode.LOAD, self.variable_index(value))
            elif value.startswith('"'):  # String literal
                string_val = value[1:-1]  # Remove quotes
                const_idx = self.add_constant(string_val)
                self.emit(Bytecode.PUSH, const_idx)
            elif value == "null":
                self.emit(Bytecode.PUSH, None)
            elif value == "true":
                self.emit(Bytecode.PUSH, 1)
            elif value == "false":
                self.emit(Bytecode.PUSH, 0)
            else:
                try:
                    # Try to parse as number
                    if "." in value:
                        num = float(value)
                    else:
                        num = int(value)
                    const_idx = self.add_constant(num)
                    self.emit(Bytecode.PUSH, const_idx)
                except ValueError:
                    # Variable
                    self.emit(Bytecode.LOAD, self.variable_index(value))
        else:
            # Direct value
            const_idx = self.add_constant(value)
            self.emit(Bytecode.PUSH, const_idx)

    def variable_index(self, name: str) -> int:
        """Get or create an index for a variable."""
        # Simple approach: use hash
        return abs(hash(name)) % 10000

    def codegen_block(self, block: IRBasicBlock) -> None:
        """Generate bytecode for a basic block."""
        for instr in block.instructions:
            self.codegen_ir_instruction(instr)

    def codegen_function(self, func: IRFunction) -> None:
        """Generate bytecode for a function."""
        self.current_instructions = []
        self.label_positions = {}
        self.label_jumps = []

        for block in func.blocks:
            self.codegen_block(block)

        self.patch_jumps()

        bytecode_func = BytecodeFunction(func.name, len(func.params), self.current_instructions)
        self.program.functions[func.name] = bytecode_func

    def codegen(self, ir_program: IRProgram) -> BytecodeProgram:
        """Generate bytecode from an IR program.

        Args:
            ir_program: The IR program to compile.

        Returns:
            The generated bytecode program.
        """
        for func in ir_program.functions:
            self.codegen_function(func)

        return self.program
