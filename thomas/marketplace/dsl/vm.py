"""Virtual machine for executing bytecode."""

from dataclasses import dataclass, field
from typing import Any

from ._exceptions import BreakException, ContinueException
from ._types import DSLConfig
from .compiler import CodeObject, OpCode


@dataclass
class CallFrame:
    """Single function call frame."""

    code: CodeObject
    pc: int = 0  # Program counter
    local_vars: dict[str, Any] = field(default_factory=dict)


class GarbageCollector:
    """Simple mark-and-sweep garbage collector."""

    def __init__(self) -> None:
        """Initialize garbage collector."""
        self.objects: list[Any] = []
        self.marked: set = set()

    def allocate(self, obj: Any) -> Any:
        """Allocate object.

        Args:
            obj: Object to allocate

        Returns:
            Allocated object
        """
        self.objects.append(obj)
        return obj

    def mark(self, obj: Any) -> None:
        """Mark object as used.

        Args:
            obj: Object to mark
        """
        self.marked.add(id(obj))

    def sweep(self) -> None:
        """Sweep unmarked objects."""
        self.objects = [obj for obj in self.objects if id(obj) in self.marked]
        self.marked.clear()


class VM:
    """Stack-based virtual machine."""

    def __init__(self, config: DSLConfig | None = None) -> None:
        """Initialize VM.

        Args:
            config: DSL configuration
        """
        self.config = config or DSLConfig()
        self.stack: list[Any] = []
        self.call_stack: list[CallFrame] = []
        self.globals: dict[str, Any] = {}
        self.gc = GarbageCollector()
        self.cycles = 0
        self.debug = False

    def execute(self, code: CodeObject) -> Any:
        """Execute bytecode.

        Args:
            code: Code object to execute

        Returns:
            Return value
        """
        frame = CallFrame(code)
        self.call_stack.append(frame)

        try:
            while self._step(frame):
                pass

            result = self.stack.pop() if self.stack else None
            return result

        finally:
            self.call_stack.pop()

    def _step(self, frame: CallFrame) -> bool:
        """Execute one instruction.

        Args:
            frame: Current call frame

        Returns:
            False if should stop execution
        """
        self.cycles += 1
        if self.cycles > self.config.max_cycles:
            raise RuntimeError("Execution timeout")

        if frame.pc >= len(frame.code.instructions):
            return False

        instr = frame.code.instructions[frame.pc]
        frame.pc += 1

        if self.debug:
            print(f"PC={frame.pc - 1}: {instr}")

        opcode = instr.opcode

        # Stack operations
        if opcode == OpCode.LOAD_CONST:
            self.stack.append(frame.code.constants[instr.arg])

        elif opcode == OpCode.LOAD_VAR:
            var_name = frame.code.variables[instr.arg]
            if var_name in frame.local_vars:
                self.stack.append(frame.local_vars[var_name])
            elif var_name in self.globals:
                self.stack.append(self.globals[var_name])
            else:
                raise NameError(f"Undefined variable: {var_name}")

        elif opcode == OpCode.STORE_VAR:
            var_name = frame.code.variables[instr.arg]
            value = self.stack.pop()
            # Store in globals if in main frame, locals otherwise
            if frame.code.name == "<main>":
                self.globals[var_name] = value
            else:
                frame.local_vars[var_name] = value

        elif opcode == OpCode.POP:
            self.stack.pop()

        elif opcode == OpCode.DUP:
            self.stack.append(self.stack[-1])

        # Arithmetic operations
        elif opcode == OpCode.ADD:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a + b)

        elif opcode == OpCode.SUB:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a - b)

        elif opcode == OpCode.MUL:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a * b)

        elif opcode == OpCode.DIV:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a / b)

        elif opcode == OpCode.MOD:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a % b)

        elif opcode == OpCode.POW:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a**b)

        elif opcode == OpCode.NEG:
            self.stack.append(-self.stack.pop())

        # Comparison operations
        elif opcode == OpCode.EQ:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a == b)

        elif opcode == OpCode.NE:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a != b)

        elif opcode == OpCode.LT:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a < b)

        elif opcode == OpCode.LE:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a <= b)

        elif opcode == OpCode.GT:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a > b)

        elif opcode == OpCode.GE:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a >= b)

        # Logical operations
        elif opcode == OpCode.AND:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(self._is_truthy(a) and self._is_truthy(b))

        elif opcode == OpCode.OR:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(self._is_truthy(a) or self._is_truthy(b))

        elif opcode == OpCode.NOT:
            self.stack.append(not self._is_truthy(self.stack.pop()))

        # Bitwise operations
        elif opcode == OpCode.BIT_AND:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a & b)

        elif opcode == OpCode.BIT_OR:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a | b)

        elif opcode == OpCode.BIT_XOR:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a ^ b)

        elif opcode == OpCode.BIT_NOT:
            self.stack.append(~int(self.stack.pop()))

        elif opcode == OpCode.LSHIFT:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a << b)

        elif opcode == OpCode.RSHIFT:
            b = self.stack.pop()
            a = self.stack.pop()
            self.stack.append(a >> b)

        # Control flow
        elif opcode == OpCode.JUMP:
            frame.pc = instr.arg

        elif opcode == OpCode.JUMP_IF_FALSE:
            if not self._is_truthy(self.stack.pop()):
                frame.pc = instr.arg

        elif opcode == OpCode.JUMP_IF_TRUE:
            if self._is_truthy(self.stack.pop()):
                frame.pc = instr.arg

        # Collections
        elif opcode == OpCode.BUILD_LIST:
            count = instr.arg
            items = [self.stack.pop() for _ in range(count)]
            self.stack.append(list(reversed(items)))

        elif opcode == OpCode.BUILD_DICT:
            count = instr.arg
            items = {}
            for _ in range(count):
                val = self.stack.pop()
                key = self.stack.pop()
                items[key] = val
            self.stack.append(items)

        elif opcode == OpCode.INDEX:
            idx = self.stack.pop()
            obj = self.stack.pop()
            self.stack.append(obj[idx])

        elif opcode == OpCode.STORE_INDEX:
            val = self.stack.pop()
            idx = self.stack.pop()
            obj = self.stack.pop()
            obj[idx] = val

        # Function calls and returns
        elif opcode == OpCode.CALL:
            arg_count = instr.arg or 0
            func = self.stack.pop()

            # Handle built-in callables
            if callable(func) and not isinstance(func, CodeObject):
                args = [self.stack.pop() for _ in range(arg_count)]
                args.reverse()
                try:
                    result = func(*args)
                except TypeError:
                    result = func()
                self.stack.append(result)
            elif isinstance(func, CodeObject):
                # Create new call frame for function
                args = [self.stack.pop() for _ in range(arg_count)]
                args.reverse()

                new_frame = CallFrame(func)
                # Bind arguments to parameters
                for i, param in enumerate(func.params):
                    if i < len(args):
                        new_frame.local_vars[param] = args[i]
                    else:
                        new_frame.local_vars[param] = None

                self.call_stack.append(new_frame)
                try:
                    result = None
                    while self._step(new_frame):
                        pass
                    result = self.stack.pop() if self.stack else None
                finally:
                    self.call_stack.pop()
                self.stack.append(result)
            else:
                raise TypeError(f"Object is not callable: {type(func)}")

        elif opcode == OpCode.RETURN:
            return False

        elif opcode == OpCode.BREAK:
            raise BreakException()

        elif opcode == OpCode.CONTINUE:
            raise ContinueException()

        elif opcode == OpCode.LOOP_ITERATE:
            # Stack: [..., iterable, body_function]
            body_func = self.stack.pop()
            iterable = self.stack.pop()

            if isinstance(iterable, (list, tuple)):
                iterator = iterable
            elif isinstance(iterable, dict):
                iterator = iterable.values()
            elif isinstance(iterable, range):
                iterator = list(iterable)
            else:
                raise TypeError(f"Object is not iterable: {type(iterable)}")

            # Call body_func for each item
            try:
                for item in iterator:
                    if isinstance(body_func, CodeObject):
                        new_frame = CallFrame(body_func)
                        if body_func.params:
                            new_frame.local_vars[body_func.params[0]] = item
                        self.call_stack.append(new_frame)
                        try:
                            while self._step(new_frame):
                                pass
                            self.stack.pop() if self.stack else None
                        except ContinueException:
                            pass
                        finally:
                            self.call_stack.pop()
                    elif callable(body_func):
                        body_func(item)
            except BreakException:
                pass

            self.stack.append(None)

        elif opcode == OpCode.NOP:
            pass

        return True

    def _is_truthy(self, value: Any) -> bool:
        """Check if value is truthy.

        Args:
            value: Value to check

        Returns:
            True if truthy
        """
        if value is None or value is False:
            return False
        if value == 0 or value == "" or value == [] or value == {}:
            return False
        return True
