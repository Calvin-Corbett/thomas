from thomas.core.autonomy import autonomy_level_name, autonomy_level_options, parse_autonomy_level
from thomas.core.config import ModelConfig
from thomas.models.chat_capabilities import profile_chat_control_map


def test_autonomy_labels_reflect_agent_and_full_autonomy() -> None:
    options = autonomy_level_options()
    assert options[3]["name"] == "Agent"
    assert options[4]["name"] == "Full Autonomy"
    assert autonomy_level_name(3) == "Agent"
    assert autonomy_level_name(4) == "Full Autonomy"


def test_parse_autonomy_level_accepts_new_and_legacy_aliases() -> None:
    assert parse_autonomy_level("agent") == 3
    assert parse_autonomy_level("full autonomy") == 4
    assert parse_autonomy_level("full_autonomy") == 4
    assert parse_autonomy_level("auto") == 3


def test_chat_capabilities_surface_updated_autonomy_labels() -> None:
    cfg = ModelConfig(name="local", provider="codex", model="gpt-5.4")
    controls = profile_chat_control_map(cfg)
    options = controls["thomas"]["autonomy_level"]["options"]
    labels = [str(item["label"]) for item in options]
    assert "L3 Agent" in labels
    assert "L4 Full Autonomy" in labels


def test_chat_capabilities_surface_all_gpt56_reasoning_efforts() -> None:
    cfg = ModelConfig(name="chatgpt", provider="openai_codex", model="gpt-5.6-sol", reasoning_effort="xhigh")
    controls = profile_chat_control_map(cfg)

    effort = controls["model"]["reasoning_effort"]
    assert effort["default_value"] == "xhigh"
    assert [item["value"] for item in effort["options"]] == ["none", "low", "medium", "high", "xhigh", "max"]
