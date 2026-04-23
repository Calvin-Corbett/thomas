# Tools - Built-in Capabilities

This directory contains the built-in tools that specialists can use to accomplish work: file operations, database queries, shell commands, web search, code search, email, SSH, and more.

## What This Directory Does

Tools are **capabilities** that specialists can execute with. Think of them as library functions. When a specialist needs to read a file, search code, query a database, or browse the web, it calls a tool.

```
Specialist executes
        ↓
needs to do something (e.g., read a file)
        ↓
calls Tool (e.g., file_readers.py)
        ↓
Tool does the work
        ↓
Returns result to specialist
```

## Tool Categories

| File | What It Does |
|---|---|
| **File Operations** | |
| `file_readers.py` | Read files (text, code, documents) |
| `filesystem.py` | File system operations (list, delete, write) |
| **Code** | |
| `code_search.py` | Search code files by pattern |
| `engineering.py` | Code generation, fixing, refactoring |
| `git.py` | Git operations (commit, branch, diff) |
| `git_conflicts.py` | Git conflict resolution |
| `git_worktree.py` | Git worktree management |
| `notebook.py` | Jupyter notebook operations |
| **Database** | |
| `database.py` | SQL queries (read-only and write) |
| `database_commands.py` | Database operations |
| `database_safety.py` | Safety checks for database operations |
| `nl_to_sql.py` | Convert natural language to SQL |
| **Web and Network** | |
| `browser.py` | Browser automation, screenshot, click |
| `web_search.py` | Web search using search engines |
| `web_search_providers.py` | Search provider integrations |
| `web_search_parsing.py` | Parse search results |
| `http_client.py` | Make HTTP requests |
| **Email and Calendar** | |
| `email_operations.py` | Send/read email |
| `email_providers.py` | Email service integrations (Gmail, Outlook) |
| `email_calendar.py` | Calendar operations |
| `calendar_operations.py` | Calendar utilities |
| **System and SSH** | |
| `shell.py` | Run shell commands |
| `ssh.py` | SSH connection and command execution |
| `ssh_config.py` | SSH configuration |
| `windows_auth.py` | Windows authentication |
| **Data and Search** | |
| `diff.py` | Diff and comparison |
| `investigation.py` | Investigation and analysis |
| `sandbox.py` | Safe execution sandbox |
| `sandbox_part01.py`, `sandbox_part02.py` | Sandbox implementation (monolith) |
| **Other** | |
| `base.py` | Base tool interface |
| `registry.py` | Tool registry |
| `api_import.py` | Import and integrate APIs |
| `cloud/` | Cloud provider tools |
| `gateway/` | Gateway/proxy tools |

## Tool Interface (base.py)

All tools inherit from `ToolBase`:

```python
from thomas.tools.base import ToolBase

class MyTool(ToolBase):
    """My custom tool."""

    def __init__(self):
        super().__init__(
            name='my_tool',
            description='Does something cool',
            version='1.0.0'
        )

    async def execute(self, **kwargs):
        """Execute the tool with arguments."""
        param1 = kwargs.get('param1')
        param2 = kwargs.get('param2')

        # Do work
        result = f"Processed {param1} and {param2}"

        return {
            'success': True,
            'output': result,
            'metadata': {'items_processed': 2}
        }

    def get_parameters(self):
        """Define what parameters this tool accepts."""
        return {
            'param1': {
                'type': 'string',
                'description': 'First parameter',
                'required': True
            },
            'param2': {
                'type': 'string',
                'description': 'Second parameter',
                'required': False
            }
        }
```

## Common Tools and How to Use Them

### Reading Files
```python
from thomas.tools.file_readers import FileReaders

reader = FileReaders()
content = await reader.execute(
    path='/path/to/file.py',
    file_type='python'  # 'python', 'text', 'json', etc.
)
print(content['output'])
```

### Searching Code
```python
from thomas.tools.code_search import CodeSearcher

searcher = CodeSearcher()
results = await searcher.execute(
    pattern='def my_function',
    directory='/code'
)
for result in results['output']:
    print(f"{result['file']}: {result['line_number']}")
```

### Git Operations
```python
from thomas.tools.git import GitOperations

git = GitOperations()
await git.execute(
    action='commit',
    message='Fix bug',
    files=['file1.py', 'file2.py']
)
```

### Database Queries
```python
from thomas.tools.database import DatabaseQuery

db = DatabaseQuery()
result = await db.execute(
    query='SELECT * FROM users WHERE active=1',
    database='mydb'
)
for row in result['output']:
    print(row)
```

