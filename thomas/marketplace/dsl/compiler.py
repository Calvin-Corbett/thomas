"""Bytecode compiler for DSL."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from ._types import (
    Assignment,
    ASTNode,
    BinaryOp,
    Block,
    BreakExpr,
    ContinueExpr,
    DictExpr,
    ForLoop,
    FunctionCall,
    FunctionDef,
    Identifier,
    IfExpr,
    IndexExpr,
    LambdaExpr,
    LetBinding,
    ListExpr,
    Literal,
    MatchExpr,
    ReturnExpr,
    UnaryOp,
    WhileLoop,
)


class OpCode(Enum):
    """Bytecode instruction opcodes."""

    # Stack operations
    LOAD_CONST = auto()
    LOAD_VAR = auto()
    STORE_VAR = auto()
    DELETE_VAR = auto()
    POP = auto()
    DUP = auto()

    # Arithmetic operations
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    POW = auto()
    NEG = auto()

    # Comparison operations
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()

    # Logical operations
    AND = auto()
    OR = auto()
    NOT = auto()

    # Bitwise operations
    BIT_AND = auto()
    BIT_OR = auto()
    BIT_XOR = auto()
    BIT_NOT = auto()
    LSHIFT = auto()
    RSHIFT = auto()

    # Control flow
    JUMP = auto()
    JUMP_IF_FALSE = auto()
    JUMP_IF_TRUE = auto()
    LOOP_ITERATE = auto()

    # Function calls
    CALL = auto()
    RETURN = auto()

    # Collections
    BUILD_LIST = auto()
    BUILD_DICT = auto()
    INDEX = auto()
    STORE_INDEX = auto()

    # Other
    BREAK = auto()
    CONTINUE = auto()
    NOP = auto()


@dataclass
class Instruction:
    """Single bytecode instruction."""

    opcode: OpCode
    arg: Any | None = None

    def __repr__(self) -> str:
        """String representation."""
        if self.arg is None:
            return self.opcode.name
        return f"{self.opcode.name} {self.arg}"


@dataclass
class CodeObject:
    """Compiled code object."""

    instructions: list[Instruction] = field(default_factory=list)
    constants: list[Any] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    upvalues: list[str] = field(default_factory=list)
    name: str = "<code>"
    params: list[str] = field(default_factory=list)

    def emit(self, opcode: OpCode, arg: Any | None = None) -> int:
        """Emit instruction and return offset.

        Args:
            opcode: Operation code
            arg: Optional argument

        Returns:
            Instruction offset
        """
        offset = len(self.instructions)
        self.instructions.append(Instruction(opcode, arg))
        return offset

    def add_constant(self, value: Any) -> int:
        """Add constant and return index.

        Args:
            value: Constant value

        Returns:
            Index in constants pool
        """
        self.constants.append(value)
        return len(self.constants) - 1

    def add_variable(self, name: str) -> int:
        """Add variable and return index.

        Args:
            name: Variable name

        Returns:
            Index in variables list
        """
        if name not in self.variables:
            self.variables.append(name)
        return self.variables.index(name)

    def patch_jump(self, offset: int, target: int) -> None:
        """Patch jump target.

        Args:
            offset: Jump instruction offset
            target: Target instruction offset
        """
        self.instructions[offset].arg = target


class Compiler:
    """Compile AST to bytecode."""

    def __init__(self) -> None:
        """Initialize compiler."""
        self.main_code = CodeObject(name="<main>")
        self.current_code = self.main_code
        self.code_stack: list[CodeObject] = []
        self.loop_stack: list[tuple[int, list[int]]] = []

    def compile(self, node: ASTNode) -> CodeObject:
        """Compile AST node.

        Args:
            node: Root node

        Returns:
            Compiled code object
        """
        self._compile_node(node)
        self.main_code.emit(OpCode.RETURN)
        return self.main_code

    def _compile_node(self, node: ASTNode) -> None:
        """Compile single node.

        Args:
            node: Node to compile
        """
        if isinstance(node, Literal):
            idx = self.current_code.add_constant(node.value)
            self.current_code.emit(OpCode.LOAD_CONST, idx)

        elif isinstance(node, Identifier):
            idx = self.current_code.add_variable(node.name)
            self.current_code.emit(OpCode.LOAD_VAR, idx)

        elif isinstance(node, BinaryOp):
            self._compile_binary_op(node)

        elif isinstance(node, UnaryOp):
            self._compile_unary_op(node)

        elif isinstance(node, FunctionCall):
            self._compile_call(node)

        elif isinstance(node, Assignment):
            self._compile_assignment(node)

        elif isinstance(node, IfExpr):
            self._compile_if(node)

        elif isinstance(node, WhileLoop):
            self._compile_while(node)

        elif isinstance(node, ForLoop):
            self._compile_for(node)

        elif isinstance(node, Block):
            for i, stmt in enumerate(node.statements):
                self._compile_node(stmt)
                # Pop intermediate results, except for last statement
                if i < len(node.statements) - 1:
                    if not isinstance(stmt, (Block, IfExpr, WhileLoop, ForLoop, Assignment, FunctionDef, LetBinding)):
                        self.current_code.emit(OpCode.POP)

        elif isinstance(node, LetBinding):
            self._compile_let(node)

        elif isinstance(node, LambdaExpr):
            self._compile_lambda(node)

        elif isinstance(node, FunctionDef):
            self._compile_function_def(node)

        elif isinstance(node, MatchExpr):
            self._compile_match(node)

        elif isinstance(node, IndexExpr):
            self._compile_index(node)

        elif isinstance(node, ListExpr):
            for elem in node.elements:
                self._compile_node(elem)
            self.current_code.emit(OpCode.BUILD_LIST, len(node.elements))

        elif isinstance(node, DictExpr):
            for key, val in node.pairs:
                self._compile_node(key)
                self._compile_node(val)
            self.current_code.emit(OpCode.BUILD_DICT, len(node.pairs))

        elif isinstance(node, ReturnExpr):
            if node.value:
                self._compile_node(node.value)
            else:
                idx = self.current_code.add_constant(None)
                self.current_code.emit(OpCode.LOAD_CONST, idx)
            self.current_code.emit(OpCode.RETURN)

        elif isinstance(node, BreakExpr):
            self.current_code.emit(OpCode.BREAK)

        elif isinstance(node, ContinueExpr):
            self.current_code.emit(OpCode.CONTINUE)

    def _compile_call(self, node: FunctionCall) -> None:
        """Compile function call.

        Args:
            node: Function call node
        """
        # Compile arguments first
        for arg in node.arguments:
            self._compile_node(arg)

        # Compile function reference
        self._compile_node(node.function)

        # Emit CALL with argument count
        self.current_code.emit(OpCode.CALL, len(node.arguments))

    def _compile_binary_op(self, node: BinaryOp) -> None:
        """Compile binary operation.

        Args:
            node: Binary op node
        """
        self._compile_node(node.left)
        self._compile_node(node.right)

        opcode_map = {
            "+": OpCode.ADD,
            "-": OpCode.SUB,
            "*": OpCode.MUL,
            "/": OpCode.DIV,
            "%": OpCode.MOD,
            "**": OpCode.POW,
            "==": OpCode.EQ,
            "!=": OpCode.NE,
            "<": OpCode.LT,
            "<=": OpCode.LE,
            ">": OpCode.GT,
            ">=": OpCode.GE,
            "&": OpCode.BIT_AND,
            "|": OpCode.BIT_OR,
            "^": OpCode.BIT_XOR,
            "<<": OpCode.LSHIFT,
            ">>": OpCode.RSHIFT,
        }

        if node.operator in opcode_map:
            self.current_code.emit(opcode_map[node.operator])
        elif node.operator == "&&":
            self.current_code.emit(OpCode.AND)
        elif node.operator == "||":
            self.current_code.emit(OpCode.OR)

    def _compile_unary_op(self, node: UnaryOp) -> None:
        """Compile unary operation.

        Args:
            node: Unary op node
        """
        self._compile_node(node.operand)

        if node.operator == "-":
            self.current_code.emit(OpCode.NEG)
        elif node.operator == "!":
            self.current_code.emit(OpCode.NOT)
        elif node.operator == "~":
            self.current_code.emit(OpCode.BIT_NOT)

    def _compile_assignment(self, node: Assignment) -> None:
        """Compile assignment.

        Args:
            node: Assignment node
        """
        self._compile_node(node.value)
        idx = self.current_code.add_variable(node.target)

        if node.operator == "=":
            self.current_code.emit(OpCode.STORE_VAR, idx)
        else:
            # Compound assignment
            self.current_code.emit(OpCode.LOAD_VAR, idx)
            op_map = {
                "+=": OpCode.ADD,
                "-=": OpCode.SUB,
                "*=": OpCode.MUL,
                "/=": OpCode.DIV,
            }
            self.current_code.emit(op_map[node.operator])
            self.current_code.emit(OpCode.STORE_VAR, idx)

    def _compile_if(self, node: IfExpr) -> None:
        """Compile if expression.

        Args:
            node: If expression node
        """
        self._compile_node(node.condition)

        jump_false = self.current_code.emit(OpCode.JUMP_IF_FALSE)
        self._compile_node(node.then_expr)

        if node.else_expr:
            jump_end = self.current_code.emit(OpCode.JUMP)
            self.current_code.patch_jump(jump_false, len(self.current_code.instructions))
            self._compile_node(node.else_expr)
            self.current_code.patch_jump(jump_end, len(self.current_code.instructions))
        else:
            self.current_code.patch_jump(jump_false, len(self.current_code.instructions))

    def _compile_while(self, node: WhileLoop) -> None:
        """Compile while loop.

        Args:
            node: While loop node
        """
        loop_start = len(self.current_code.instructions)
        break_jumps: list[int] = []

        self.loop_stack.append((loop_start, break_jumps))

        self._compile_node(node.condition)
        jump_false = self.current_code.emit(OpCode.JUMP_IF_FALSE)

        self._compile_node(node.body)

        self.current_code.emit(OpCode.JUMP, loop_start)
        self.current_code.patch_jump(jump_false, len(self.current_code.instructions))

        self.loop_stack.pop()

        for break_jump in break_jumps:
            self.current_code.patch_jump(break_jump, len(self.current_code.instructions))

    def _compile_for(self, node: ForLoop) -> None:
        """Compile for loop.

        Translates to a while loop over an iterator.
        for i in items do body => for_each(items, fn |i| body)

        Args:
            node: For loop node
        """
        # Create an iterator from the iterable
        self._compile_node(node.iterable)

        # Create a function that represents the loop body
        code_obj = CodeObject(name="<for_body>", params=[node.variable])
        self.code_stack.append(self.current_code)
        self.current_code = code_obj

        if node.body:
            self._compile_node(node.body)
        else:
            idx = code_obj.add_constant(None)
            code_obj.emit(OpCode.LOAD_CONST, idx)

        code_obj.emit(OpCode.RETURN)

        self.current_code = self.code_stack.pop()

        # Create helper to iterate
        const_idx = self.current_code.add_constant(code_obj)
        self.current_code.emit(OpCode.LOAD_CONST, const_idx)

        # Emit LOOP_ITERATE opcode
        self.current_code.emit(OpCode.LOOP_ITERATE)

    def _compile_let(self, node: LetBinding) -> None:
        """Compile let binding.

        Args:
            node: Let binding node
        """
        self._compile_node(node.value)
        idx = self.current_code.add_variable(node.name)
        self.current_code.emit(OpCode.STORE_VAR, idx)
        self._compile_node(node.body)

    def _compile_lambda(self, node: Any) -> None:
        """Compile lambda expression.

        Args:
            node: Lambda node
        """
        code_obj = CodeObject(name="<lambda>", params=node.parameters)
        self.code_stack.append(self.current_code)
        self.current_code = code_obj

        if node.body:
            self._compile_node(node.body)
        else:
            idx = code_obj.add_constant(None)
            code_obj.emit(OpCode.LOAD_CONST, idx)

        code_obj.emit(OpCode.RETURN)

        self.current_code = self.code_stack.pop()
        const_idx = self.current_code.add_constant(code_obj)
        self.current_code.emit(OpCode.LOAD_CONST, const_idx)

    def _compile_function_def(self, node: FunctionDef) -> None:
        """Compile function definition.

        Args:
            node: Function def node
        """
        code_obj = CodeObject(name=node.name, params=node.parameters)
        self.code_stack.append(self.current_code)
        self.current_code = code_obj

        if node.body:
            self._compile_node(node.body)
        else:
            idx = code_obj.add_constant(None)
            code_obj.emit(OpCode.LOAD_CONST, idx)

        code_obj.emit(OpCode.RETURN)

        self.current_code = self.code_stack.pop()
        const_idx = self.current_code.add_constant(code_obj)
        self.current_code.emit(OpCode.LOAD_CONST, const_idx)
        var_idx = self.current_code.add_variable(node.name)
        self.current_code.emit(OpCode.STORE_VAR, var_idx)

    def _compile_match(self, node: MatchExpr) -> None:
        """Compile match expression as if-elif chain.

        Args:
            node: Match expression node
        """
        if not node.patterns:
            if node.default:
                self._compile_node(node.default)
            return

        self._compile_node(node.expr)

        jump_ends: list[int] = []
        dup_for_next = True

        for pattern_expr, result_expr in node.patterns:
            # If not the first pattern, duplicate the value for comparison
            if dup_for_next:
                self.current_code.emit(OpCode.DUP)

            # Compile pattern (right side of comparison)
            self._compile_node(pattern_expr)

            # Compare equality
            self.current_code.emit(OpCode.EQ)

            # If true, execute result and skip remaining patterns
            jump_false = self.current_code.emit(OpCode.JUMP_IF_FALSE)

            # Remove the duplicated value from stack
            self.current_code.emit(OpCode.POP)

            # Compile result
            self._compile_node(result_expr)

            # Jump to end
            jump_ends.append(self.current_code.emit(OpCode.JUMP))

            # Patch false jump to next pattern
            self.current_code.patch_jump(jump_false, len(self.current_code.instructions))

        # If no patterns matched, use default or push None
        if node.default:
            self.current_code.emit(OpCode.POP)  # Pop the original value
            self._compile_node(node.default)
        else:
            # Replace value with None
            self.current_code.emit(OpCode.POP)
            idx = self.current_code.add_constant(None)
            self.current_code.emit(OpCode.LOAD_CONST, idx)

        # Patch all jump_end jumps
        for jump_end in jump_ends:
            self.current_code.patch_jump(jump_end, len(self.current_code.instructions))

    def _compile_index(self, node: IndexExpr) -> None:
        """Compile index expression.

        Args:
            node: Index expression node
        """
        self._compile_node(node.object)
        self._compile_node(node.index)
        self.current_code.emit(OpCode.INDEX)
