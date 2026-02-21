import argparse
import json

import pytest

from thomas.messages.p055_message_edit_command import (
    ERR_EXTERNAL_FAILURE,
    ERR_INVALID_INPUT,
    ERR_MISSING_CONFIG,
    MessageEditCommandError,
    MessageEditCommandInput,
    execute_message_edit,
)

from thomas.cli.commands.messages import p055_message_edit_command as cli_mod


class _FakeEditorKw:
    def __init__(self):
        self.calls = []

    def edit_message(self, *, message_id: str, text: str, channel_id=None, metadata=None):
        self.calls.append((message_id, text, channel_id, metadata))
        return {"edited": True, "id": message_id, "text": text}


class _FakeEditorPos:
    def __init__(self):
        self.calls = []

    def edit_message(self, message_id: str, new_text: str):
        self.calls.append((message_id, new_text))
        return {"ok": True}


def test_execute_success_keyword_editor():
    editor = _FakeEditorKw()
    req = MessageEditCommandInput(message_id="abc123", new_text="hello", channel_id="chan")
    out = execute_message_edit(req, editor=editor)
    assert out.message_id == "abc123"
    assert out.new_text == "hello"
    assert out.channel_id == "chan"
    assert out.edited is True
    assert out.provider_result == {"edited": True, "id": "abc123", "text": "hello"}
    assert editor.calls == [("abc123", "hello", "chan", None)]


def test_execute_success_positional_editor():
    editor = _FakeEditorPos()
    req = MessageEditCommandInput(message_id="m1", new_text="updated")
    out = execute_message_edit(req, editor=editor)
    assert out.message_id == "m1"
    assert out.new_text == "updated"
    assert out.edited is True
    assert editor.calls == [("m1", "updated")]


def test_execute_invalid_input_missing_message_id():
    editor = _FakeEditorPos()
    with pytest.raises(MessageEditCommandError) as ei:
        execute_message_edit(MessageEditCommandInput(message_id="", new_text="hi"), editor=editor)
    err = ei.value
    assert err.code == ERR_INVALID_INPUT
    assert err.message == "message_id is required."


def test_execute_invalid_input_empty_text():
    editor = _FakeEditorPos()
    with pytest.raises(MessageEditCommandError) as ei:
        execute_message_edit(MessageEditCommandInput(message_id="m1", new_text="   "), editor=editor)
    err = ei.value
    assert err.code == ERR_INVALID_INPUT
    assert err.message == "new_text must not be empty."


def test_execute_missing_config_no_editor():
    with pytest.raises(MessageEditCommandError) as ei:
        execute_message_edit(MessageEditCommandInput(message_id="m1", new_text="hi"), editor=None)
    err = ei.value
    assert err.code == ERR_MISSING_CONFIG


def test_execute_external_failure_wrapped_deterministically():
    class Boom:
        def edit_message(self, message_id: str, new_text: str):
            raise RuntimeError("kaboom")

    with pytest.raises(MessageEditCommandError) as ei:
        execute_message_edit(MessageEditCommandInput(message_id="m1", new_text="hi"), editor=Boom())
    err = ei.value
    assert err.code == ERR_EXTERNAL_FAILURE
    assert err.message == "Message edit failed due to an external error."
    assert err.details == {"cause": "RuntimeError"}


def _parse_cli(argv):
    parser = argparse.ArgumentParser()
    cli_mod._add_arguments(parser)
    return parser.parse_args(argv)


def test_cli_json_success(capsys):
    args = _parse_cli(["--json", "--id", "m1", "--text", "hello"])
    rc = cli_mod.handle(args, compat=_FakeEditorPos())
    assert rc == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["message_id"] == "m1"
    assert payload["result"]["new_text"] == "hello"


def test_cli_json_failure_invalid_input(capsys):
    args = _parse_cli(["--json", "--id", "", "--text", "hello"])
    rc = cli_mod.handle(args, compat=_FakeEditorPos())
    assert rc == 1

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == ERR_INVALID_INPUT


def test_cli_metadata_must_be_json_object(capsys):
    args = _parse_cli(["--json", "--id", "m1", "--text", "hello", "--metadata", "[1,2]"])
    rc = cli_mod.handle(args, compat=_FakeEditorPos())
    assert rc == 1

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == ERR_INVALID_INPUT
    assert payload["error"]["message"] == "metadata must be a JSON object."
