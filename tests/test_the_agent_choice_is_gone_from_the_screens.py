"""You asked for the agent-agnostic choice to go: "remove it from the model selector thing too".

Build still picks its own runner (Thomas's loop, or Claude Code for Claude models) without asking. What is gone is
every place you could choose one: the Models | Agents switch in the model menu, the Agent column in Advanced model
settings, the picker script, and the route that listed agents for the picker.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_picker_script_is_gone_and_chat_does_not_load_it():
    assert not (WEB / "js" / "coding_agent_picker.js").exists()
    assert "coding_agent_picker" not in _text(WEB / "chat.html")


def test_the_model_menu_has_no_agents_switch():
    html = _text(WEB / "chat.html")
    assert "data-mm-view" not in html
    assert 'id="tc-model-title">Models<' in html


def test_nothing_in_the_web_client_reaches_for_the_picker():
    leftovers = [
        path.name
        for path in (WEB / "js").glob("*.js")
        if "ThomasCodingAgentPicker" in _text(path) or "thomas:agents-updated" in _text(path)
    ]
    assert leftovers == []


def test_builds_requests_no_longer_carry_a_chosen_agent():
    lifecycle = _text(WEB / "js" / "unified_code_lifecycle.js")
    stream = _text(WEB / "js" / "chat_stream_actions.js")
    assert "agent: String(context.agent" not in lifecycle
    assert "build_agent" not in stream


def test_the_picker_route_is_not_registered():
    table = _text(ROOT / "thomas" / "server" / "routes" / "evolve_agent_registration.py")
    assert "/api/evolve/agent/agents" not in table
