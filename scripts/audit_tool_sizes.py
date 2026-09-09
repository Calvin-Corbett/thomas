import importlib.util
import inspect
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Core imports to simulate app environment
from thomas.tools.base import Tool
from thomas.tools.registry import ToolRegistry

# from thomas.core.tokens import estimate_tokens # This might not exist?
try:
    from thomas.core.tokens import estimate_tokens
except ImportError:
    # Fallback if tokens module is missing
    def estimate_tokens(text):
        return len(text) // 4


from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.shell import register_shell_tools

# Setup logging
logging.basicConfig(level=logging.ERROR)
log = logging.getLogger("thomas")


class FlexibleRegistry:
    """Adapter to support both strict Tool objects and functional registration."""

    def __init__(self, real_registry: ToolRegistry):
        self._real = real_registry
        # Expose internal storage if needed by scripts
        self._tools = self._real._tools

    def register(self, tool_or_name: Any, handler: Any = None, schema: dict = None, description: str = ""):
        if isinstance(tool_or_name, Tool):
            self._real.register(tool_or_name)
            return

        # Functional case
        name = str(tool_or_name)
        if not handler:
            return  # Can't register without handler

        # Create a dynamic Tool wrapper
        # We need a class that inherits from Tool
        class FunctionalTool(Tool):
            pass

        t = FunctionalTool()
        t.name = name
        t.description = description or ""
        t.parameters = schema or {}
        t.execute = handler  # This might not work if execute expects 'self', but for audit we only need metadata

        # Patch execute to accept args if needed, but we don't RUN it.
        # We just need it to sit in the registry.

        self._real.register(t)

    def add_tool(self, name, handler, schema, description=""):
        self.register(name, handler, schema, description)

    def __setitem__(self, key, value):
        # Support registry[name] = fn
        # We don't have schema here, so we might miss token counting of schema?
        # But usually this is used for simple tools.
        # We'll try to infer or just create a stub.
        class StubTool(Tool):
            pass

        t = StubTool()
        t.name = key
        t.description = getattr(value, "__doc__", "") or ""
        t.parameters = {}  # No schema known
        self._real.register(t)

    def get_all_tools(self):
        return self._real.get_all_tools()

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __len__(self):
        return len(self._real._tools)


def audit_tool_sizes():
    print("Auditing Tool Sizes (Aggressive Scan)...")

    real_registry = ToolRegistry()
    registry = FlexibleRegistry(real_registry)

    # 1. Register "Standard" tools (simulating app.py)
    print("Loading standard tools...")
    try:
        # Dummy config values
        sandbox = Path(".")
        register_filesystem_tools(registry, sandbox, 1024 * 1024)
        register_shell_tools(registry, sandbox, allowed=True)
        register_git_tools(registry, sandbox)
        register_code_search_tools(registry, sandbox)
        register_diff_tools(registry, sandbox)
    except Exception as e:
        print(f"Standard tool registration partial failure: {e}")
        import traceback

        traceback.print_exc()

    # 2. Scan for other tools in thomas/tools/*.py
    tools_dir = str(ROOT / "thomas" / "tools")
    print(f"Scanning {tools_dir} for extra tools...")

    # Ensure thomas.tools is importable
    try:
        import thomas.tools  # noqa: F401  -- import only for availability probe
    except ImportError as e:
        print(f"Could not import thomas.tools: {e}")

    for filename in os.listdir(tools_dir):
        if filename.endswith(".py") and filename not in ["__init__.py", "base.py", "registry.py", "sandbox.py"]:
            module_name = f"thomas.tools.{filename[:-3]}"
            try:
                # Simple import
                module = importlib.import_module(module_name)

                added_count = 0

                # Strategy A: Look for Tool subclasses
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
                        try:
                            t = _smart_instantiate(obj)
                            if t:
                                if not t.name:
                                    t.name = name.lower()
                                registry.register(t)
                                added_count += 1
                        except Exception as e:
                            print(f"Failed to instantiate class {name}: {e}")

                # Strategy B: Look for register_tools function
                if hasattr(module, "register_tools") and callable(module.register_tools):
                    try:
                        sig = inspect.signature(module.register_tools)
                        if len(sig.parameters) == 1:
                            module.register_tools(registry)
                            added_count += 1
                        elif len(sig.parameters) == 2:
                            module.register_tools(registry, Path("."))
                            added_count += 1
                        elif len(sig.parameters) >= 3:
                            module.register_tools(registry, Path("."), allowed=True)
                            added_count += 1

                    except Exception as e:
                        print(f"Failed to call register_tools in {module_name}: {e}")

                # Strategy C: Look for TOOL_SPECS list
                if hasattr(module, "TOOL_SPECS") and isinstance(module.TOOL_SPECS, list):
                    for spec in module.TOOL_SPECS:
                        if isinstance(spec, dict) and "name" in spec:
                            name = spec["name"]
                            if name not in registry._tools:
                                # If register_tools didn't register it, it implies we might have missed it
                                # But we can't easily instantiate a handler from just a name if register_tools failed
                                pass

                if added_count == 0:
                    print(f"No tools found in {module_name} (checked classes and register_tools)")

            except Exception as e:
                print(f"Failed to import module {module_name}: {e}")
                # import traceback
                # traceback.print_exc()

    # 3. Measure
    results = []
    print(f"Total Unique Tools in Registry: {len(registry)}")

    for name in registry._tools:
        t = registry.get(name)
        try:
            spec = t.get_spec().to_openai()
            json_str = json.dumps(spec, ensure_ascii=False)
            tokens = estimate_tokens(json_str)
            results.append((t.name, tokens, len(json_str), t.category))
        except Exception as e:
            print(f"Error measuring {t.name}: {e}")

    # Sort
    results.sort(key=lambda x: x[1], reverse=True)

    print("\n" + "=" * 90)
    print(f"{'TOOL NAME':<35} | {'TOKENS':<8} | {'CHARS':<8} | {'CATEGORY':<15}")
    print("=" * 90)

    for name, tok, chars, cat in results:
        flag = "!!!" if tok > 1000 else ("!" if tok > 500 else "")
        print(f"{name:<35} | {tok:<8} | {chars:<8} | {cat:<15} {flag}")

    total_tokens = sum(r[1] for r in results)
    print("=" * 90)
    print(f"TOTAL PAYLOAD: {total_tokens} tokens")
    print("=" * 90)


def _smart_instantiate(cls):
    """Instantiate a Tool class with dummy args if needed."""
    try:
        return cls()
    except TypeError:
        # Inspect __init__
        try:
            sig = inspect.signature(cls.__init__)
            kwargs = {}
            for param in sig.parameters.values():
                if param.name == "self":
                    continue
                if param.default == inspect.Parameter.empty:
                    name = param.name.lower()
                    if "dir" in name or "path" in name or "root" in name:
                        kwargs[param.name] = "."
                    elif "allow" in name:
                        kwargs[param.name] = True
                    elif "timeout" in name:
                        kwargs[param.name] = 30
                    elif "db_path" in name:
                        kwargs[param.name] = ":memory:"
                    else:
                        kwargs[param.name] = None
            return cls(**kwargs)
        except Exception:
            return None


if __name__ == "__main__":
    audit_tool_sizes()
