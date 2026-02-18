#!/usr/bin/env python3
&quot;&quot;&quot;Agent Dispatcher: Delegates to task-specific agents.&quot;&quot;&quot;
import sys
import subprocess
import os
from pathlib import Path

def main():
    if len(sys.argv) &lt; 2:
        print(&quot;Usage: python run.py &lt;task&gt; [args...]&quot;)
        sys.exit(1)
    
    task = sys.argv[1]
    agent_file = f&quot;{task}_agent.py&quot;
    agent_path = Path(__file__).parent / agent_file
    
    if not agent_path.exists():
        print(f&quot;❌ Agent {agent_file} not found. Brain will generate it.&quot;)
        sys.exit(1)
    
    print(f&quot;🧠 Delegating to {agent_file}...&quot;)
    result = subprocess.run([sys.executable, str(agent_path)] + sys.argv[2:], 
                           capture_output=True, text=True, cwd=Path(__file__).parent)
    print(&quot;📤 Agent stdout:&quot;, result.stdout)
    if result.stderr:
        print(&quot;📤 Agent stderr:&quot;, result.stderr)
    result.check_returncode()

if __name__ == &quot;__main__&quot;:
    main()
