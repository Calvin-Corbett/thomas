"""Virtual machine for executing Thomas bytecode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._exceptions import RuntimeError as Thomas_RuntimeError
from .codegen import Bytecode, BytecodeFunction, BytecodeProgram


@dataclass
class CallFrame:
    """A function call frame."""

    function: BytecodeFunction
    pc: int = 0  # Program counter
    locals: dict[int, Any] = field(default_factory=dict)
    return_address: int = 0


class VirtualMachine:
    """Stack-based virtual machine for executing bytecode."""

    def __init__(self, program: BytecodeProgram, step_limit: int = 1000000) -> None:
        """Initialize the virtual machine.

        Args:
            program: The bytecode program to execute.
            step_limit: Maximum number of steps to prevent infinite loops.
        """
        self.program = program
        self.step_limit = step_limit
        self.stack: list[Any] = []
        self.call_stack: list[CallFrame] = []
        self.step_count = 0
        self.trace = False

    def push(self, value: Any) -> None:
        """Push a value onto the stack."""
        if len(self.stack) > 10000:
            raise Thomas_RuntimeError("Stack overflow")
        self.stack.append(value)

    def pop(self) -> Any:
        """Pop a value from the stack."""
        if not self.stack:
            raise Thomas_RuntimeError("Stack underflow")
        return self.stack.pop()

    def peek(self) -> Any:
        """Peek at the top of the stack without popping."""
        if not self.stack:
            raise Thomas_RuntimeError("Stack underflow")
        return self.stack[-1]

    def get_local(self, index: int) -> Any:
        """Get a local variable."""
        frame = self.call_stack[-1]
        if index not in frame.locals:
            frame.locals[index] = None
        return frame.locals[index]

    def set_local(self, index: int, value: Any) -> None:
        """Set a local variable."""
        frame = self.call_stack[-1]
        frame.locals[index] = value

    def current_frame(self) -> CallFrame:
        """Get the current call frame."""
        if not self.call_stack:
            raise Thomas_RuntimeError("No active function")
        return self.call_stack[-1]

    def current_instruction(self) -> Any:
        """Get the current instruction."""
        frame = self.current_frame()
        if frame.pc >= len(frame.function.instructions):
            return None
        return frame.function.instructions[frame.pc]

    def execute_builtin(self, name: str) -> None:
        """Execute a built-in function."""
        if name == "print":
            value = self.pop()
            print(value)
            self.push(None)

        elif name == "len":
            value = self.pop()
            if isinstance(value, (list, str)):
                self.push(len(value))
            else:
                raise Thomas_RuntimeError(f"len() cannot be applied to {type(value)}")

        elif name == "type":
            value = self.pop()
            type_name = type(value).__name__
            self.push(type_name)

        else:
            raise Thomas_RuntimeError(f"Unknown built-in function: {name}")

    def execute_instruction(self, instr: Any) -> bool:
        """Execute a single instruction.

        Returns:
            False if execution should halt, True otherwise.
        """
        if instr is None:
            return False

        frame = self.current_frame()
        op = instr.opcode

        if self.trace:
            print(f"  {instr}")

        if op == Bytecode.PUSH:
            # Push a constant
            if instr.arg is not None:
                if isinstance(instr.arg, int) and instr.arg < len(self.program.constant_pool):
                    const_map = {v: k for k, v in self.program.constant_pool.items()}
                    value = const_map.get(instr.arg, instr.arg)
                else:
                    value = instr.arg
            else:
                value = None
            self.push(value)

        elif op == Bytecode.POP:
            self.pop()

        elif op == Bytecode.ADD:
            right = self.pop()
            left = self.pop()
            self.push(left + right)

        elif op == Bytecode.SUB:
            right = self.pop()
            left = self.pop()
            self.push(left - right)

        elif op == Bytecode.MUL:
            right = self.pop()
            left = self.pop()
            self.push(left * right)

        elif op == Bytecode.DIV:
            right = self.pop()
            left = self.pop()
            if right == 0:
                raise Thomas_RuntimeError("Division by zero")
            self.push(left / right)

        elif op == Bytecode.MOD:
            right = self.pop()
            left = self.pop()
            if right == 0:
                raise Thomas_RuntimeError("Division by zero")
            self.push(int(left) % int(right))

        elif op == Bytecode.NEG:
            value = self.pop()
            self.push(-value)

        elif op == Bytecode.NOT:
            value = self.pop()
            self.push(1 if not value else 0)

        elif op == Bytecode.EQ:
            right = self.pop()
            left = self.pop()
            self.push(1 if left == right else 0)

        elif op == Bytecode.NE:
            right = self.pop()
            left = self.pop()
            self.push(1 if left != right else 0)

        elif op == Bytecode.LT:
            right = self.pop()
            left = self.pop()
            self.push(1 if left < right else 0)

        elif op == Bytecode.GT:
            right = self.pop()
            left = self.pop()
            self.push(1 if left > right else 0)

        elif op == Bytecode.LE:
            right = self.pop()
            left = self.pop()
            self.push(1 if left <= right else 0)

        elif op == Bytecode.GE:
            right = self.pop()
            left = self.pop()
            self.push(1 if left >= right else 0)

        elif op == Bytecode.AND:
            right = self.pop()
            left = self.pop()
            self.push(1 if (left and right) else 0)

        elif op == Bytecode.OR:
            right = self.pop()
            left = self.pop()
            self.push(1 if (left or right) else 0)

        elif op == Bytecode.LOAD:
            index = instr.arg
            value = self.get_local(index)
            self.push(value)

        elif op == Bytecode.STORE:
            value = self.pop()
            index = instr.arg
            self.set_local(index, value)

        elif op == Bytecode.CALL:
            func_name = instr.arg
            if func_name in self.program.functions:
                # User-defined function
                func = self.program.functions[func_name]
                new_frame = CallFrame(func, 0, {})

                # Pop arguments
                for i in range(func.param_count - 1, -1, -1):
                    arg = self.pop()
                    new_frame.locals[i] = arg

                self.call_stack.append(new_frame)
            else:
                # Built-in function
                self.execute_builtin(func_name)

        elif op == Bytecode.RET:
            if len(self.call_stack) > 1:
                self.call_stack.pop()
                return True
            else:
                return False  # End of main

        elif op == Bytecode.JMP:
            frame.pc = instr.arg - 1  # -1 because pc will be incremented

        elif op == Bytecode.JMP_IF_FALSE:
            condition = self.pop()
            if not condition:
                frame.pc = instr.arg - 1

        elif op == Bytecode.PRINT:
            value = self.pop()
            print(value)

        elif op == Bytecode.HALT:
            return False

        frame.pc += 1
        return True

    def execute(self) -> Any:
        """Execute the program.

        Returns:
            The final value on the stack, if any.

        Raises:
            Thomas_RuntimeError: If an error occurs during execution.
        """
        # Set up main execution frame
        if "main" in self.program.functions:
            main_func = self.program.functions["main"]
            main_frame = CallFrame(main_func, 0, {})
            self.call_stack.append(main_frame)
        else:
            raise Thomas_RuntimeError("No main function found")

        # Execute instructions
        while self.step_count < self.step_limit:
            self.step_count += 1

            if not self.call_stack:
                break

            frame = self.current_frame()
            if frame.pc >= len(frame.function.instructions):
                # Function ended without explicit return
                if len(self.call_stack) > 1:
                    self.call_stack.pop()
                    continue
                else:
                    break

            instr = frame.function.instructions[frame.pc]
            if not self.execute_instruction(instr):
                break

        if self.step_count >= self.step_limit:
            raise Thomas_RuntimeError(f"Execution exceeded step limit ({self.step_limit})")

        # Return value from stack if any
        if self.stack:
            return self.stack[-1]
        return None

    def set_trace(self, enabled: bool) -> None:
        """Enable or disable execution tracing."""
        self.trace = enabled
