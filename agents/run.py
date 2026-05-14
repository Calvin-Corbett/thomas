#!/usr/bin/env python3
# Scaffold dispatcher demo — minimal entry point delegating to <task>_agent.py
# files. Not imported by any production module.
"""Agent Dispatcher: Delegates to task-specific agents."""
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <task> [args...]")
        sys.exit(1)

    task = sys.argv[1]
    agent_file = f"{task}_agent.py"
    agent_path = Path(__file__).parent / agent_file

    if not agent_path.exists():
        print(f"❌ Agent {agent_file} not found. Brain will generate it.")
        sys.exit(1)

    print(f"🧠 Delegating to {agent_file}...")
    result = subprocess.run([sys.executable, str(agent_path)] + sys.argv[2:],
                           capture_output=True, text=True, cwd=Path(__file__).parent)
    print("📤 Agent stdout:", result.stdout)
    if result.stderr:
        print("📤 Agent stderr:", result.stderr)
    result.check_returncode()

if __name__ == "__main__":
    main()
