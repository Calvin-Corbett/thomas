import sys
import traceback

print("Python:", sys.version)
print("Executable:", sys.executable)
print()

try:
    print("Importing thomas.core.config...")
    from thomas.core.config import load_config
    print("  OK")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()

try:
    print("Importing thomas.server.app...")
    from thomas.server.app import serve
    print("  OK")
except Exception as e:
    print(f"  FAILED: {e}")
    traceback.print_exc()
