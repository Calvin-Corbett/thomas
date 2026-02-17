from thomas.models.chat_controls import resolve_ui_control_request
from thomas.models.switching import ModelSwitchResolution


def test_resolve_ui_control_request_includes_model_patch() -> None:
    model_switch = ModelSwitchResolution(
        profile="anthropic",
        model_id="claude-opus-4-6",
        matched_model="claude-opus-4-6",
        confidence=0.95,
        explanation="family=opus,version=4.6",
    )
    res = resolve_ui_control_request("i want 4.6 opus", model_switch=model_switch)
    assert res is not None
    assert res.patch["activeProfile"] == "anthropic"
    assert res.patch["activeModelId"] == "claude-opus-4-6"
    assert any(op.get("kind") == "model" for op in res.operations)


def test_resolve_ui_control_request_parses_boolean_setting() -> None:
    res = resolve_ui_control_request("please turn on tool details")
    assert res is not None
    assert res.patch["settings"]["showToolDetails"] is True


def test_resolve_ui_control_request_parses_mode_and_theme() -> None:
    res = resolve_ui_control_request("set mode to thinking and theme to dark")
    assert res is not None
    assert res.patch["mode"] == "thinking"
    assert res.patch["settings"]["theme"] == "dark"


def test_resolve_ui_control_request_parses_autonomy_level() -> None:
    res = resolve_ui_control_request("set autonomy level 4 full auto")
    assert res is not None
    assert res.patch["settings"]["autonomyLevel"] == 4
    assert "mode" not in res.patch


def test_resolve_ui_control_request_parses_short_autonomy_phrase() -> None:
    res = resolve_ui_control_request("full auto")
    assert res is not None
    assert res.patch["settings"]["autonomyLevel"] == 4


def test_resolve_ui_control_request_does_not_misread_file_names_as_autonomy_command() -> None:
    res = resolve_ui_control_request(
        "create a file named autonomy_level4_test.txt with the text LEVEL4_OK and confirm when done"
    )
    assert res is None


def test_resolve_ui_control_request_ignores_non_directive_text() -> None:
    res = resolve_ui_control_request("the inspector panel is flickering a lot")
    assert res is None
