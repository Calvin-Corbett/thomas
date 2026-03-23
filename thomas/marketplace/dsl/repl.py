"""Interactive REPL for DSL."""

import time
from dataclasses import dataclass
from typing import Any

from ._exceptions import DSLException
from ._types import DSLConfig
from .interpreter import Interpreter
from .lexer import Lexer
from .parser import Parser


@dataclass
class REPLConfig:
    """Configuration for REPL."""

    prompt: str = "dsl> "
    multiline_prompt: str = "... "
    history_file: str = ".dsl_history"
    show_types: bool = False
    show_timing: bool = True
    show_ast: bool = False
    max_history: int = 1000


class REPL:
    """Interactive Read-Eval-Print Loop."""

    def __init__(self, config: REPLConfig | None = None, dsl_config: DSLConfig | None = None) -> None:
        """Initialize REPL.

        Args:
            config: REPL configuration
            dsl_config: DSL configuration
        """
        self.config = config or REPLConfig()
        self.dsl_config = dsl_config or DSLConfig()
        self.interpreter = Interpreter(self.dsl_config)
        self.history: list[str] = []
        self.variables: dict[str, Any] = {}
        self._load_history()

    def run(self) -> None:
        """Run REPL."""
        print("DSL REPL v1.0 - Type 'help' for commands")

        while True:
            try:
                # Read input
                line = self._read_line()
                if not line:
                    continue

                # Handle special commands
                if self._handle_command(line):
                    continue

                # Parse and evaluate
                self._eval_and_print(line)

            except KeyboardInterrupt:
                print("\nKeyboardInterrupt")
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

        self._save_history()

    def _read_line(self) -> str:
        """Read input line, handling multiline input.

        Returns:
            Complete input line
        """
        try:
            line = input(self.config.prompt)
        except KeyboardInterrupt:
            raise

        # Check if line needs continuation
        while line.endswith("\\"):
            line = line[:-1]  # Remove backslash
            try:
                cont = input(self.config.multiline_prompt)
                line += cont
            except KeyboardInterrupt:
                raise

        return line.strip()

    def _handle_command(self, line: str) -> bool:
        """Handle special REPL commands.

        Args:
            line: Input line

        Returns:
            True if command was handled
        """
        if line == "help":
            self._show_help()
            return True

        if line == "vars":
            self._show_variables()
            return True

        if line == "history":
            self._show_history()
            return True

        if line == "clear":
            self.interpreter.global_env.bindings.clear()
            return True

        if line == "exit" or line == "quit":
            raise EOFError()

        if line.startswith("del "):
            name = line[4:].strip()
            if name in self.interpreter.global_env.bindings:
                del self.interpreter.global_env.bindings[name]
            return True

        if line.startswith("show "):
            name = line[5:].strip()
            if name in self.interpreter.global_env.bindings:
                val = self.interpreter.global_env.bindings[name]
                print(f"{name} = {val}")
            return True

        if line == "reset":
            self.interpreter = Interpreter(self.dsl_config)
            return True

        return False

    def _eval_and_print(self, line: str) -> None:
        """Evaluate code and print result.

        Args:
            line: Code to evaluate
        """
        self.history.append(line)

        try:
            start = time.time()

            # Lex
            lexer = Lexer(line, self.dsl_config)
            tokens = lexer.tokenize()

            # Parse
            parser = Parser(tokens, self.dsl_config)
            ast = parser.parse()

            if self.config.show_ast:
                print(f"AST: {ast}")

            # Interpret
            result = self.interpreter.interpret(ast)

            elapsed = time.time() - start

            # Print result
            if result is not None:
                print(f"{result}")

            if self.config.show_timing:
                print(f"({elapsed:.4f}s)")

        except DSLException as e:
            print(f"Error: {e.message}")
            if e.location:
                print(f"  at {e.location}")
        except Exception as e:
            print(f"Error: {e}")

    def _show_help(self) -> None:
        """Show help information."""
        help_text = """
DSL REPL Commands:
  help          - Show this help
  vars          - Show all variables
  history       - Show command history
  clear         - Clear all variables
  reset         - Reset interpreter
  exit/quit     - Exit REPL
  del <name>    - Delete variable
  show <name>   - Show variable value

Special syntax:
  Line ending with \\ continues to next line
        """
        print(help_text)

    def _show_variables(self) -> None:
        """Show all defined variables."""
        print("Variables:")
        for name, value in self.interpreter.global_env.bindings.items():
            print(f"  {name} = {value}")

    def _show_history(self) -> None:
        """Show command history."""
        print("History:")
        for i, line in enumerate(self.history[-20:], 1):
            print(f"  {i}: {line}")

    def _load_history(self) -> None:
        """Load history from file."""
        try:
            with open(self.config.history_file) as f:
                self.history = f.read().strip().split("\n")
        except FileNotFoundError:
            pass

    def _save_history(self) -> None:
        """Save history to file."""
        try:
            with open(self.config.history_file, "w") as f:
                f.write("\n".join(self.history[-self.config.max_history :]))
        except Exception:
            pass


def main() -> None:
    """Main entry point."""
    config = REPLConfig()
    dsl_config = DSLConfig(debug_mode=False)
    repl = REPL(config, dsl_config)
    repl.run()


if __name__ == "__main__":
    main()
