import json

import pytest


def test_contract_success_envelope_is_json_serializable():
    from thomas.browser.p025_browser_json_output_contract import success

    payload = success({"title": "Example", "url": "https://example.com"}, command="open")
    dumped = json.dumps(payload, ensure_ascii=False)
    loaded = json.loads(dumped)

    assert loaded["ok"] is True
    assert loaded["data"]["result"]["title"] == "Example"
    assert loaded["meta"]["contract"]
    assert loaded["meta"]["contract_version"]


def test_contract_failure_envelope_is_deterministic():
    from thomas.browser.p025_browser_json_output_contract import failure

    payload = failure("invalid_input", "Invalid URL.", details={"url": "no spaces allowed"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["url"] == "no spaces allowed"


def test_failure_from_exception_maps_common_types():
    from thomas.browser.p025_browser_json_output_contract import failure_from_exception

    v = failure_from_exception(ValueError("bad"))
    assert v["error"]["code"] == "invalid_input"

    f = failure_from_exception(FileNotFoundError("missing"))
    assert f["error"]["code"] == "missing_config"

    m = failure_from_exception(ModuleNotFoundError("nope"))
    assert m["error"]["code"] == "missing_config"

    e = failure_from_exception(RuntimeError("boom"))
    assert e["error"]["code"] == "external_failure"

    t = failure_from_exception(TypeError("wrong"))
    assert t["error"]["code"] == "internal_error"


def test_schema_is_valid_json_and_mentions_required_fields():
    from thomas.browser.p025_browser_json_output_contract import browser_json_schema

    schema = browser_json_schema()
    dumped = json.dumps(schema)
    loaded = json.loads(dumped)

    assert loaded["type"] == "object"
    assert "oneOf" in loaded
    assert "$defs" in loaded
    assert "meta" in loaded["$defs"]


def test_cli_patch_adds_flags_without_touching_callback_signature():
    click = pytest.importorskip("click")
    from click.testing import CliRunner

    from thomas.cli.commands.browser.p025_browser_json_output_contract import attach_json_output_options

    @click.command()
    def cmd():
        # No parameters accepted; patch must not break signature.
        click.echo("ok")

    assert attach_json_output_options(cmd) is True

    runner = CliRunner()
    result = runner.invoke(cmd, ["--json"])  # should be accepted
    assert result.exit_code == 0
    assert result.output.strip() == "ok"

    result_schema = runner.invoke(cmd, ["--json-schema"])  # prints schema + exits
    assert result_schema.exit_code == 0
    parsed = json.loads(result_schema.output)
    assert parsed["type"] == "object"


def test_cli_register_wraps_leaf_commands_for_json_output_and_captures_logging():
    click = pytest.importorskip("click")
    from click.testing import CliRunner

    from thomas.cli.commands.browser.p025_browser_json_output_contract import register

    import logging

    logging.basicConfig(level=logging.WARNING)

    @click.group()
    def root():
        pass

    @root.command()
    def hello():
        click.echo("hello")

    @root.command()
    def loggy():
        logging.getLogger(__name__).warning("warn")
        click.echo("done")

    assert register(root) is True

    runner = CliRunner()
    result = runner.invoke(root, ["hello", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert "hello" in payload["data"]["stdout"]

    result2 = runner.invoke(root, ["loggy", "--json"])
    assert result2.exit_code == 0
    payload2 = json.loads(result2.output)
    assert payload2["ok"] is True
    assert "done" in payload2["data"]["stdout"]
    assert "warn" in payload2["data"]["stderr"]


def test_cli_register_emits_json_error_envelope_on_exception():
    click = pytest.importorskip("click")
    from click.testing import CliRunner

    from thomas.cli.commands.browser.p025_browser_json_output_contract import register

    @click.group()
    def root():
        pass

    @root.command()
    def boom():
        raise RuntimeError("kaboom")

    register(root)
    runner = CliRunner()
    result = runner.invoke(root, ["boom", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "external_failure"


def test_cli_register_emits_json_error_envelope_on_parse_error():
    click = pytest.importorskip("click")
    from click.testing import CliRunner

    from thomas.cli.commands.browser.p025_browser_json_output_contract import register

    @click.group()
    def root():
        pass

    @root.command()
    @click.argument("required")
    def needs_arg(required: str):  # noqa: ARG001
        click.echo("should not run")

    register(root)
    runner = CliRunner()
    result = runner.invoke(root, ["needs-arg", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