### Web Search
```python
from thomas.tools.web_search import WebSearcher

searcher = WebSearcher()
results = await searcher.execute(
    query='latest climate change news',
    num_results=10
)
for result in results['output']:
    print(f"{result['title']}: {result['url']}")
```

### Shell Commands
```python
from thomas.tools.shell import ShellExecutor

shell = ShellExecutor()
result = await shell.execute(
    command='ls -la /tmp'
)
print(result['output'])
print(f"Exit code: {result['exit_code']}")
```

### SSH
```python
from thomas.tools.ssh import SSHClient

ssh = SSHClient()
result = await ssh.execute(
    host='server.example.com',
    command='uptime',
    username='admin'
)
print(result['output'])
```

## Tool Safety and Constraints

Tools respect **capability tokens** from the orchestrator:

```python
# Specialist declares what tools it can use
def get_capability_tokens(self):
    return [
        CapabilityToken(
            tool_name="shell",
            allowed=True,
            constraints={"max_commands": 10}
        ),
        CapabilityToken(
            tool_name="database",
            allowed=False  # Not allowed
        )
    ]
```

The orchestrator enforces these constraints. Tools check before executing:

```python
async def execute(self, contract, **kwargs):
    # Check if allowed
    if not contract.can_use_tool('shell'):
        raise PermissionError("Tool not allowed by contract")

    # Check limits
    if contract.tool_usage('shell') >= contract.get_limit('shell'):
        raise LimitExceededError("Command limit exceeded")

    # Safe to execute
    result = await shell_command(...)
    return result
```

## Monolith Pattern

Some tools are split into parts (especially large ones like `sandbox`):

- `sandbox.py` — Stub/loader
- `sandbox_part01.py` — First part
- `sandbox_part02.py` — Second part

When you edit:
1. Find the actual code file
2. Edit that `_partXX.py`
3. Clear `.pyc` files
4. Restart

## Common Mistakes

### ✗ Don't do this:

1. **Call tool directly without contract** — Let specialist handle it.
2. **Assume all tools are always available** — Check capability tokens.
3. **Make unbounded calls** — Respect tool limits (max files, max queries, etc.)
4. **Ignore error handling** — Tools can fail gracefully.
5. **Hardcode credentials** — Use secrets management.

### ✓ Do this:

1. Use tools through specialist interface
2. Check capability tokens before using
3. Respect limits and constraints
4. Handle tool errors gracefully
5. Use `secrets_v2.py` for credentials

## Tool Registration

Tools are registered in `registry.py` or `thomas/core/tool_factory.py`:

```python
from thomas.tools.registry import TOOL_REGISTRY

# Register
TOOL_REGISTRY.register('my_tool', {
    'class': MyTool,
    'description': 'What it does',
    'requires_auth': False,
    'timeout': 30.0,
    'max_retries': 3
})

# Get registered tool
tool = TOOL_REGISTRY.get('my_tool')
```

## Creating a New Tool

1. Create `thomas/tools/my_tool.py`:

```python
from thomas.tools.base import ToolBase

class MyTool(ToolBase):
    def __init__(self):
        super().__init__(
            name='my_tool',
            description='Does something specific'
        )

    async def execute(self, **kwargs):
        try:
            result = await do_work(kwargs)
            return {
                'success': True,
                'output': result
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def get_parameters(self):
        return {
            'input': {
                'type': 'string',
                'description': 'Input parameter',
                'required': True
            }
        }
```

2. Register in `registry.py`:

```python
from thomas.tools.my_tool import MyTool

TOOL_REGISTRY.register('my_tool', {
    'class': MyTool,
    'description': 'Does something specific'
})
```

3. Use in specialists via capability tokens
4. Restart server

## For AI Agents

### To use a tool in a specialist:
```python
# In specialist.execute()
tool = TOOL_REGISTRY.get('file_readers')
result = await tool.execute(path='/file.py')
```

### To add a new tool:
1. Create `thomas/tools/my_tool.py` inheriting from `ToolBase`
2. Implement `execute()` and `get_parameters()`
3. Register in `registry.py`
4. Add to `get_capability_tokens()` in relevant specialists
5. Restart server

### To fix a tool error:
1. Check tool's `execute()` method
2. Add logging to trace what failed
3. Verify capability tokens allow the tool
4. Check tool constraints/limits aren't exceeded

## Cloud and Gateway Tools

- `cloud/` — AWS, Azure, GCP integrations
- `gateway/` — Proxy and gateway utilities

These are less commonly used but available for cloud workloads.

## See Also

- `thomas/orchestrator/protocol.py` — Capability tokens
- `thomas/core/tool_factory.py` — Tool registration
- `thomas/specialists/*.py` — Tools used by specialists
- `docs/CHAT_EXECUTION_MODEL.md` — Overall system
