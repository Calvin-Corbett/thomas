"""Intermediate representation (IR) for the Thomas compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from ._types import (
    ArrayLit,
    AssignStmt,
    ASTNode,
    ASTVisitor,
    BinaryExpr,
    Block,
    BoolLit,
    CallExpr,
    ExprStmt,
    FloatLit,
    ForStmt,
    FuncDecl,
    Identifier,
    IfStmt,
    IndexAssignStmt,
    IndexExpr,
    IntLit,
    NullLit,
    Program,
    ReturnStmt,
    StringLit,
    TokenType,
    Type,
    UnaryExpr,
    VarDecl,
    WhileStmt,
)


class IROpcode(Enum):
    """IR instruction opcodes."""

    BIN_OP = auto()
    UNARY_OP = auto()
    COPY = auto()
    CALL = auto()
    RETURN = auto()
    LABEL = auto()
    JUMP = auto()
    COND_JUMP = auto()
    PARAM = auto()
    LOAD_ARRAY = auto()
    STORE_ARRAY = auto()
    ALLOC = auto()


@dataclass
class IRInstruction:
    """An intermediate representation instruction."""

    opcode: IROpcode
    result: str | None = None  # Destination temp variable
    arg1: Any | None = None
    arg2: Any | None = None
    arg3: Any | None = None  # Extra argument for some ops

    def __str__(self) -> str:
        if self.opcode == IROpcode.BIN_OP:
            return f"{self.result} = {self.arg1} {self.arg2} {self.arg3}"
        elif self.opcode == IROpcode.UNARY_OP:
            return f"{self.result} = {self.arg1} {self.arg2}"
        elif self.opcode == IROpcode.COPY:
            return f"{self.result} = {self.arg1}"
        elif self.opcode == IROpcode.CALL:
            return f"{self.result} = call {self.arg1}({self.arg2})"
        elif self.opcode == IROpcode.RETURN:
            return f"return {self.arg1}" if self.arg1 else "return"
        elif self.opcode == IROpcode.LABEL:
            return f"{self.arg1}:"
        elif self.opcode == IROpcode.JUMP:
            return f"jump {self.arg1}"
        elif self.opcode == IROpcode.COND_JUMP:
            return f"if {self.arg1} jump {self.arg2}"
        elif self.opcode == IROpcode.PARAM:
            return f"param {self.arg1}"
        elif self.opcode == IROpcode.LOAD_ARRAY:
            return f"{self.result} = {self.arg1}[{self.arg2}]"
        elif self.opcode == IROpcode.STORE_ARRAY:
            return f"{self.arg1}[{self.arg2}] = {self.arg3}"
        elif self.opcode == IROpcode.ALLOC:
            return f"{self.result} = alloc({self.arg1})"
        return str(self.opcode)


@dataclass
class IRBasicBlock:
    """A basic block in the IR."""

    label: str
    instructions: list[IRInstruction] = field(default_factory=list)

    def add_instruction(self, instr: IRInstruction) -> None:
        """Add an instruction to this block."""
        self.instructions.append(instr)


@dataclass
class IRFunction:
    """An intermediate representation of a function."""

    name: str
    params: list[tuple[str, Type]]
    return_type: Type
    blocks: list[IRBasicBlock] = field(default_factory=list)

    def add_block(self, block: IRBasicBlock) -> None:
        """Add a basic block to this function."""
        self.blocks.append(block)


@dataclass
class IRProgram:
    """An intermediate representation of a complete program."""

    functions: list[IRFunction] = field(default_factory=list)

    def add_function(self, func: IRFunction) -> None:
        """Add a function to the program."""
        self.functions.append(func)


class IRBuilder(ASTVisitor):
    """Builds IR from an AST."""

    def __init__(self) -> None:
        """Initialize the IR builder."""
        self.program = IRProgram()
        self.current_function: IRFunction | None = None
        self.current_block: IRBasicBlock | None = None
        self.temp_counter = 0
        self.label_counter = 0
        self.local_vars: dict[str, str] = {}  # Map variable name to temp

    def gen_temp(self) -> str:
        """Generate a new temporary variable."""
        temp = f"$t{self.temp_counter}"
        self.temp_counter += 1
        return temp

    def gen_label(self) -> str:
        """Generate a new label."""
        label = f"L{self.label_counter}"
        self.label_counter += 1
        return label

    def emit(self, instr: IRInstruction) -> None:
        """Emit an instruction to the current block."""
        if self.current_block:
            self.current_block.add_instruction(instr)

    def build(self, program: ASTNode) -> IRProgram:
        """Build IR from an AST.

        Args:
            program: The AST to convert to IR.

        Returns:
            The generated IRProgram.
        """
        program.accept(self)
        return self.program

    def visit_program(self, node: Program) -> str | None:
        """Visit a program node."""
        for decl in node.declarations:
            if isinstance(decl, FuncDecl):
                decl.accept(self)
        return None

    def visit_func_decl(self, node: FuncDecl) -> str | None:
        """Visit a function declaration."""
        old_function = self.current_function
        old_block = self.current_block

        self.current_function = IRFunction(node.name, node.params, node.return_type)
        self.local_vars.clear()
        self.temp_counter = 0

        # Create entry block
        entry_block = IRBasicBlock("entry")
        self.current_function.add_block(entry_block)
        self.current_block = entry_block

        # Map parameters to temps
        for param_name, _ in node.params:
            temp = self.gen_temp()
            self.local_vars[param_name] = temp
            self.emit(IRInstruction(IROpcode.PARAM, result=temp, arg1=param_name))

        # Generate code for body
        node.body.accept(self)

        # Add implicit return if not present
        if not self.block_ends_with_return():
            self.emit(IRInstruction(IROpcode.RETURN))

        self.program.add_function(self.current_function)

        self.current_function = old_function
        self.current_block = old_block

        return None

    def block_ends_with_return(self) -> bool:
        """Check if current block ends with a return."""
        if not self.current_block or not self.current_block.instructions:
            return False
        return self.current_block.instructions[-1].opcode == IROpcode.RETURN

    def visit_var_decl(self, node: VarDecl) -> str | None:
        """Visit a variable declaration."""
        temp = self.gen_temp()
        self.local_vars[node.name] = temp

        if node.init_expr:
            init_value = node.init_expr.accept(self)
            if init_value:
                self.emit(IRInstruction(IROpcode.COPY, result=temp, arg1=init_value))

        return temp

    def visit_block(self, node: Block) -> str | None:
        """Visit a block."""
        for stmt in node.statements:
            stmt.accept(self)
        return None

    def visit_if_stmt(self, node: IfStmt) -> str | None:
        """Visit an if statement."""
        cond_value = node.condition.accept(self)

        then_label = self.gen_label()
        else_label = self.gen_label()
        end_label = self.gen_label()

        if cond_value:
            self.emit(IRInstruction(IROpcode.COND_JUMP, arg1=cond_value, arg2=then_label))
            if node.else_branch:
                self.emit(IRInstruction(IROpcode.JUMP, arg1=else_label))
            else:
                self.emit(IRInstruction(IROpcode.JUMP, arg1=end_label))

        # Then branch
        then_block = IRBasicBlock(then_label)
        self.current_function.add_block(then_block)
        old_block = self.current_block
        self.current_block = then_block
        node.then_branch.accept(self)
        if not self.block_ends_with_return():
            self.emit(IRInstruction(IROpcode.JUMP, arg1=end_label))
        self.current_block = old_block

        # Else branch
        if node.else_branch:
            else_block = IRBasicBlock(else_label)
            self.current_function.add_block(else_block)
            self.current_block = else_block
            node.else_branch.accept(self)
            if not self.block_ends_with_return():
                self.emit(IRInstruction(IROpcode.JUMP, arg1=end_label))
            self.current_block = old_block

        # End block
        end_block = IRBasicBlock(end_label)
        self.current_function.add_block(end_block)
        self.current_block = end_block

        return None

    def visit_while_stmt(self, node: WhileStmt) -> str | None:
        """Visit a while statement."""
        loop_label = self.gen_label()
        body_label = self.gen_label()
        end_label = self.gen_label()

        # Jump to loop condition
        self.emit(IRInstruction(IROpcode.JUMP, arg1=loop_label))

        # Loop condition block
        loop_block = IRBasicBlock(loop_label)
        self.current_function.add_block(loop_block)
        old_block = self.current_block
        self.current_block = loop_block

        cond_value = node.condition.accept(self)
        if cond_value:
            self.emit(IRInstruction(IROpcode.COND_JUMP, arg1=cond_value, arg2=body_label))
            self.emit(IRInstruction(IROpcode.JUMP, arg1=end_label))

        # Body block
        body_block = IRBasicBlock(body_label)
        self.current_function.add_block(body_block)
        self.current_block = body_block
        node.body.accept(self)
        self.emit(IRInstruction(IROpcode.JUMP, arg1=loop_label))

        # End block
        end_block = IRBasicBlock(end_label)
        self.current_function.add_block(end_block)
        self.current_block = end_block
        self.current_block = old_block

        return None

    def visit_for_stmt(self, node: ForStmt) -> str | None:
        """Visit a for statement."""
        loop_label = self.gen_label()
        body_label = self.gen_label()
        update_label = self.gen_label()
        end_label = self.gen_label()

        # Init
        if node.init:
            node.init.accept(self)

        self.emit(IRInstruction(IROpcode.JUMP, arg1=loop_label))

        # Condition block
        loop_block = IRBasicBlock(loop_label)
        self.current_function.add_block(loop_block)
        old_block = self.current_block
        self.current_block = loop_block

        if node.condition:
            cond_value = node.condition.accept(self)
            if cond_value:
                self.emit(IRInstruction(IROpcode.COND_JUMP, arg1=cond_value, arg2=body_label))
        self.emit(IRInstruction(IROpcode.JUMP, arg1=end_label))

        # Body block
        body_block = IRBasicBlock(body_label)
        self.current_function.add_block(body_block)
        self.current_block = body_block
        node.body.accept(self)
        self.emit(IRInstruction(IROpcode.JUMP, arg1=update_label))

        # Update block
        update_block = IRBasicBlock(update_label)
        self.current_function.add_block(update_block)
        self.current_block = update_block
        if node.update:
            node.update.accept(self)
        self.emit(IRInstruction(IROpcode.JUMP, arg1=loop_label))

        # End block
        end_block = IRBasicBlock(end_label)
        self.current_function.add_block(end_block)
        self.current_block = end_block
        self.current_block = old_block

        return None

    def visit_return_stmt(self, node: ReturnStmt) -> str | None:
        """Visit a return statement."""
        if node.value:
            value = node.value.accept(self)
            self.emit(IRInstruction(IROpcode.RETURN, arg1=value))
        else:
            self.emit(IRInstruction(IROpcode.RETURN))
        return None

    def visit_assign_stmt(self, node: AssignStmt) -> str | None:
        """Visit an assignment statement."""
        value = node.value.accept(self)
        if node.target in self.local_vars:
            target_temp = self.local_vars[node.target]
        else:
            target_temp = self.gen_temp()
            self.local_vars[node.target] = target_temp

        if node.op == TokenType.ASSIGN:
            self.emit(IRInstruction(IROpcode.COPY, result=target_temp, arg1=value))
        elif node.op == TokenType.PLUS_ASSIGN:
            temp = self.gen_temp()
            self.emit(IRInstruction(IROpcode.BIN_OP, result=temp, arg1=target_temp, arg2="+", arg3=value))
            self.emit(IRInstruction(IROpcode.COPY, result=target_temp, arg1=temp))
        elif node.op == TokenType.MINUS_ASSIGN:
            temp = self.gen_temp()
            self.emit(IRInstruction(IROpcode.BIN_OP, result=temp, arg1=target_temp, arg2="-", arg3=value))
            self.emit(IRInstruction(IROpcode.COPY, result=target_temp, arg1=temp))

        return target_temp

    def visit_index_assign_stmt(self, node: IndexAssignStmt) -> str | None:
        """Visit an array index assignment."""
        index_value = node.index.accept(self)
        value = node.value.accept(self)
        array_temp = self.local_vars.get(node.target)
        if array_temp:
            self.emit(IRInstruction(IROpcode.STORE_ARRAY, arg1=array_temp, arg2=index_value, arg3=value))
        return None

    def visit_expr_stmt(self, node: ExprStmt) -> str | None:
        """Visit an expression statement."""
        node.expr.accept(self)
        return None

    def visit_binary_expr(self, node: BinaryExpr) -> str | None:
        """Visit a binary expression."""
        left = node.left.accept(self)
        right = node.right.accept(self)

        temp = self.gen_temp()

        op_map = {
            TokenType.PLUS: "+",
            TokenType.MINUS: "-",
            TokenType.STAR: "*",
            TokenType.SLASH: "/",
            TokenType.PERCENT: "%",
            TokenType.EQ: "==",
            TokenType.NE: "!=",
            TokenType.LT: "<",
            TokenType.GT: ">",
            TokenType.LE: "<=",
            TokenType.GE: ">=",
            TokenType.LOGICAL_AND: "&&",
            TokenType.LOGICAL_OR: "||",
            TokenType.AND: "&&",
            TokenType.OR: "||",
        }

        op = op_map.get(node.op, str(node.op))
        self.emit(IRInstruction(IROpcode.BIN_OP, result=temp, arg1=left, arg2=op, arg3=right))

        return temp

    def visit_unary_expr(self, node: UnaryExpr) -> str | None:
        """Visit a unary expression."""
        operand = node.operand.accept(self)
        temp = self.gen_temp()

        op_map = {
            TokenType.MINUS: "-",
            TokenType.NOT: "!",
        }

        op = op_map.get(node.op, str(node.op))
        self.emit(IRInstruction(IROpcode.UNARY_OP, result=temp, arg1=op, arg2=operand))

        return temp

    def visit_call_expr(self, node: CallExpr) -> str | None:
        """Visit a function call."""
        args = []
        for arg in node.args:
            arg_value = arg.accept(self)
            args.append(arg_value)

        temp = self.gen_temp()
        self.emit(IRInstruction(IROpcode.CALL, result=temp, arg1=node.name, arg2=args))

        return temp

    def visit_index_expr(self, node: IndexExpr) -> str | None:
        """Visit an array index expression."""
        index = node.index.accept(self)
        array_temp = self.local_vars.get(node.target)

        temp = self.gen_temp()
        if array_temp:
            self.emit(IRInstruction(IROpcode.LOAD_ARRAY, result=temp, arg1=array_temp, arg2=index))

        return temp

    def visit_array_lit(self, node: ArrayLit) -> str | None:
        """Visit an array literal."""
        temp = self.gen_temp()
        self.emit(IRInstruction(IROpcode.ALLOC, result=temp, arg1=len(node.elements)))

        for i, elem in enumerate(node.elements):
            elem_value = elem.accept(self)
            index_temp = self.gen_temp()
            self.emit(IRInstruction(IROpcode.COPY, result=index_temp, arg1=i))
            self.emit(IRInstruction(IROpcode.STORE_ARRAY, arg1=temp, arg2=index_temp, arg3=elem_value))

        return temp

    def visit_identifier(self, node: Identifier) -> str | None:
        """Visit an identifier."""
        return self.local_vars.get(node.name, node.name)

    def visit_int_lit(self, node: IntLit) -> str | None:
        """Visit an integer literal."""
        return str(node.value)

    def visit_float_lit(self, node: FloatLit) -> str | None:
        """Visit a float literal."""
        return str(node.value)

    def visit_string_lit(self, node: StringLit) -> str | None:
        """Visit a string literal."""
        return f'"{node.value}"'

    def visit_bool_lit(self, node: BoolLit) -> str | None:
        """Visit a boolean literal."""
        return str(node.value)

    def visit_null_lit(self, node: NullLit) -> str | None:
        """Visit a null literal."""
        return "null"
