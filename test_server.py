import sys
import traceback

print("Starting server...")
sys.stdout.flush()

try:
    from thomas.server.app import serve
    from thomas.core.config import load_config
    from pathlib import Path
    
    print("Imports OK")
    sys.stdout.flush()
    
    config = load_config()
    print(f"Config loaded, default_model={config.default_model}")
    sys.stdout.flush()
    
    errors = config.validate()
    if errors:
        print("Config errors:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    
    print("Starting serve()...")
    sys.stdout.flush()
    serve(config, host="127.0.0.1", port=8900)
    
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
    sys.exit(1)
