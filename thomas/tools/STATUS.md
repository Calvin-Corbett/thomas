# Module: tools

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (most tools have real code, 4 placeholders) |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — tool framework is core to the agent loop         |
| Has real tests   | partial                                                |
| Blocking issues  | 4 files placeholder, git_conflicts.py over 800 limit   |

## What This Is

The tool library — everything Thomas can actually DO. 17,000 lines across
42 files. Defines the Tool base class and all concrete tool implementations:
browser automation, web search, email, SSH, database, git, voice, sandbox
execution, NL-to-SQL, HTTP client, dependency scanning, and the Windows
auth gate.

This is the "everything assistant" in practice — each tool is a capability
Thomas can use when talking to the user.

## What Actually Works

- `base.py` — Tool base class, ToolResult types. Foundation of all tools. Real.
- `browser.py` (947 lines) — Playwright-based browser automation. Real code.
- `web_search.py` (552 lines) — Web search with provider abstraction. Real.
- `web_search_providers.py` (765 lines) — Search provider implementations. Real.
- `voice.py` (764 lines) — Voice integration bridge (STT, TTS, voice chat). Real.
- `ssh.py` (866 lines) — SSH remote execution with connection pooling. Real.
- `email_providers.py` (715 lines) — Gmail and Microsoft Graph email. Real.
- `database.py` (793 lines) — Database tool. Real.
- `database_commands.py` (807 lines) — DB command implementations. Real.
- `nl_to_sql.py` (591 lines) — Natural language to SQL. Real.
- `http_client.py` (511 lines) — HTTP request tool. Real.
- `git_conflicts.py` (1114 lines) — Git conflict resolution. Real but over limit.
- `engineering.py` (857 lines) — Engineering tools. Real but over limit.
- `sandbox_part01.py` (892 lines) — Sandboxed code execution. Real but over limit.
- `dep_scanner_part01.py` (902 lines) — Dependency scanning. Real but over limit.
- `windows_auth.py` (292 lines) — OS-level auth gate. Real, production-used.
- `mcp_client.py` / `mcp_tools.py` / `mcp_bridge.py` — Executable MCP stdio
  client (JSON-RPC 2.0, newline-delimited), adapter registering discovered
  tools as `mcp.<server>.<tool>`, and startup bridge consumed by the REPL.
  Real, tested (tests/test_mcp_client.py, hermetic fake-server fixture).

## What Is Placeholder

- `git_worktree.py` — **PLACEHOLDER.** Git worktree operations.
- `notebook.py` — **PLACEHOLDER.** Jupyter notebook tool.
- `plugin_bridge.py` — **PLACEHOLDER.** Plugin bridge tool.

## Architecture Notes

Tools plug into the agent loop via `thomas/agent/loop_tool_exec.py`. The
agent decides to call a tool → tool_exec resolves it from the registry →
calls `execute()` → returns ToolResult back to the agent.

The tools module is how Thomas earns the "everything assistant" title. Each
tool is an installable capability. The marketplace vision (from the product owner) means
new tools should eventually be installable through the marketplace too.

## Known Gaps

- 3 placeholder files (git_worktree, notebook, plugin_bridge)
- 4 files over 800-line limit (git_conflicts, engineering, sandbox, dep_scanner)
- No notebook tool (important for data work)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `base.py` — Every tool inherits from this. Changes break everything.
- `windows_auth.py` — Security-critical. Don't change auth behavior.
