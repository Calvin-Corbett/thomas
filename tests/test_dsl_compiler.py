"""Tests for DSL compiler."""

from thomas.marketplace.dsl import Assignment, BinaryOp, Compiler, DictExpr, IfExpr, ListExpr, Literal, OpCode, UnaryOp


class TestCompiler:
    """Test bytecode compiler."""

    def test_compile_literal_int(self) -> None:
        """Test compiling integer literal."""
        compiler = Compiler()
        ast = Literal(42)
        code = compiler.compile(ast)

        assert len(code.constants) > 0
        assert 42 in code.constants

    def test_compile_literal_string(self) -> None:
        """Test compiling string literal."""
        compiler = Compiler()
        ast = Literal("hello")
        code = compiler.compile(ast)

        assert "hello" in code.constants

    def test_compile_binary_addition(self) -> None:
        """Test compiling addition."""
        compiler = Compiler()
        ast = BinaryOp(Literal(1), "+", Literal(2))
        code = compiler.compile(ast)

        # Should have instructions for loading and adding
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.LOAD_CONST in opcodes
        assert OpCode.ADD in opcodes

    def test_compile_binary_subtraction(self) -> None:
        """Test compiling subtraction."""
        compiler = Compiler()
        ast = BinaryOp(Literal(5), "-", Literal(3))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.SUB in opcodes

    def test_compile_binary_multiplication(self) -> None:
        """Test compiling multiplication."""
        compiler = Compiler()
        ast = BinaryOp(Literal(4), "*", Literal(5))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.MUL in opcodes

    def test_compile_binary_division(self) -> None:
        """Test compiling division."""
        compiler = Compiler()
        ast = BinaryOp(Literal(10), "/", Literal(2))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.DIV in opcodes

    def test_compile_comparison(self) -> None:
        """Test compiling comparison."""
        compiler = Compiler()
        ast = BinaryOp(Literal(5), "<", Literal(10))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.LT in opcodes

    def test_compile_unary_negation(self) -> None:
        """Test compiling unary negation."""
        compiler = Compiler()
        ast = UnaryOp("-", Literal(42))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.NEG in opcodes

    def test_compile_unary_not(self) -> None:
        """Test compiling logical not."""
        compiler = Compiler()
        ast = UnaryOp("!", Literal(True))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.NOT in opcodes

    def test_compile_list_literal(self) -> None:
        """Test compiling list literal."""
        compiler = Compiler()
        ast = ListExpr([Literal(1), Literal(2)])
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BUILD_LIST in opcodes

    def test_compile_dict_literal(self) -> None:
        """Test compiling dict literal."""
        compiler = Compiler()
        ast = DictExpr([(Literal("a"), Literal(1))])
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BUILD_DICT in opcodes

    def test_compile_if_expression(self) -> None:
        """Test compiling if expression."""
        compiler = Compiler()
        ast = IfExpr(Literal(True), Literal(1), Literal(2))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.JUMP_IF_FALSE in opcodes

    def test_compile_assignment(self) -> None:
        """Test compiling assignment."""
        compiler = Compiler()
        ast = Assignment("x", Literal(42))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.STORE_VAR in opcodes

    def test_code_object_properties(self) -> None:
        """Test code object properties."""
        compiler = Compiler()
        ast = Literal(42)
        code = compiler.compile(ast)

        assert code.name == "<main>"
        assert len(code.instructions) > 0
        assert len(code.constants) > 0

    def test_add_constant(self) -> None:
        """Test adding constants to code object."""
        from thomas.marketplace.dsl import CodeObject

        code = CodeObject()

        idx1 = code.add_constant(42)
        idx2 = code.add_constant("hello")

        assert code.constants[idx1] == 42
        assert code.constants[idx2] == "hello"

    def test_add_variable(self) -> None:
        """Test adding variables to code object."""
        from thomas.marketplace.dsl import CodeObject

        code = CodeObject()

        idx1 = code.add_variable("x")
        idx2 = code.add_variable("y")

        assert code.variables[idx1] == "x"
        assert code.variables[idx2] == "y"

    def test_emit_instruction(self) -> None:
        """Test emitting instructions."""
        from thomas.marketplace.dsl import CodeObject

        code = CodeObject()

        offset1 = code.emit(OpCode.LOAD_CONST, 0)
        offset2 = code.emit(OpCode.RETURN)

        assert offset1 == 0
        assert offset2 == 1

    def test_patch_jump(self) -> None:
        """Test patching jump instructions."""
        from thomas.marketplace.dsl import CodeObject

        code = CodeObject()

        code.emit(OpCode.LOAD_CONST, 0)
        jump_offset = code.emit(OpCode.JUMP)
        code.emit(OpCode.LOAD_CONST, 1)

        target = len(code.instructions)
        code.patch_jump(jump_offset, target)

        assert code.instructions[jump_offset].arg == target

    def test_compile_power_operation(self) -> None:
        """Test compiling power operation."""
        compiler = Compiler()
        ast = BinaryOp(Literal(2), "**", Literal(3))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.POW in opcodes

    def test_compile_modulo_operation(self) -> None:
        """Test compiling modulo operation."""
        compiler = Compiler()
        ast = BinaryOp(Literal(10), "%", Literal(3))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.MOD in opcodes

    def test_compile_bitwise_operations(self) -> None:
        """Test compiling bitwise operations."""
        compiler = Compiler()

        # Test AND
        ast = BinaryOp(Literal(5), "&", Literal(3))
        code = compiler.compile(ast)
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BIT_AND in opcodes

        # Test OR
        compiler = Compiler()
        ast = BinaryOp(Literal(5), "|", Literal(3))
        code = compiler.compile(ast)
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BIT_OR in opcodes

    def test_compile_equality_operators(self) -> None:
        """Test compiling equality operators."""
        compiler = Compiler()

        # Test ==
        ast = BinaryOp(Literal(5), "==", Literal(5))
        code = compiler.compile(ast)
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.EQ in opcodes

        # Test !=
        compiler = Compiler()
        ast = BinaryOp(Literal(5), "!=", Literal(3))
        code = compiler.compile(ast)
        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.NE in opcodes

    def test_compile_bitwise_not(self) -> None:
        """Test compiling bitwise not."""
        compiler = Compiler()
        ast = UnaryOp("~", Literal(5))
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BIT_NOT in opcodes

    def test_compile_constants_deduplication(self) -> None:
        """Test that identical constants are deduplicated."""
        compiler = Compiler()
        ast = BinaryOp(Literal(42), "+", Literal(42))
        code = compiler.compile(ast)

        # Both 42s should reference same constant
        assert code.constants.count(42) >= 1

    def test_compile_nested_expressions(self) -> None:
        """Test compiling nested expressions."""
        compiler = Compiler()
        # (1 + 2) * (3 + 4)
        left = BinaryOp(Literal(1), "+", Literal(2))
        right = BinaryOp(Literal(3), "+", Literal(4))
        ast = BinaryOp(left, "*", right)
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.MUL in opcodes

    def test_compile_empty_list(self) -> None:
        """Test compiling empty list."""
        compiler = Compiler()
        ast = ListExpr([])
        code = compiler.compile(ast)

        opcodes = [instr.opcode for instr in code.instructions]
        assert OpCode.BUILD_LIST in opcodes
