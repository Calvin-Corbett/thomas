import json

from thomas.plugins.p106_plugin_command_registry_bridge import (
    dispatch_plugin_command,
    register_bridge_tool,
)


class DummyCommandRegistry:
    """A minimal registry supporting both resolve and invoke patterns."""

    def __init__(self, commands):
        self.commands = dict(commands)

    def get_command(self, name):
        return self.commands.get(name)

    def list_commands(self):
        return list(self.commands.keys())


class DummyInvokingRegistry(DummyCommandRegistry):
    def invoke(self, name, **kwargs):
        cmd = self.get_command(name)
        if cmd is None:
            raise KeyError(name)
        return cmd(**kwargs)


class DummyToolRegistry:
    def __init__(self):
        self.registered = {}

    def register_tool(self, name, fn, description=None, input_schema=None, output_schema=None):
        self.registered[name] = {
            "fn": fn,
            "description": description,
            "input_schema": input_schema,
            "output_schema": output_schema,
        }


def test_dispatch_success_returns_ok_and_result():
    reg = DummyCommandRegistry({"add": lambda a, b: a + b})

    out = dispatch_plugin_command({"command": "add", "args": {"a": 2, "b": 3}}, command_registry=reg)
    assert out["ok"] is True
    assert out["command"] == "add"
    assert out["result"] == 5
    assert out["error"] is None


def test_dispatch_uses_registry_invoke_when_available():
    reg = DummyInvokingRegistry({"add": lambda a, b: a + b})

    out = dispatch_plugin_command({"command": "add", "args": {"a": 1, "b": 4}}, command_registry=reg)
    assert out["ok"] is True
    assert out["result"] == 5


def test_dispatch_invalid_input_is_deterministic_error():
    reg = DummyCommandRegistry({})

    out = dispatch_plugin_command(["not", "an", "object"], command_registry=reg)
    assert out["ok"] is False
    assert out["error"]["code"] == "INVALID_INPUT"


def test_dispatch_missing_command_returns_command_not_found():
    reg = DummyCommandRegistry({"add": lambda a, b: a + b})

    out = dispatch_plugin_command({"command": "nope", "args": {}}, command_registry=reg)
    assert out["ok"] is False
    assert out["error"]["code"] == "COMMAND_NOT_FOUND"


def test_dispatch_argument_mismatch_is_invalid_input():
    reg = DummyCommandRegistry({"add": lambda a, b: a + b})

    out = dispatch_plugin_command({"command": "add", "args": {"a": 1, "c": 2}}, command_registry=reg)
    assert out["ok"] is False
    assert out["error"]["code"] == "INVALID_INPUT"
    assert "unexpected" in out["error"]["details"]


def test_dispatch_command_exception_is_external_failure_with_details():
    def boom(**_kwargs):
        raise ValueError("boom")

    reg = DummyCommandRegistry({"boom": boom})

    out = dispatch_plugin_command({"command": "boom", "args": {}}, command_registry=reg)
    assert out["ok"] is False
    assert out["error"]["code"] == "EXTERNAL_FAILURE"
    assert out["error"]["details"]["exception"] == "ValueError"
    assert out["error"]["details"]["message"] == "boom"


def test_register_bridge_tool_registers_callable_and_schema():
    reg = DummyCommandRegistry({"add": lambda a, b: a + b})
    tools = DummyToolRegistry()

    register_bridge_tool(tools, command_registry=reg, tool_name="plugins.invoke")

    assert "plugins.invoke" in tools.registered
    tool = tools.registered["plugins.invoke"]
    assert callable(tool["fn"])
    assert tool["input_schema"]["type"] == "object"
    assert tool["output_schema"]["type"] == "object"

    # And the tool can actually dispatch
    out = tool["fn"]({"command": "add", "args": {"a": 1, "b": 4}})
    assert out["ok"] is True
    assert out["result"] == 5


def test_register_bridge_tool_lazy_registry_provider_returns_missing_config():
    tools = DummyToolRegistry()

    register_bridge_tool(tools, command_registry_provider=lambda: None, tool_name="plugins.invoke")

    out = tools.registered["plugins.invoke"]["fn"]({"command": "anything", "args": {}})
    assert out["ok"] is False
    assert out["error"]["code"] == "MISSING_CONFIG"


def test_cli_schema_output_is_json_machine_readable():
    # Import lazily so click is only involved in this test.
    from click.testing import CliRunner

    from thomas.cli.commands.plugins.p106_plugin_command_registry_bridge import COMMAND

    runner = CliRunner()
    res = runner.invoke(COMMAND, ["--schema", "--json"])
    assert res.exit_code == 0

    payload = json.loads(res.output)
    assert "request_schema" in payload
    assert "response_schema" in payload
    assert payload["request_schema"]["type"] == "object"
