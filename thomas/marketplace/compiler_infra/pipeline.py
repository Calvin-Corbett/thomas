"""Compiler pipeline orchestration for the Thomas language."""

from __future__ import annotations

import time
from typing import Any

from ._exceptions import CompilerError
from .codegen import CodeGenerator
from .ir import IRBuilder
from .lexer import Lexer
from .optimizer import IROptimizer
from .parser import Parser
from .type_checker import TypeChecker
from .vm import VirtualMachine


class CompilerConfig:
    """Configuration for the compiler pipeline."""

    def __init__(self) -> None:
        """Initialize compiler configuration."""
        self.optimize: bool = True
        self.optimization_passes: list[str] | None = None
        self.trace_vm: bool = False
        self.verbose: bool = False
        self.filename: str = "<source>"


class CompilationPhase:
    """Result of a compilation phase."""

    def __init__(self, name: str) -> None:
        """Initialize a compilation phase.

        Args:
            name: The name of the phase.
        """
        self.name = name
        self.start_time: float = 0
        self.end_time: float = 0

    @property
    def duration_ms(self) -> float:
        """Get the phase duration in milliseconds."""
        return (self.end_time - self.start_time) * 1000

    def __str__(self) -> str:
        return f"{self.name}: {self.duration_ms:.2f}ms"


class CompilationResult:
    """Result of a complete compilation."""

    def __init__(self) -> None:
        """Initialize a compilation result."""
        self.phases: dict[str, CompilationPhase] = {}
        self.result: Any = None
        self.errors: list[CompilerError] = []

    @property
    def total_time_ms(self) -> float:
        """Get total compilation time in milliseconds."""
        return sum(phase.duration_ms for phase in self.phases.values())

    def add_phase(self, phase: CompilationPhase) -> None:
        """Add a phase result."""
        self.phases[phase.name] = phase

    def __str__(self) -> str:
        lines = ["Compilation Result:"]
        for phase in self.phases.values():
            lines.append(f"  {phase}")
        lines.append(f"  Total: {self.total_time_ms:.2f}ms")
        return "\n".join(lines)


class Compiler:
    """Main compiler orchestrator."""

    def __init__(self, config: CompilerConfig | None = None) -> None:
        """Initialize the compiler.

        Args:
            config: Compiler configuration.
        """
        self.config = config or CompilerConfig()
        self.result = CompilationResult()

    def compile(self, source: str) -> CompilationResult:
        """Compile source code through the entire pipeline.

        Args:
            source: The source code to compile.

        Returns:
            A CompilationResult containing the compiled bytecode and timing info.

        Raises:
            CompilerError: If compilation fails at any stage.
        """
        try:
            # Phase 1: Lexical analysis
            phase = CompilationPhase("Lexing")
            phase.start_time = time.time()
            lexer = Lexer(source, self.config.filename)
            tokens = lexer.tokenize()
            phase.end_time = time.time()
            self.result.add_phase(phase)

            if self.config.verbose:
                print(f"Lexing produced {len(tokens)} tokens")

            # Phase 2: Parsing
            phase = CompilationPhase("Parsing")
            phase.start_time = time.time()
            parser = Parser(tokens)
            ast = parser.parse_program()
            phase.end_time = time.time()
            self.result.add_phase(phase)

            if self.config.verbose:
                print(f"Parsing produced AST with {len(ast.declarations)} declarations")

            # Phase 3: Type checking
            phase = CompilationPhase("Type Checking")
            phase.start_time = time.time()
            type_checker = TypeChecker()
            type_checker.check(ast)
            phase.end_time = time.time()
            self.result.add_phase(phase)

            if self.config.verbose:
                print("Type checking completed")

            # Phase 4: IR generation
            phase = CompilationPhase("IR Generation")
            phase.start_time = time.time()
            ir_builder = IRBuilder()
            ir_program = ir_builder.build(ast)
            phase.end_time = time.time()
            self.result.add_phase(phase)

            if self.config.verbose:
                print(f"IR generation produced {len(ir_program.functions)} functions")

            # Phase 5: Optimization
            if self.config.optimize:
                phase = CompilationPhase("Optimization")
                phase.start_time = time.time()
                optimizer = IROptimizer()
                ir_program = optimizer.optimize(ir_program, self.config.optimization_passes)
                phase.end_time = time.time()
                self.result.add_phase(phase)

                if self.config.verbose:
                    print("Optimization completed")

            # Phase 6: Code generation
            phase = CompilationPhase("Code Generation")
            phase.start_time = time.time()
            codegen = CodeGenerator()
            bytecode_program = codegen.codegen(ir_program)
            phase.end_time = time.time()
            self.result.add_phase(phase)

            if self.config.verbose:
                print(f"Code generation produced {len(bytecode_program.functions)} functions")

            self.result.result = bytecode_program
            return self.result

        except CompilerError as e:
            self.result.errors.append(e)
            raise

    def execute(self, bytecode_program: Any) -> Any:
        """Execute compiled bytecode.

        Args:
            bytecode_program: The compiled bytecode program.

        Returns:
            The result of execution.

        Raises:
            RuntimeError: If execution fails.
        """
        phase = CompilationPhase("Execution")
        phase.start_time = time.time()

        vm = VirtualMachine(bytecode_program)
        if self.config.trace_vm:
            vm.set_trace(True)

        result = vm.execute()

        phase.end_time = time.time()
        self.result.add_phase(phase)

        return result

    def compile_and_execute(self, source: str) -> Any:
        """Compile and execute source code in one step.

        Args:
            source: The source code to compile and execute.

        Returns:
            The execution result.

        Raises:
            CompilerError: If compilation fails.
            RuntimeError: If execution fails.
        """
        result = self.compile(source)
        if result.result:
            return self.execute(result.result)
        return None


def compile(source: str, optimize: bool = True, filename: str = "<source>") -> Any:
    """Convenience function to compile source code.

    Args:
        source: The source code to compile.
        optimize: Whether to apply optimizations.
        filename: The source filename for error reporting.

    Returns:
        The compiled bytecode program.

    Raises:
        CompilerError: If compilation fails.
    """
    config = CompilerConfig()
    config.optimize = optimize
    config.filename = filename

    compiler = Compiler(config)
    result = compiler.compile(source)
    return result.result


def compile_and_execute(source: str, optimize: bool = True, filename: str = "<source>") -> Any:
    """Convenience function to compile and execute source code.

    Args:
        source: The source code to compile and execute.
        optimize: Whether to apply optimizations.
        filename: The source filename for error reporting.

    Returns:
        The execution result.

    Raises:
        CompilerError: If compilation fails.
        RuntimeError: If execution fails.
    """
    config = CompilerConfig()
    config.optimize = optimize
    config.filename = filename

    compiler = Compiler(config)
    return compiler.compile_and_execute(source)
