# P110 - Plugin hook before-tool

This run demonstrates a **plugin hook that executes before a tool runs**, enabling a plugin to:

- **allow** a tool invocation as-is
- **modify** the tool arguments before execution
- **block** the tool invocation before execution

The Thomas-native model used here is:

- **Input:** tool name + args (`ToolCall`)
- **Output:** an action (`allow | modify | block`) + optional reason + optional modified args (`BeforeToolDecision`)

## CLI parity command

### Default (modify)

```bash
thomas plugins p110-plugin-hook-before-tool --json
```

Example output (shape):

```json
{
  "ok": true,
  "data": {
    "tool": {
      "name": "demo.echo",
      "original_args": {"text": "hello"},
      "final_args": {"text": "[p110 before-tool] hello"}
    },
    "hook": {
      "action": "modify",
      "reason": "prefixed text arg",
      "modified_args": {"text": "[p110 before-tool] hello"}
    },
    "tool_executed": true,
    "tool_result": "[p110 before-tool] hello"
  },
  "error": null
}
```

### Block (simulated external failure)

```bash
thomas plugins p110-plugin-hook-before-tool --simulate-external-failure --json
```

Example output (shape):

```json
{
  "ok": false,
  "data": {
    "tool": {"name": "demo.echo", "original_args": {"text": "hello"}, "final_args": null},
    "hook": {"action": "block", "reason": "simulated external validation failure", "modified_args": null},
    "tool_executed": false,
    "tool_result": null
  },
  "error": {"code": "external_failure", "type": "ExternalHookFailure", "message": "simulated external validation failure"}
}
```

### Output schema

```bash
thomas plugins p110-plugin-hook-before-tool --json-schema
```
